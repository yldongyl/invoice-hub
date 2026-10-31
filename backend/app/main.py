# -*- coding: utf-8 -*-
"""FastAPI 应用入口（WP1.1 · ADR-0001 双轨制：backend 确定性核心，零大模型依赖）。

只读 API 面 + /healthz（WP1.2）、受控写命令入口（WP1.5：risk-challenge / actions /
batch / export / intake，全部经 governed_commands 五要素框架）、M2 读路径垂直切片
（WP2.1/2.2：dashboard 聚合 / alerts 读侧 / exists 深链校验 / 列表投影与切换器）与
M3 受理通道面（WP3.1/3.2：intake——recognize 契约端点 / 门户上传 / 批次 / KPI / 渠道 / 规则版本 / Job 桩）。
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import (actions as actions_api, cases as cases_api, dashboard as dashboard_api,
                     intake as intake_api, workbench as workbench_api, providers as providers_api,
                     matching as matching_api, adapters as adapters_api, platform as platform_api,
                     audit_reports as audit_reports_api)
from app.domain.registry import get_registry
from app.services import identity_service, persistence
from app.services.errors import CommandError

APP_VERSION = "0.4.4-m3-wp3.6"
# P03 WP2.3 部署形态：backend 同源静态托管 web/（单端口，免 CORS）；
# web/ = ui-design 12 页接线副本（ADR-0003），根路径重定向到总览仪表盘（P07 RUNBOOK 入口）
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app() -> FastAPI:
    app = FastAPI(
        title="invoice-hub backend",
        description="全球采购平台票据智能与合规中台 · 确定性核心（无大模型依赖）",
        version=APP_VERSION,
    )

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        """live API 鉴权门禁：/v1 与 /api 业务接口必须携带 Bearer 会话。

        登录/会话端点、healthz、web 静态资源保持公开；MCP/Agent 分属独立服务不走本门禁。
        """
        path = request.url.path
        request.state.ihub_session = None
        public_api = path in {"/healthz", "/api/platform/auth/login", "/api/platform/auth/mfa/challenge", "/api/platform/sso/login"}
        auth_disabled = os.environ.get("INVOICE_HUB_DISABLE_AUTH") == "1"
        if (path.startswith("/v1") or path.startswith("/api")) and not public_api and not auth_disabled:
            auth = request.headers.get("authorization", "")
            scheme, _, token = auth.partition(" ")
            try:
                session_payload = identity_service.verify_session_token(
                    token if scheme.lower() == "bearer" and token else None
                )
                request.state.ihub_session = session_payload
                if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                    actor = identity_service.current_actor(session_payload)
                    try:
                        raw = await request.body()
                        if raw and (request.headers.get("content-type") or "").split(";")[0] == "application/json":
                            data = json.loads(raw.decode("utf-8"))
                            if isinstance(data, dict) and "actor" in data and data["actor"] not in (actor, "human", "system"):
                                return JSONResponse(status_code=403, content={"detail": {"error_code": "E_ACTOR_MISMATCH", "message": f"请求操作人 {data['actor']!r} 与当前登录用户 {actor!r} 不一致"}})
                    except json.JSONDecodeError:
                        pass
            except CommandError as e:
                return JSONResponse(status_code=e.http, content={"detail": {"error_code": e.code, "message": e.message}})
        return await call_next(request)
    app.include_router(cases_api.router)
    app.include_router(actions_api.router)
    app.include_router(dashboard_api.router)
    app.include_router(intake_api.router)
    app.include_router(workbench_api.router)
    app.include_router(providers_api.router)
    app.include_router(matching_api.router)
    app.include_router(adapters_api.router)
    app.include_router(platform_api.router)
    app.include_router(audit_reports_api.router)
    app.include_router(audit_reports_api.anno_router)

    # M2 WP2.3：web 运行副本同源托管（/web/*.html 直访；仅目录存在时挂载，测试/最小部署不受影响）
    if WEB_DIR.is_dir():
        app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/web/login.html")

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
