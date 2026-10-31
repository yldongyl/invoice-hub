# -*- coding: utf-8 -*-
"""mcp/ · MCP Server 对外协议网关（ADR-0001 / FN-A-04）。

6 工具封装 = 4 只读 + 2 受控写（confirm_token 策略强制）。
零 DB 直连，全量消费 backend REST API。
"""

from mcp.server import McpServer
from mcp.tools_registry import list_tools, load_mcp_contract

__all__ = ["McpServer", "list_tools", "load_mcp_contract"]
