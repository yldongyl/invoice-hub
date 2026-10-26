# -*- coding: utf-8 -*-
"""WP1.6 规则引擎测试（P02 验收：正反用例 + 两套容差边界值 ±0.06 / ±S$50 恰好等于与超出；
注册制门禁：未注册/已注册未实装均拒绝）。"""

import pytest

from app.domain.registry import get_registry
from app.services import rules
from app.services.errors import E_RULE_NOT_IMPLEMENTED, E_RULE_NOT_REGISTERED, CommandError

BASE = {"instance": "CN", "tolerance_reconcile": 0.06, "tolerance_po": 50}


def _ctx(**kw):
    return {**BASE, **kw}


# ── 金额勾稽：正反 + 边界 ─────────────────────────────────────────────────────

def test_amount_tax_sum_positive_negative():
    r = rules.amount_tax_sum_check(_ctx(net=100000.0, tax=13000.0, gross=113000.0))
    assert r["result"] == "PASSED" and r["rule_id"] == "amount_tax_sum_check"
    bad = rules.amount_tax_sum_check(_ctx(net=100000.0, tax=13000.0, gross=113050.0))
    assert bad["result"] == "FAILED"


def test_amount_tax_sum_tolerance_boundary():
    """±0.06：恰好等于 → 容差内；+0.01 → 超出。"""
    eq = rules.amount_tax_sum_check(_ctx(net=100.0, tax=13.0, gross=113.06))
    over = rules.amount_tax_sum_check(_ctx(net=100.0, tax=13.0, gross=113.07))
    assert eq["result"] == "PASSED" and over["result"] == "FAILED"


def test_amount_sum_check_os():
    ok = rules.amount_sum_check(_ctx(instance="OS", net=78600.0, tax=4100.0, freight=1500.0,
                                     gross=84200.0))
    bad = rules.amount_sum_check(_ctx(instance="OS", net=78600.0, tax=4100.0, freight=1501.0,
                                      gross=84200.0))
    assert ok["result"] == "PASSED" and bad["result"] == "FAILED"


def test_line_amount_sum_check():
    ok = rules.line_amount_sum_check(_ctx(net=100000.0,
                                          lines=[{"amount": 76000.0}, {"amount": 24000.0}]))
    assert ok["result"] == "PASSED"
    bad = rules.line_amount_sum_check(_ctx(net=100000.0,
                                           lines=[{"amount": 76000.0}, {"amount": 24100.0}]))
    assert bad["result"] == "FAILED"
    none = rules.line_amount_sum_check(_ctx(net=1.0, lines=[]))
    assert none["result"] == "NOT_VERIFIED"


def test_tolerance_check_both_schemes_boundaries():
    """CON-12：两套容差分开判定——勾稽 ±0.06 / PO ±S$50；恰好等于=容差内。"""
    t1 = rules.tolerance_check(_ctx(kind="reconcile", diff=-0.06))
    t2 = rules.tolerance_check(_ctx(kind="reconcile", diff=-0.07))
    t3 = rules.tolerance_check(_ctx(kind="po", diff=50.0))
    t4 = rules.tolerance_check(_ctx(kind="po", diff=50.01))
    assert t1["result"] == "PASSED" and t2["result"] == "AMOUNT_VARIANCE"
    assert t3["result"] == "PASSED" and t4["result"] == "AMOUNT_VARIANCE"
    assert "容差" in t1["note"] and "PO 匹配" in t3["note"]


# ── 格式/区间/币种/税号 ──────────────────────────────────────────────────────

def test_invoice_no_format_seed_passes():
    assert rules.invoice_no_format_check(_ctx(invoice_no="24112000000387"))["result"] == "PASSED"
    assert rules.invoice_no_format_check(
        _ctx(instance="OS", invoice_no="SI-SG-77125"))["result"] == "PASSED"
    assert rules.invoice_no_format_check(_ctx(invoice_no="bad id!!"))["result"] == "FAILED"


def test_date_valid_range_boundaries():
    ok = rules.date_valid_range(_ctx(issue_date="2026-10-17", today="2026-10-26"))
    fut = rules.date_valid_range(_ctx(issue_date="2026-11-01", today="2026-10-26"))
    old = rules.date_valid_range(_ctx(issue_date="2014-12-31", today="2026-10-26"))
    bad = rules.date_valid_range(_ctx(issue_date="2026-13-99", today="2026-10-26"))
    assert ok["result"] == "PASSED"
    assert fut["result"] == old["result"] == bad["result"] == "FAILED"


def test_currency_and_uen():
    assert rules.currency_iso_check(_ctx(currency="CNY"))["result"] == "PASSED"
    assert rules.currency_iso_check(_ctx(currency="rmb"))["result"] == "FAILED"
    assert rules.sg_uen_format_check(_ctx(tax_id="M90345678A"))["result"] == "PASSED"
    assert rules.sg_uen_format_check(_ctx(tax_id="M9034567A"))["result"] == "FAILED"


def _valid_uscc(prefix17):
    """用 GB32100 权重补出合法校验位（正反用例的「正」）。"""
    tot = sum(rules._CN_CHARSET.index(prefix17[i]) * rules._CN_W[i] for i in range(17))
    return prefix17 + rules._CN_CHARSET[(31 - tot % 31) % 31]


def test_tax_id_checksum_structure_checksum_demo():
    good = _valid_uscc("91110108MA01C3872")
    assert rules.tax_id_checksum(_ctx(tax_id=good))["result"] == "PASSED"
    demo = rules.tax_id_checksum(_ctx(tax_id="91110108MA01C3872X"))
    assert demo["result"] == "NOT_VERIFIED" and "虚构" in demo["note"]
    broken = rules.tax_id_checksum(_ctx(tax_id="91110"))
    assert broken["result"] == "FAILED"
    os_ = rules.tax_id_checksum(_ctx(instance="OS", tax_id="M90345678A"))
    assert os_["result"] == "NOT_VERIFIED"


# ── 主数据/实体 ──────────────────────────────────────────────────────────────

def test_supplier_and_buyer_match():
    s = {"name": "北京中科华创科技有限公司", "tax_id": "91110108MA01C3872X",
         "master_name": "北京中科华创科技有限公司", "master_tax_id": "91110108MA01C3872X",
         "master_id": "SUP-10042"}
    assert rules.supplier_master_match(_ctx(supplier=s))["result"] == "PASSED"
    s2 = dict(s, master_tax_id="91110108MA01C3872Y")
    assert rules.supplier_master_match(_ctx(supplier=s2))["result"] == "FAILED"
    assert rules.supplier_master_match(_ctx(supplier={"name": "x"}))["result"] == "NOT_VERIFIED"
    b = {"name": "澜坞（上海）采购科技有限公司", "master_entities": ["澜坞（上海）采购科技有限公司"]}
    assert rules.buyer_entity_match(_ctx(buyer=b))["result"] == "PASSED"
    b2 = {"name": "Lanwu Procurement Technology (Singapore) Pte. Ltd.",
          "master_entities": ["澜坞（上海）采购科技有限公司"]}
    assert rules.buyer_entity_match(_ctx(instance="OS", buyer=b2))["result"] == "FAILED"


# ── 红线与查重键（CON-05） ───────────────────────────────────────────────────

def test_redline_policy_branches():
    failed = rules.redline_policy(_ctx(authenticity_result="FAILED"))
    assert failed["result"] == "FAILED" and "BLOCKED" in failed["note"]
    assert rules.redline_policy(_ctx(authenticity_result="NOT_VERIFIED"))["result"] == "NOT_VERIFIED"
    assert rules.redline_policy(_ctx(authenticity_result="PASSED"))["result"] == "PASSED"


def test_dedup_business_key_two_instances():
    """CN=代码(空→空串)+号码+价税合计（税号辅助）；OS=号码+价税合计+供应商。"""
    cn1 = rules.dedup_business_key(_ctx(invoice_code=None, invoice_no="24112000000387",
                                        gross=113000.0, tax_id="T"))
    cn2 = rules.dedup_business_key(_ctx(invoice_code="", invoice_no="24112000000387",
                                         gross=113000.0, tax_id="OTHER"))
    assert cn1["note"].split("：")[-1].split("（")[0] == cn2["note"].split("：")[-1].split("（")[0]
    assert "seller_tax_id" in cn1["note"]
    os_ = rules.dedup_business_key(_ctx(instance="OS", invoice_no="SCH-SG-77410",
                                        gross=128900.0, supplier_id="SUP-20871"))
    assert "SCH-SG-77410|128900.00|SUP-20871" in os_["note"]


# ── 置信度分档与降级标注（FN-0-06） ──────────────────────────────────────────

def test_confidence_bands_from_registry():
    codes = set(get_registry().category("confidence_band"))
    assert rules.confidence_band(95) == "≥95%"
    assert rules.confidence_band(94) == rules.confidence_band(80) == "80–94%"
    assert rules.confidence_band(79) == "<80%"
    for p in (100, 95, 94, 80, 79, 0):
        assert rules.confidence_band(p) in codes


def test_auth_failure_degradation_marks_all_fields():
    rep = rules.auth_failure_degradation({"authenticity_result": "FAILED",
                                          "field_bands": {"total.gross_amount": 96,
                                                          "header.invoice_no": 99}})
    assert rep["degraded"] is True
    assert all(f["degrade_note"] for f in rep["fields"]) and len(rep["fields"]) == 2
    ok = rules.auth_failure_degradation({"authenticity_result": "PASSED",
                                         "field_bands": {"a": 90}})
    assert ok["degraded"] is False and ok["fields"][0]["degrade_note"] is None


# ── 注册制门禁 ───────────────────────────────────────────────────────────────

def test_unregistered_rule_rejected():
    with pytest.raises(CommandError) as ei:
        rules.run_rule("made_up_rule", _ctx())
    assert ei.value.code == E_RULE_NOT_REGISTERED


def test_registered_but_unimplemented_rule_rejected():
    """已注册未实装（归属 M3/M4）：显式报错，不静默缺席。"""
    for rid in ("tax_code_mapping", "po_line_coverage", "credit_link_check",
                "gst_rate_sg_check", "manual_edit_audit", "tax_rate_13_check"):
        with pytest.raises(CommandError) as ei:
            rules.run_rule(rid, _ctx())
        assert ei.value.code == E_RULE_NOT_IMPLEMENTED, rid


def test_chinese_family_alias_resolves_to_machine_id():
    r = rules.run_rule("行级勾稽", _ctx(net=1.0, lines=[{"amount": 1.0}]))
    assert r["rule_id"] == "line_amount_sum_check"
