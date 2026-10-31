# -*- coding: utf-8 -*-
"""匹配就绪化与税码映射 API（WP4.4 · FN-6-01~06）。

端点：
  - GET  /v1/matching/queue              CN+OS 统一待确认差异队列与计数
  - GET  /v1/matching/queue/{case_id}    单案确认卡双栏详情
  - GET  /v1/matching/taxcodes           税码映射表（Tab2 · v1.4 表驱动）
  - POST /v1/matching/taxcodes/map       税码实时映射试算
"""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services import governed_commands as gc, identity_service, matching_service, mapping_governance
from app.services.errors import CommandError
from app.services.persistence import get_session

router = APIRouter(prefix="/v1/matching")


def _fail(e: CommandError):
    raise HTTPException(
        status_code=e.http,
        detail={"error_code": e.code, "message": e.message, **e.details},
    )


class TaxMapReq(BaseModel):
    instance: str = "CN"
    rate: str | float
    is_credit: bool = False
    origin_tax_code: str = "J1"


class AdoptReq(BaseModel):
    src_field: str
    actor: str = "human"
    opinion: Optional[str] = None


class RejectReq(BaseModel):
    src_field: str
    reason: str
    actor: str = "human"


class LinkConfirmReq(BaseModel):
    credit_case_id: str
    origin_case_id: str
    actor: str = "human"
    opinion: Optional[str] = None


class LinkRejectReq(BaseModel):
    credit_case_id: str
    origin_case_id: str
    reason: str
    actor: str = "human"


@router.get("/queue")
def get_queue(instance: Optional[str] = Query(None, pattern="^(CN|OS)$")):
    with get_session() as s:
        return matching_service.get_matching_queue(s, instance=instance)


@router.get("/queue/{case_id}")
def get_queue_item(case_id: str):
    try:
        with get_session() as s:
            return matching_service.get_case_matching_detail(s, case_id)
    except CommandError as e:
        _fail(e)


@router.get("/taxcodes")
def get_tax_codes():
    with get_session() as s:
        items = matching_service.get_tax_codes_table(s)
        return {"version": "v1.4", "total": len(items), "items": items}


@router.post("/taxcodes/map")
def map_tax_code(req: TaxMapReq):
    res = matching_service.map_tax_code(
        instance=req.instance,
        rate=req.rate,
        is_credit=req.is_credit,
        origin_tax_code=req.origin_tax_code,
    )
    return res


# ───────────────────────── 映射治理与推荐队列（Tab2 · FN-6-07/08/09） ─────────────────────────

@router.get("/presets")
def get_preset_rules():
    with get_session() as s:
        return mapping_governance.get_preset_rules(s)


@router.get("/recommendations")
def get_ai_recommendations():
    with get_session() as s:
        items = mapping_governance.list_ai_recommendations(s)
        return {"total": len(items), "items": items}


@router.post("/recommendations/adopt")
def adopt_ai_recommendation(req: AdoptReq, request: Request):
    try:
        with get_session() as s:
            actor = identity_service.bind_actor(request.state.ihub_session, req.actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["edit_field"])
            return mapping_governance.adopt_recommendation(
                s, src_field=req.src_field, actor=actor, opinion=req.opinion
            )
    except CommandError as e:
        _fail(e)


@router.post("/recommendations/reject")
def reject_ai_recommendation(req: RejectReq, request: Request):
    try:
        with get_session() as s:
            actor = identity_service.bind_actor(request.state.ihub_session, req.actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["edit_field"])
            return mapping_governance.reject_recommendation(
                s, src_field=req.src_field, reason=req.reason, actor=actor
            )
    except CommandError as e:
        _fail(e)


@router.get("/history")
def get_confirmation_history():
    with get_session() as s:
        items = mapping_governance.get_confirmation_history(s)
        return {"total": len(items), "items": items}


# ───────────────────────── Link 候选与确认（Tab3 · FN-4-06 / FN-6-10） ─────────────────────────

@router.get("/links/candidates")
def get_link_candidates():
    with get_session() as s:
        items = mapping_governance.list_all_link_candidates(s)
        return {"total": len(items), "items": items}


@router.get("/links/candidates/{case_id}")
def get_case_link_candidates(case_id: str):
    try:
        with get_session() as s:
            return mapping_governance.infer_link_candidates(s, case_id)
    except CommandError as e:
        _fail(e)


@router.post("/links/confirm")
def confirm_link_endpoint(req: LinkConfirmReq, request: Request):
    try:
        with get_session() as s:
            actor = identity_service.bind_actor(request.state.ihub_session, req.actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["edit_field"])
            return mapping_governance.confirm_link(
                s,
                credit_case_id=req.credit_case_id,
                origin_case_id=req.origin_case_id,
                actor=actor,
                opinion=req.opinion,
            )
    except CommandError as e:
        _fail(e)


@router.post("/links/reject")
def reject_link_endpoint(req: LinkRejectReq, request: Request):
    try:
        with get_session() as s:
            actor = identity_service.bind_actor(request.state.ihub_session, req.actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["edit_field"])
            return mapping_governance.reject_link(
                s,
                credit_case_id=req.credit_case_id,
                origin_case_id=req.origin_case_id,
                reason=req.reason,
                actor=actor,
            )
    except CommandError as e:
        _fail(e)

