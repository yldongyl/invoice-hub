# -*- coding: utf-8 -*-
"""案件聚合查询测试（WP1.2 验收⑤ seed 一致性 · WP1.7 租户上下文强制）。"""

import pytest

from app.services import case_repository as repo
from app.services.tenant import TenantContext
from app.services.errors import CommandError


def ctx(cid: str) -> TenantContext:
    return TenantContext.of_case_id(cid)


@pytest.mark.parametrize("case_id", ["INV-CN-2026-0387", "INV-CN-2026-0379", "INV-SG-2026-0125"])
def test_aggregate_full_case_deep_equal_seed(session, seeds_cases, case_id):
    """三演示案件聚合视图与 seeds/cases.json 深度一致（逐字段，非抽样）。"""
    seed = next(c for c in seeds_cases["cases"] if c["caseId"] == case_id)
    agg = repo.aggregate_case(session, ctx(case_id), case_id)
    assert agg is not None
    assert agg == seed, f"{case_id} 聚合视图与种子不一致"


def test_aggregate_all_11_cases_deep_equal(session, seeds_cases):
    """全部 11 案（含 list 级异构键集）聚合重建逐案一致。"""
    for seed in seeds_cases["cases"]:
        agg = repo.aggregate_case(session, ctx(seed["caseId"]), seed["caseId"])
        assert agg == seed, f"{seed['caseId']} 与种子不一致"


def test_aggregate_missing_case(session):
    assert repo.aggregate_case(session, ctx("INV-CN-2026-9999"), "INV-CN-2026-9999") is None


def test_aggregate_tenant_mismatch_rejected(session):
    """四隔离①：OS 上下文聚合 CN 案件 → E_TENANT_MISMATCH。"""
    with pytest.raises(CommandError) as ei:
        repo.aggregate_case(session, TenantContext.of("OS"), "INV-CN-2026-0387")
    assert ei.value.code == "E_TENANT_MISMATCH"


def test_aggregate_requires_context(session):
    with pytest.raises(CommandError) as ei:
        repo.aggregate_case(session, TenantContext.of(None), "INV-CN-2026-0387")
    assert ei.value.code == "E_TENANT_MISSING"


def test_evidence_field_query(session, seeds_cases):
    ev = repo.get_evidence(session, ctx("INV-CN-2026-0387"), "INV-CN-2026-0387",
                           field="total.gross_amount")
    assert len(ev) >= 1
    assert all(e.field == "total.gross_amount" for e in ev)
    seed_ev = [e for e in next(c for c in seeds_cases["cases"]
                               if c["caseId"] == "INV-CN-2026-0387")["evidence"]
               if e["field"] == "total.gross_amount"]
    assert [e.evidence_raw for e in ev] == seed_ev


def test_timeline_projection(session, seeds_cases):
    from app.domain.registry import get_registry
    rows = repo.get_timeline(session, ctx("INV-SG-2026-0125"), "INV-SG-2026-0125")
    seed = next(c for c in seeds_cases["cases"] if c["caseId"] == "INV-SG-2026-0125")
    assert [r.event_raw for r in rows] == seed["timeline"]
    acts = get_registry().code_set("timeline_event")
    assert all(r.act in acts for r in rows)


def test_object_links_five_types(session):
    """五类 Link 可查询（FN-0-04）；0387 应有 来自/匹配/收货/包含 四类（非冲减案无冲减）。"""
    rows = repo.get_links(session, ctx("INV-CN-2026-0387"), "INV-CN-2026-0387")
    types = {r.link_type for r in rows}
    assert {"来自", "匹配", "收货", "包含"} <= types
    assert "冲减" not in types  # 非红字案
    # 0384 红字票：relation=CANDIDATE 候选冲减行存在但未确认（confirmed=false，FN-4-06/6-10）
    offset = [r for r in repo.get_links(session, ctx("INV-CN-2026-0384"), "INV-CN-2026-0384")
              if r.link_type == "冲减"]
    assert len(offset) == 1 and offset[0].ref == "INV-CN-2026-0310"
    assert offset[0].link_raw["confirmed"] is False


def test_list_cases_filters(session, seeds_cases):
    items, total, _, _ = repo.list_cases(session, TenantContext.of("OS"))
    assert total == sum(1 for c in seeds_cases["cases"] if c["meta"]["instance"] == "OS")
    assert all(i["meta"]["instance"] == "OS" for i in items)
    cn = repo.list_cases(session, TenantContext.of("CN"), status="BLOCKED")[0]
    os_ = repo.list_cases(session, TenantContext.of("OS"), status="BLOCKED")[0]
    assert {i["caseId"] for i in cn} == {"INV-CN-2026-0385", "INV-CN-2026-0379"}
    assert {i["caseId"] for i in os_} == {"INV-SG-2026-0122"}
    r_cn = repo.list_cases(session, TenantContext.of("CN"), risk="重复票")[0]
    r_os = repo.list_cases(session, TenantContext.of("OS"), risk="重复票")[0]
    assert {i["caseId"] for i in r_cn} == {"INV-CN-2026-0385"}
    assert {i["caseId"] for i in r_os} == {"INV-SG-2026-0122"}
    items, _, _, _ = repo.list_cases(session, TenantContext.of("OS"), keyword="Siemens")
    assert [i["caseId"] for i in items] == ["INV-SG-2026-0125"]
    # CN 上下文永远检索不到 OS 案件（数据隔离）
    assert repo.list_cases(session, TenantContext.of("CN"), keyword="Siemens")[1] == 0


def test_check_rows(session, seeds_cases):
    checks = repo.check_rows(session, ctx("INV-CN-2026-0379"), "INV-CN-2026-0379")
    seed = next(c for c in seeds_cases["cases"] if c["caseId"] == "INV-CN-2026-0379")
    assert checks == seed["checks"]
