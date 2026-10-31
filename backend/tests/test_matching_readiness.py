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
