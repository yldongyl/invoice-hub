# -*- coding: utf-8 -*-
"""工作台 API（WP3.4 · FN-8-01/02/06/07 队列侧支撑 + FN-8-09 不采纳留痕通道）。

写路径纪律：claim/batch_*/release/export/advice_reject 全部经 governed_commands
（/v1/cases/{id}/actions/*、/v1/batch/actions/* 既有入口 + 本文件 /v1/audit/actions/export）；
本文件新增面=只读（queue/co-signers）+ 导出执行与限时下载。
"""

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.services import governed_commands as gc
from app.services import workbench
from app.services.audit_chain import append_block, now_iso
from app.services.errors import CommandError
from app.services.persistence import get_session
from app.services.tenant import TenantContext

router = APIRouter(prefix="/v1")


def _fail(e: CommandError):
    raise HTTPException(status_code=e.http,
                        detail={"error_code": e.code, "message": e.message, **e.details})


class AgentAuditEventBody(BaseModel):
    trace: str
    actor: str = "王莉"
    model_name: str | None = None
    intent: str
    query: str
    tool_called: str = "none"
    case_id: str | None = None
    zero_write: bool = True
    domain: str = "PLATFORM"


class ExportBody(BaseModel):
    actor: str
    instance: str = Field(pattern="^(CN|OS)$")
    token: str
    self_confirmed: bool = False
    opinion: str | None = None
    filters: dict | None = None
    rows: int | None = None


@router.get("/workbench/queue")
def queue_stats(request: Request, instance: str | None = Query(None), actor: str | None = Query(None)):
    """队列归属与待复核数（FN-8-01 Header 展示；workbench「队列：… · 待复核 N」同源；支持 actor 真实认领统计 FN-8-02）。"""
    try:
        ctx = TenantContext.of(instance)
    except CommandError as e:
        _fail(e)
    # 若 query 未显式传 actor，尝试从会话中获取当前登录操作人
    effective_actor = actor
    if not effective_actor and getattr(request.state, "ihub_session", None):
        sess = request.state.ihub_session
        effective_actor = (sess.get("user") or {}).get("name") if isinstance(sess, dict) else None

    with get_session() as session:
        return workbench.queue_stats(session, ctx, actor=effective_actor)


@router.post("/agent/audit-events")
def record_agent_audit_event(body: AgentAuditEventBody):
    """Agent 对话审计事件落链（FN-8-08 · PLATFORM 链域留痕 · 零写事件校验）。"""
    with get_session() as session:
        op_info = f"AI:{body.model_name} · 提问人:{body.actor}" if body.model_name else f"提问人:{body.actor}"
        note = (
            f"Agent 对话审计 · 意图:{body.intent} · 工具:{body.tool_called} · "
            f"提问:{body.query[:80]} · 零写确认:{body.zero_write}"
        )
        blk = append_block(
            session,
            ts=now_iso(),
            trace=body.trace,
            actor="ai",
            act="AGENT_CONVERSATION",
            cs=body.case_id,
            from_state=None,
            to_state=None,
            note=note,
            op=op_info[:80],
            category="action",
            domain=body.domain or "PLATFORM",
            commit=True,
        )
        return {
            "status": "recorded",
            "blk": blk.blk,
            "chain_hash": blk.chain_hash,
            "prev_hash": blk.prev_hash,
            "trace_id": blk.trace,
            "chain_scope": blk.chain_scope,
        }


@router.get("/workbench/co-signers")
def co_signers():
    """BLOCKED 双人解除可选会签人（管理员角色启用真人，FN-8-06；RBAC 服务 M5 实装前为演示桩读取）。

    路径置于 /v1/workbench/* 下——避免被既有 /v1/cases/{caseId} 详情路由捕获（注册序在其前会遮蔽）。
    """
    with get_session() as session:
        return {"items": workbench.co_signers(session),
                "note": "会签人须管理员权限位且为启用真人、不得与发起人同人、须本人执行勾选"
                        "（governed unblock 校验，M1 已实装）"}


@router.post("/audit/actions/export")
def export_action(body: ExportBody):
    """导出执行（受控五要素 · FN-8-07）：AUDIT_EXPORT 入链头 → 限时票据发放。"""
    with get_session() as session:
        try:
            return gc.execute(session, actor=body.actor, action="export", instance=body.instance,
                              token=body.token, self_confirmed=body.self_confirmed,
                              opinion=body.opinion, filters=body.filters, rows=body.rows)
        except CommandError as e:
            _fail(e)


@router.get("/exports/{token}")
def export_download(token: str):
    """限时下载（24h 失效→410；FN-8-07 页面口径「下载链接 24 小时后失效（演示口径）」）。"""
    with get_session() as session:
        try:
            blob, fname = workbench.download(session, token)
        except CommandError as e:
            _fail(e)
    return Response(content=blob, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
