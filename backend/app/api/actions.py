# -*- coding: utf-8 -*-
"""受控写 API（WP1.5 · P02 §3 actions 端点接线）。

写路径全部经 governed_commands.execute（依赖纪律⑤：框架外写路径=缺陷）。
演示口径：risk-challenge 为本地凭据桩（SSO/MFA 真实身份属 M5）；TODO(WP1.7) 租户上下文注入。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import governed_commands as gc
from app.services.errors import CommandError
from app.services.persistence import get_session

router = APIRouter(prefix="/v1")


class ChallengeBody(BaseModel):
    actor: str
    action: str = Field(pattern="^(release|hold|return|edit_field|claim|unblock|batch_claim|batch_release|export)$")
    case_ids: list[str] | None = None      # 批量命令的目标集


class ActionBody(BaseModel):
    actor: str
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


class BatchActionBody(ActionBody):
    case_ids: list[str]


def _fail(e: CommandError):
    raise HTTPException(status_code=e.http,
                        detail={"error_code": e.code, "message": e.message, **e.details})


def _scope_for(action: str, case_id: str | None, case_ids: list[str] | None) -> str:
    return gc.scope_ref(action, case_id, case_ids)  # 与命令框架同源，防绑定口径漂移


@router.post("/cases/{case_id}/risk-challenge")
def risk_challenge(case_id: str, body: ChallengeBody):
    with get_session() as session:
        try:
            return gc.issue_risk_challenge(session, body.actor, body.action, case_id)
        except CommandError as e:
            _fail(e)


@router.post("/batch/risk-challenge")
def batch_risk_challenge(body: ChallengeBody):
    scope = _scope_for(body.action, None, body.case_ids)
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


@router.post("/cases/{case_id}/actions/{action}")
def case_action(case_id: str, action: str, body: ActionBody):
    if action not in gc.ACTION_PERMS or action.startswith("batch_"):
        raise HTTPException(400, detail={"error_code": "UNKNOWN_ACTION",
                                         "message": f"不支持的单案动作 {action!r}"})
    with get_session() as session:
        try:
            out = gc.execute(session, actor=body.actor, action=action, case_id=case_id,
                             token=body.token, self_confirmed=body.self_confirmed,
                             opinion=body.opinion, co_signer=body.co_signer,
                             co_signer_self=body.co_signer_self, field=body.field,
                             new_value=body.new_value, reason=body.reason,
                             filters=body.filters, rows=body.rows)
            # trace 来自命令执行上下文（流转/事件实际 trace；编号发号器正式实装属 WP1.7）
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
            return gc.execute(session, actor=body.actor, action=action, case_ids=body.case_ids,
                              token=body.token, self_confirmed=body.self_confirmed,
                              opinion=body.opinion)
        except CommandError as e:
            _fail(e)
