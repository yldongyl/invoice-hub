# -*- coding: utf-8 -*-
"""案件聚合查询测试（WP1.2 · P02 验收⑤ seed 一致性逐字段断言）。"""

import pytest

from app.services import case_repository as repo


@pytest.mark.parametrize("case_id", ["INV-CN-2026-0387", "INV-CN-2026-0379", "INV-SG-2026-0125"])
def test_aggregate_full_case_deep_equal_seed(session, seeds_cases, case_id):
    """三演示案件聚合视图与 seeds/cases.json 深度一致（逐字段，非抽样）。"""
    seed = next(c for c in seeds_cases["cases"] if c["caseId"] == case_id)
    agg = repo.aggregate_case(session, case_id)
    assert agg is not None
    assert agg == seed, f"{case_id} 聚合视图与种子不一致"


def test_aggregate_all_11_cases_deep_equal(session, seeds_cases):
    """全部 11 案（含 list 级异构键集）聚合重建逐案一致。"""
    for seed in seeds_cases["cases"]:
        agg = repo.aggregate_case(session, seed["caseId"])
        assert agg == seed, f"{seed['caseId']} 与种子不一致"


def test_aggregate_missing_case(session):
    assert repo.aggregate_case(session, "INV-CN-2026-9999") is None


def test_evidence_field_query(session, seeds_cases):
    ev = repo.get_evidence(session, "INV-CN-2026-0387", field="total.gross_amount")
    assert len(ev) >= 1
    assert all(e.field == "total.gross_amount" for e in ev)
    seed_ev = [e for e in next(c for c in seeds_cases["cases"]
                               if c["caseId"] == "INV-CN-2026-0387")["evidence"]
               if e["field"] == "total.gross_amount"]
    assert [e.evidence_raw for e in ev] == seed_ev


def test_timeline_projection(session, seeds_cases):
    from app.domain.registry import get_registry
    rows = repo.get_timeline(session, "INV-SG-2026-0125")
    seed = next(c for c in seeds_cases["cases"] if c["caseId"] == "INV-SG-2026-0125")
    assert [r.event_raw for r in rows] == seed["timeline"]
    acts = get_registry().code_set("timeline_event")
    assert all(r.act in acts for r in rows)


def test_object_links_five_types(session):
    """五类 Link 可查询（FN-0-04）；0387 应有 来自/匹配/收货/包含 四类（非冲减案无冲减）。"""
    rows = repo.get_links(session, "INV-CN-2026-0387")
    types = {r.link_type for r in rows}
    assert {"来自", "匹配", "收货", "包含"} <= types
    assert "冲减" not in types  # 非红字案
    # 0384 红字票：relation=CANDIDATE 候选冲减行存在但未确认（confirmed=false，FN-4-06/6-10）
    offset = [r for r in repo.get_links(session, "INV-CN-2026-0384") if r.link_type == "冲减"]
    assert len(offset) == 1 and offset[0].ref == "INV-CN-2026-0310"
    assert offset[0].link_raw["confirmed"] is False


def test_list_cases_filters(session, seeds_cases):
    items, total, _, _ = repo.list_cases(session, instance="OS")
    assert total == sum(1 for c in seeds_cases["cases"] if c["meta"]["instance"] == "OS")
    assert all(i["instance"] == "OS" for i in items)
    items, total, _, _ = repo.list_cases(session, status="BLOCKED")
    assert total == 3  # 0385 / 0379 / 0122
    items, total, _, _ = repo.list_cases(session, risk="重复票")
    assert {i["caseId"] for i in items} == {"INV-CN-2026-0385", "INV-SG-2026-0122"}
    items, total, _, _ = repo.list_cases(session, keyword="Siemens")
    assert [i["caseId"] for i in items] == ["INV-SG-2026-0125"]


def test_check_rows(session, seeds_cases):
    checks = repo.check_rows(session, "INV-CN-2026-0379")
    seed = next(c for c in seeds_cases["cases"] if c["caseId"] == "INV-CN-2026-0379")
    assert checks == seed["checks"]
