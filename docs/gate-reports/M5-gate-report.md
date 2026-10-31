# M5 门禁评审报告

- **评审日期**：2026-10-28
- **评审会话标识**：P00 + P10 独立验收会话（独立验收评审员，与实现会话严格分离，只评审不修复）
- **被评审提交与工作区范围**：全量工作区覆盖 M5 全部 WP5.1–WP5.7 交付成果、测试套件、UI 接线与验证报告
- **评审依据**：《invoice-hub实施规划.md》§4-M5 验收小节；《细化功能清单/vibe-coding-prompts/P06-M5-平台支撑与AgentMCP.md》§3 验收标准 9 条；《采购平台票据智能与合规中台-细化功能清单.md》对应 FN 条目（现场逐句核对）；P10 里程碑门禁评审全步骤规范。
- **环境信息**：Windows 11 Enterprise (win32)，Python 3.14.3 / Python 3.13.3 (`backend/.venv`)，FastAPI 0.115，SQLite `runtime/invoice_hub.db`。

---

## 1. 交付物盘点（工作包 × 存在性 × 完整性）

对照 P06 工作包清单（WP5.1–WP5.7）逐项盘点交付物，核对存在性与内容完整性：

| 工作包 | 交付文件路径 | 存在性 | 完整性判定 |
|---|---|---|---|
| **WP5.1 租户/RBAC/身份桩** | `backend/app/services/tenant_service.py`<br>`backend/app/services/rbac_service.py`<br>`backend/app/services/identity_service.py`<br>`backend/app/api/platform.py`<br>`backend/tests/test_platform_admin_m5.py` | ✅ 存在 | **完整**。双租户档案与四隔离校验完整；4×7(8) 动态权限矩阵实装；权限位注入受控框架；AI/LLM 零角色严格断言；SSO 演示桩（IdP 断言推导只读锁定 + 服务端二次校验真实逻辑）；账密登录 + MFA 强制校验 + 30 天信任设备；全员 MFA 用户表在位。 |
| **WP5.2 监控/队列/告警/配置/KMS/边界** | `backend/app/services/monitoring_service.py`<br>`backend/app/services/alert_engine.py`<br>`backend/app/services/platform_config_service.py`<br>`backend/app/api/platform.py`<br>`backend/tests/test_platform_admin_m5.py` | ✅ 存在 | **完整**。6 核心服务健康指标探测与 24h 序列；4 异步队列实时治理与断点续跑；告警引擎 4 基线规则实装；P0 红线不可停用强制拦截（开关回弹保持开启 + 违例审计留痕）；配置中心（全配置项、diff 弹窗数据 API、发布版本自增、联动 5 大适配器兼容性校验通知、旧版安全回滚、重置草稿零审计）；KMS 凭证全掩码与轮换留痕；模型数据边界配置与 30 天自动清理。 |
| **WP5.3 审计报表与归档合规** | `backend/app/services/audit_service.py`<br>`backend/app/services/sla_reporting_service.py`<br>`backend/app/services/archival_service.py`<br>`backend/app/services/sampling_service.py`<br>`backend/app/api/audit_reports.py`<br>`backend/tests/test_audit_reporting_m5.py` | ✅ 存在 | **完整**。审计四维检索过滤 + 统计条聚合 + 哈希链重验并登记 VerifyRun；CSV 导出自入链头（blk# 严格递增）+ 24h 限时凭证；SLA 六卡 P95 全达标 + 可用性 99.62% + 吞吐 62 张/分；识别质量指标表 + 错误自动放行率红线大卡（0.02% ≤ 0.05% + 12 周序列趋近 0）；AI 异常归因建议卡处置；10/7/2 年保留策略实体与生命周期清理；双实例独立成链校验；数据最小外发合规视图；周期抽检任务管理（QA-YYYY-Wnn-NN）+ SHA-256 比对 + 记录入链 + 异常联动冻结自动放行。 |
| **WP5.4 标注与数据沉淀** | `backend/app/services/annotation_service.py`<br>`backend/app/api/platform.py`<br>`backend/tests/test_platform_admin_m5.py` | ✅ 存在 | **完整**。错误样本自动回流（人工修正/验真失败/字段冲突样本自动入队、真实错误优先）；ANNO 发号器与任务四态流转；双人背靠背与一致率统计（97.2%）；沉淀规则转化接入规则引擎（rule_catalog，版本化+可回滚）；「标注数据不出客户控制域」合规开关（关闭被强制拦截+留痕）；防宽表退化说明数据完备。 |
| **WP5.5 LangGraph Agent 域** | `agent/conversation_graph.py`<br>`agent/investigation_graph.py`<br>`agent/attribution_agent.py`<br>`agent/mapping_assistant.py`<br>`agent/model_client.py`<br>`agent/backend_client.py`<br>`agent/tools.py`<br>`agent/config.py`<br>`agent/main.py`<br>`tests/test_agent_domain_m5.py` | ✅ 存在 | **完整**。三条 seed 意图对话图（金额差异>5000 调 `case.search` / 0387 证据链调 `case.get_evidence` / 海外重复票调 `dedup.report`）真实打通工具链；蓝标系统结果与橙标 AI 线索同屏严格分离；法定免责声明块；被调用 MCP 工具名标注；唤起只读详情卡（带「Agent 唤起 · 未修改数据」标记）；对话全程零写操作断言；会话审计留痕；AI 建议卡生成服务；主动调查编排；LLM 映射推荐真实实现；周期异常归因分析；模型客户端可替换配置化、逐次调用审计与 Prompt 30 天清理任务；零 DB 直连。 |
| **WP5.6 MCP Server 网关** | `mcp/server.py`<br>`mcp/auth.py`<br>`mcp/config.py`<br>`mcp/main.py`<br>`mcp/tools_registry.py`<br>`tests/test_mcp_server_m5.py` | ✅ 存在 | **完整**。按 `contracts/mcp-tools.json` 契约实装 6 项工具（4 只读 + 2 受控写）；streamable-http 协议；OAuth2 client_credentials 鉴权桩与双 scope（`invoice.read` / `invoice.write.controlled`）绑定；`write_tools_require_human_confirm_token` 策略强制拦截（缺失 token 428 拒绝，缺失 operator 400 拒绝）；工具实现为 backend API 薄封装；与 `agent/` 共用底层客户端与工具层的同源断言通过；tools/list 可枚举且与契约逐字一致；零 DB 直连。 |
| **WP5.7 剩余页面接线与全量回归** | `web/platform-admin.html`<br>`web/audit-reports.html`<br>`web/agent-workbench.html`<br>`web/api-portal.html`<br>`tools/verify_portal_sync.py`<br>`scripts/demo_replay.py`<br>`tests/test_demo_replay.py`<br>`tests/scenarios/test_scenarios_m5.py`<br>`docs/ui-verification-report-M5.md`<br>`docs/ui-verification-M5-shots/` | ✅ 存在 | **完整**。12 页面全量接线且 demo-mode 回退可用；CON-14 消息铃铛接告警计数与降级；CON-13 case-detail「人工查验」登记操作区；api-portal 页面内容与 contracts/ 文件同步校验脚本纳入 CI 门禁；全量 E2E 场景回归 + 蓝图 §13.2 八个 Demo 场景回放脚本（`scripts/demo_replay.py`）可用且全绿。 |

**缺件检查结论**：全量 7 大工作包交付物 **0 缺失、100% 完整**。

---

## 2. 运行证据（命令 × 结果摘要，评审员亲自执行）

评审员在运行环境下逐项亲自执行各项测试、契约校验与演示回放命令，以现场执行实测输出为准：

| # | 命令 | 运行环境 | 执行结果 | 摘要证据 |
|---|---|---|---|---|
| 1 | `python scripts/hub.py seed` | Python venv | **PASS** | `✅ make seed 完成（幂等重建）：23 类资产 / 244 行`<br>cases: 11, evidence: 36, timeline: 34, batches: 9, providers: 6, routing_policy: 1, adapters: 5, mapping_rules: 7, rules: 22, versions: 19。 |
| 2 | `python scripts/hub.py verify:enums` | `tools/check_enums.py` | **PASS** | `enum-registry v1.2.0 类别 25 / 值 142`<br>Sheet08 数据行 142（第 5 行起）<br>`✅ check_enums 通过：enum-registry 与 Sheet08 全 142 行逐行逐字一致`。 |
| 3 | `python scripts/hub.py verify:contracts` | `tools/validate_contracts.py` | **PASS** | `✅ validate_contracts 全绿：40 项检查通过`<br>含 9 个 JSON Schema 编译、openapi 全量 lint、11 案件过 Schema、routing_policy.json 过 routing-config.schema、编号规则与 25 类枚举强一致。 |
| 4 | `python scripts/hub.py verify:ui` | `tools/check_seeds_vs_ui.py` | **PASS** | `通过断言组 41｜口径注记 12｜已登记豁免 6｜失败 0`<br>全量 3 演示案件、dashboard 双实例、workbench 10 案、intake 批次、matching 队列与 adapters 状态对照全绿。 |
| 5 | `python scripts/hub.py verify:contracts-sync` | `tools/verify_portal_sync.py` | **PASS** | `[SUCCESS] api-portal 契约同步校验全部通过！文档站与 contracts/ 100% 同步！`<br>校验 web/ 与 ui-design/ 的 api-portal.html：6 个 MCP 工具、REST 端点、Webhook 事件码与 Schema 字段逐一匹配。 |
| 6 | `tools/check_breaking_changes.py` | `tools/check_breaking_changes.py` | **PASS** | `✅ v1 冻结契约破坏性变更检测通过（无破坏向后兼容性行为）`。 |
| 7 | `python scripts/hub.py test` | pytest (全量单元+契约) | **PASS** | **`405 passed, 1 warning in 88.78s`**<br>零失败（0 failure）。覆盖 M0–M5 全模块单元、集成、契约与页面标记测试。 |
| 8 | `python scripts/hub.py test-e2e` | pytest (`-m scenario`) | **PASS** | **`34 passed in 15.18s`**（全量 E2E 场景集）<br>包括 M3 12 场景 + M4 5 场景 + M5 7 场景（S-M5-01~07）及演示场景，100% 重复通过。 |
| 9 | `python scripts/hub.py test-redline` | pytest (`-m redline`) | **PASS** | **`16 passed in 6.26s`**（全量红线回归集）<br>R-01~R-06 全部实装并闭环通过，零 skip。 |
| 10 | `python scripts/hub.py demo-replay` | `scripts/demo_replay.py` | **PASS** | **`回放完毕：8 / 8 场景全部通过（ALL GREEN）！`**<br>数电票直读、PDF 待复核、重复票阻断、篡改票阻断、海外邮箱建档、Provider 切换、差异主动调查、Agent 对话操作全绿。 |
| 11 | `python scripts/hub.py smoke` | `tools/smoke.py` | **PASS** | **`冒烟结果：10/10 PASS`** 全绿。<br>覆盖 healthz、11 案件在库、双实例聚合、0387 详情、七要素证据、时间线、审计链完整性、受控写防守、web 托管与 demo-mode 回退在位。 |

---

## 3. 验收标准逐条判定（P06 §3 九条 / 规划 §4-M5 七条）

| # | 验收标准 | 判定 | 证据与执行细节（文件、行号、输出） |
|---|---|---|---|
| **1** | **红线告警关闭被拦截且尝试留痕** | **PASS** | **亲自执行** `backend/tests/test_platform_admin_m5.py:test_redline_alert_disable_blocked_and_audited` 与场景 `test_s_m5_01_redline_alert_disable_blocked_and_audited`：<br>- 向 `/api/platform/alerts/rules/false_auto_release_rate/toggle` 发送 `new_state: False` 请求；<br>- 返回 HTTP 403 强制拦截，响应 detail 表明「错误自动放行率 > 0.05% 为产品红线告警，不可停用，尝试行为已记入审计日志」；<br>- 重新 GET rules 断言规则保持 `on: True`（开关回弹保持开启）；<br>- 查验 SQLite 审计链，追加块记录 `【红线告警拦截】用户尝试关闭产品红线告警规则 false_auto_release_rate · 已强制拒绝并阻断`，`op_component="platform-admin/redline-guard"`。 |
| **2** | **配置发布 diff / 适配器通知 / 回滚可复现** | **PASS** | **亲自执行** `test_config_diff_and_reset_zero_audit`、`test_config_publish_version_diff_and_adapter_notifications`、`test_config_rollback`：<br>- 存入草稿后请求 `/api/platform/config/diff` 返回字段级变更数组（前值与后值清晰对照）；<br>- 执行 reset 重置草稿，断言 `audit_chain.head_blk` 严格不变（零审计记录）；<br>- 执行 publish 发布配置，版本自增为 `vYYYY-MM-DD.seq`，diff 明细追加不可篡改审计链，且联动返回 5 大目标适配器（SAP Ariba / Oracle ERP / Coupa / SAP S/4HANA / 自研 ERP）`status="COMPATIBLE"` 兼容性校验通知；<br>- 执行 rollback 回滚至指定历史版本，旧配置与旧版本号成功恢复，操作全量留痕。 |
| **3** | **Agent 对话三脚本意图走真实工具链，带未修改标记与审计** | **PASS** | **亲自执行** `tests/test_agent_domain_m5.py`（lines 54–120）：<br>① **意图 1（金额差异>5000）**：真实调用 `case.search`，返回包含 `tag-blue` 系统结果与 `tag-orange` AI 线索，带免责声明块，唤起只读卡带「Agent 唤起 · 未修改数据」标记，断言 `zero_write_asserted is True`；<br>② **意图 2（0387 证据链）**：真实调用 `case.get_evidence`，返回字段级七要素证据与 SM2 验签回执，蓝橙同屏分离；<br>③ **意图 3（海外重复票筛查）**：真实调用 `dedup.report`，跨实例查重并标记 BLOCKED 案件；<br>④ 审计链查验确认对话全流程写入 `CONVERSATION_RECORD` 事件。 |
| **4** | **MCP 客户端可枚举 6 工具，写工具无 confirm_token 被拒，agent 与 mcp 同源断言** | **PASS** | **亲自执行** `tests/test_mcp_server_m5.py`：<br>① `test_mcp_tools_list_contract_exact_match`：`GET /mcp/v1/tools/list` 枚举 6 个工具，名称（`case.search`, `case.get_evidence`, `dedup.report`, `provider.list`, `invoices.recognize`, `case.action`）、方向（4 只读 + 2 受控写）与 `contracts/mcp-tools.json` 100% 逐字一致；<br>② `test_case_action_missing_confirm_token_rejected_428` 与 `test_invoices_recognize_missing_confirm_token_rejected_428`：缺失 `confirm_token` 均被 HTTP 428 强制拦截（`E_CONFIRM_TOKEN_REQUIRED`），缺失 `operator` 返回 HTTP 400（`E_OPERATOR_REQUIRED`）；<br>③ `test_mcp_and_agent_tool_layer_source_parity`：对比 MCP 与 Agent 对同一关键词查询，返回条目与底层数据全等，断言同源一致。 |
| **5** | **审计导出自入链头（blk# 严格递增）** | **PASS** | **亲自执行** `backend/tests/test_audit_reporting_m5.py:test_export_audit_csv_self_audit_at_chain_head` 与 `test_s_m5_05_audit_export_self_audit_at_chain_head`：<br>- 记录导出前链头 `old_head`；<br>- 请求 `POST /api/audit/export` 导出 CSV；<br>- 断言返回的 `audit_blk == old_head + 1`（链头严格递增）；<br>- 查验新链头块，事件类型为 `AUDIT_EXPORT`，记录导出人、筛选条件与行数；同时返回带 24h 有效期的凭证与下载链接 `/v1/exports/{token}`。 |
| **6** | **12 页全部接线且 demo-mode 回退可用** | **PASS** | **亲自走查与单测验证** `backend/tests/test_api_web.py`：<br>- `test_all_12_pages_served` 确认 12 页面托管 200 OK；<br>- `test_platform_admin_wired_markers`、`test_audit_reports_wired_markers` 确认页面引用 `api-client.js` 与 `demo-mode.js`，挂接真实 API；<br>- 原型 mock 保留完整，未连接后台时自动回落内嵌 mock 并呈现 `#ihub-demo-badge` 演示角标（`pointer-events:none`、`top:60px`）；<br>- 详见 `docs/ui-verification-report-M5.md` 59/59 项通过。 |
| **7** | **全部 E2E 场景回归通过 + 蓝图 8 个 Demo 场景回放可用** | **PASS** | ① `pytest -m scenario` 全量 34 个 E2E 场景 100% 通过（涵盖 M3、M4、M5 全部场景）；<br>② 执行 `python scripts/demo_replay.py`：蓝图 §13.2 八大场景回放 8/8 全部通过，并输出投屏演示步骤对照表。 |
| **8** | **依赖纪律终检：backend 零 LLM import；agent/mcp 零 DB 直连** | **PASS** | ① `backend/tests/test_dependency_discipline.py` 通过：backend 无大模型框架引用、无 agent/mcp 引用、状态字面量无裸硬编码；<br>② `tests/test_agent_domain_m5.py:test_agent_domain_dependency_discipline` 通过：agent 零直接 DB/ORM 引用，backend 零 agent 引用；<br>③ `tests/test_mcp_server_m5.py:test_mcp_dependency_discipline` 通过：mcp 零直接 DB/ORM 引用，backend 零 mcp 引用；<br>④ GitHub Actions 与 GitLab CI 配置均集成一致性门禁、红线回归、单测覆盖率与 Demo 回放。 |
| **9** | **Excel Sheet02/03/04 全部行状态回填完毕，受阻项为零或已注明** | **PASS** | 评审员使用 openpyxl 亲自读取 `细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx`：<br>- **Sheet02（全局约定 FN-0）**：共 15 行，状态全为「待验收」，未完成项 0，受阻项 0；<br>- **Sheet03（分层功能 FN-1~9）**：共 102 行，状态全为「已实现」，未完成项 0，受阻项 0；<br>- **Sheet04（接口面 FN-A）**：共 9 行，状态全为「已实现」，未完成项 0，受阻项 0；<br>合计 126 项全部回填，未开始/进行中项清零。 |

---

## 4. 依赖纪律检查（6 项红线核查）

| # | 检查项 | 评审手段 | 判定 | 证据说明 |
|---|---|---|---|---|
| **1** | **backend 零 LLM import** | 静态扫描 + 自动化单测 | **PASS** | ① `test_dependency_discipline.py::test_no_model_framework_references` 通过；<br>② 正则扫描 `backend/app/` 全部 Python 源码，命中 `langgraph`、`openai`、`anthropic`、`google.generativeai` 计数为 0；确定性核心无 LLM 调用。 |
| **2** | **agent / mcp 零 DB 直连** | 静态扫描 + 自动化单测 | **PASS** | ① `test_agent_domain_dependency_discipline` 与 `test_mcp_dependency_discipline` 全绿；<br>② 扫描 `agent/` 与 `mcp/` 目录下全部 Python 源码，零 `sqlite3`、`sqlalchemy`、`get_session` 或 `models` 直连引用；全量通过 `BackendClient` 消费 backend REST API。 |
| **3** | **web 只消费 REST API** | 源码走查 + 依赖审查 | **PASS** | `web/` 下各页面统一引用 `web/js/api-client.js` 进行标准 fetch REST API 请求，零 Node.js 原生模块、零外部 SDK、零数据库直连；保留完整 demo-mode 回退机制。 |
| **4** | **枚举零硬编码** | `check_enums.py` + 代码扫描 | **PASS** | ① `tools/check_enums.py` 全量通过（142/142 值对齐）；<br>② `test_dependency_discipline.py::test_enum_discipline_no_bare_enum_literals_in_services` 通过；<br>③ 案件六态、来源六枚举、四校验结果等核心逻辑均从 `contracts/enum-registry.json` 解析校验，无散落硬编码。 |
| **5** | **写路径全过受控框架** | 端点调用链走查 | **PASS** | 抽查 3 个核心变异端点：<br>① `POST /api/platform/alerts/rules/{rule_id}/toggle`：通过 `governed_commands` 拦截红线尝试并写审计；<br>② `POST /api/platform/config/publish`：通过受控发布流程记录操作人、前后值 diff、追加审计块并联动适配器通知；<br>③ `POST /mcp/v1/tools/call`（`case.action`）：强制校验 `confirm_token` 与 `operator`，转发受控命令执行并写审计。 |
| **6** | **ui-design 只读 / 旧仓零拷贝** | mtime 审查 + 文本扫描 | **PASS** | ① `../ui-design/` 目录全部 16 个文件修改时间保持在 2026-10-21/22（早于工程建设），零改动；<br>② 扫描全库代码，无任何来自旧仓 `ariba-mock/` 或 `invoice-platform/` 的代码拷贝或 contracts 路径引用。 |

---

## 5. 口径深度抽查记录（深度抽查 6 处，对照清单原文文字逐句核验）

| 抽查条目 | 细化功能清单规则原文要点 | 实现与测试行为 | 判定 |
|---|---|---|---|
| **FN-0-09 AI / LLM 治理边界**<br>*(必查项)* | ① 确定性判断（税额计算、容差判定、授权检查、查重、状态转换）一律归规则引擎；LLM 只承担不确定性推理；<br>② 输出强制携带「AI 生成」橙标 + 模型名与版本 + 置信度 + 免责声明；系统查询蓝标分离展示；<br>③ AI 建议不自动执行任何写操作；采纳仍走 FN-0-08，不采纳留痕 `LLM_ADVICE_REJECTED`；<br>④ AI/LLM 不持有任何 RBAC 角色；Prompt/响应保存期限（30 天清理）；逐次调用审计；<br>⑤ 模型不得自行宣称发票真实。 | 走查 `agent/conversation_graph.py`、`agent/model_client.py` 及 `backend/app/services/rbac_service.py`：<br>① 状态机与四校验全部由规则引擎驱动，大模型输出永不直接写入 checks/status；<br>② 对话图输出严格组装 `tag-blue` 系统结果与 `tag-orange` AI 线索，内嵌法定免责声明块；<br>③ 对话运行后断言 `zero_write_asserted is True`；`test_case_detail_ai_advice_reject` 验证不采纳留痕于时间线与审计链；<br>④ `test_ai_agent_zero_role_strictly_enforced` 验证 AI 主体调用写操作直接抛 `E_PERM_DENIED` 拒绝；配置中心包含 30 天清理任务与调用审计。 | **PASS** |
| **FN-A-04 MCP Server 网关**<br>*(必查项)* | ① 六项工具：4 只读（`case.search`, `case.get_evidence`, `dedup.report`, `provider.list`）+ 2 受控写（`invoices.recognize`, `case.action`）；<br>② 受控边界：只读任意调用，**写工具必须携带人工确认 token（confirm_token）与 operator**，AI 禁止静默写；<br>③ 鉴权：OAuth2 client_credentials + 双 scope（`invoice.read` / `invoice.write.controlled`）+ policy 强制 confirm；<br>④ Agent 工作台底层即调用本工具集（同源断言，禁止私有旁路）。 | 走查 `mcp/server.py:120-195` 及 `tests/test_mcp_server_m5.py`：<br>① `tools_registry.py` 严格装载 6 工具；<br>② `server.py:call_tool` 对受控写工具强制校验：缺 `confirm_token` 抛 HTTP 428（`E_CONFIRM_TOKEN_REQUIRED`），缺 `operator` 抛 HTTP 400（`E_OPERATOR_REQUIRED`）；<br>③ `mcp/auth.py` 验证 Bearer Token 与 scope 匹配，只读 token 调用写工具返回 HTTP 403；<br>④ `test_mcp_and_agent_tool_layer_source_parity` 实测证明 MCP 与 Agent 共享同一底层逻辑。 | **PASS** |
| **FN-9-02 RBAC 角色权限矩阵** | ① 4 角色 × 7 操作权限矩阵（基线）；管理员=全权限；复核员/运营/审计只读各司其职；<br>② 矩阵编辑 = 高风险变更（二次确认 + diff 入审计）；<br>③ **AI/LLM 不持有任何角色**。 | 走查 `backend/app/services/rbac_service.py`：<br>① 完整实装 4 角色（管理员/复核员/运营/审计只读）× 8 权限位定义；<br>② 修改矩阵调用 `update_role_matrix` 记录变更 diff 并写入审计块；<br>③ `require_permission` 明确拦截所有以 AI 开头的主体身份，抛出 `AI/Agent/LLM 不持有任何 RBAC 角色` 异常。 | **PASS** |
| **FN-9-08 告警引擎与红线不可停用** | ① 告警规则管理：4 条基线规则（Provider P95、**错误自动放行率 >0.05% P0 红线**、队列积压、GPU 利用率）；<br>② 红线告警不可停用，关闭尝试被拦截且留痕；<br>③ 告警联动（抽检异常 → 冻结自动放行）。 | 走查 `backend/app/services/alert_engine.py:45-65` 及 `backend/tests/test_platform_admin_m5.py`：<br>① `toggle_rule` 检查若为 `redline` 且 `new_state=False`，抛出 HTTP 403 异常，开关保持原状（回弹）；<br>② 违规关闭尝试记录至 `audit_chain`，标记为 `【红线告警拦截】`；<br>③ `sampling_service.py` 出现抽检异常自动触发熔断，更新配置冻结自动放行通道。 | **PASS** |
| **FN-8-12 SLA 与质量报表** | ① 6 链路 P95 真实统计（直读/抽取/OCR/同步/查重/归档）；<br>② 可用性（含降级链路）与吞吐标尺；<br>③ 识别质量指标表；<br>④ **产品红线指标（错误自动放行率 ≤ 0.05%）与 12 周序列**。 | 走查 `backend/app/services/sla_reporting_service.py`：<br>① 返回 6 链路 P95 统计卡，状态全为「达标」；<br>② 滚动可用性 99.62%，吞吐 62 张/分；<br>③ 质量表包含高风险字段单独统计与整票正确率；<br>④ 错误自动放行率当前值 0.02%（≤0.05% 红线），提供 12 周历史点阵序列。 | **PASS** |
| **FN-8-13 标注任务管理与规则沉淀** | ① 错误样本自动回流（识别错/验真异常/人工修正样本入队）；<br>② ANNO 任务四态流转与双人背靠背一致率；<br>③ 修正沉淀为规则条款（版本化+可回滚）；<br>④ **「标注数据不出客户控制域」合规开关（关闭被拦截+留痕）**。 | 走查 `backend/app/services/annotation_service.py`：<br>① `auto_feed_error_sample` 接收错误样本生成 ANNO 任务；<br>② 任务经审核后调用 `crystallize_rule` 生成版本化规则注入注册表；<br>③ `toggle_data_domain_boundary` 对关闭合规开关抛出 403 拦截并记入审计链。 | **PASS** |

---

## 6. 画面验证复核（UI 报告复审与亲自抽查）

- **核验报告与截图审查**：
  复核 `docs/ui-verification-report-M5.md`，报告全量 59 项自动化断言 **59 PASS / 0 FAIL / 0 阻断**（100% 通过）；12 张 1680×1050 自动化高精度截图全量归档在 `docs/ui-verification-M5-shots/`。

- **评审员亲自代码与交互抽查（3 个区块）**：
  1. **抽查区块 1：`web/platform-admin.html` 红线告警关闭拦截与回弹**：
     - 代码定位：`web/platform-admin.html:711-721`（`toggleAlertRule`）；
     - 走查实测：对 `r.redline` 检查，若尝试置为关闭，前端强制将 `r.on = true`，重新追加 `el.classList.add('on')`，并弹出 toast 提示「『错误自动放行率 > 0.05%』为产品红线告警，不可停用 · 本次尝试已记入审计日志」；后端 API 对应返回 403，审计链成功留痕。
  2. **抽查区块 2：`web/audit-reports.html` 归档合规视图与红线 12 周趋势图**：
     - 代码定位：`web/audit-reports.html:543-575, 970-1006`；
     - 走查实测：Tab 3 呈现 XML/OFD/PDF 等 6 张归档统计卡与手绘 SVG 构成 Donut（结构化占比 71.6%）；Tab 2 错误自动放行率大卡内联 SVG 折线图，包含红线 0.05% 虚线对照，12 周趋势平稳趋零（当前 0.02%）。
  3. **抽查区块 3：`web/agent-workbench.html` Agent 对话蓝橙标同屏分离与只读卡唤起**：
     - 代码定位：`web/agent-workbench.html:382-440`；
     - 走查实测：输入推荐意图后，系统查询结果冠以 `SYS_TAG` 蓝标（`系统查询结果`），大模型线索冠以 `AI_TAG` 橙标（`AI 生成`），底部紧随黄底法定免责声明块；点击卡片底部「📂 查看案件详情」按钮调用 `openCase(id, 'agent')` 唤起只读定位卡，右侧横幅显式标注「Agent 对话唤起 · 只读定位，未修改任何数据」。

---

## 7. 台账与 TODO 对账

- **台账状态核对**：
  评审员使用 openpyxl 扫描 `细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx`：
  - `02-全局约定FN-0`：15 项全部为「待验收」，0 项未完成；
  - `03-分层功能FN-1~9`：102 项全部为「已实现」，0 项未完成；
  - `04-接口面FN-A`：9 项全部为「已实现」，0 项未完成；
  - **总完成率 100%（126/126）**，受阻项为 0。
- **TODO 扫描对账**：
  正则扫描全库源码命中 2 处 TODO：
  - `TODO(H39)`：出现在 `backend/app/services/tenant.py`，对应清单附录 D 的 H39 数据驻留与合规边界推断标注（演示口径）；
  - `TODO(CON-12)`：出现在 `backend/tests/test_config_center.py`，对应 Sheet06 的 CON-12 容差分离决议；
  - 扫描结论：**代码中所有 TODO 均在清单附录 D 及 Sheet06 登记范围内，无任何清单外的口径漂移 TODO**。

---

## 8. 缺陷清单

| 编号 | 级别 | 复现描述 | 关联 FN | 处置建议 |
|---|---|---|---|---|
| — | — | **本次评审未发现任何 BLOCKER 或 MAJOR 缺陷项** | — | — |
| N-01 | MINOR | `fastapi.testclient` 使用当前版本的 starlette 依赖触发 1 条 StarletteDeprecationWarning | FN-A-01 | 后续升级 FastAPI 依赖时平滑适配 httpx2，不影响功能与测试 |

---

## 9. 门禁评审结论

**评审结论：【通过（PASS）】**

- **判定依据**：
  1. WP5.1~WP5.7 全部交付物完整在位，无缺件；
  2. 亲自执行全量测试（405 passed / 0 failed）、E2E 场景（34 passed）、红线回归（16 passed）、Demo 场景回放（8/8 passed）、冒烟测试（10/10 passed）全绿；
  3. 契约校验 40/40 项通过，枚举一致性 142/142 逐字对齐，API 门户契约 100% 同步，零破坏性变更；
  4. 依赖纪律 6 项红线严格通过：backend 零 LLM import，agent/mcp 零 DB 直连，写路径全受控；
  5. 12 页全量接线且 demo-mode 正常回退；
  6. Excel 三张台账 126 项 100% 回填，受阻项为 0。

**放行建议**：同意 M5 正式结项，立即推进 P10 §5 全量终验。
