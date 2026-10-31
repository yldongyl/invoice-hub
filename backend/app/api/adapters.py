# -*- coding: utf-8 -*-
"""Adapter 适配层与沙箱建档 API（WP4.6 · FN-7-01~08）。

端点：
  - GET  /v1/adapters                         目标系统 Adapter 列表与指标
  - GET  /v1/adapters/{adapter_id}            单个 Adapter 档案与连接配置
  - GET  /v1/adapters/{adapter_id}/mapping    字段映射模板（v1.4）
  - GET  /v1/adapters/{adapter_id}/queue      回执与失败重试队列
  - POST /v1/adapters/{adapter_id}/file       建档五步链路执行（沙箱/生产）
"""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import adapter_service
from app.services.errors import CommandError
from app.services.persistence import get_session

router = APIRouter(prefix="/v1/adapters")


def _fail(e: CommandError):
    raise HTTPException(
        status_code=e.http,
        detail={"error_code": e.code, "message": e.message, **e.details},
    )


class FilingReq(BaseModel):
    case_id: str = Field(description="待建档发票案件号，如 INV-CN-2026-0387")
    is_sandbox: bool = Field(default=True, description="True=沙箱测试建档（不写回状态）；False=正式建档")
    actor: str = Field(default="system")
    opinion: Optional[str] = None


@router.get("")
def get_adapters():
    with get_session() as s:
        items = adapter_service.list_adapters(s)
        return {"total": len(items), "adapters": items}


@router.get("/{adapter_id}")
def get_adapter(adapter_id: str):
    try:
        return adapter_service.get_adapter_profile(adapter_id)
    except CommandError as e:
        _fail(e)


@router.get("/{adapter_id}/mapping")
def get_adapter_mapping(adapter_id: str):
    try:
        return adapter_service.get_mapping_template(adapter_id)
    except CommandError as e:
        _fail(e)


@router.get("/{adapter_id}/queue")
def get_adapter_queue(adapter_id: str):
    try:
        items = adapter_service.list_adapter_queue(adapter_id)
        return {"adapter_id": adapter_id, "total": len(items), "queue": items}
    except CommandError as e:
        _fail(e)


@router.post("/{adapter_id}/file")
def post_file_invoice(adapter_id: str, req: FilingReq):
    try:
        with get_session() as s:
            return adapter_service.execute_filing(
                s,
                adapter_id=adapter_id,
                case_id=req.case_id,
                actor=req.actor,
                is_sandbox=req.is_sandbox,
                opinion=req.opinion,
            )
    except CommandError as e:
        _fail(e)
