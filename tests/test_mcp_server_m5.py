# -*- coding: utf-8 -*-
"""M5 MCP Server 全量测试套件（WP5.6 · FN-A-04 · contracts/mcp-tools.json）。

覆盖内容：
  - 1. tools/list 可枚举且与 contracts/mcp-tools.json 及 enum-registry 完全一致（6 工具 = 4 只读 + 2 受控写）；
  - 2. OAuth2 client_credentials 鉴权桩与双 scope（invoice.read / invoice.write.controlled）权限校验；
  - 3. write_tools_require_human_confirm_token 策略强制（invoices.recognize 与 case.action 缺 token 428 拒绝，缺 operator 400 拒绝）；
  - 4. 4 只读工具执行与 backend API 薄封装转发验证；
  - 5. 与 agent/ 共用工具层的同源断言测试（禁止私有旁路）；
  - 6. 依赖纪律验证：mcp/ 零 DB 直连，backend/ 零 mcp import。
"""

import json
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

INVOICE_HUB_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = INVOICE_HUB_ROOT / "backend"
MCP_ROOT = INVOICE_HUB_ROOT / "mcp"
CONTRACTS_DIR = INVOICE_HUB_ROOT / "contracts"

if str(INVOICE_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(INVOICE_HUB_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agent.backend_client import BackendClient
from mcp.main import app as mcp_app
from mcp.server import McpServer
from mcp.tools_registry import list_tools, load_mcp_contract
from app.main import create_app as create_backend_app


@pytest.fixture
def backend_client():
    """提供对接 backend API 的客户端（用于同源测试）。"""
    backend_app = create_backend_app()
    client = TestClient(backend_app)
    return BackendClient(http_client=client)


@pytest.fixture
def mcp_client(backend_client):
    """提供针对 MCP Server 的 TestClient，注入统一 backend_client。"""
    # 替换 mcp_app 内的后端客户端以确保测试隔离
    from mcp import main as mcp_main
    mcp_main.backend_client = backend_client
    mcp_main.mcp_server = McpServer(backend_client)
    return TestClient(mcp_app)


# ───────────────────────── 1. tools/list 与契约 100% 一致性 ─────────────────────────

def test_mcp_tools_list_contract_exact_match(mcp_client):
    """断言 tools/list 可枚举 6 项工具，且与 contracts/mcp-tools.json 完全一致。"""
    res = mcp_client.get("/mcp/v1/tools/list")
    assert res.status_code == 200
    data = res.json()
    tools = data["tools"]
    assert len(tools) == 6

    contract_tools = load_mcp_contract()["tools"]
    contract_names = [t["name"] for t in contract_tools]

    # 六项工具名称严格对齐
    expected_names = [
        "case.search",
        "case.get_evidence",
        "dedup.report",
        "provider.list",
        "invoices.recognize",
        "case.action",
    ]
    assert [t["name"] for t in tools] == expected_names
    assert [t["name"] for t in tools] == contract_names

    # 4 只读 + 2 受控写
    read_tools = [t for t in tools if t["access"] == "read"]
    write_tools = [t for t in tools if t["access"] == "controlled_write"]
    assert len(read_tools) == 4
    assert len(write_tools) == 2
    assert all(t.get("confirm_token_required") is True for t in write_tools)


# ───────────────────────── 2. OAuth2 Client Credentials 鉴权与双 Scope ─────────────────────────

def test_oauth2_token_issuance_and_scopes(mcp_client):
    """测试 OAuth2 client_credentials 令牌签发（双 scope 绑定）。"""
    # 1. 签发只读 token (invoice.read)
    res_read = mcp_client.post("/oauth/token", json={
        "grant_type": "client_credentials",
        "client_id": "joule-agent-client-01",
        "client_secret": "sec-demo-9f8a32b1",
        "scope": "invoice.read",
    })
    assert res_read.status_code == 200
    token_read = res_read.json()
    assert token_read["token_type"] == "Bearer"
    assert token_read["scope"] == "invoice.read"

    # 2. 签发受控写 token (invoice.read invoice.write.controlled)
    res_write = mcp_client.post("/oauth/token", json={
        "grant_type": "client_credentials",
        "client_id": "joule-agent-client-01",
        "client_secret": "sec-demo-9f8a32b1",
        "scope": "invoice.read invoice.write.controlled",
    })
    assert res_write.status_code == 200
    token_write = res_write.json()
    assert "invoice.write.controlled" in token_write["scope"]

    # 3. 错误凭证被拒
    res_err = mcp_client.post("/oauth/token", json={
        "grant_type": "client_credentials",
        "client_id": "invalid-client",
        "client_secret": "wrong-secret",
    })
    assert res_err.status_code == 401


def test_scope_enforcement_for_tools(mcp_client):
    """测试工具调用的 Scope 权限控制：只读工具需 invoice.read，写工具需 invoice.write.controlled。"""
    # 1. 无 token 调用只读工具 -> 401
    res_no_auth = mcp_client.post("/mcp/v1/tools/call", json={
        "name": "case.search",
        "arguments": {"keyword": "中科华创"},
    })
    assert res_no_auth.status_code == 401

    # 2. 持有只读 token 调用只读工具 -> 200 成功
    res_read_ok = mcp_client.post(
        "/mcp/v1/tools/call",
        json={"name": "case.search", "arguments": {"keyword": "中科华创"}},
        headers={"Authorization": "Bearer test-read-token"},
    )
    assert res_read_ok.status_code == 200

    # 3. 仅持有只读 token 尝试调用受控写工具 -> 403 权限不足（缺少 invoice.write.controlled）
    res_write_denied = mcp_client.post(
        "/mcp/v1/tools/call",
        json={
            "name": "case.action",
            "arguments": {
                "caseId": "INV-CN-2026-0387",
                "action": "RELEASE",
                "confirm_token": "valid-token",
                "operator": "王莉",
            },
        },
        headers={"Authorization": "Bearer test-read-token"},
    )
    assert res_write_denied.status_code == 403
    assert "invoice.write.controlled" in res_write_denied.json()["detail"]


# ───────────────────────── 3. 受控写工具 confirm_token 策略强制 ─────────────────────────

def test_case_action_missing_confirm_token_rejected_428(mcp_client):
    """红线断言：调用 case.action 缺失 confirm_token 被 428 Precondition Required 拦截。"""
    res = mcp_client.post(
        "/mcp/v1/tools/call",
        json={
            "name": "case.action",
            "arguments": {
                "caseId": "INV-CN-2026-0387",
                "action": "RELEASE",
                "operator": "王莉",
                # confirm_token 缺失！
            },
        },
        headers={"Authorization": "Bearer test-write-token"},
    )
    assert res.status_code == 428
    detail = res.json()["detail"]
    assert detail["error_code"] == "E_CONFIRM_TOKEN_REQUIRED"
    assert "write_tools_require_human_confirm_token" in detail["message"]


def test_case_action_missing_operator_rejected_400(mcp_client):
    """断言：调用受控写工具缺失 operator 被 400 拦截。"""
    res = mcp_client.post(
        "/mcp/v1/tools/call",
        json={
            "name": "case.action",
            "arguments": {
                "caseId": "INV-CN-2026-0387",
                "action": "RELEASE",
                "confirm_token": "fake-token",
                # operator 缺失！
            },
        },
        headers={"Authorization": "Bearer test-write-token"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "E_OPERATOR_REQUIRED"


def test_invoices_recognize_missing_confirm_token_rejected_428(mcp_client):
    """红线断言：调用 invoices.recognize 缺失 confirm_token 被 428 拦截。"""
    res = mcp_client.post(
        "/mcp/v1/tools/call",
        json={
            "name": "invoices.recognize",
            "arguments": {
                "file_ref": "minio://bucket/inv.pdf",
                "instance": "CN",
                "operator": "王莉",
                # confirm_token 缺失！
            },
        },
        headers={"Authorization": "Bearer test-write-token"},
    )
    assert res.status_code == 428
    assert res.json()["detail"]["error_code"] == "E_CONFIRM_TOKEN_REQUIRED"


# ───────────────────────── 4. 4 只读工具执行与 API 薄封装验证 ─────────────────────────

def test_readonly_tools_execution(mcp_client):
    """测试 4 项只读工具调度执行与返回结构。"""
    auth = {"Authorization": "Bearer test-read-token"}

    # 1. case.search
    r1 = mcp_client.post("/mcp/v1/tools/call", json={"name": "case.search", "arguments": {"keyword": "中科华创"}}, headers=auth)
    assert r1.status_code == 200
    assert r1.json()["tool"] == "case.search"
    assert r1.json()["count"] >= 1

    # 2. case.get_evidence
    r2 = mcp_client.post("/mcp/v1/tools/call", json={"name": "case.get_evidence", "arguments": {"caseId": "INV-CN-2026-0387"}}, headers=auth)
    assert r2.status_code == 200
    assert r2.json()["tool"] == "case.get_evidence"
    assert r2.json()["caseId"] == "INV-CN-2026-0387"
    assert len(r2.json()["evidence"]) >= 1

    # 3. dedup.report
    r3 = mcp_client.post("/mcp/v1/tools/call", json={"name": "dedup.report", "arguments": {}}, headers=auth)
    assert r3.status_code == 200
    assert r3.json()["tool"] == "dedup.report"
    assert "conclusion" in r3.json()

    # 4. provider.list
    r4 = mcp_client.post("/mcp/v1/tools/call", json={"name": "provider.list", "arguments": {}}, headers=auth)
    assert r4.status_code == 200
    assert r4.json()["tool"] == "provider.list"
    assert r4.json()["count"] >= 6


# ───────────────────────── 5. 与 agent/ 共用工具层的同源断言 ─────────────────────────

def test_mcp_and_agent_tool_layer_source_parity(backend_client):
    """同源断言测试：验证 MCP 工具层与 Agent 域调用的查询逻辑基于同一底层工具层，返回一致。"""
    from agent.tools import case_search as agent_case_search
    from mcp.server import McpServer

    mcp_srv = McpServer(backend_client)

    # 1. 直接通过 Agent 工具层查询
    agent_res = agent_case_search(backend_client, query="中科华创")

    # 2. 通过 MCP Server 工具分发查询
    mcp_res = mcp_srv.call_tool("case.search", {"keyword": "中科华创"}, authorization="Bearer test-read-token")

    # 3. 断言二者底层数据完全一致
    assert len(agent_res) == mcp_res["count"]
    agent_ids = [c.get("caseId") or c.get("id") for c in agent_res]
    mcp_ids = [c.get("caseId") or c.get("id") for c in mcp_res["items"]]
    assert agent_ids == mcp_ids


# ───────────────────────── 6. 依赖纪律严格自查（代码评审红线） ─────────────────────────

def test_mcp_dependency_discipline():
    """红线自查：
    1. mcp/ 目录下绝对严禁直接连接 DB 或 import 任何 ORM/SQLAlchemy/sqlite3；
    2. backend/ 绝对严禁 import mcp/。
    """
    forbidden_db_patterns = ["import sqlite3", "from sqlalchemy", "import sqlalchemy", "get_session", "persistence.py"]
    for p in MCP_ROOT.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for f_kw in forbidden_db_patterns:
            assert f_kw not in text, f"mcp/{p.name} 存在直连 DB 或 ORM 引用违规: {f_kw}"

    import re
    pat = re.compile(r"^\s*(?:from|import)\s+mcp\b")
    for p in BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in str(p) or ".venv" in str(p) or "venv" in str(p):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not pat.search(line), f"backend/{p.name} 违规 import mcp: {line}"
