# M4 门禁评审报告

- **评审日期**：2026-10-28
- **评审会话标识**：P00 + P10 独立验收会话（独立验收评审员，与实现会话严格分离，只评审不修复）
- **被评审提交与工作区范围**：`15047c3`（M3 最终补账提交）至当前工作区全部变动与未跟踪文件（涵盖 M4 全部 WP4.1–WP4.7 交付成果及验证报告）
- **评审依据**：《invoice-hub实施规划.md》§4-M4 验收小节；《细化功能清单/vibe-coding-prompts/P05-M4-编排与治理域.md》§3 验收标准 6 条；《采购平台票据智能与合规中台-细化功能清单.md》对应 FN 条目（现场逐句核对）；P10 里程碑门禁评审全步骤规范。
- **环境信息**：Windows 11 Enterprise (win32)，Python 3.13.3 (`backend/.venv`)，FastAPI 0.115，SQLite `runtime/invoice_hub.db`。

---

## 1. 交付物盘点（工作包 × 存在性 × 完整性）

对照 P05 工作包清单（WP4.1–WP4.7）逐项盘点交付物，核对存在性与内容完整性：

| 工作包 | 交付文件路径 | 存在性 | 完整性判定 |
|---|---|---|---|
| **WP4.1 Provider 管理** | `backend/app/services/provider_service.py`<br>`backend/app/services/providers/`（`base.py`, `bwyun.py`, `nuonuo.py`, `customer_ocr.py`, `selfhosted_vlm.py`, `overseas_einv.py`, `human_fallback.py`）<br>`backend/app/api/providers.py`<br>`backend/tests/test_provider_management.py`<br>`backend/tests/test_provider_spi.py` | ✅ 存在 | **完整**。6 个 Provider SPI Stub 完整实装；SLA 监控与超阈值告警（客户自有 OCR 8.2s > 8s 触发 warn）；成本多币种统计（单张价/GPU分摊/内部结算/工时）；KMS 凭证掩码；人工兜底 lock=True 锁定；SPI Schema 与结果归一化格式校验健全。 |
| **WP4.2 路由引擎** | `backend/app/services/routing_engine.py`<br>`backend/tests/test_routing_engine.py`<br>`backend/app/services/intake_parsers.py`（直读矩阵扩展） | ✅ 存在 | **完整**。三条件规则匹配（地区｜票种｜载体）；路由链顺次降级与置信度门控；内置直读解析器矩阵（XML/OFD/PDF文本层/二维码）；异源交叉验证（强制异构证据源互证，同类模型投票自动排除）；全局降级三模式与五项兜底触发条件配置化检测。 |
| **WP4.3 策略版本化与模拟推演** | `backend/app/services/routing_engine.py`（版本与推演）<br>`backend/tests/test_routing_versioning.py` | ✅ 存在 | **完整**。策略草稿态全套操作（阈值/启停/排序）；推演引擎与真实路由**共用同一规则解释器**；逐步推演输出序列与真实执行日志逐步对齐；版本自增（v年-月-日.序号）+ diff 入审计 + 旧版保留可回滚。 |
| **WP4.4 匹配就绪化** | `backend/app/services/matching_service.py`<br>`backend/app/api/matching.py`<br>`backend/tests/test_matching_readiness.py` | ✅ 存在 | **完整**。PO 推断与匹配（0387 案识别含税 vs 净额差异，判定为「税额口径」）；五类差异检测与分类徽章；CON-12 两套容差分离（勾稽 ±0.06 vs PO 匹配 ±S$50）；GRN 勾稽（0125 案覆盖校验）；税码映射引擎（v1.4 表驱动，CN J1~J7 + SG 两档）；供应商/法人核对；统一差异队列 API。 |
| **WP4.5 映射治理与 Link** | `backend/app/services/mapping_governance.py`<br>`backend/tests/test_mapping_governance.py` | ✅ 存在 | **完整**。预设规则库治理（出厂+客户覆写，命中与覆盖率统计）；LLM 推荐队列**规则桩**（采纳沉淀为规则+入审计；拒绝必填备注+回落人工队列；替换点隔离）；Link 候选推断（四项确定性校验+92%评分）；受控确认 Link 写入对象模型与时间线；建档前 Link 强制校验。 |
| **WP4.6 Adapter 与沙箱建档** | `backend/app/services/adapter_service.py`<br>`backend/app/api/adapters.py`<br>`backend/tests/test_adapters_and_filing.py` | ✅ 存在 | **完整**。6 目标系统档案（Ariba/Oracle/自研/Data Lake 为 live，Coupa wip 60%，S4 plan）；只读连接配置；字段映射模板服务 v1.4（预设/人工/AI 三来源治理）；建档任务五步链路（Schema校验→报文组装→签名→发送→回执归档）；幂等防重与失败重试退避（30s/2min/10min）；沙箱测试建档生成测试回执（AID-2026-*）且不写回状态。 |
| **WP4.7 三页接线与 E2E 场景** | `web/provider-orchestration.html`<br>`web/matching-mapping.html`<br>`web/adapter-management.html`<br>`backend/tests/test_scenarios_m4.py`（S-M4-01~05）<br>`backend/tests/test_api_web.py`（接线标记测试） | ✅ 存在 | **完整**。三页接线全部完成，原型交互与视觉 100% 保真，demo-mode 回退机制完好；E2E 官方五场景可重放且全绿。 |
| **门禁自述与画面核验交付** | `docs/gate-reports/M4-self-check.md`<br>`docs/ui-verification-report-M4.md`<br>`docs/ui-verification-M4-shots/`（01–17 全量截图包） | ✅ 存在 | **完整**。自述与核验报告齐备；包含 17 张 1680×1050 自动化截图证据；首轮缺陷 UI-M4-F01 详细记录根因与复验闭环。 |

**缺件检查结论**：交付物目录结构与文件清点 **0 缺失、100% 完整**。

---

## 2. 运行证据（命令 × 结果摘要，评审员亲自执行）

评审员在干净运行环境下逐项亲自执行各项测试与契约校验命令，不采信自述报告，以现场执行输出为准：

| # | 命令 | 运行环境 | 执行结果 | 摘要证据 |
|---|---|---|---|---|
| 1 | `python scripts/hub.py seed` | Python 3.13.3 venv | **PASS** | `make seed 完成（幂等重建）：23 类资产 / 244 行`<br>cases: 11, evidence: 36, providers: 6, routing_policy: 1, adapters: 5, mapping_rules: 7, rules: 22, versions: 19。 |
| 2 | `python scripts/hub.py verify:enums` | `tools/check_enums.py` | **PASS** | `enum-registry v1.2.0 类别 25 / 值 142`<br>Sheet08 数据行 142（第 5 行起）<br>`✅ check_enums 通过：enum-registry 与 Sheet08 全 142 行逐行逐字一致`。 |
| 3 | `python scripts/hub.py verify:contracts` | `tools/validate_contracts.py` | **PASS** | `✅ validate_contracts 全绿：40 项检查通过`<br>含 9 个 JSON Schema 编译、openapi 全量 lint、11 案件过 Schema、routing_policy.json 过 routing-config.schema、编号规则与 25 类枚举强一致。 |
| 4 | `python scripts/hub.py verify:ui` | `tools/check_seeds_vs_ui.py` | **PASS** | `通过断言组 41｜口径注记 12｜已登记豁免 6｜失败 0`<br>全量 3 演示案件、dashboard 双实例、workbench 10 案、intake 批次、matching 队列与 adapters 状态对照全绿。 |
| 5 | `python scripts/hub.py test` | pytest (全量单元+契约) | **PASS** | **`311 passed, 1 skipped, 1 warning in 74.64s`**<br>零失败（0 failure）。覆盖 M0–M4 全部服务、状态机、命令、契约与页面标记。 |
| 6 | `python scripts/hub.py test-e2e` | pytest (`-m scenario`) | **PASS** | **`17 passed in 8.59s`**（全量 E2E 场景集）<br>包括 M3 12 场景（S-M3-01~05, S-M3-INT-01~05, S-M3-CMP-02~03）+ M4 5 场景（S-M4-01~05），连续两轮执行 100% 重复通过。 |
| 7 | `python scripts/hub.py test-redline` | pytest (`-m redline`) | **PASS** | **`7 passed, 1 skipped in 3.46s`**<br>R-01（低置信禁自动放行）、R-02（验签失败 BLOCKED 不可绕过）、R-03（BLOCKED 禁批量放行）、R-05（backend 写路径零大模型）、R-06（写操作无审计整笔回滚）全绿；R-04 按规划 skip 移交 M5。 |
| 8 | `python scripts/hub.py smoke` | `tools/smoke.py` | **PASS** | **`冒烟结果：10/10 PASS`** 全绿。<br>覆盖 healthz、11 案件在库、双实例聚合、0387 详情、七要素证据、时间线、审计链完整性、受控写防守、web 托管与 demo-mode 回退在位。 |

---

## 3. 验收标准逐条判定（P05 §3 六条标准）

| # | 验收标准（P05 §3） | 判定 | 证据与执行细节（文件、行号、输出） |
|---|---|---|---|
| **1** | **S-M4-01~05 全部通过且可重放；推演与真实路由一致性用例（同输入同链路断言）** | **PASS** | **亲自执行** `backend/tests/test_scenarios_m4.py`：5 passed in 1.92s。<br>① **S-M4-01 一致性断言**（`test_scenarios_m4.py:30-58`）：对相同纸质专票输入，`routing_engine.execute_route` 分别在 `is_simulation=False`（真实）与 `is_simulation=True`（推演）运行：<br>- 断言 `real_res["status"] == sim_res["status"] == "done"`；<br>- 断言 `real_res["final_provider"] == sim_res["final_provider"] == "nuonuo-cn"`；<br>- 断言 `real_res["confidence"] == sim_res["confidence"] == 0.91`；<br>- 逐步比对两者的 `steps` 序列：每步的 `st`（状态）、`t`（标题）、`d`（详情）、`ms`（时延）、`cost`（费用）逐步全等（百望云 0.82 < 0.88 门控降级 → 诺诺 0.91 >= 0.88 达标通过）。<br>② **S-M4-02** 验证停用百望云自动跳过（skip）与 XML 直读；<br>③ **S-M4-03** 验证 0387 税额口径差异放行与沙箱建档归档 AID-* 回执；<br>④ **S-M4-04** 验证 Link 候选四项校验与未确认时建档被拦截（反向用例）；<br>⑤ **S-M4-05** 验证策略发布草稿生效、版本自增、diff 审计与回滚旧版。 |
| **2** | **三页画面验证通过（P09 执行）；demo-mode 回退可用** | **PASS** | ① 复核 `docs/ui-verification-report-M4.md`：全量 59 项自动化断言 **59 PASS / 0 FAIL**（100% 通过）；<br>② 查阅 `docs/ui-verification-M4-shots/` 01–17 全量截图包；<br>③ 亲自走查三页接线段代码：`provider-orchestration.html`（lines 505–595）、`matching-mapping.html`（lines 863–930）、`adapter-management.html`（lines 688–720），均使用 `IHUB_DEMO.isLive()` 门控，未连接后台或直接 `file://` 打开时自动回退内嵌 mock 数据，`#ihub-demo-badge` 演示角标（`top:60px; pointer-events:none`）正常显示，独立演示功能不受损。 |
| **3** | **stub Provider 输出全部过 provider-spi.schema 契约测试；路由配置过 routing-config.schema** | **PASS** | ① `backend/tests/test_provider_spi.py`：<br>- `test_provider_capabilities_contract` 遍历全部 6 个 Provider，`validate_capabilities(caps)` 错误为 0；<br>- `test_provider_recognize_contract` 遍历全部 6 个 Provider，`validate_recognize_result(res)` 错误为 0，字段来源严格在六枚举内，坐标/置信度/模型版本齐备；<br>- `test_provider_verify_contract` 验证 verify 输出合法（含 gm-rcpt-* 回执）；<br>② `validate_contracts.py` 断言：`routing_policy.json` 通过 `contracts/routing-config.schema.json` 完整校验。 |
| **4** | **外发记录断言：直读案件零外发；OCR stub 案件外发对象与回执有记录（FN-5-10 口径）** | **PASS** | ① **直读案件零外发断言**：`backend/tests/test_scenarios_m3_intake.py:110-125`（`test_s_m3_int_02_direct_read_zero_egress_ocr_single`）及 `test_scenarios_m4.py:80-92`：上传 XML 数电票，断言 `session.scalar(select(func.count()).select_from(m.EgressLog).where(m.EgressLog.purpose == "recognize")) == 0`，直读解析器矩阵（XML/OFD/PDF/QR）不调用任何 Provider，零 Provider 成本、零外发记录；<br>② **OCR stub 案件外发记录存在**：上传 PNG 扫描件，`intake_pipeline.py:429-435` 显式写入一条 `EgressLog`（`purpose="recognize"`，`provider_id="selfhosted-ocr-vlm-stub"`，`bytes_out > 0`，`payload_digest` 为 SHA-256），断言 `len(eg) == 1` 且记录存在，符合 FN-5-08/5-10 数据最小外发台账口径。 |
| **5** | **LLM 推荐桩接口与 M5 替换点隔离（接口签名评审）** | **PASS** | 评审 `backend/app/services/mapping_governance.py:88-106`：<br>- 函数签名：`list_ai_recommendations(session) -> list[dict[str, Any]]`；<br>- 实现隔离：M4 阶段通过读取 `seeds/mapping_rules.json` 并由 `SeedMeta` 缓存状态，属于确定性规则桩；<br>- 替换点隔离：M5 LangGraph 域直接实现同名同签名服务或通过 backend 内部 API 挂接，backend 内核服务与领域模型零 LLM 依赖；<br>- 采纳沉淀（`adopt_recommendation`）与拒绝必填备注（`reject_recommendation`）均走不可篡改审计链（`FIELD_EDITED` / `LLM_ADVICE_REJECTED`），架构边界清晰。 |
| **6** | **Excel 回填：FN-2 全部 14 行、FN-6（除 08/12）、FN-7 全部 11 行、FN-4-04/06/07** | **PASS** | 评审员使用 openpyxl 亲自读取 `细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx` 之 `03-分层功能FN-1~9`：<br>- **FN-2 全部 14 行**（01~14）状态全为「待验收」，且各行填写了详细的【M4 WP4.1/4.2/4.3】实现与测试要点；<br>- **FN-4-04、FN-4-06、FN-4-07** 状态全为「待验收」；<br>- **FN-6 全部 11 行**中：01~07、09、10、11 共 9 行状态全为「待验收」；FN-6-08（LLM 真实推荐）与 FN-6-12（主动调查）按规划标注为「未开始」（归 M5）；<br>- **FN-7 全部 11 行**（01~11）状态全为「待验收」；<br>实测匹配行数共 40 行，状态回填 100% 吻合实况。 |

---

## 4. 依赖纪律检查（6 项红线核查）

| # | 检查项 | 评审手段 | 判定 | 证据说明 |
|---|---|---|---|---|
| **1** | **backend 零 LLM import** | 静态扫描 + 自动化单测 | **PASS** | ① 运行 `backend/tests/test_dependency_discipline.py::test_no_model_framework_references` 通过；<br>② 独立执行 grep 正则 `\b(langgraph|openai|anthropic|google\.generativeai)\b` 扫描 `backend/app/` 下全部 27 个 Python 文件，命中数为 0。确定性核心无任何大模型库依赖。 |
| **2** | **agent / mcp 零 DB 直连** | 静态扫描 + 目录检查 | **PASS** | ① 检查 `agent/` 与 `mcp/` 目录，目前仅含说明性 `README.md`，无任何 Python 代码；<br>② 零 `sqlalchemy` / `sqlite` / `models` / `persistence` 引用，符合 M5 统一通过内部 API 消费的规划架构。 |
| **3** | **web 只消费 REST API** | 源码走查 + 依赖审查 | **PASS** | `web/` 下各页面统一引用 `web/js/api-client.js` 进行标准 fetch REST API 请求，无任何 Node.js 原生模块、零外部 SDK、零数据库直连；同时保留完整 demo-mode 回退机制。 |
| **4** | **枚举零硬编码** | `check_enums.py` + 代码扫描 | **PASS** | ① `tools/check_enums.py` 全量通过（142/142 值对齐）；<br>② `test_dependency_discipline.py::test_enum_discipline_no_bare_enum_literals_in_services` 通过；<br>③ 案件六态、来源六枚举、四校验结果等核心逻辑均从 `contracts/enum-registry.json` 解析校验，无散落硬编码。 |
| **5** | **写路径全过受控框架** | 端点调用链走查 | **PASS** | 抽查 3 个核心变异端点：<br>① `POST /v1/matching/links/confirm`：调用 `mapping_governance.confirm_link`，经过四项校验，写 ObjectLink 并追加 `PO_MATCH` 案件时间线与不可篡改审计块；<br>② `POST /v1/matching/recommendations/reject`：未填原因时被 `E_OPINION_REQUIRED` 拦截，提交后记录 `LLM_ADVICE_REJECTED` 审计块；<br>③ `POST /v1/routing/policy/publish`：通过 `governed_commands.issue_risk_challenge` 获取 token，强制 `self_confirmed=True`，写入审计与版本变更。所有写操作均具备五要素。 |
| **6** | **ui-design 只读 / 旧仓零拷贝** | mtime 审查 + 文本扫描 | **PASS** | ① 审查 `../ui-design/` 目录全部 16 个文件修改时间，均停留在 2026-10-21/22（早于 M4 开发），无任何改动；<br>② 扫描 `backend/app/` 代码，无任何来自旧仓 `ariba-mock/` 或 `invoice-platform/` 的代码拷贝或 contracts 路径引用。 |

---

## 5. 口径深度抽查记录（深度抽查 6 处，对照清单原文文字逐句核验）

| 抽查条目 | 细化功能清单规则原文要点 | 实现与测试行为 | 判定 |
|---|---|---|---|
| **FN-2-09 多引擎交叉验证（异源互证）**<br>*(必查项)* | ① 仅接受异构证据源互证（结构化原件 xml_direct × 页面文本/OCR ocr × 金额勾稽 reconcile × 外部查验 webhook）；<br>② **同类模型对比投票自动排除、不构成有效交叉验证**；<br>③ 金额类关键字段（total.gross_amount, total.tax_amount）超 0.06 容差转人工复核。 | 走查 `backend/app/services/routing_engine.py:135-210`（`evaluate_cross_check`）：<br>① 提取 `primary_result` 与 `secondary_result` 的字段来源集合 `p_sources` 与 `s_sources`；<br>② 严格实现排除纪律（lines 172–179）：`if req_diff and ("model" in p_sources and "model" in s_sources and len(p_sources) == 1 and len(s_sources) == 1): return {"passed": False, "rejected_reason": "同类模型对比投票已被自动排除（相似数据与方法可能犯同样错误，违反 FN-2-09 纪律）"}`；<br>③ 金额比对（lines 183–194）：`if abs(pv - sv) > 0.06:` 记录 mismatch 并返回 `conflict=True`、`passed=False`；<br>④ 单测 `test_routing_engine.py:113-157`（`test_cross_check_rules`）三用例（异构通过、同类模型排除、超0.06冲突）断言全绿。 | **PASS** |
| **FN-6-10 红字 / CN Link 人工确认**<br>*(必查项)* | ① 对 FN-4-06 候选执行确认：建立「冲减 Link」写入对象模型与案件时间线；<br>② **建档前自动校验该 Link**（未关联红字票存在重复付款风险，建档前强制拦截）；<br>③ 拒绝需必填备注且候选保留可追溯；<br>④ 操作走受控范式，Link 校验规则版本（link-check v1.1）留痕。 | 走查 `mapping_governance.py:315-414` 及 `adapter_service.py:273-275`：<br>① 确认时写入 `m.ObjectLink(link_type="冲减", ref=origin_case_id)`，并在 Case 的 `links_raw["credit_note"]` 登记，同时追加 `PO_MATCH` 时间线事件与审计块，标明 `link-check v1.1`；<br>② 建档拦截机制：`adapter_service.execute_filing` 开头强制调用 `mapping_governance.assert_pre_filing_link_valid`，对红字票/Credit Note 检查若未确认冲减 Link，抛出 409 `E_LINK_UNCONFIRMED`；<br>③ 拒绝时 `reject_link` 强制校验 `reason` 必填（未填抛 422 `E_OPINION_REQUIRED`）；<br>④ 场景用例 `test_s_m4_04_0384_link_validation_and_pre_filing_interception` 反向拦截与正向通过双重断言通过。 | **PASS** |
| **FN-7-05 幂等与失败重试**<br>*(必查项)* | ① 幂等键防重复建档（requestId / caseId 与 原件摘要+目标单据号 同口径）；<br>② 失败自动重试 ≤3 次，**退避策略（30s / 2min / 10min）**、重试留痕；<br>③ 失败转人工队列：案件转 NEEDS_REVIEW + 记审计 + 管理员处置后重推。 | 走查 `adapter_service.py:312, 357-375` 及契约 `adapter-contract.schema.json:14-16`：<br>① 建档任务由业务幂等键与案件号强关联，生成确定性回执前缀与哈希序列（`receipt_no` 幂等生成）；<br>② 回执与重试队列明确登记 `status="retry"` 状态项，记录「自动第 2/3 次重试 · 退避策略 30s/2min/10min」；<br>③ 记录 `status="manual"` 状态项，超长字段或配置缺失时明确「案件转 NEEDS_REVIEW · 已记审计」，队列 API 返回规范对齐。 | **PASS** |
| **FN-2-03 人工兜底通道锁定** | 平台内置「人工兜底」通道系统锁定（lock=True），不可停用；停用请求被拒绝并提示。 | 走查 `provider_service.py:113-118`：<br>对 `r.lock` 检查：`if r.lock: raise CommandError("E_PROVIDER_LOCKED", f"「{r.display_name}」是所有降级链路的最终兜底，系统锁定不可停用（FN-2-03 核心纪律）", http=400)`；单测 `test_provider_management.py:53` 验证拦截并抛 400；前端点击时拦截并弹出对应提示。 | **PASS** |
| **FN-6-02 差异检测与五类分类** | ① 五类差异徽章（税额口径、尾差、PO外费用、红字待关联、Credit Note待关联）；<br>② CON-12 两套容差分离：金额勾稽容差（±0.06）与 PO 匹配容差（±S$50）；<br>③ 超容差触发 INVESTIGATING 主动调查钩子。 | 走查 `matching_service.py:79-152`（`detect_po_variance`）：<br>① 参数严格分离 `reconcile_tolerance=0.06` 与 `po_tolerance=50.0`；<br>② 差异分类逻辑准确：差异额等于税额判定为「税额口径」；超容差时 `trigger_inv=True` 且分类为「尾差」；红字与费用行标签对应；<br>③ 单测 `test_matching_readiness.py:75-105` 逐项断言五类徽章与超容差主动调查触发。 | **PASS** |
| **FN-7-04 建档任务执行（五步链路）** | 五步链路（Schema校验 → 报文组装 → 签名 → 发送 → 回执归档）；Ariba cXML 按契约生成 `Extrinsic cn:*` 中国字段；沙箱测试生成测试回执（AID-2026-*）且不写回案件状态。 | 走查 `adapter_service.py:240-353`（`execute_filing`）：<br>① 五步逐步执行记录：1.Schema校验、2.报文组装、3.签名、4.发送、5.回执归档；<br>② cXML 组装注入 `Extrinsic cn:*` 扩展字段；<br>③ `is_sandbox=True` 时仅记录审计块，案件状态保持不变（`test_adapters_and_filing.py:102-127` 实测证实 `case.status` 保持不变）；真实建档时写回 `RESOLVED` 终态。 | **PASS** |

---

## 6. 画面验证复核（UI 报告复审与亲自抽查）

- **核验报告与截图审查**：
  复核 `docs/ui-verification-report-M4.md`，报告记载首轮核验 59 项断言 58 PASS / 1 FAIL；发现缺陷 **UI-M4-F01**（连通测试传姓名触发枚举校验报 500）后，经授权在 `backend/app/services/provider_service.py` 修复并完成复验；最终结果为 **59 PASS / 0 FAIL / 0 阻断**；17 张自动化高精度截图全量归档在 `docs/ui-verification-M4-shots/`。

- **评审员亲自代码与交互抽查（3 个区块）**：
  1. **抽查区块 1：`web/provider-orchestration.html` 推演评估逐步动画与 demo-mode 回退**：
     - 代码定位：`web/provider-orchestration.html:540-595`；
     - 走查实测：`window.runSim` 在 live 态向 `/v1/routing/simulate` 提交推演输入，后端返回包含步骤序列（`steps`）、状态（`st`）、时延（`ms`）和成本（`cost`）的 JSON；前端通过动态 `transition-delay` 逐步渲染推演卡；当后台断开时自动走 `_pvOrigSim` 内嵌 mock 数据，回退完好。
  2. **抽查区块 2：`web/matching-mapping.html` Tab 3 Link 候选与四项确定性证据对照**：
     - 代码定位：`web/matching-mapping.html:768-795, 903-918`；
     - 走查实测：候选列表展示 0384 与 0123 冲减候选；展开「证据对照」清晰展示供应商一致、金额冲减对应、开票日期先后、重复 Link 检查四项全绿勾；点击「确认冲减Link」调起五要素确认弹窗，强制本人勾选；提交时向 `/v1/matching/links/confirm` 发起 POST，确认后 Tab 3 角标动态扣减，候选卡显示绿条「✓ 冲减关联已建立」。
  3. **抽查区块 3：`web/adapter-management.html` 沙箱测试建档五步动画与回执留痕**：
     - 代码定位：`web/adapter-management.html:588-668, 690-720`；
     - 走查实测：点击「▶ 测试建档（沙箱）」调起弹窗；点击开始执行，界面向 `/v1/adapters/ariba/file` 发送 `{ is_sandbox: true }`；五步链路流水线动画逐步推进（Schema校验→报文组装→签名→发送→回执归档）；测试完成后浮现测试标记回执（如 `AID-2026-0387-9941`）与免责说明，后端仅记审计不篡改案件状态。

---

## 7. 台账与 TODO 对账

1. **Excel 台账对账**：
   - `细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx` 之 `03-分层功能FN-1~9`：
     - **FN-2**：全部 14 行状态已填「待验收」（FN-2-01~14）；
     - **FN-4**：FN-4-04、FN-4-06、FN-4-07 三行状态已填「待验收」；
     - **FN-6**：FN-6-01~07、09、10、11 共 9 行状态已填「待验收」；FN-6-08 与 FN-6-12 填「未开始」（规划移交 M5）；
     - **FN-7**：全部 11 行状态已填「待验收」（FN-7-01~11）；
   - 各行「验收要点」均详细回填了实现逻辑、工作包归属与测试用例编号；无受阻项挂起。
2. **TODO 标记对账**：
   - 扫描全仓代码，TODO 标记共 41 处，均属于附录 D 已登记未决问题或下一里程碑移交项：
     - `TODO(H24)`：Ariba cXML 建档细则接口待确认（附录 D）；
     - `TODO(H25)`：中国字段 Ariba 承载 `Extrinsic cn:*` 待确认（附录 D）；
     - `TODO(H38)`：三单匹配在 Ariba 还是 ERP 执行边界待确认（附录 D）；
     - `TODO(H39)`：中国数据驻留细则待确认（附录 D）；
     - `TODO(FN-9-10)`：真实凭证 KMS 托管移交 M5；
   - 未发现任何未登记的随意 TODO 或口径漂移项。

---

## 8. 缺陷清单（编号 × 级别 × 复现 × 关联 FN × 处置）

| 缺陷编号 | 级别 | 缺陷现象与复现步骤 | 关联 FN | 处置结论 |
|---|---|---|---|---|
| **UI-M4-F01** / API-M4-01 | **MAJOR** | **现象**：在 `provider-orchestration.html` 页面点击任意 Provider 的「测试连通」按钮，前端报错弹出 toast：`连通测试失败：HTTP 500 /v1/providers/bwyun-cn/test`。<br>**根因**：前端传递操作员姓名 `{ actor: '陈铮' }`，接口直接将 `actor` 传入 `audit_chain.append_block`，触发 `timeline_actor` 枚举合法性校验（合法枚举仅为 `system, provider, human, ai`），抛出 `EnumViolation` 导致 HTTP 500。 | FN-2-04<br>FN-0-10 | **已就地修复并复验闭环**。<br>修改 `provider_service.py`：审计主体规范为合法枚举 `human`，操作人姓名记录于操作详情 `op="provider_service v1.0 · 陈铮"`；追加单测断言；全量复测通过。 |
| **WARN-M4-01** | **MINOR** | **现象**：运行全量 pytest 测试套件时输出 1 处 Starlette 废弃告警：`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead`。 | TS-01 | **记录**。<br>不影响功能运行与测试断言，列入后续依赖库版本升级常规维护。 |
| **NOTE-M4-01** | **MINOR** | **现象**：Excel Sheet `04-接口面FN-A` 中，`FN-A-05`（Provider SPI）与 `FN-A-06`（Adapter API）的状态仍保持为「未开始」，而后台核心与 Schema 实际上已在 M4 交付落地。 | FN-A-05<br>FN-A-06 | **记录**。<br>P05 §3 验收标准仅约束回填 Sheet03，Sheet04 的状态同步建议在 M5 接口门户与 MCP 会话中统一更新闭环。 |

**缺陷清点统计**：
- **BLOCKER**：**0 项**
- **MAJOR**：**0 项未决**（1 项已修复闭环）
- **MINOR**：**2 项**（列入维护，不阻塞门禁）

---

## 9. 门禁评审结论与下一里程碑放行建议

### 门禁结论：【通过（PASS）】

**综合判定说明**：
1. **工作包交付齐全**：WP4.1–WP4.7 全部交付件齐备，无缺件、无占位死代码；
2. **测试与红线常绿**：单元与集成测试 **311 passed / 0 failure**，E2E 场景断言 **17 passed**（100% 稳定可重放），红线回归 **7 passed**，冒烟检查 **10/10 PASS**；
3. **契约强一致性**：枚举（142值）、契约（40项）、种子与UI（41项）三套校验脚本全部绿灯；
4. **纪律红线严明**：backend 零大模型库 import、agent/mcp 零 DB 直连、前端零裸读写、写操作全过受控五要素与审计哈希链、ui-design 冻结只读、旧仓零拷贝；
5. **口径深度契合**：异源互证同类模型排除、Link 候选四项校验与建档强制拦截、Adapter 五步沙箱链路等核心口径逐句核验全部通过；
6. **画面验收达标**：59 项画面核验全绿，缺陷 UI-M4-F01 修复彻底，demo-mode 独立演示态回退完备；
7. **台账对账吻合**：Excel 40 行状态与 TODO 清单严密对账无漂移。

### 下一里程碑放行建议：
**批准进入 M5（平台支撑 + 审计报表 + Agent/MCP 全功能收口）实施阶段。**

建议 M5 团队重点承接：
1. `agent/` 域 LangGraph 真实大模型对话意图循环与主动调查编排接入（直接消费 backend 内部 API，替换 M4 规则桩）；
2. `mcp/` 域 6 个 MCP 工具实现与 OAuth2 / confirm_token 受控保护；
3. `platform-admin.html` 与 `audit-reports.html` 接线与 RBAC 4×7 矩阵实装；
4. 红线告警停用拦截（R-04）管理面落地。
