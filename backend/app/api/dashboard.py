# -*- coding: utf-8 -*-
"""仪表盘/告警/深链读 API（M2 WP2.1/2.2 · FN-8-11/FN-5-09 读侧/FN-0-14）。

口径：
  - 全部为只读查询，无业务写（依赖纪律⑤不涉；聚合真算逻辑见 services/dashboard.py）；
  - 租户上下文强制（WP1.7 同口径）：instance 缺失 E_TENANT_MISSING→400、
    越权 E_TENANT_MISMATCH→403；P03 演示口径接受 cn/os 小写，归一为大写契约值（契约 instance 枚举不变）；
  - 响应结构一律过 contracts：dashboard-response.schema.json / alerts-response.schema.json /
    case-read.schema.json（$defs.existsResponse），由契约测试断言；
  - 深链存在性：不存在→404 CASE_NOT_FOUND（页面友好提示由前端接线 WP2.3 承载）。
"""

from fastapi import APIRouter, HTTPException, Query

from app.services import dashboard as dash
from app.services.errors import CommandError
from app.services.persistence import get_session
from app.services.tenant import TenantContext

router = APIRouter(prefix="/v1")


def _ctx(instance: str | None) -> TenantContext:
    try:
        # 演示口径归一：?instance=cn|os 小写 → 契约大写（非法值仍由 of() 拒绝）
        return TenantContext.of(instance.upper() if instance else instance)
    except CommandError as e:
        raise HTTPException(status_code=e.http,
                            detail={"error_code": e.code, "message": e.message})


@router.get("/dashboard")
def get_dashboard(instance: str | None = Query(None, description="租户上下文 CN|OS（大小写均可）")):
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            return dash.get_dashboard(session, ctx)
        except CommandError as e:
            raise HTTPException(status_code=e.http,
                                detail={"error_code": e.code, "message": e.message})


@router.get("/alerts")
def list_alerts(instance: str | None = Query(None)):
    """告警列表（FN-5-09 读侧：规则命中/状态事件生成告警视图，seed 六条基线入表同源）。"""
    ctx = _ctx(instance)
    with get_session() as session:
        try:
            items = dash.build_alert_items(session, ctx)
        except CommandError as e:
            raise HTTPException(status_code=e.http,
                                detail={"error_code": e.code, "message": e.message})
        return {"instance": ctx.instance, "items": items, "total": len(items)}


@router.get("/cases/{case_id}/exists")
def case_exists(case_id: str, instance: str | None = Query(None),
                tab: str | None = Query(None, description="audit-reports ?tab= 定位参数（FN-0-14，可选校验）")):
    ctx = _ctx(instance)
    try:
        ctx.assert_matches_case_id(case_id)  # 越权先行（与详情面同序：403 优先于 404）
    except CommandError as e:
        raise HTTPException(status_code=e.http,
                            detail={"error_code": e.code, "message": e.message})
    with get_session() as session:
        try:
            return dash.resolve_deeplink(session, ctx, case_id, tab)
        except CommandError as e:
            raise HTTPException(status_code=e.http,
                                detail={"error_code": e.code, "message": e.message})
