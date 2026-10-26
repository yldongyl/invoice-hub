# -*- coding: utf-8 -*-
"""WP1.6 四校验编排器测试（独立执行 / BLOCKED 不中止其余 / 结果只由规则引擎写入）。"""

import pytest

from app.domain import models as m
from app.domain.registry import get_registry
from app.services import case_repository as repo, orchestrator, rules, state_machine
from app.services.tenant import TenantContext

ITEMS = None  # 运行期取 registry.check_item


def _items():
    return get_registry().category("check_item")


def _ctx_for(session, cid, **extra):
    case = session.get(m.Case, cid)
    return orchestrator.build_context(session, case, extra=extra)


SUP = {"name": "北京中科华创科技有限公司", "tax_id": "91110108MA01C3872X",
       "master_name": "北京中科华创科技有限公司", "master_tax_id": "91110108MA01C3872X",
       "master_id": "SUP-10042"}
BUY = {"name": "澜坞（上海）采购科技有限公司", "master_entities": ["澜坞（上海）采购科技有限公司"]}


def test_run_all_four_items_independent(fresh_session):
    """0387：四项全产出；缺输入项如实 NOT_VERIFIED，不牵连其余。"""
    ctx = _ctx_for(fresh_session, "INV-CN-2026-0387", supplier=SUP, buyer=BUY)
    res = orchestrator.run_all(fresh_session, ctx)
    assert set(res.keys()) == set(_items())
    assert res["authenticity"]["result"] == "PASSED"           # sm2 ok=True
    assert res["poMatch"]["result"] == "AMOUNT_VARIANCE"       # variance 13000 > ±50
    assert res["duplicate"]["result"] == "NOT_VERIFIED"        # 池未接入（M3）
    assert res["supplierMatch"]["result"] in ("PASSED", "NOT_VERIFIED")
    for item in _items():
        assert res[item]["result"] in get_registry().code_set("check_result")


def test_rule_exception_does_not_aboart_others(fresh_session, monkeypatch):
    """单项规则异常 → 该项 NOT_VERIFIED + 注记，其余三项照常产出。"""
    ctx = _ctx_for(fresh_session, "INV-CN-2026-0387", supplier=SUP, buyer=BUY)
    orig = rules.RULES["supplier_master_match"]
    monkeypatch.setitem(rules.RULES, "supplier_master_match",
                        lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
    res = orchestrator.run_all(fresh_session, ctx)
    assert res["supplierMatch"]["result"] == "NOT_VERIFIED"
    assert res["authenticity"]["result"] == "PASSED" and res["poMatch"]["result"] == "AMOUNT_VARIANCE"


def test_redline_blocked_does_not_aboart_remaining_checks(fresh_session):
    """BLOCKED 不中止其余校验：RECOGNIZED+验签失败 → 四项全产出 + 红线流转 + 建档挂起。"""
    case = fresh_session.get(m.Case, "INV-CN-2026-0379")
    case.status = state_machine.STATUS.RECOGNIZED
    fresh_session.commit()
    ctx = _ctx_for(fresh_session, "INV-CN-2026-0379",
                   supplier={"name": case.supplier, "tax_id": "91510100MA62T3791X",
                             "master_name": case.supplier, "master_tax_id": "91510100MA62T3791X",
                             "master_id": "SUP-10377"})
    res = orchestrator.run_all(fresh_session, ctx)
    assert res["authenticity"]["result"] == "FAILED"
    out = orchestrator.apply_results(fresh_session, case, res)
    assert out["redline"]["item"] == "authenticity"
    fresh = fresh_session.get(m.Case, "INV-CN-2026-0379")
    assert fresh.status == "BLOCKED" and fresh.doc_hold_pending is True
    assert set(fresh.checks_raw.keys()) == set(_items())          # 四项结论全保留（供解除参考）
    assert fresh.checks_raw["duplicate"]["result"] == "NOT_VERIFIED"


def test_results_written_only_via_engine_snapshot(fresh_session):
    """apply_results 同步投影与快照；聚合视图的 checks 即引擎输出。"""
    case = fresh_session.get(m.Case, "INV-CN-2026-0386")
    ctx = _ctx_for(fresh_session, "INV-CN-2026-0386",
                   supplier={"name": case.supplier, "master_name": case.supplier,
                             "master_id": None}, buyer=BUY)
    res = orchestrator.run_all(fresh_session, ctx)
    before = dict(case.checks_raw)
    orchestrator.apply_results(fresh_session, case, res)
    agg = repo.aggregate_case(fresh_session, TenantContext.of("CN"), "INV-CN-2026-0386")
    assert agg["checks"] != before
    assert agg["checks"] == {k: {"result": v["result"], "note": v["note"]} for k, v in res.items()}
    rows = repo.check_rows(fresh_session, TenantContext.of("CN"), "INV-CN-2026-0386")
    assert rows == agg["checks"]


def test_no_po_pomatch_not_verified(fresh_session):
    case = fresh_session.get(m.Case, "INV-CN-2026-0383")
    ctx = _ctx_for(fresh_session, "INV-CN-2026-0383",
                   supplier={"name": case.supplier, "master_name": case.supplier}, buyer=BUY)
    res = orchestrator.run_all(fresh_session, ctx)
    assert res["poMatch"]["result"] == "NOT_VERIFIED"


def test_os_directory_and_dedup_hit(fresh_session):
    """OS 名录命中→PASSED；查重池命中→FAILED 且 redline=duplicate。"""
    ctx = _ctx_for(fresh_session, "INV-SG-2026-0125", taxid_directory_hit=True,
                   pool_keys=["SI-SG-77125|84200.00|SUP-20871"])
    res = orchestrator.run_all(fresh_session, ctx)
    assert res["authenticity"]["result"] == "PASSED"
    assert res["duplicate"]["result"] == "FAILED"
    assert orchestrator.redline_of(res)["item"] == "duplicate"
