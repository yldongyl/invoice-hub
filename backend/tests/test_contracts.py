# -*- coding: utf-8 -*-
"""契约测试（WP1.1–1.2 验收：聚合查询输出过 contracts/invoice-case.schema.json 校验）。

全部 11 案（full+list）逐一验证；时间线事件另过 events.schema.json；
枚举字段值全部 ∈ enum-registry / 契约内联取值域（P02 验收④）。
"""

from sqlalchemy import select

from app.domain import models as m
from app.domain.registry import get_contract_enums, get_registry
from app.services import case_repository as repo
from tests.conftest import schema_errors


def test_aggregate_passes_invoice_case_schema(session, seeds_cases, case_validator):
    for seed in seeds_cases["cases"]:
        agg = repo.aggregate_case(session, seed["caseId"])
        errs = schema_errors(case_validator, agg)
        assert not errs, f"{seed['caseId']} 契约校验失败: {[e.message for e in errs]}"


def test_timeline_items_pass_events_schema(session, seeds_cases, events_validator):
    for seed in seeds_cases["cases"]:
        for ev in seed.get("timeline") or []:
            errs = schema_errors(events_validator, ev)
            assert not errs, f"{seed['caseId']} timeline 事件校验失败: {ev}"


def test_all_enum_values_in_registry(session, seeds_cases):
    """枚举一致性：案件状态/来源/校验结果/事件码/主体/风险标签/实例/票态全在注册表或契约取值域。"""
    reg, ce = get_registry(), get_contract_enums()
    for c in session.scalars(select(m.Case)):
        assert c.status in reg.code_set("case_status"), c.case_id
        assert c.instance in ce.instance, c.case_id
        if c.risk_label is not None:
            assert c.risk_label in reg.code_set("risk_label"), c.case_id
    for e in session.scalars(select(m.FieldEvidence)):
        assert e.source in reg.code_set("field_source")
        assert 0.0 <= e.confidence <= 1.0
    for r in session.scalars(select(m.CheckResult)):
        assert r.item in reg.code_set("check_item")
        assert r.result in reg.code_set("check_result")
    for t in session.scalars(select(m.TimelineEvent)):
        assert t.act in reg.code_set("timeline_event")
        assert t.actor in reg.code_set("timeline_actor")
    for b in session.scalars(select(m.Batch)):
        st = {"受理中": "受理中 / 识别中", "识别中": "受理中 / 识别中"}.get(b.status, b.status)
        assert st in reg.code_set("batch_status"), b.batch_id
    for c in seeds_cases["cases"]:
        links = c.get("links") or {}
        if links.get("po_state") is not None:
            assert links["po_state"] in ce.check_result
        credit = links.get("credit_note")
        if credit:
            assert credit["relation"] in ce.credit_relation


def test_five_link_types_queryable(session, seeds_cases):
    """五类 Link（匹配/收货/来自/冲减/包含）词表 = 清单 FN-0-04，装载后逐案可查。"""
    from app.domain.models import LINK_TYPES
    seen = set()
    for c in seeds_cases["cases"]:
        rows = session.scalars(select(m.ObjectLink).where(m.ObjectLink.case_id == c["caseId"]))
        for r in rows:
            assert r.link_type in LINK_TYPES, (c["caseId"], r.link_type)
            seen.add(r.link_type)
    assert set(LINK_TYPES) <= seen  # 全部五类至少出现一次（跨 11 案）
