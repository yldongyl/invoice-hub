# -*- coding: utf-8 -*-
"""FastAPI 应用入口（WP1.1 · ADR-0001 双轨制：backend 确定性核心，零大模型依赖）。

只读 API 面 + /healthz（WP1.2）与受控写命令入口（WP1.5：risk-challenge / actions /
batch / export，全部经 governed_commands 五要素框架）；受理流水线（WP1.6）等后续工作包挂载。
"""

from fastapi import FastAPI

from app.api import actions as actions_api, cases as cases_api
from app.domain.registry import get_registry
from app.services import persistence

APP_VERSION = "0.2.0-m1-wp1.3-1.5"


def create_app() -> FastAPI:
    app = FastAPI(
        title="invoice-hub backend",
        description="全球采购平台票据智能与合规中台 · 确定性核心（无大模型依赖）",
        version=APP_VERSION,
    )
    app.include_router(cases_api.router)
    app.include_router(actions_api.router)

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
