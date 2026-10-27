# -*- coding: utf-8 -*-
"""工作台 API（WP3.4 · FN-8-01/02/06/07 队列侧支撑 + FN-8-09 不采纳留痕通道）。

写路径纪律：claim/batch_*/release/export/advice_reject 全部经 governed_commands
（/v1/cases/{id}/actions/*、/v1/batch/actions/* 既有入口 + 本文件 /v1/audit/actions/export）；
本文件新增面=只读（queue/co-signers）+ 导出执行与限时下载。
"""

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.services import governed_commands as gc
from app.services import workbench
from app.services.errors import CommandError
from app.services.persistence import get_session
from app.services.tenant import TenantContext

router = APIRouter(prefix="/v1")


def _fail(e: CommandError):
    raise HTTPException(status_code=e.http,
                        detail={"error_code": e.code, "message": e.message, **e.details})


class ExportBody(BaseModel):
    actor: str
    instance: str = Field(pattern="^(CN|OS)$")
    token: str
    self_confirmed: bool = False
    opinion: str | None = None
    filters: dict | None = None
    rows: int | None = None


@router.get("/workbench/queue")
def queue_stats(instance: str | None = Query(None)):
    """队列归属与待复核数（FN-8-01 Header 展示；workbench「队列：… · 待复核 N」同源）。"""
    try:
        ctx = TenantContext.of(instance)
    except CommandError as e:
        _fail(e)
    with get_session() as session:
        return workbench.queue_stats(session, ctx)


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
