# -*- coding: utf-8 -*-
"""受控写 API（WP1.5 框架入口 + WP1.7 租户强制 + WP1.8 发布/回滚动作 + §3 收尾信封）。

写路径全部经 governed_commands.execute（依赖纪律⑤：框架外写路径=缺陷）。
单案动作响应附契约合规 full 聚合（case 字段）——P02 §3 收尾：响应结构过 Schema 校验。
演示口径：risk-challenge 为本地凭据桩（SSO/MFA 真实身份属 M5）。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import case_repository as repo
from app.services import governed_commands as gc
from app.services.errors import CommandError
from app.services.persistence import get_session
from app.services.tenant import TenantContext

router = APIRouter(prefix="/v1")

# 案件/批量/配置动作面词汇（M3 intake=受理提交，专用入口 /v1/intake/*，不在此面暴露）
ACTIONS = "|".join(sorted(k for k in gc.ACTION_PERMS if k != "intake"))


class ChallengeBody(BaseModel):
    actor: str
    instance: str = Field(pattern="^(CN|OS)$")   # WP1.7：写路径租户上下文必携带
    action: str = Field(pattern=f"^({ACTIONS})$")
    case_ids: list[str] | None = None


class ActionBody(BaseModel):
    actor: str
    instance: str = Field(pattern="^(CN|OS)$")
    token: str
    self_confirmed: bool = False
    opinion: str | None = None
    co_signer: str | None = None           # unblock 双人会签
    co_signer_self: bool = False
    field: str | None = None               # edit_field
    new_value: str | int | float | bool | None = None
    reason: str | None = None
    filters: dict | None = None            # export
    rows: int | None = None
    config_key: str | None = None          # publish
    config_payload: dict | None = None
    to_version: str | None = None          # rollback
    advice_id: str | None = None           # advice_reject（不采纳 AI 建议留痕，WP3.4）


class BatchActionBody(ActionBody):
    case_ids: list[str]


def _fail(e: CommandError):
    raise HTTPException(status_code=e.http,
                        detail={"error_code": e.code, "message": e.message, **e.details})


@router.post("/cases/{case_id}/risk-challenge")
def risk_challenge(case_id: str, body: ChallengeBody):
    with get_session() as session:
        try:
            ctx = TenantContext.of(body.instance)
            if repo.get_case_row(session, ctx, case_id) is None:
                raise HTTPException(404, detail={"error_code": "CASE_NOT_FOUND",
                                                 "message": f"案件 {case_id} 不存在"})
            return gc.issue_risk_challenge(session, body.actor, body.action, case_id)
        except CommandError as e:
            _fail(e)


@router.post("/batch/risk-challenge")
def batch_risk_challenge(body: ChallengeBody):
    scope = gc.scope_ref(body.action, None, body.case_ids)
    with get_session() as session:
        try:
            return gc.issue_risk_challenge(session, body.actor, body.action, scope)
        except CommandError as e:
            _fail(e)


@router.post("/audit/risk-challenge")
def export_risk_challenge(body: ChallengeBody):
    with get_session() as session:
        try:
            return gc.issue_risk_challenge(session, body.actor, "export", "audit-export")
        except CommandError as e:
            _fail(e)


@router.post("/config/{key}/risk-challenge")
def config_risk_challenge(key: str, body: ChallengeBody):
    with get_session() as session:
        try:
            return gc.issue_risk_challenge(
                session, body.actor, body.action, gc.scope_ref(body.action, config_key=key))
        except CommandError as e:
            _fail(e)


def _execute(session, body: ActionBody, action: str, case_id: str | None = None,
             case_ids: list[str] | None = None):
    return gc.execute(session, actor=body.actor, action=action, instance=body.instance,
                      case_id=case_id, case_ids=case_ids, token=body.token,
                      self_confirmed=body.self_confirmed, opinion=body.opinion,
                      co_signer=body.co_signer, co_signer_self=body.co_signer_self,
                      field=body.field, new_value=body.new_value, reason=body.reason,
                      filters=body.filters, rows=body.rows,
                      config_key=body.config_key, to_version=body.to_version,
                      config_payload=body.config_payload, advice_id=body.advice_id)


@router.post("/cases/{case_id}/actions/{action}")
def case_action(case_id: str, action: str, body: ActionBody):
    if action not in gc.ACTION_PERMS or action.startswith("batch_") or action == "intake":
        raise HTTPException(400, detail={"error_code": "UNKNOWN_ACTION",
                                         "message": f"不支持的单案动作 {action!r}"})
    with get_session() as session:
        try:
            out = _execute(session, body, action, case_id=case_id)
            # §3 收尾：响应附契约合规 full 聚合（校验面=case 字段，信封为服务层结果）
            ctx = TenantContext.of(body.instance)
            agg = repo.aggregate_case(session, ctx, case_id)
            if agg is not None:
                out["case"] = agg
            if "trace" in out:
                out["trace_id"] = out["trace"]
            return out
        except CommandError as e:
            _fail(e)


@router.post("/batch/actions/{action}")
def batch_action(action: str, body: BatchActionBody):
    if action not in ("batch_claim", "batch_release"):
        raise HTTPException(400, detail={"error_code": "UNKNOWN_ACTION",
                                         "message": f"不支持的批量动作 {action!r}"})
    with get_session() as session:
        try:
            return _execute(session, body, action, case_ids=body.case_ids)
        except CommandError as e:
            _fail(e)


@router.post("/config/actions/{action}")
def config_action(action: str, body: ActionBody):
    if action not in ("publish", "rollback"):
        raise HTTPException(400, detail={"error_code": "UNKNOWN_ACTION",
                                         "message": f"不支持的配置动作 {action!r}"})
    with get_session() as session:
        try:
            return _execute(session, body, action)
        except CommandError as e:
            _fail(e)
