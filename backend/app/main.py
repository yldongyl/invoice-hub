# -*- coding: utf-8 -*-
"""FastAPI 应用入口（WP1.1 · ADR-0001 双轨制：backend 确定性核心，零大模型依赖）。

本入口只装配只读 API 面 + /healthz（M1 首阶段范围）；受理流水线（WP1.6）、
受控写入口（WP1.5）、状态机（WP1.3）等在后续工作包挂载路由位。
"""

from fastapi import FastAPI

from app.api import cases as cases_api
from app.domain.registry import get_registry
from app.services import persistence

APP_VERSION = "0.1.0-m1-wp1.1-1.2"


def create_app() -> FastAPI:
    app = FastAPI(
        title="invoice-hub backend",
        description="全球采购平台票据智能与合规中台 · 确定性核心（无大模型依赖）",
        version=APP_VERSION,
    )
    app.include_router(cases_api.router)

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
