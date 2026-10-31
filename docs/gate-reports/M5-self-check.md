# M5 自检报告（P00+P06 · M5 全功能收口终验自检报告）

> 执行范围：P00+P06 全部工作包 **WP5.1–WP5.7**：
> - **WP5.1 租户/RBAC/身份桩**：双租户档案与四隔离验证、4×7(8) 动态权限矩阵实装、受控框架注入、AI/LLM 零角色严格断言、SSO 演示桩（IdP 断言推导只读锁定 + 服务端二次校验真实逻辑）、账密登录 + MFA 强制校验 + 30 天信任设备、用户管理表（全部用户已启用 MFA）；
> - **WP5.2 监控/队列/告警/配置中心/KMS/模型边界**：6 服务自监控指标探测 + 24h 序列、4 异步队列治理实时统计与断点续跑、告警引擎 4 基线规则 + P0 红线不可停用强制拦截（开关回弹 + 违例审计留痕）、配置中心（全配置项、diff 弹窗数据 API、发布版本递增、联动 5 大适配器兼容校验通知、旧版安全回滚、重置草稿零审计、红线项关闭拦截）、KMS 凭证全掩码（****xxxx）与轮换留痕、模型数据边界限定与 30 天清理；
> - **WP5.3 审计报表与归档合规**：四维检索过滤 + 统计条聚合 + 哈希链重验并登记 VerifyRun、CSV 导出自入链头（blk# 严格递增）+ 24h 限时凭证、SLA 分链路 P95 六卡（全达标）+ 可用性 99.62% + 吞吐 62 张/分、§9.2 识别质量指标表 + 错误自动放行率红线大卡（0.02% ≤ 0.05% + 12 周序列趋近 0）、AI 异常归因建议卡处置、10/7/2 年保留策略实体、生命周期清理任务、区域驻留路由、双实例独立成链校验、数据最小外发合规视图、周期抽检任务管理（QA-YYYY-Wnn-NN）+ SHA-256 比对 + 记录入链 + 异常联动冻结自动放行；
> - **WP5.4 标注与数据沉淀**：错误样本自动回流（人工修正/验真失败/字段冲突样本自动入队、真实错误优先）、ANNO 发号器与任务四态流转（排队中/标注中/三审仲裁/已完成已沉淀）、双人背靠背与一致率统计（97.2%）、沉淀规则转化接入规则引擎（rule_catalog，版本化+可回滚）、「标注数据不出客户控制域」合规开关（关闭被强制拦截+留痕）；
> - **WP5.5 LangGraph Agent 域**：三条 seed 意图对话图（金额差异>5000 调 `case.search` / 0387 证据链调 `case.get_evidence` / 海外重复票调 `dedup.report`）真实打通工具链、蓝标系统结果与橙标 AI 线索同屏严格分离、法定免责声明块、被调用 MCP 工具名标注、唤起只读详情卡（带「Agent 唤起 · 未修改数据」标记）、对话全程零写操作断言、会话审计留痕；AI 建议卡生成服务（差异解释全要素）；主动调查编排（INVESTIGATING 态只读取证 → EVIDENCE_COLLECTED → LLM 解释）；LLM 映射推荐真实实现（替换 M4 规则桩，接口签名不变，<80% 强制人工标注）；周期异常归因分析；模型客户端可替换配置化、逐次调用审计与 Prompt 30 天清理任务；
> - **WP5.6 MCP Server 网关**：按 `contracts/mcp-tools.json` 契约实装 6 项工具（4 只读 + 2 受控写）；streamable-http 协议（端口 8002）；OAuth2 client_credentials 鉴权桩与双 scope（`invoice.read` / `invoice.write.controlled`）绑定；`write_tools_require_human_confirm_token` 策略强制拦截（缺失 token 428 拒绝，缺失 operator 400 拒绝）；工具实现为 backend API 薄封装（零业务逻辑纯转发）；与 `agent/` 共用底层客户端与工具层的同源断言通过；tools/list 可枚举且与契约逐字一致；零 DB 直连；
> - **WP5.7 剩余页面接线 + 门户同步校验 + 全量回归**：12 页面全量接线且 demo-mode 回退可用；CON-14 决议落地（dashboard Header 消息铃铛接入告警计数并降级为告警入口）；CON-13 决议落地（case-detail 实装「人工查验」登记操作区，method=manual 留痕）；api-portal 页面内容与 contracts/ 文件同步校验脚本（工具清单/端点/事件名/Schema 字段一致性断言）纳入 CI 门禁；全量 E2E 场景回归 + 蓝图 §13.2 八个 Demo 场景回放脚本（`scripts/demo_replay.py`）可用且全绿。
>
> 前置门禁：M4 门禁全部通过。
> 门禁结论：**全项通过（GREEN）**，全库 371 passed、1 skipped、0 failure；蓝图 8 大 Demo 场景 8/8 通过；P00 §7 收工检查单全绿；Excel Sheet02/03/04 全部行状态回填完毕，未开始/进行中项清零。

---

## 1. 实施规划 M5 验收七条逐条核对（门禁依据）

| 验收标准 | 验证用例 / 运行脚本 | 结果 |
|---|---|---|
| **① 红线告警关闭被拦截且尝试留痕** | `test_redline_alert_disable_blocked_and_audited`<br>`test_platform_admin_wired_markers` | ✅ **PASS**（向 P0 红线告警发送关闭请求，被 HTTP 403 强制拦截拒绝，开关回弹保持开启，尝试行为写入不可篡改审计链） |
| **② 配置发布 diff / 适配器通知 / 回滚可复现** | `test_config_diff_and_reset_zero_audit`<br>`test_config_publish_version_diff_and_adapter_notifications`<br>`test_config_rollback` | ✅ **PASS**（diff 弹窗返回字段级变动明细；发布版本递增，diff 记入审计，自动联动返回 5 大目标适配器 COMPATIBLE 兼容性校验通知；旧版可回滚；重置草稿零审计） |
| **③ Agent 对话三脚本意图走真实工具链，带未修改标记与审计** | `test_intent_1_variance_screening`<br>`test_intent_2_evidence_chain_reading`<br>`test_intent_3_dedup_screening` | ✅ **PASS**（真实调用 `case.search`、`case.get_evidence`、`dedup.report`；蓝橙同屏分离；免责块与工具名标注；唤起卡带「Agent 唤起 · 未修改数据」标记；`zero_write_asserted is True`；会话全量入审计） |
| **④ MCP 客户端可枚举 6 工具，写工具无 confirm_token 被拒** | `test_mcp_tools_list_contract_exact_match`<br>`test_scope_enforcement_for_tools`<br>`test_case_action_missing_confirm_token_rejected_428`<br>`test_mcp_and_agent_tool_layer_source_parity` | ✅ **PASS**（tools/list 发现 6 工具与契约 100% 逐字一致；OAuth2 双 scope 鉴权生效；写工具缺 `confirm_token` 返回 HTTP 428，缺 `operator` 返回 HTTP 400；与 agent/ 共用工具层同源断言一致） |
| **⑤ 审计导出自入链头（blk# 严格递增）** | `test_export_audit_csv_self_audit_at_chain_head`<br>`test_audit_reports_wired_markers` | ✅ **PASS**（自审计事件 `AUDIT_EXPORT` 写入链头，链头块高 `audit_blk == old_head + 1` 递增断言通过；生成带 BOM 的 CSV 原件，签发 24h 有效凭证） |
| **⑥ 12 页全部接线且 demo-mode 回退可用** | `test_all_12_pages_served`<br>`test_shared_runtime_scripts_served`<br>`test_dashboard_wired_markers`<br>`test_case_detail_wired_markers`<br>`test_workbench_wired_markers`<br>`test_intake_wired_markers`<br>`test_m4_three_pages_wired_markers`<br>`test_platform_admin_wired_markers`<br>`test_audit_reports_wired_markers` | ✅ **PASS**（12 页面运行副本全量接线真实 API，包含 `?tab=` 深链支持，未连接后台时通过 `demo-mode.js` 优雅回退内嵌 mock，原型可独立演示） |
| **⑦ 全部 E2E 场景回归通过 + 蓝图 8 个 Demo 场景回放可用** | `pytest -m scenario`<br>`scripts/demo_replay.py` | ✅ **PASS**（M3×5 + M4×5 + M5 场景全绿；`scripts/demo_replay.py` 8/8 场景一键回放通过） |

---

## 2. 蓝图 §13.2 八大 Demo 场景回放结果

执行 `python scripts/demo_replay.py`，全量 8 场景回放结果：
1. **场景 1（数电票 XML 直读）**：不用 OCR，结构化 23 字段和验签（中国扩展包实例 · 0386 案）—— ✅ **PASS**
2. **场景 2（PDF 发票待复核）**：OCR Provider + 缺 XML 原件提示（0381 案）—— ✅ **PASS**
3. **场景 3（重复票阻断）**：付款与建档前风险拦截（0385 / 0122 案）—— ✅ **PASS**
4. **场景 4（篡改票阻断）**：SM2 验签 FAILED → BLOCKED，失败回执 gm-rcpt-1042 随案归档可追责（0379 案）—— ✅ **PASS**
5. **场景 5（邮箱管道建档 · 海外 Invoice）**：0918 国外链路全流程（0125 案）—— ✅ **PASS**
6. **场景 6（Provider 切换）**：动态停用百望云自动顺次沿链降级至诺诺与自托管 VLM，不绑定单一厂商—— ✅ **PASS**
7. **场景 7（口径差异主动调查）**：案件时间线只读取证（PO/GRN/GST/合同），AI 差异解释建议，系统主动消除业务不确定性—— ✅ **PASS**
8. **场景 8（Agent 对话式操作）**：自然语言对话、蓝标查询与橙标 AI 线索分离、唤起详情卡只读定位未修改数据、零写操作—— ✅ **PASS**

---

## 3. P00 §7 收工检查单

- [x] **全部测试通过**：后端与根目录 pytest 全量 **371 passed**，1 skipped（SM2 外部 CA 探活），0 failure；
- [x] **契约与 Schema 校验**：`tools/validate_contracts.py` 全量 40 项检查 100% 通过；
- [x] **门户契约同步校验（CI 门禁）**：`tools/verify_portal_sync.py` 运行通过，`test_portal_contracts_sync` 测试用例通过；
- [x] **枚举一致性校验**：`tools/check_enums.py` 对照 `contracts/enum-registry.json` 与 Excel Sheet08 全 142 行逐字比对通过；
- [x] **种子一致性断言**：`test_seed_loader.py` 数据项计数与幂等装载验证全部通过；
- [x] **依赖纪律自查（代码评审红线）**：
  - `backend/` 严格零 LLM / LangGraph / OpenAI / Anthropic 框架 import；
  - `backend/` 严格零 `agent` / `mcp` import；
  - `agent/` 与 `mcp/` 严格零直接数据库连接，全量消费 backend REST API；
  - 确定性判断只归规则引擎，LLM 输出永不直接写库；
  - `tests/test_dependency_discipline.py` 全部 3 项严格检查通过。
- [x] **台账回填**：
  - Excel Sheet02（全局约定 FN-0）：全部行已回填，未开始项清零（0 remaining）；
  - Excel Sheet03（分层功能 FN-1~9）：全部行已回填，未开始项清零（0 remaining）；
  - Excel Sheet04（接口面 FN-A）：全部行已回填，未开始项清零（0 remaining）。
