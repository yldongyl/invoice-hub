# P08 · 全量测试体系化验收报告

> **执行日期**：2026-10-28  
> **依据规范**：细化功能清单 `FN-A-08`（三层契约测试）、《实施规划》§7（测试与验收策略）、P08 专项阶段提示词  
> **门禁总结论**：**ALL GREEN · 全量通过（405 / 405 Passed，0 Skipped，0 Failed）**  
> **核心覆盖率**：`domain + services` 模块语句覆盖率 **90%**（远超 ≥80% 指标要求）

---

## 1. 测试套件执行汇总表

| 测试分层 / 门禁项 | 命令入口 | 用例数 / 范围 | 执行结果 | 覆盖率 / 关键指标 | 状态 |
|---|---|---|---|---|---|
| **全量测试套件** | `make test`<br>`python scripts/hub.py test` | 405 个测试 | **405 passed**, 0 failed | `domain+services` **90%** | ✅ **通过** |
| **三层契约测试** | `pytest -m contract` | 11 个核心测试 | **11 passed**, 0 failed | 结构/语义/版本兼容 100% 覆盖 | ✅ **通过** |
| **E2E 场景断言** | `make test-e2e`<br>`python scripts/hub.py test-e2e` | 34 个测试（17 官方场景） | **34 passed**, 0 failed | 17 条官方场景全量一键重放 | ✅ **通过** |
| **红线回归集** | `make test-redline`<br>`python scripts/hub.py test-redline` | 16 个测试（R-01~R-06） | **16 passed**, 0 failed | 零 skip，全量激活拦截 | ✅ **通过** |
| **Demo 场景回放** | `make demo-replay`<br>`python scripts/hub.py demo-replay` | 8 个演示场景 | **8 / 8 passed** | 输出演示步骤对照表 | ✅ **通过** |
| **一致性与前置校验** | `make verify`<br>`python scripts/hub.py verify` | 4 项工具脚本流水线 | **全绿通过** | 枚举/Schema/UI/文档同步 100% | ✅ **通过** |

---

## 2. 分层测试核验明细

### 2.1 三层契约测试（FN-A-08）
- **结构层（Structural Layer）**：
  - `contracts/` 全部 9 个 JSON Schema 编译校验（符合 JSON Schema Draft 2020-12 规范）——通过；
  - `openapi.yaml` 规范 lint（含 paths, webhooks, 唯一 operationId, $ref 引用）——通过；
  - `seeds/cases.json`（11 案）、`seeds/routing_policy.json`（全规则）过对应 Schema 静态校验——通过。
- **语义层（Semantic Layer）**：
  - 核心 API 响应结构过 Schema 校验（`/v1/cases/{id}` 校验 `invoice-case.schema.json`、`/v1/cases` 校验 `case-read.schema.json`、`/v1/dashboard` 校验 `dashboard-response.schema.json`、`/v1/alerts` 校验 `alerts-response.schema.json`）——通过；
  - 枚举字段值一致性校验（数据库全部数据严格 ∈ `contracts/enum-registry.json`）——通过；
  - 编号格式规则断言（正则匹配案件号 `^INV-(CN|SG)-\d{4}-\d{4}$`、批次号 `^BT-\d{8}-\d{3}$`、trace `^tr-[0-9a-f]{8}$`、回执 `^gm-rcpt-\d+$`）——通过；
  - 状态机非法流转拒绝语义校验（非法跳转返回 `E_ILLEGAL_TRANSITION`）——通过。
- **版本兼容层（Version Compatibility Layer）**：
  - `contracts/CHANGELOG.md` 治理记录审计（v1 FROZEN 总纲、FROZEN/COMPAT/SYNC 记录、TODO 未决项追踪）——通过；
  - `tools/check_breaking_changes.py` 破坏性变更检测（字段删除、类型变更、新增 required、枚举删除）——当前 contracts 零破坏性变更；
  - 破坏性变更检测器合成变体验证（4 类变体反向断言必然报错拦截，确保检测器非空跑）——通过。

### 2.2 单元测试最小集核对（P08 §1.2）

| 核心领域对象 | 必测用例点 | 对应测试文件 | 实际执行结论 |
|---|---|---|---|
| **状态机** | 六条流转规则逐条；非法流转拒绝；BLOCKED 双人解除（缺会签拒绝）；认领子态不扩状态 | `test_state_machine.py`<br>`test_governed_commands.py` | ✅ **全部通过** |
| **审计哈希链** | 链校验通过；篡改任一字段定位 blk#；导出事件入链头；WORM 禁止 update/delete | `test_audit_chain.py` | ✅ **全部通过** |
| **受控写框架** | 五要素逐项缺失拒绝（5 用例）；批量含 BLOCKED 跳过明细；处置意见必填类动作缺备注拒绝 | `test_governed_commands.py` | ✅ **全部通过** |
| **人工修正字段** | 原因必填；source=manual/conf=1.0；raw_text 追溯原值；原 bbox 保留；FIELD_EDITED 审计 | `test_governed_commands.py` | ✅ **全部通过** |
| **规则引擎** | 附录 C 已实装规则正反用例；两套容差（±0.06 / ±S$50）边界值；验签失败全字段降级 | `test_rules.py` | ✅ **全部通过** |
| **查重服务** | CN/OS 双键构造；相似度阈值边界（含等于判命中）；DEDUP_BLOCKED 排除出池；幂等/查重键分离 | `test_compliance_wp33.py` | ✅ **全部通过** |
| **路由引擎** | 三条件匹配优先级；降级链；停用 Provider 自动跳过；同类模型排除；五项兜底触发 | `test_routing_engine.py` | ✅ **全部通过** |
| **推演一致性** | 同输入：模拟推演输出步骤 = 真实路由执行日志逐步比对完全一致（时延/成本/步骤） | `test_scenarios_m4.py::test_s_m4_01` | ✅ **全部通过** |
| **建档链路** | 五步顺序；冲减 Link 未确认拦截；BLOCKED/INVESTIGATING 挂起；幂等重发不重复投递 | `test_adapters_and_filing.py` | ✅ **全部通过** |
| **发号器/租户** | 分域递增（CN:0388/OS:0126）；四隔离越权访问拒绝；无租户上下文强制报错 | `test_issuer_tenant.py` | ✅ **全部通过** |
| **配置中心** | diff 计算；发布版本递增；旧版安全回滚恢复；重置草稿零审计；红线项绕过拦截 | `test_config_center.py` | ✅ **全部通过** |

### 2.3 17 条官方 E2E 场景执行情况（P08 §1.3）

所有 17 条官方 E2E 场景均实现一键重放，断言失败信息规范化输出：

- `S-M3-01`: 上传→流水线→NEEDS_REVIEW→受控放行→RESOLVED 全链留痕 —— ✅ **PASS**
- `S-M3-02`: 重复票→DEDUP_BLOCKED→批量放行跳过→双人会签解除 —— ✅ **PASS**
- `S-M3-03`: 篡改票（0379 路径重放）→SM2 FAILED→BLOCKED→建档挂起→失败回执归档 —— ✅ **PASS**
- `S-M3-04`: 多源冲突（0381 路径）→降级 82%→NEEDS_REVIEW→人工修正以 XML 为准 —— ✅ **PASS**
- `S-M3-05`: 受控写五要素逐项缺失→全部拒绝（权限/凭据/本人勾选/处置意见/审计留痕） —— ✅ **PASS**
- `S-M4-01`: "纸质专票"推演与真实路由行为一致（百望云 0.82 降级诺诺 0.91） —— ✅ **PASS**
- `S-M4-02`: 停用百望云→数电票路由自动跳过（skip）→XML 直读不受影响+留痕 —— ✅ **PASS**
- `S-M4-03`: 0387 口径差异：确认卡完整→放行→Ariba 沙箱建档→回执归档 —— ✅ **PASS**
- `S-M4-04`: 0384→0310 Link 确认与拦截（反向未确认拦截 409，确认冲减通过） —— ✅ **PASS**
- `S-M4-05`: 策略发布：草稿改阈值→推演生效→发布版本递增+diff 入审计→回滚恢复 —— ✅ **PASS**
- `S-M5-01`: 红线告警关闭拦截+留痕（尝试关闭 P0 告警 403 拦截，开关回弹，尝试行为入审计） —— ✅ **PASS**
- `S-M5-02`: 配置发布→行为变化→回滚恢复（发布 0.90 阈值导致低置信流转，回滚恢复） —— ✅ **PASS**
- `S-M5-03`: Agent 三意图真实工具链（蓝橙标分离、免责声明、唤起只读卡未修改数据、零写事件） —— ✅ **PASS**
- `S-M5-04`: MCP 枚举 6 工具+写工具无 confirm_token 拒绝 428+agent/mcp 同源 —— ✅ **PASS**
- `S-M5-05`: 审计导出自入链头（blk# 严格递增）+ 哈希链整体验证全通过 —— ✅ **PASS**
- `S-M5-06`: 标注回流→沉淀规则→规则生效（修正样本自动排队，沉淀规则接入引擎生效） —— ✅ **PASS**
- `S-M5-07`: 抽检异常→冻结自动放行联动（抽检异常熔断自动放行，违例入不可篡改审计链） —— ✅ **PASS**

### 2.4 红线回归集闭环结果（P08 §1.4）

| 红线编号 | 定义与断言点 | 验证结果 | 关联 FN |
|---|---|---|---|
| **R-01** | 低置信（<80）案件不存在任何自动放行路径（conf=70 全 PASSED 终停 NEEDS_REVIEW，evaluate 源码走查含 `_auto_release_floor` 闸门） | ✅ **PASS** | FN-0-06 / FN-5-05 |
| **R-02** | 验签失败→BLOCKED 不可绕过（单人放行报 409，配置中心关闭强制人工报 403 E_CONFIG_REDLINE_BYPASS） | ✅ **PASS** | FN-5-01 / FN-0-02 |
| **R-03** | BLOCKED 不可批量放行（批量操作全部跳过且 processed=0，状态零变化，无伪造审计块） | ✅ **PASS** | FN-0-08 / FN-8-06 |
| **R-04** | 错误自动放行率红线告警不可停用（尝试关闭 P0 告警强制 403 拦截，开关回弹，尝试行为入审计链，**解除 M3 skip 闭环**） | ✅ **PASS** | FN-9-08 / P00 §5 |
| **R-05** | LLM 输出永不直接写入 checks/status/字段值（backend 唯一入口收口在 orchestrator，Agent 域零 DB 直连且对话全程零写操作） | ✅ **PASS** | FN-0-09 / ADR-0001 |
| **R-06** | 写操作无审计记录→测试失败（审计链断链注入时 release/hold/claim 整笔回滚，状态不变且不留半块） | ✅ **PASS** | FN-0-08 / FN-0-10 |

---

## 3. 蓝图 §13.2 八大 Demo 场景演示步骤对照表

执行 `make demo-replay` 或 `python scripts/hub.py demo-replay` 8 场景全绿并输出以下投屏对照表：

| 序号 | 演示场景 | 涉及发票/案件 | 页面入口与操作端点 | 投屏讲解要点与业务价值 |
|---|---|---|---|---|
| **①** | **数电票 XML 直读** | INV-CN-2026-0386<br>(中科华创数电票) | `/web/case-detail.html`<br>`GET /v1/cases/0386` | 免 OCR 零外发、零成本、零时延，结构化 23 字段全解析与真实 SM2 验签 |
| **②** | **PDF 发票待复核** | INV-CN-2026-0381<br>(恒信电子扫描件) | `/web/agent-workbench.html`<br>`GET /v1/cases/0381` | 扫描件调用百望云 OCR，系统自动提示缺 XML 原件，降级至人工复核 |
| **③** | **重复票阻断** | INV-CN-2026-0385<br>INV-SG-2026-0122 | `/web/agent-workbench.html`<br>`GET /v1/cases/0385` | 采购付款与建档前拦截，代码+号码+金额+供应商双键跨实例查重，BLOCKED 排除出发票池 |
| **④** | **篡改票阻断** | INV-CN-2026-0379<br>(金额篡改数电票) | `/web/case-detail.html`<br>`GET /v1/cases/0379` | 真实国密 SM2 验签失败拦截，失败回执 gm-rcpt-1042 随案归档，可用于司法举证与追责 |
| **⑤** | **邮箱管道建档（海外链路）** | INV-SG-2026-0125<br>(西门子海外发票) | `/web/intake-pipeline.html`<br>`GET /v1/cases/0125` | 0918 新加坡实例全链路，通过 SAP DOX 桩与 Ariba cXML 适配器完成建档与回执归档 |
| **⑥** | **Provider 切换** | 纸质专票路由链<br>(百望云→诺诺/VLM) | `/web/provider-orchestration.html`<br>`GET/POST /v1/providers` | 动态停用百望云，识别路由自动沿链降级至诺诺与自托管 VLM，企业不被单一 OCR 厂商绑定 |
| **⑦** | **口径差异主动调查** | INV-SG-2026-0125<br>(含税总额 vs 订单净额) | `/web/case-detail.html`<br>`POST /v1/cases/.../investigate` | 时间线只读取证运费与税额差异，AI 生成差异解释与受控处置建议，消除业务不确定性 |
| **⑧** | **Agent 对话式操作** | 对话侧边栏 / MCP 服务<br>(王莉财务经理会话) | `/web/case-detail.html`<br>`POST /mcp/v1/tools/call` | 自然语言查询、蓝标系统结果与橙标 AI 线索同屏分离、唤起只读卡未改数据、零写事件保障 |

---

## 4. 依赖纪律与代码走查结论

1. **`backend/` 确定性核心**：严格零 `agent` / `mcp` import，零大模型框架（LangGraph / OpenAI / Anthropic / LiteLLM）引用（`test_dependency_discipline.py` 全部 3 项检查全绿）；
2. **`agent/` 与 `mcp/` 域**：严格零直接数据库连接与 SQLAlchemy ORM 引用，所有数据读取与业务执行 100% 消费 `BackendClient` REST API；
3. **确定性收口**：所有税额勾稽、容差判断、查重与状态转换均严格收口在规则引擎与状态机，大模型输出永不直接写入核心数据表。

---

## 5. 验收产物索引

- **测试规范手册**：`docs/TESTING.md`
- **覆盖率数据文件**：`docs/test-reports/coverage.json`
- **破坏性变更检测工具**：`tools/check_breaking_changes.py`
- **CI 门禁配置文件**：`.github/workflows/ci.yml`、`.gitlab-ci.yml`
- **全量 E2E 场景套件**：`tests/scenarios/`（`test_scenarios_m3.py`、`test_scenarios_m4.py`、`test_scenarios_m5.py`）
- **红线回归套件**：`tests/redline/test_redline.py`
