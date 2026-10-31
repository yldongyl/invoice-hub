# -*- coding: utf-8 -*-
"""MCP 工具契约注册表（WP5.6 · 严格单一事实源）。

直接从 contracts/mcp-tools.json 读取并解析 6 项工具定义，确保 tools/list 与机器可读契约 100% 逐字一致。
"""

import json
from typing import Any
from mcp.config import MCP_TOOLS_CONTRACT_PATH


def load_mcp_contract() -> dict[str, Any]:
    """读取 contracts/mcp-tools.json 原文。"""
    if not MCP_TOOLS_CONTRACT_PATH.is_file():
        raise FileNotFoundError(f"MCP 契约文件不存在: {MCP_TOOLS_CONTRACT_PATH}")
    return json.loads(MCP_TOOLS_CONTRACT_PATH.read_text(encoding="utf-8"))


def list_tools() -> list[dict[str, Any]]:
    """返回供 tools/list 枚举的 6 项工具清单。"""
    contract = load_mcp_contract()
    return list(contract.get("tools", []))


def get_tool_definition(tool_name: str) -> dict[str, Any] | None:
    """按名称查找工具契约定义。"""
    for t in list_tools():
        if t["name"] == tool_name:
            return t
    return None


def get_mcp_policy() -> dict[str, Any]:
    """获取 MCP 调用安全策略（confirm_token 约束、操作人约束）。"""
    return load_mcp_contract().get("policy", {})
