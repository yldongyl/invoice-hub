# -*- coding: utf-8 -*-
"""路由引擎与降级/交叉验证全套用例（WP4.2 · FN-2-08/09/10/13/14 · FN-2-01）。

验证要点：
  1. 三条件（地区｜票种｜载体）优先级先命中先决匹配（FN-2-08）；
  2. S-M4-01 纸质专票剧本推演：百望云 0.82 < 0.88 门控降级 → 诺诺 0.91 达标通过；
  3. S-M4-02 停用百望云 → 路由链自动跳过（skip）→ 直接执行诺诺，降级留痕；
  4. 异源交叉验证（FN-2-09）：结构化×文本×勾稽×查验互证一致；同类模型投票被自动排除；关键字段冲突转人工；
  5. 全局降级三模式与五项兜底触发条件配置化判定（FN-2-10）；
  6. 内置直读矩阵（XML、OFD 解包、PDF 文本层、二维码解码，FN-2-01）：免 Provider 零成本、零外发记录。
"""

import pytest

from app.services import intake_parsers, provider_service, routing_engine


def test_three_condition_matching(fresh_session):
    """断言三条件匹配规则引擎（FN-2-08）。"""
    policy = routing_engine.get_effective_policy(fresh_session)

    # 1. CN + 数电票 + XML 原件 + PDF -> cn_e_invoice_recognize
    r1 = routing_engine.match_rule(
        policy, region="CN 中国", invoice_type="数电票", carrier="XML 原件 + PDF"
    )
    assert r1 is not None and r1["route_id"] == "cn_e_invoice_recognize"

    # 2. CN + 增值税专票/普票（纸质扫描） + 纸质扫描 / 图片 -> cn_vat_paper_recognize
    r2 = routing_engine.match_rule(
        policy, region="CN 中国", invoice_type="增值税专票/普票（纸质扫描）", carrier="纸质扫描 / 图片"
    )
    assert r2 is not None and r2["route_id"] == "cn_vat_paper_recognize"

    # 3. APAC + Supplier Invoice + PDF（原生文本层） -> ap_supplier_invoice_recognize
    r3 = routing_engine.match_rule(
        policy, region="APAC 亚太 / EU 欧盟", invoice_type="Supplier Invoice", carrier="PDF（原生文本层）"
    )
    assert r3 is not None and r3["route_id"] == "ap_supplier_invoice_recognize"

    # 4. 未匹配的组合 -> 返回 None
    r_none = routing_engine.match_rule(
        policy, region="US 美国", invoice_type="Unknown Type", carrier="Unknown Carrier"
    )
    assert r_none is None


def test_s_m4_01_paper_vat_fallback_script(fresh_session):
    """S-M4-01 纸质专票剧本推演与真实路由行为一致。

    执行链路：百望云 0.82 < 0.88（不达标降级）→ 诺诺 0.91 >= 0.88（达标采纳并终止）→ 多源交叉验证 → 终点。
    """
    res = routing_engine.execute_route(
        fresh_session,
        region="CN 中国",
        invoice_type="增值税专票/普票（纸质扫描）",
        carrier="纸质扫描 / 图片",
        doc_type_hint="增值税专票/普票（纸质扫描）",
        sha256="4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
    )
    assert res["status"] == "done"
    assert res["final_provider"] == "nuonuo-cn"
    assert res["confidence"] == 0.91

    # 检查 steps 逐步推演结构与原型一致
    steps = res["steps"]
    step_types = [s["st"] for s in steps]
    assert "info" in step_types
    assert "fail" in step_types  # 百望云置信度不足
    assert "ok" in step_types    # 诺诺达标
    assert "done" in step_types  # 终点

    # 找到百望云 step
    bw_step = next(s for s in steps if "百望云" in s["t"])
    assert bw_step["st"] == "fail"
    assert "0.82 < 阈值 0.88" in bw_step["d"]

    # 找到诺诺 step
    nn_step = next(s for s in steps if "诺诺" in s["t"])
    assert nn_step["st"] == "ok"
    assert "0.91 ≥ 阈值 0.88" in nn_step["d"]


def test_s_m4_02_disabled_provider_auto_skip(fresh_session):
    """S-M4-02 停用百望云 → 路由链自动跳过（skip）→ 直接由诺诺识别通过。"""
    # 1. 停用百望云
    provider_service.toggle_provider(fresh_session, "bwyun-cn", enabled=False, actor="human")

    # 2. 执行纸质专票路由
    res = routing_engine.execute_route(
        fresh_session,
        region="CN 中国",
        invoice_type="增值税专票/普票（纸质扫描）",
        carrier="纸质扫描 / 图片",
        doc_type_hint="增值税专票/普票（纸质扫描）",
        sha256="4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
    )
    assert res["status"] == "done"
    assert res["final_provider"] == "nuonuo-cn"

    # 百望云步骤标记为 skip
    bw_step = next(s for s in res["steps"] if "百望云" in s["t"])
    assert bw_step["st"] == "skip"
    assert "Provider 已停用 → 按路由链自动跳过" in bw_step["d"]

    # 诺诺步骤成功
    nn_step = next(s for s in res["steps"] if "诺诺" in s["t"])
    assert nn_step["st"] == "ok"

    # 恢复启用
    provider_service.toggle_provider(fresh_session, "bwyun-cn", enabled=True, actor="human")


def test_cross_check_rules():
    """断言异源交叉验证核心纪律（FN-2-09）。"""
    rule = {
        "cross_check": {
            "enabled": True,
            "require_different_source": True,
            "fields": ["total.gross_amount", "total.tax_amount"],
        }
    }

    # 1. 异构证据源互证（xml_direct × ocr），金额一致 -> 通过
    p_res = {
        "fields": [
            {"name": "total.gross_amount", "value": 1000.0, "source": "xml_direct"},
            {"name": "total.tax_amount", "value": 130.0, "source": "xml_direct"},
        ]
    }
    s_res = {
        "fields": [
            {"name": "total.gross_amount", "value": 1000.0, "source": "ocr"},
            {"name": "total.tax_amount", "value": 130.0, "source": "ocr"},
        ]
    }
    cc1 = routing_engine.evaluate_cross_check(rule, p_res, s_res)
    assert cc1["passed"] is True
    assert cc1["heterogeneous"] is True

    # 2. 同类模型对比投票（两方均为 model 来源）-> 自动排除，不作为有效交叉互证
    p_model = {"fields": [{"name": "total.gross_amount", "value": 1000.0, "source": "model"}]}
    s_model = {"fields": [{"name": "total.gross_amount", "value": 1000.0, "source": "model"}]}
    cc2 = routing_engine.evaluate_cross_check(rule, p_model, s_model)
    assert cc2["passed"] is False
    assert "同类模型" in cc2["rejected_reason"]

    # 3. 关键金额字段冲突（超 0.06 容差）-> 判定冲突并降级
    s_conflict = {
        "fields": [
            {"name": "total.gross_amount", "value": 1030.0, "source": "ocr"},
            {"name": "total.tax_amount", "value": 130.0, "source": "ocr"},
        ]
    }
    cc3 = routing_engine.evaluate_cross_check(rule, p_res, s_conflict)
    assert cc3["passed"] is False
    assert cc3.get("conflict") is True


def test_global_fallback_and_triggers(fresh_session):
    """断言全局降级与五项兜底触发条件配置化检测（FN-2-10）。"""
    policy = routing_engine.get_effective_policy(fresh_session)

    # 1. 最终置信度低于阈值（如 0.75 < 0.80）
    triggers_low_conf = routing_engine.check_fallback_triggers(
        final_confidence=0.75,
        has_conflict=False,
        verify_failed=False,
        all_providers_failed=False,
        policy=policy,
    )
    assert "最终置信度低于阈值" in triggers_low_conf

    # 2. 关键字段冲突命中
    triggers_conflict = routing_engine.check_fallback_triggers(
        final_confidence=0.92,
        has_conflict=True,
        verify_failed=False,
        all_providers_failed=False,
        policy=policy,
    )
    assert "关键字段冲突（金额/税额/发票号）" in triggers_conflict

    # 3. 未命中启用规则时，流转至人工复核 NEEDS_REVIEW
    res_unmatched = routing_engine.execute_route(
        fresh_session,
        region="US 美国",
        invoice_type="Unknown",
        carrier="Unknown",
    )
    assert res_unmatched["status"] == "manual"
    assert res_unmatched["final_provider"] == "human-fallback"
    assert "Provider全链路降级失败" in res_unmatched["fallback_triggers"]


def test_direct_read_parsers():
    """断言内置直读矩阵（XML、OFD、二维码直读，FN-2-01）：免 Provider 零成本。"""
    # 1. 二维码解码直读
    qr_str = "01,10,011002000111,20000001,1000.00,20261020,98765432101234567890"
    qr_res = intake_parsers.parse_qrcode_text(qr_str)
    assert qr_res is not None
    assert qr_res["invoice_code"] == "011002000111"
    assert qr_res["invoice_no"] == "20000001"
    assert qr_res["gross"] == 1000.0
    assert qr_res["issue_date"] == "2026-10-20"
    assert qr_res["source"] == "qr_code"
    assert qr_res["confidence"] == 0.99

    # 2. XML 直读
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <EInvoice>
      <Header>
        <InvoiceNo>24312000000099999999</InvoiceNo>
        <InvoiceType>数电票</InvoiceType>
        <IssueDate>2026-10-25</IssueDate>
      </Header>
      <Seller><Name>测试销售方</Name></Seller>
      <Total>
        <GrossAmount>5680.00</GrossAmount>
        <NetAmount>5026.55</NetAmount>
        <TaxAmount>653.45</TaxAmount>
      </Total>
    </EInvoice>""".encode("utf-8")
    doc = intake_parsers.parse_einvoice_xml(xml_content)
    assert doc is not None
    assert doc["invoice_no"] == "24312000000099999999"
    assert doc["gross"] == 5680.0
