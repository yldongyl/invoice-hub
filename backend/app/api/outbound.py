# -*- coding: utf-8 -*-
"""出站建档与回写台账 API（FN-7-05 / FN-7-06 · 20261102 S4）。

端点：
  - GET  /v1/outbound/batches                           出站批次列表与 KPI 统计（支持多平台/状态筛选）
  - GET  /v1/outbound/batches/{batch_id}                单个出站批次明细与单据列表
  - POST /v1/outbound/records/{record_id}/risk-challenge 受控重推五要素凭据与风险提示
  - POST /v1/outbound/records/{record_id}/repush        受控重推执行
"""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services import identity_service, outbound_service
from app.services.errors import CommandError
from app.services.persistence import get_session

router = APIRouter(prefix="/v1/outbound")


def _fail(e: CommandError):
    raise HTTPException(
        status_code=e.http,
        detail={"error_code": e.code, "message": e.message, **e.details},
    )


class RepushChallengeReq(BaseModel):
    actor: str = Field(description="操作人，受控要求仅 ops 或 admin")


class RepushReq(BaseModel):
    actor: str
    token: str
    self_confirmed: bool = Field(default=False)
    opinion: Optional[str] = None


@router.get("/batches")
def get_outbound_batches(
    adapter: Optional[str] = Query(None, description="平台过滤，如 ariba / oracle / SAP Ariba 等"),
    status: Optional[str] = Query(None, description="批次状态过滤，如 已完成 / 部分失败 / 待人工处理 等"),
):
    """获取出站批次列表与 KPI 五卡数据（FN-7-06）。"""
    with get_session() as s:
        try:
            return outbound_service.list_outbound_batches(s, adapter=adapter, status=status)
        except CommandError as e:
            _fail(e)


@router.get("/batches/{batch_id}")
def get_outbound_batch(batch_id: str):
    """获取单个出站批次明细（FN-7-06）。"""
    with get_session() as s:
        try:
            return outbound_service.get_outbound_batch_detail(s, batch_id=batch_id)
        except CommandError as e:
            _fail(e)


@router.post("/records/{record_id}/risk-challenge")
def post_repush_challenge(record_id: int, req: RepushChallengeReq, request: Request):
    """受控重推风险凭据签发（五要素②）。"""
    with get_session() as s:
        try:
            actor = identity_service.bind_actor(request.state.ihub_session, req.actor)
            return outbound_service.issue_repush_challenge(s, actor=actor, record_id=record_id)
        except CommandError as e:
            _fail(e)


@router.post("/records/{record_id}/repush")
def post_repush_record(record_id: int, req: RepushReq, request: Request):
    """受控重推执行（五要素闭环，仅 ops/admin）。"""
    with get_session() as s:
        try:
            actor = identity_service.bind_actor(request.state.ihub_session, req.actor)
            return outbound_service.execute_repush(
                s,
                record_id=record_id,
                actor=actor,
                token=req.token,
                self_confirmed=req.self_confirmed,
                opinion=req.opinion,
            )
        except CommandError as e:
            _fail(e)
