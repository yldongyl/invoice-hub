# -*- coding: utf-8 -*-
"""MCP Server 配置（WP5.6 · ADR-0001 / FN-A-04）。

配置项：
  - MCP 服务端口：8002（streamable-http）；
  - 后端核心 API 地址：默认 http://127.0.0.1:8000；
  - 契约文件路径：contracts/mcp-tools.json。
"""

import os
from pathlib import Path

MCP_HOST = os.environ.get("INVOICE_HUB_MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("INVOICE_HUB_MCP_PORT", "8002"))

BACKEND_BASE_URL = os.environ.get("INVOICE_HUB_BACKEND_URL", "http://127.0.0.1:8000")

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
MCP_TOOLS_CONTRACT_PATH = CONTRACTS_DIR / "mcp-tools.json"

# OAuth2 演示客户端凭证
DEMO_CLIENT_ID = os.environ.get("INVOICE_HUB_CLIENT_ID", "joule-agent-client-01")
DEMO_CLIENT_SECRET = os.environ.get("INVOICE_HUB_CLIENT_SECRET", "sec-demo-9f8a32b1")
