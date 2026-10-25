# -*- coding: utf-8 -*-
"""案件只读 API（P02 §3 最小 API 面 · 供 M2 接线与契约测试；非完整对外 API）。

范围裁决（用户确认）：本会话仅落 只读四端点 + /healthz；
POST /v1/cases/{caseId}/actions/*（受控写入口）属 WP1.5，路由位见文件尾注记。
TODO(WP1.5): actions 端点五要素（权限→风险提示→二次确认+本人勾选→处置意见→审计+流转）接入受控命令框架。
TODO(WP1.7): 租户上下文强制注入（缺失即报错）与四隔离过滤收口。
"""

from fastapi import APIRouter, HTTPException, Query

from app.domain import models as m
from app.services import case_repository as repo
from app.services.persistence import get_session

router = APIRouter(prefix="/v1")


@router.get("/cases")
def list_cases(instance: str | None = Query(None, description="实例域 CN|OS（FN-0-11）"),
               status: str | None = None, keyword: str | None = None,
               risk: str | None = None, page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=200)):
    with get_session() as session:
        items, total, page, page_size = repo.list_cases(
            session, instance=instance, status=status, keyword=keyword,
            risk=risk, page=page, page_size=page_size)
        return {"items": items, "total": total, "page": page, "pageSize": page_size}


@router.get("/cases/{case_id}")
def get_case(case_id: str, view: str = Query("full", pattern="^(summary|full)$")):
    with get_session() as session:
        if view == "summary":
            items, total, _, _ = repo.list_cases(session, keyword=None, page=1, page_size=200)
            hit = next((i for i in items if i["caseId"] == case_id), None)
            if hit is None:
                raise HTTPException(404, detail={"error_code": "CASE_NOT_FOUND",
                                                 "message": f"案件 {case_id} 不存在"})
            return hit
        agg = repo.aggregate_case(session, case_id)
        if agg is None:
            raise HTTPException(404, detail={"error_code": "CASE_NOT_FOUND",
                                             "message": f"案件 {case_id} 不存在"})
        return agg


@router.get("/cases/{case_id}/evidence")
def get_evidence(case_id: str, field: str | None = Query(None, description="Schema 字段路径")):
    with get_session() as session:
        if session.get(m.Case, case_id) is None:
            raise HTTPException(404, detail={"error_code": "CASE_NOT_FOUND",
                                             "message": f"案件 {case_id} 不存在"})
        rows = repo.get_evidence(session, case_id, field=field)
        return {"caseId": case_id, "field": field,
                "items": [r.evidence_raw for r in rows], "total": len(rows)}


@router.get("/cases/{case_id}/timeline")
def get_timeline(case_id: str):
    with get_session() as session:
        if session.get(m.Case, case_id) is None:
            raise HTTPException(404, detail={"error_code": "CASE_NOT_FOUND",
                                             "message": f"案件 {case_id} 不存在"})
        rows = repo.get_timeline(session, case_id)
        return {"caseId": case_id, "items": [r.event_raw for r in rows], "total": len(rows)}
