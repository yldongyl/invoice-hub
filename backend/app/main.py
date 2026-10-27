# -*- coding: utf-8 -*-
"""FastAPI 应用入口（WP1.1 · ADR-0001 双轨制：backend 确定性核心，零大模型依赖）。

只读 API 面 + /healthz（WP1.2）、受控写命令入口（WP1.5：risk-challenge / actions /
batch / export / intake，全部经 governed_commands 五要素框架）、M2 读路径垂直切片
（WP2.1/2.2：dashboard 聚合 / alerts 读侧 / exists 深链校验 / 列表投影与切换器）与
M3 受理通道面（WP3.1/3.2：intake——recognize 契约端点 / 门户上传 / 批次 / KPI / 渠道 / 规则版本 / Job 桩）。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import (actions as actions_api, cases as cases_api, dashboard as dashboard_api,
                     intake as intake_api, workbench as workbench_api)
from app.domain.registry import get_registry
from app.services import persistence

APP_VERSION = "0.4.3-m3-wp3.4-3.5"
# P03 WP2.3 部署形态：backend 同源静态托管 web/（单端口，免 CORS）；
# web/ = ui-design 12 页接线副本（ADR-0003），根路径重定向到总览仪表盘（P07 RUNBOOK 入口）
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app() -> FastAPI:
    app = FastAPI(
        title="invoice-hub backend",
        description="全球采购平台票据智能与合规中台 · 确定性核心（无大模型依赖）",
        version=APP_VERSION,
    )
    app.include_router(cases_api.router)
    app.include_router(actions_api.router)
    app.include_router(dashboard_api.router)
    app.include_router(intake_api.router)
    app.include_router(workbench_api.router)

    # M2 WP2.3：web 运行副本同源托管（/web/*.html 直访；仅目录存在时挂载，测试/最小部署不受影响）
    if WEB_DIR.is_dir():
        app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/web/dashboard-overview.html")

    @app.get("/healthz")
    def healthz():
        # 健康检查：枚举注册表可达 + DB 可连（演示口径，非完整探活）
        db_ok = True
        try:
            from sqlalchemy import text
            with persistence.get_session() as s:
                s.execute(text("SELECT 1"))
        except Exception:  # pragma: no cover - 仅在连接异常时触发
            db_ok = False
        return {
            "status": "ok" if db_ok else "degraded",
            "component": "invoice-hub-backend",
            "version": APP_VERSION,
            "enum_registry_version": get_registry().version,
            "database": "reachable" if db_ok else "unreachable",
        }

    return app


app = create_app()
