# -*- coding: utf-8 -*-
"""案件仓储（WP1.2 聚合查询 · WP1.7 租户上下文强制注入收口）。

口径：
  - 一切读写必须携带 TenantContext（instance 缺失即 E_TENANT_MISSING；与数据归属不符即
    E_TENANT_MISMATCH 越权拒绝——四隔离①在存储层的实现）；
  - 聚合重建严格按 seed 原始顶层键集还原——full 视图输出逐字段等于 seeds/cases.json
    对应案件（P02 验收⑤），天然满足契约测试；
  - 列表/摘要投影输出 = 契约合法的 list 级案件形态（caseId/detail_level/status/summary/
    meta/facts，与种子同构）——满足 P02 §3「响应结构必须过 contracts Schema 校验」；
  - 本层只读（写路径一律经 governed_commands）。
"""

from sqlalchemy import func, or_, select

from app.domain import models as m
from app.services.tenant import TenantContext


def _evidence_by_case(session, case_id):
    rows = session.scalars(
        select(m.FieldEvidence).where(m.FieldEvidence.case_id == case_id)
        .order_by(m.FieldEvidence.seq)).all()
    return [r.evidence_raw for r in rows]


def aggregate_case(session, ctx: TenantContext, case_id: str) -> dict | None:
    """case-detail 全量视图（FN-0-01/05/07/10/04 聚合；ctx 校验归属实例）。"""
    ctx.assert_matches_case_id(case_id)
    c = session.get(m.Case, case_id)
    if c is None:
        return None
    values = {
        "caseId": c.case_id, "detail_level": c.detail_level, "status": c.status,
        "summary": c.summary, "meta": c.meta_raw, "facts": c.facts_raw,
        "checks": c.checks_raw, "evidence": _evidence_by_case(session, case_id),
        "timeline": [r.event_raw for r in session.scalars(
            select(m.TimelineEvent).where(m.TimelineEvent.case_id == case_id)
            .order_by(m.TimelineEvent.seq))],
        "links": c.links_raw, "items": c.items_raw, "file": c.file_raw,
        "source_xml": c.source_xml, "paper_template": c.paper_template,
        "ai": c.ai_raw, "nextAction": c.next_action_raw,
    }
    return {k: values[k] for k in c.seed_keys}


def get_case_row(session, ctx: TenantContext, case_id: str) -> m.Case | None:
    ctx.assert_matches_case_id(case_id)
    return session.get(m.Case, case_id)


def get_links(session, ctx: TenantContext, case_id: str, link_type: str | None = None):
    """五类 Link 查询（FN-0-04 可查询）。"""
    ctx.assert_matches_case_id(case_id)
    q = select(m.ObjectLink).where(m.ObjectLink.case_id == case_id)
    if link_type:
        q = q.where(m.ObjectLink.link_type == link_type)
    return session.scalars(q.order_by(m.ObjectLink.seq)).all()


def get_evidence(session, ctx: TenantContext, case_id: str, field: str | None = None):
    """字段级证据查询（FN-0-05；evidence?field= 入口）。"""
    ctx.assert_matches_case_id(case_id)
    q = select(m.FieldEvidence).where(m.FieldEvidence.case_id == case_id)
    if field:
        q = q.where(m.FieldEvidence.field == field)
    return session.scalars(q.order_by(m.FieldEvidence.seq)).all()


def get_timeline(session, ctx: TenantContext, case_id: str):
    ctx.assert_matches_case_id(case_id)
    return session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == case_id)
        .order_by(m.TimelineEvent.seq)).all()


def summary_of(session, c: m.Case) -> dict:
    """列表投影（M2 WP2.1 · M-M1-005 瘦身）：GET /v1/cases 行一律投影形态
    （caseId/detail_level/status/summary/meta/facts，契约=contracts/case-read.schema
    $defs.listProjection，内部读面首次接线前的形态收敛，无既有消费者）。

    full 案件不再内嵌全量聚合——详情走 GET /v1/cases/{id}?view=full（northbound
    invoice-case.schema.json 契约不变，openapi v1 承诺保持）；列表键集与 list 案件同构，
    投影不再过 invoice-case.schema（allOf full 全要素约束所迫的聚合膨胀由此关闭）。
    """
    return {
        "caseId": c.case_id, "detail_level": c.detail_level, "status": c.status,
        "summary": c.summary, "meta": c.meta_raw, "facts": c.facts_raw,
    }


def list_cases(session, ctx: TenantContext, *, status: str | None = None,
               keyword: str | None = None, risk: str | None = None,
               page: int = 1, page_size: int = 20):
    """案件列表（FN-8-01；实例过滤由 ctx 强制注入——四隔离①）。"""
    q = select(m.Case).where(m.Case.instance == ctx.instance)
    if status:
        q = q.where(m.Case.status == status)
    if risk:
        q = q.where(m.Case.risk_label == risk)
    if keyword:
        like = f"%{keyword}%"
        q = q.where(or_(m.Case.case_id.like(like), m.Case.supplier.like(like)))
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.scalars(q.order_by(m.Case.case_id)
                           .offset((page - 1) * page_size).limit(page_size)).all()
    return [summary_of(session, r) for r in rows], total, page, page_size


def check_rows(session, ctx: TenantContext, case_id: str):
    ctx.assert_matches_case_id(case_id)
    rows = session.scalars(
        select(m.CheckResult).where(m.CheckResult.case_id == case_id)
        .order_by(m.CheckResult.seq)).all()
    return {r.item: {"result": r.result, "note": r.note} for r in rows}
