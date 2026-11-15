# -*- coding: utf-8 -*-
"""匹配就绪化服务与差异分类测试（WP4.4 · FN-6-01~06 · CON-12）。

验证要点：
  1. PO 推断与含税/净额口径识别（FN-6-01）：0387 案差异 ¥13,000.00 恰等于 13% 税额，
     判定为「税额口径」差异而非金额错误；
  2. 差异检测与五类分类服务（FN-6-02）：税额口径（蓝）、尾差（橙）、PO 外费用（紫）、
     红字待关联（红）、Credit Note 待关联（橙）；
  3. 两套容差分开配置（CON-12）：勾稽容差 ±0.06 与 PO 匹配容差 ±S$50 分开生效；
  4. 超容差触发 INVESTIGATING 主动调查钩子（如 0125 案差 S$5,600 > ±S$50）；
  5. GRN 勾稽与 PO 外费用行标记（FN-6-03）：0125 运费行无对应收货标记为 PO 外费用；
  6. 税码映射引擎（FN-6-04 · v1.4 表驱动）：CN 七档 J1~J7、SG 两档 SG-SR/SG-ZR、红字沿用原票；
  7. 差异队列 API：CN+OS 统一待确认队列、已处理计数、双栏确认卡明细完整。
"""

import pytest

from app.services import matching_service, rules


def test_po_tax_variance_inference():
    """断言 PO 推断与含税/净额口径识别（FN-6-01 · 0387 案场景）。"""
    # 0387 案：发票价税合计 ¥113,000.00，PO 净额 ¥100,000.00，税额 ¥13,000.00
    res = matching_service.detect_po_variance(
        instance="CN",
        invoice_amount=113000.00,
        po_amount=100000.00,
        tax_amount=13000.00,
    )
    assert res["is_tax_variance"] is True
    assert "税额口径" in res["diff_types"]
    assert res["variance"] == 13000.00
    assert "判定为「税额口径」差异而非金额错误" in res["analysis"]


def test_five_diff_type_classifications():
    """断言全站统一五类差异分类徽章（FN-6-02）。"""
    # 1. 税额口径
    d1 = matching_service.detect_po_variance(
        instance="CN", invoice_amount=113000.0, po_amount=100000.0, tax_amount=13000.0
    )
    assert "税额口径" in d1["diff_types"]

    # 2. 尾差（0381 案：差额超 0.06 但属于金额冲突）
    d2 = matching_service.detect_po_variance(
        instance="CN", invoice_amount=5680.0, po_amount=5650.0, has_source_conflict=True
    )
    assert "尾差" in d2["diff_types"]

    # 3. PO 外费用（0125 案运费）
    d3 = matching_service.detect_po_variance(
        instance="OS", invoice_amount=84200.0, po_amount=78600.0, has_po_extra_charge=True
    )
    assert "PO 外费用" in d3["diff_types"]

    # 4. 红字待关联（0384 案）
    d4 = matching_service.detect_po_variance(
        instance="CN", invoice_amount=-8420.0, is_credit=True, has_unlinked_credit=True
    )
    assert "红字待关联" in d4["diff_types"]

    # 5. Credit Note 待关联（0123 案）
    d5 = matching_service.detect_po_variance(
        instance="OS", invoice_amount=-2450.0, is_credit=True, has_unlinked_credit=True
    )
    assert "Credit Note 待关联" in d5["diff_types"]


def test_dual_tolerance_separation_and_investigating_hook():
    """断言两套容差分离配置（CON-12）与超容差主动调查钩子。"""
    # A. CN 勾稽容差：差额 0.05 <= 0.06，在容差范围内，不触发调查
    cn_ok = matching_service.detect_po_variance(
        instance="CN", invoice_amount=1000.05, po_amount=1000.00, reconcile_tolerance=0.06
    )
    assert cn_ok["exceeds_tolerance"] is False
    assert cn_ok["trigger_investigating"] is False

    # CN 勾稽容差：差额 0.08 > 0.06，超容差
    cn_exceed = matching_service.detect_po_variance(
        instance="CN", invoice_amount=1000.08, po_amount=1000.00, reconcile_tolerance=0.06
    )
    assert cn_exceed["exceeds_tolerance"] is True
    assert cn_exceed["trigger_investigating"] is True

    # B. OS BTP PO 匹配容差：差额 S$40 <= S$50，在容差范围内
    os_ok = matching_service.detect_po_variance(
        instance="OS", invoice_amount=1040.0, po_amount=1000.0, po_tolerance=50.0
    )
    assert os_ok["exceeds_tolerance"] is False
    assert os_ok["trigger_investigating"] is False

    # 0125 案：差额 S$5,600 远超 ±S$50 → 触发主动调查
    os_exceed = matching_service.detect_po_variance(
        instance="OS", invoice_amount=84200.0, po_amount=78600.0, po_tolerance=50.0
    )
    assert os_exceed["exceeds_tolerance"] is True
    assert os_exceed["trigger_investigating"] is True


def test_tax_code_mapping_v14_engine():
    """断言税码映射引擎 v1.4 表驱动（FN-6-04）。"""
    # 1. CN 七档税率
    cn_cases = [
        ("13%", "J1"), ("0.13", "J1"), ("增值税 13%", "J1"),
        ("9%", "J2"),  ("0.09", "J2"),
        ("6%", "J3"),  ("0.06", "J3"),
        ("3%", "J4"),  ("0.03", "J4"),
        ("1%", "J5"),  ("0.01", "J5"),
        ("0%", "J6"),  ("0.00", "J6"),
        ("免税", "J7"),
    ]
    for rate_input, expected_code in cn_cases:
        res = matching_service.map_tax_code("CN", rate_input)
        assert res["result"] == "PASSED"
        assert res["tax_code"] == expected_code
        assert res["version"] == "v1.4"

    # 2. SG 两档 GST
    sg_cases = [
        ("9%", "SG-SR"), ("GST 9%", "SG-SR"),
        ("0%", "SG-ZR"), ("zero-rated", "SG-ZR"),
    ]
    for rate_input, expected_code in sg_cases:
        res = matching_service.map_tax_code("SG", rate_input)
        assert res["result"] == "PASSED"
        assert res["tax_code"] == expected_code

    # 3. 红字票 / Credit Note 沿用原票税码
    res_credit = matching_service.map_tax_code("CN", "13%", is_credit=True, origin_tax_code="J1")
    assert res_credit["result"] == "PASSED"
    assert res_credit["tax_code"] == "J1"
    assert "冲减方向" in res_credit["usage"]


def test_matching_queue_and_card_api(api_client):
    """断言差异队列 API 与双栏确认卡数据完整性（FN-6-02/06）。"""
    # 1. 差异队列
    r = api_client.get("/v1/matching/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 5
    ids = [it["id"] for it in data["items"]]
    assert "INV-CN-2026-0387" in ids
    assert "INV-CN-2026-0384" in ids
    assert "INV-CN-2026-0381" in ids
    assert "INV-SG-2026-0125" in ids
    assert "INV-SG-2026-0123" in ids

    # 2. 0387 案确认卡数据
    r_card = api_client.get("/v1/matching/queue/INV-CN-2026-0387")
    assert r_card.status_code == 200
    card = r_card.json()
    assert card["supplier"] == "北京中科华创科技有限公司"
    assert card["amount"] == "¥113,000.00"
    detail = card["detail"]
    assert len(detail["comp"]) == 3
    assert "GRN-2026-1102" in detail["grn"]
    assert detail["ai"]["conf"] == 88
    assert "口径差异" in detail["ai"]["conclude"]

    # 3. 税码映射表 API
    r_tax = api_client.get("/v1/matching/taxcodes")
    assert r_tax.status_code == 200
    assert r_tax.json()["version"] == "v1.4"
    assert r_tax.json()["total"] >= 10


def test_allowed_actions_state_edge_alignment(api_client):
    """断言状态机动作边对齐：消灭 live 态 409（任务 3 · FN-6-11、FN-0-02）。"""
    # 0387 案 (NEEDS_REVIEW)：允许放行(release)与补PO行(hold)，禁止退回(return)
    r_0387 = api_client.get("/v1/matching/queue/INV-CN-2026-0387")
    assert r_0387.status_code == 200
    acts_0387 = r_0387.json()["allowed_actions"]
    assert acts_0387["q1_release"]["allowed"] is True
    assert acts_0387["q1_po"]["allowed"] is True
    assert acts_0387["q1_return"]["allowed"] is False
    assert "INVESTIGATING" in acts_0387["q1_return"]["reason"]

    # 0125 案 (INVESTIGATING)：允许放行(release)与退回(return)，禁止再次补PO行(hold)
    r_0125 = api_client.get("/v1/matching/queue/INV-SG-2026-0125")
    assert r_0125.status_code == 200
    acts_0125 = r_0125.json()["allowed_actions"]
    assert acts_0125["q1_release"]["allowed"] is True
    assert acts_0125["q1_po"]["allowed"] is False
    assert "INVESTIGATING" in acts_0125["q1_po"]["reason"]
    assert acts_0125["q1_return"]["allowed"] is True


def test_seed_card_overrides_case_0123_consistency():
    """断言 0123 案种子卡双源对齐无漂移（任务 4 · seeds/ 为单一事实源）。"""
    import json
    from pathlib import Path

    seeds_file = Path(__file__).resolve().parents[2] / "seeds" / "mapping_rules.json"
    seeds_data = json.loads(seeds_file.read_text(encoding="utf-8"))
    c0123_candidate = None
    for item in seeds_data["link_candidates"]["items"]:
        if item["inv"] == "INV-SG-2026-0123":
            c0123_candidate = item
            break
    assert c0123_candidate is not None

    # 比对 _CARD_OVERRIDES["INV-SG-2026-0123"]
    override = matching_service._CARD_OVERRIDES["INV-SG-2026-0123"]
    assert override["amount"] == c0123_candidate["amount"]
    # 候选原票金额 US$49,000.00
    orig_comp = [c for c in override["detail"]["comp"] if "候选原票" in c["k"]][0]
    assert orig_comp["v"] == c0123_candidate["origin"]["amount"]
    assert c0123_candidate["origin"]["caseId"] in orig_comp["k"]
    # 税码 SG-SR
    assert override["detail"]["taxmap"][0]["to"] == "SG-SR"
    # 部分冲减模式
    assert "部分冲减" in override["detail"]["tol"]


def test_uom_quantity_check_rules():
    """断言商品数量计量单位 UOM 对照与换算规则（任务 6 · 20261102 专家口径 S5 第 5 条 · #64）。"""
    # 1. 单位一致数量一致
    res1 = rules.uom_quantity_check({
        "invoice_qty": 500.0, "invoice_uom": "件",
        "po_qty": 500.0, "po_uom": "件",
        "tolerance": 0.0,
    })
    assert res1["result"] == "PASSED"
    assert res1["status"] == "MATCHED"

    # 2. 单位不一致且换算成功（箱 vs EA，1箱=10EA）
    res2 = rules.uom_quantity_check({
        "invoice_qty": 10.0, "invoice_uom": "箱",
        "po_qty": 100.0, "po_uom": "EA",
        "tolerance": 0.0,
    })
    assert res2["result"] == "PASSED"
    assert res2["status"] == "CONVERTED_MATCH"
    assert res2["converted_qty"] == 100.0

    # 3. 单位不一致换算后超容差（箱 vs EA，10箱=100EA vs 90EA）
    res3 = rules.uom_quantity_check({
        "invoice_qty": 10.0, "invoice_uom": "箱",
        "po_qty": 90.0, "po_uom": "EA",
        "tolerance": 0.0,
    })
    assert res3["result"] == "AMOUNT_VARIANCE"
    assert res3["status"] == "UOM_VARIANCE"

    # 4. 缺失换算比率
    res4 = rules.uom_quantity_check({
        "invoice_qty": 10.0, "invoice_uom": "平方米",
        "po_qty": 100.0, "po_uom": "EA",
        "tolerance": 0.0,
    })
    assert res4["result"] == "NOT_VERIFIED"
    assert res4["status"] == "UOM_VARIANCE"


def test_aggregate_po_lines_match_and_ambiguity():
    """断言多明细合计开票与概括描述消歧（任务 7 · 20261102 专家口径 S5 第 2/3 条 · #66/#67）。"""
    # 1. 正常多行聚合（两行 PO 合计 ¥100,000 与发票 ¥100,000 匹配）
    res1 = rules.aggregate_po_lines_match({
        "invoice_amount": 100000.0,
        "po_lines": [
            {"item_no": "0010", "description": "模块A", "amount": 60000.0},
            {"item_no": "0020", "description": "模块B", "amount": 40000.0},
        ],
        "tolerance": 0.06,
    })
    assert res1["result"] == "PASSED"
    assert res1["within_tolerance"] is True
    assert res1["has_ambiguity"] is False

    # 2. 存在重复模糊概括描述（消歧预警）
    res2 = rules.aggregate_po_lines_match({
        "invoice_amount": 100000.0,
        "po_lines": [
            {"item_no": "0010", "description": "技术服务费", "amount": 60000.0},
            {"item_no": "0020", "description": "技术服务费", "amount": 40000.0},
        ],
        "tolerance": 0.06,
    })
    assert res2["within_tolerance"] is True
    assert res2["has_ambiguity"] is True
    assert "歧义待消歧" in res2["ambiguous_reason"]


def test_cost_center_match_rule():
    """断言主数据成本中心比对（任务 8 · 20261102 专家口径 S4 场景 1 · #61）。"""
    # 一致
    c1 = rules.cost_center_match({
        "invoice_cost_center": "CC-2080-HQ", "po_cost_center": "CC-2080-HQ"
    })
    assert c1["matched"] is True
    assert c1["result"] == "PASSED"

    # 前缀匹配一致
    c2 = rules.cost_center_match({
        "invoice_cost_center": "CC-1020 IT-Ops", "po_cost_center": "CC-1020"
    })
    assert c2["matched"] is True

    # 不一致
    c3 = rules.cost_center_match({
        "invoice_cost_center": "CC-2080-HQ", "po_cost_center": "CC-1010-ENG"
    })
    assert c3["matched"] is False
    assert c3["result"] == "AMOUNT_VARIANCE"


def test_assert_pre_filing_link_valid_credit_memo():
    """断言红字发票未关联有效原蓝票号时建档强制拦截（任务 8 · 20261102 S4 #63）。"""
    from app.domain import models as m
    from app.services.mapping_governance import assert_pre_filing_link_valid
    from app.services.errors import CommandError

    # 模拟未关联有效原票号的红字案件
    class DummySession:
        def scalar(self, stmt):
            return None

    dummy_case_unconfirmed = m.Case(
        case_id="INV-CN-2026-9999",
        invoice_type="增值税红字专用发票",
        facts_raw={"invoiceAmount": -5000.0},
        links_raw={"credit_note": {"confirmed": False, "ref": ""}},
    )

    with pytest.raises(CommandError) as exc_info:
        assert_pre_filing_link_valid(DummySession(), dummy_case_unconfirmed)
    assert exc_info.value.code == "E_LINK_UNCONFIRMED"
    assert "建档拦截" in exc_info.value.message
    assert "original_invoice_no" in exc_info.value.message
