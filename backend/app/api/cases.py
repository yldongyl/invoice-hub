# -*- coding: utf-8 -*-
"""案件只读 API（P02 §3 最小 API 面 → M2 WP2.1 读面收口）。

口径：
  - WP1.7：所有查询必须携带租户上下文 instance（CN|OS）——缺失 E_TENANT_MISSING→400、
    越权（数据归属实例不符）E_TENANT_MISMATCH→403；
  - M2 列表瘦身（M-M1-005，CHANGELOG ⑦）：`GET /v1/cases` 行=case-read.schema
    listProjection 投影（full 案件不再内嵌全量聚合；列表不在北向 openapi 面，无既有消费者）；
    `?view=switcher`=case-detail 案件切换器（三 full 案：号+票种+状态，FN-8-03/FN-0-14）；
  - 北向集成面（openapi.yaml v1 FROZEN）承诺不变：`GET /v1/cases/{id}` view=summary|full
    均返回完整聚合（契约 allOf 所迫，R5 §5.3 双形态口径维持）并过 invoice-case.schema；
  - evidence 项级过 $defs/evidenceEntry、timeline 项级过 events.schema（契约测试断言）；
  - 写路径（actions/risk-challenge）已由 WP1.5 落地于 api/actions.py，全部经受控命令框架。
"""

from fastapi import APIRouter, HTTPException, Query, Response

from app.services import case_repository as repo
from app.services import dashboard as dash
from app.services import object_store, rbac_service
from app.services.audit_chain import append_block, new_trace_id, now_iso
from app.services.errors import CommandError
from app.services.persistence import get_session
from app.services.tenant import TenantContext

router = APIRouter(prefix="/v1")


def _fail(e: CommandError):
    raise HTTPException(status_code=e.http, detail={"error_code": e.code, "message": e.message})


def _ctx(instance: str | None) -> TenantContext:
    try:
        return TenantContext.of(instance)
    except CommandError as e:
        raise HTTPException(status_code=e.http,
                            detail={"error_code": e.code, "message": e.message})


def _not_found(case_id: str):
    raise HTTPException(404, detail={"error_code": "CASE_NOT_FOUND",
                                     "message": f"案件 {case_id} 不存在"})


@router.get("/cases")
def list_cases(instance: str | None = Query(None, description="租户上下文 CN|OS（FN-0-11/WP1.7 强制）"),
               view: str = Query("list", pattern="^(list|switcher)$",
                                 description="list=列表投影（默认）；switcher=case-detail 案件切换器（三演示 full 案）"),
               status: str | None = None, keyword: str | None = None,
               risk: str | None = None, page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=200)):
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            if view == "switcher":
                return dash.get_switcher(session, ctx)
            items, total, page, page_size = repo.list_cases(
                session, ctx, status=status, keyword=keyword,
                risk=risk, page=page, page_size=page_size)
        except CommandError as e:
            _fail(e)
        return {"items": items, "total": total, "page": page, "pageSize": page_size}


@router.get("/cases/{case_id}")
def get_case(case_id: str, view: str = Query("full", pattern="^(summary|full)$"),
             instance: str | None = Query(None)):
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            agg = repo.aggregate_case(session, ctx, case_id)
        except CommandError as e:
            _fail(e)
        if agg is None:
            _not_found(case_id)
        # 北向 v1 承诺（openapi /v1/cases/{caseId} 200=invoice-case.schema）：
        # summary 亦返回完整聚合（契约 allOf 禁 full 案件轻量投影——R5 §5.3 透明登记，
        # M2 列表瘦身已满足 web 侧性能诉求，详情面维持）
        return agg


@router.get("/cases/{case_id}/evidence")
def get_evidence(case_id: str, field: str | None = Query(None, description="Schema 字段路径"),
                 instance: str | None = Query(None)):
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            if repo.get_case_row(session, ctx, case_id) is None:
                _not_found(case_id)
            rows = repo.get_evidence(session, ctx, case_id, field=field)
        except CommandError as e:
            _fail(e)
        return {"caseId": case_id, "field": field,
                "items": [r.evidence_raw for r in rows], "total": len(rows)}


@router.get("/cases/{case_id}/timeline")
def get_timeline(case_id: str, instance: str | None = Query(None)):
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            if repo.get_case_row(session, ctx, case_id) is None:
                _not_found(case_id)
            rows = repo.get_timeline(session, ctx, case_id)
        except CommandError as e:
            _fail(e)
        return {"caseId": case_id, "items": [r.event_raw for r in rows], "total": len(rows)}


@router.get("/cases/{case_id}/original")
def get_original_file(case_id: str, instance: str | None = Query(None),
                      actor: str = Query("王莉", description="操作人（权限与审计留痕）")):
    """只读原件查看与下载通道（FN-3-08 差距收敛 · 受权限+租户校验+审计查看事件）。"""
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            rbac_service.require_permission(session, actor, "案件查看")
            c = repo.get_case_row(session, ctx, case_id)
            if c is None:
                _not_found(case_id)

            # 审计留痕：查看原件事件入不可篡改哈希链
            append_block(
                session, ts=now_iso(), trace=c.trace_id or new_trace_id(),
                actor="human", act="REVIEW_OPENED", cs=case_id,
                from_state=c.status, to_state="查看原件",
                note=f"查看发票原件文件（FN-3-08 通道）· 操作人：{actor}",
                op=actor, category="action"
            )
            session.commit()

            file_info = c.file_raw or {}
            pdf_name = file_info.get("pdf") or f"{case_id}.pdf"
            sha = file_info.get("sha256")

            # 1. 优先从对象库读取已落盘原件
            local_path = object_store.find_by_digest(sha) if sha else None
            if local_path:
                content = object_store.read(local_path)
                media_type = "application/pdf" if pdf_name.endswith(".pdf") else "application/octet-stream"
            elif c.source_xml:
                # 2. 次选 XML 原件直读
                content = c.source_xml.encode("utf-8")
                media_type = "application/xml; charset=utf-8"
                if not pdf_name.endswith(".xml"):
                    pdf_name = f"{case_id}.xml"
            else:
                # 3. 演示桩兜底
                content = f"%PDF-1.4\n% Invoice-Hub Original Stub for {case_id}\n%%EOF".encode("utf-8")
                media_type = "application/pdf"

            return Response(
                content=content,
                media_type=media_type,
                headers={"Content-Disposition": f'inline; filename="{pdf_name}"'}
            )
        except CommandError as e:
            _fail(e)
