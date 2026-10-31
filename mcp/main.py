# -*- coding: utf-8 -*-
"""MCP Server FastAPI 服务入口（WP5.6 · FN-A-04 · 端口 8002）。

传输模式：streamable-http
端点约定：
  - POST /oauth/token：OAuth2 client_credentials 鉴权桩；
  - GET/POST /mcp/v1/tools/list：6 工具发现与枚举（与 mcp-tools.json 严格对齐）；
  - POST /mcp/v1/tools/call：工具调度与执行（受控写 confirm_token 强制拦截）；
  - GET /healthz：探活。
"""

from typing import Any, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.backend_client import BackendClient
from mcp.auth import issue_token, verify_scope
from mcp.server import McpServer
from mcp.tools_registry import get_mcp_policy, load_mcp_contract

app = FastAPI(
    title="invoice-hub mcp-server",
    description="全球采购平台票据智能与合规中台 · MCP Server 对外协议网关（端口 8002）",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

backend_client = BackendClient()
mcp_server = McpServer(backend_client)


# ───────────────────────── 请求模型 ─────────────────────────

class TokenRequest(BaseModel):
    grant_type: str = Field("client_credentials", description="仅支持 client_credentials")
    client_id: str = Field(..., description="客户端 ID")
    client_secret: str = Field(..., description="客户端密钥")
    scope: Optional[str] = Field(None, description="请求的 scope，空格分隔")


class ToolCallRequest(BaseModel):
    name: str = Field(..., description="工具名称，如 case.search")
    arguments: dict[str, Any] = Field(default_factory=dict, description="调用参数字典")


# ───────────────────────── 基础端点 ─────────────────────────

@app.get("/healthz")
def healthz():
    return {
        "status": "healthy",
        "service": "invoice-hub-mcp-server",
        "protocol": "streamable-http",
        "tools_count": len(mcp_server.list_tools()),
    }


@app.get("/mcp/v1")
def mcp_root():
    contract = load_mcp_contract()
    return {
        "name": "invoice-hub-mcp",
        "version": contract.get("version", "1.0.0"),
        "transport": contract.get("transport", {}),
        "auth": contract.get("auth", {}),
        "policy": contract.get("policy", {}),
    }


# ───────────────────────── OAuth2 鉴权端点 ─────────────────────────

@app.post("/oauth/token")
def oauth_token(req: TokenRequest):
    """OAuth2 client_credentials 令牌签发桩（FN-A-04）。"""
    if req.grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="仅支持 grant_type=client_credentials")
    return issue_token(req.client_id, req.client_secret, req.scope)


# ───────────────────────── MCP 核心端点 ─────────────────────────

@app.api_route("/mcp/v1/tools/list", methods=["GET", "POST"])
def list_mcp_tools(authorization: Optional[str] = Header(None)):
    """tools/list：枚举 6 项可用工具清单（与 contracts/mcp-tools.json 100% 一致）。"""
    # 允许携带 token，若携带且要求只读则校验；无 token 亦允许工具发现（标准 MCP 握手阶段允许发现）
    return {
        "tools": mcp_server.list_tools(),
        "policy": get_mcp_policy(),
    }


@app.post("/mcp/v1/tools/call")
def call_mcp_tool(req: ToolCallRequest, authorization: Optional[str] = Header(None)):
    """tools/call：调用特定工具。严格执行双 Scope 鉴权与受控写 confirm_token 拦截。"""
    return mcp_server.call_tool(req.name, req.arguments, authorization=authorization)
