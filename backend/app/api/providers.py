# -*- coding: utf-8 -*-
"""Provider 编排与路由调度 API（WP4.1/4.2 · FN-2-02~10 · FN-2-13/14）。

包含端点：
  - GET  /v1/providers                 Provider 实例列表（含 SLA、成本与 KMS 掩码）
  - GET  /v1/providers/{provider_id}   Provider 详情
  - POST /v1/providers/{provider_id}/toggle  启停 Provider（lock 保护，停用产生 PROVIDER_DISABLED 审计）
  - POST /v1/providers/{provider_id}/test    连通性测试（握手时延 + SPI 契约归一化校验 + 入审计）
  - GET  /v1/providers/metrics/sla     SLA 监控与超阈值告警
  - GET  /v1/providers/metrics/costs   成本多币种统计
  - GET  /v1/routing/policy            获取当前生效的路由与降级策略
  - POST /v1/routing/evaluate          路由执行/模拟推演（与真实路由共用同一规则解释器）
"""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import governed_commands as gc, identity_service, provider_service, routing_engine
from app.services.errors import CommandError
from app.services.persistence import get_session

router = APIRouter(prefix="/v1")


def _fail(e: CommandError):
    raise HTTPException(
        status_code=e.http,
        detail={"error_code": e.code, "message": e.message, **e.details},
    )


class ToggleBody(BaseModel):
    enabled: bool
    actor: str = "human"
    opinion: Optional[str] = None


class TestBody(BaseModel):
    actor: str = "human"


class RouteEvalBody(BaseModel):
    region: str = Field(description="CN | APAC | EU | US")
    invoice_type: str = Field(description="数电票 | 增值税专票/普票（纸质扫描） | Supplier Invoice | Credit Note")
    carrier: str = Field(description="XML 原件 + PDF | 纸质扫描 / 图片 | PDF（原生文本层）")
    doc_type_hint: Optional[str] = None


@router.get("/providers")
def get_providers():
    with get_session() as s:
        items = provider_service.list_providers(s)
        return {"total": len(items), "providers": items}


@router.get("/providers/metrics/sla")
def get_sla_metrics():
    with get_session() as s:
        return provider_service.get_sla_stats(s)


@router.get("/providers/metrics/costs")
def get_cost_metrics():
    with get_session() as s:
        return provider_service.get_cost_stats(s)


@router.get("/providers/{provider_id}")
def get_provider(provider_id: str):
    try:
        with get_session() as s:
            return provider_service.get_provider_detail(s, provider_id)
    except CommandError as e:
        _fail(e)


@router.post("/providers/{provider_id}/toggle")
def toggle_provider(provider_id: str, body: ToggleBody, request: Request):
    try:
        with get_session() as s:
            actor = identity_service.bind_actor(request.state.ihub_session, body.actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["publish"])
            return provider_service.toggle_provider(
                s,
                provider_id=provider_id,
                enabled=body.enabled,
                actor=actor,
                opinion=body.opinion,
            )
    except CommandError as e:
        _fail(e)


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, request: Request, body: TestBody = TestBody()):
    try:
        with get_session() as s:
            actor = identity_service.bind_actor(request.state.ihub_session, body.actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["publish"])
            return provider_service.test_connection(s, provider_id=provider_id, actor=actor)
    except CommandError as e:
        _fail(e)


@router.get("/routing/policy")
def get_routing_policy():
    try:
        with get_session() as s:
            return routing_engine.get_effective_policy(s)
    except CommandError as e:
        _fail(e)


@router.get("/routing/policy/draft")
def get_routing_draft():
    with get_session() as s:
        d = routing_engine.get_draft_policy(s)
        return {"has_draft": d is not None, "draft": d}


@router.post("/routing/policy/draft")
def save_routing_draft(payload: dict[str, Any], request: Request, actor: str = "human"):
    try:
        with get_session() as s:
            bound_actor = identity_service.bind_actor(request.state.ihub_session, actor)
            identity_service.require_session_permission(s, request.state.ihub_session, gc.ACTION_PERMS["publish"])
            return routing_engine.save_draft_policy(s, payload, actor=bound_actor)
    except CommandError as e:
        _fail(e)


@router.delete("/routing/policy/draft")
def delete_routing_draft():
    with get_session() as s:
        deleted = routing_engine.delete_draft_policy(s)
        return {"deleted": deleted}


@router.get("/routing/policy/versions")
def get_routing_versions():
    with get_session() as s:
        versions = routing_engine.list_policy_versions(s)
        return {"total": len(versions), "versions": versions}


@router.post("/routing/evaluate")
def evaluate_routing(body: RouteEvalBody):
    try:
        with get_session() as s:
            return routing_engine.execute_route(
                s,
                region=body.region,
                invoice_type=body.invoice_type,
                carrier=body.carrier,
                doc_type_hint=body.doc_type_hint,
                is_simulation=False,
            )
    except CommandError as e:
        _fail(e)


@router.post("/routing/simulate")
def simulate_routing(body: RouteEvalBody):
    """策略模拟测试（只读沙箱，FN-2-11）：
    按当前草稿策略（若无则取已发布版）推演完整链路，与真实路由共用同一解释器，不产生真实外发与调用。"""
    try:
        with get_session() as s:
            return routing_engine.execute_route(
                s,
                region=body.region,
                invoice_type=body.invoice_type,
                carrier=body.carrier,
                doc_type_hint=body.doc_type_hint,
                is_simulation=True,
            )
    except CommandError as e:
        _fail(e)

