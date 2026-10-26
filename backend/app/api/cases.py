# -*- coding: utf-8 -*-
"""案件只读 API（P02 §3 最小 API 面 · 供 M2 接线与契约测试；非完整对外 API）。

WP1.7 收口：所有查询必须携带租户上下文 instance（CN|OS）——缺失 E_TENANT_MISSING→400、
越权（数据归属实例不符）E_TENANT_MISMATCH→403。响应结构一律过 contracts Schema 校验
（list/summary=契约合法 list 级案件形态；full=聚合逐字；evidence/timeline 项级校验由契约测试覆盖）。
"""

from fastapi import APIRouter, HTTPException, Query

from app.services import case_repository as repo
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
               status: str | None = None, keyword: str | None = None,
               risk: str | None = None, page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=200)):
    ctx = _ctx(instance)
    with get_session() as session:
        try:
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
        if view == "summary":
            try:
                items, _, _, _ = repo.list_cases(session, ctx, keyword=None, page=1, page_size=500)
            except CommandError as e:
                _fail(e)
            hit = next((i for i in items if i["caseId"] == case_id), None)
            if hit is None:
                _not_found(case_id)
            return hit
        try:
            agg = repo.aggregate_case(session, ctx, case_id)
        except CommandError as e:
            _fail(e)
        if agg is None:
            _not_found(case_id)
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
