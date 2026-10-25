# mcp/ · MCP Server（对外 Agent 生态，ADR-0001）

6 工具封装 = 4 只读（case.search / case.get_evidence / dedup.report / provider.list）+ 2 受控写（invoices.recognize / case.action，须 confirm_token + operator）。

- **实装里程碑**：M5（FN-A-04）；M0 仅目录占位，**无代码**。
- **契约基准**：`contracts/mcp-tools.json`（工具面）+ `contracts/openapi.yaml`（REST 同源语义）。
- **鉴权**：OAuth2 client_credentials + 双 scope（invoice.read / invoice.write.controlled），policy 强制人工确认 token；演示桩口径。
