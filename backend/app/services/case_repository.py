# -*- coding: utf-8 -*-
"""案件仓储（WP1.2 · 案件聚合查询）。

提供一次取出 case-detail 所需全量视图（meta/checks/字段分组含证据/timeline/links/items/file），
重建严格按 seed 原始顶层键集还原——输出必须逐字段等于 seeds/cases.json 对应案件
（P02 验收⑤），从而天然满足 contracts/invoice-case.schema.json 契约测试。
本层只读（写路径 WP1.5 受控命令框架实装后接入）。
"""

from sqlalchemy import func, or_, select

from app.domain import models as m


def _evidence_by_case(session, case_id):
    rows = session.scalars(
        select(m.FieldEvidence).where(m.FieldEvidence.case_id == case_id)
        .order_by(m.FieldEvidence.seq)).all()
    return [r.evidence_raw for r in rows]


def aggregate_case(session, case_id: str) -> dict | None:
    """case-detail 全量视图（FN-0-01/05/07/10/04 聚合）。"""
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


def get_links(session, case_id: str, link_type: str | None = None):
    """五类 Link 查询（FN-0-04 可查询）。"""
    q = select(m.ObjectLink).where(m.ObjectLink.case_id == case_id)
    if link_type:
        q = q.where(m.ObjectLink.link_type == link_type)
    return session.scalars(q.order_by(m.ObjectLink.seq)).all()


def get_evidence(session, case_id: str, field: str | None = None):
    """字段级证据查询（FN-0-05；evidence?field= 入口）。"""
    q = select(m.FieldEvidence).where(m.FieldEvidence.case_id == case_id)
    if field:
        q = q.where(m.FieldEvidence.field == field)
    return session.scalars(q.order_by(m.FieldEvidence.seq)).all()


def get_timeline(session, case_id: str):
    return session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == case_id)
        .order_by(m.TimelineEvent.seq)).all()


def list_cases(session, *, instance: str | None = None, status: str | None = None,
               keyword: str | None = None, risk: str | None = None,
               page: int = 1, page_size: int = 20):
    """案件列表（FN-8-01 读模型最小口径；租户上下文强制注入属 WP1.7，见接口 TODO 注记）。"""
    q = select(m.Case)
    if instance:
        q = q.where(m.Case.instance == instance)
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
    return [summary_of(r) for r in rows], total, page, page_size


def summary_of(c: m.Case) -> dict:
    """列表/摘要投影（FN-8-01 列口径；full 聚合的子集）。"""
    return {
        "caseId": c.case_id, "status": c.status, "detail_level": c.detail_level,
        "instance": c.instance, "region": c.region, "type": c.invoice_type,
        "supplier": c.supplier, "supplier_id": c.supplier_id,
        "amount": c.amount_display, "currency": c.currency,
        "confidence": c.confidence, "provider": c.provider, "po": c.po,
        "risk_label": c.risk_label, "claimed_by": c.claimed_by,
        "doc_hold_pending": c.doc_hold_pending, "summary": c.summary,
    }


def check_rows(session, case_id: str):
    rows = session.scalars(
        select(m.CheckResult).where(m.CheckResult.case_id == case_id)
        .order_by(m.CheckResult.seq)).all()
    return {r.item: {"result": r.result, "note": r.note} for r in rows}
