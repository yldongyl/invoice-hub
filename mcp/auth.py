# -*- coding: utf-8 -*-
"""OAuth2 client_credentials 鉴权桩与双 Scope 校验（WP5.6 · FN-A-04）。

鉴权规范：
  - Grant 类型：client_credentials；
  - 核心双 scope：
    ① `invoice.read`：只读工具必需；
    ② `invoice.write.controlled`：受控写工具额外必需；
  - 演示口径：支持预设 demo 凭证签发与验证，严格执行 scope 绑定。
"""

import secrets
from typing import Optional, Set
from fastapi import Header, HTTPException, status

from mcp.config import DEMO_CLIENT_ID, DEMO_CLIENT_SECRET

SCOPE_READ = "invoice.read"
SCOPE_WRITE_CONTROLLED = "invoice.write.controlled"
VALID_SCOPES = {SCOPE_READ, SCOPE_WRITE_CONTROLLED}

# 内存令牌存储: token -> {client_id, scopes, expires_at}
_ACTIVE_TOKENS: dict[str, dict] = {}


def issue_token(client_id: str, client_secret: str, scope: Optional[str] = None) -> dict:
    """OAuth2 /oauth/token 签发端点桩（client_credentials 模式）。"""
    if client_id != DEMO_CLIENT_ID or client_secret != DEMO_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_client", "error_description": "客户端 ID 或密钥无效"},
        )

    # 解析请求的 scope，默认赋予只读；若显式请求写入则需在合法范围内
    req_scopes = set(scope.split()) if scope else {SCOPE_READ}
    invalid = req_scopes - VALID_SCOPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_scope", "error_description": f"不支持的 scope: {invalid}"},
        )

    token = f"mcp-oauth-{secrets.token_hex(16)}"
    token_data = {
        "client_id": client_id,
        "scopes": req_scopes,
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    _ACTIVE_TOKENS[token] = token_data

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": " ".join(sorted(req_scopes)),
    }


def verify_scope(authorization: Optional[str], required_scope: str) -> dict:
    """校验请求头中的 Bearer Token 及其是否持有指定的 scope。"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 请求头（OAuth2 Bearer Token 必需）",
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 格式无效，必须为 'Bearer <token>'",
        )

    token = parts[1]
    token_info = _ACTIVE_TOKENS.get(token)

    # 演示口径友好：支持特定测试令牌直通
    if token == "test-read-token":
        token_info = {"client_id": "test", "scopes": {SCOPE_READ}}
    elif token == "test-write-token":
        token_info = {"client_id": "test", "scopes": {SCOPE_READ, SCOPE_WRITE_CONTROLLED}}

    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth2 凭证无效或已过期",
        )

    scopes: Set[str] = token_info.get("scopes", set())
    if required_scope not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"权限不足：当前凭证缺少必需的权限范围「{required_scope}」（持有: {sorted(scopes)}）",
        )

    return token_info
