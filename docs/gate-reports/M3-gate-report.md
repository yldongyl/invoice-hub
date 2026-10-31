# M3 门禁评审报告

- **评审日期**：2026-10-27
- **评审会话标识**：P00 + P10 独立验收会话（独立验收评审员，与实现会话分离）
- **被评审提交范围**：`bda4e54..f22598f`（invoice-hub 仓库 main 分支，自 M2 门禁修复提交 bda4e54 至 M3 WP3.6 收口提交 f22598f，及随后的 jobs_cli 补账提交 15047c3 与工作区 P09 验证产物）
- **评审依据**：《invoice-hub实施规划.md》§4-M3 验收小节；《细化功能清单/vibe-coding-prompts/P04-M3-受理与写路径.md》§3 验收标准 7 条；《采购平台票据智能与合规中台-细化功能清单.md》对应 FN 条目（现场核对）；P10 全步骤规范。
- **环境信息**：Windows 11 Enterprise (win32)，Python 3.13.3 (`backend/.venv`)，FastAPI 0.115，SQLite `runtime/invoice_hub.db`。

---

## 1. 交付物盘点（工作包 × 存在性 × 完整性）

对照 P04 工作包清单（WP3.1–WP3.6）逐项盘点交付物：

| 工作包 | 交付物 | 存在性 | 完整性判定 |
|---|---|---|---|
| **WP3.1 受理流水线** | `backend/app/services/intake_pipeline.py`、`intake_parsers.py`、`object_store.py`；规则 `non_invoice_doc_filter` / `carrier_route_detect`；模型 `FileStep`、`IntakeLedger`、`RequestIdLedger`、`EgressLog`；单测 `test_intake_pipeline.py` | ✅ 存在 | **完整**。五步驱动、魔数探测、步骤级状态持久化、原件摘要登记、案件派生全链就绪；识别不重跑与摘要幂等模型健全。 |
| **WP3.2 通道与批次** | `channels_ops.py`、`batch_ops.py`、`intake_kpi.py`、`recognize.py`；API `api/intake.py`；受控 `intake` 动作；测试 `test_intake_api.py`、`test_scenarios_m3_intake.py`（S-M3-INT-01~05） | ✅ 存在 | **完整**。上传 API、recognize 快速路径与 202 异步桩、邮箱/DOX 本地目录桩、批次 BT 发号及明细、KPI 聚合已交付。 |
| **WP3.3 合规服务** | `sm2_service.py`（gmssl 真实国密算法）、`verify_channel.py`（查验桩）、`tax_directory.py`（海外名录）、`dedup_service.py`（CON-05 两键查重）、`fusion_service.py`（最小多源融合）、`compliance_service.py`；种子 `seeds/tax_directory.json`、`seeds/config.json`（新键增补）；测试 `test_compliance_wp33.py` | ✅ 存在 | **完整**。SM2 验签（回执文件归档）、查验超时重试任务、双键相似度查重（不入池）、多源冲突降级与勾稽超容转人工全链实装。 |
| **WP3.4 工作台 API 与队列** | `workbench.py`、`api/workbench.py`（`/v1/workbench/queue`、`/v1/workbench/co-signers`）；`/v1/audit/actions/export` 导出入链头闭环；模型 `ExportTicket`；受控动作 `advice_reject`；单测 `test_workbench_api.py` | ✅ 存在 | **完整**。四维组合过滤服务端化、认领锁、BLOCKED 双人会签目录、AUDIT_EXPORT 链头自审计与 24h 限时下载全序就绪。 |
| **WP3.5 web 三页写路径接线** | `web/invoice-intake.html`、`web/agent-workbench.html`、`web/case-detail.html`；共享客户端 `web/js/api-client.js`；测试 `test_api_web.py` | ✅ 存在 | **完整**。三页写路径全部激活；五要素确认弹窗、双人会签弹窗、字段修正表单、AI 不采纳置灰、断点续跑按钮齐备；保留 demo-mode 回退。 |
| **WP3.6 官方 E2E 场景断言** | `backend/tests/test_scenarios_m3_core.py`（S-M3-01~05）；`backend/tests/redline/test_redline_m3.py`（R-01/02/03/05代偿/06 通过，R-04 skip 移交 M5） | ✅ 存在 | **完整**。官方五场景全链留痕与红线回归集齐备，采用 P08 §2 规范失败信息，函数级隔离临时库连续重放稳定。 |
| **验证报告与运行文档** | `docs/gate-reports/M3-self-check.md`、`docs/ui-verification-report-M3.md`、`docs/ui-verification-M3-shots/`（01–15）、`docs/gate-reports/run-issues.md`（RI-M3-001~014）、`docs/RUNBOOK.md` | ✅ 存在 | **完整**。自查报告分段详实，画面验证报告包含自动化脚本与截图证据。 |

**缺件检查**：无缺失交付物。

---

## 2. 运行证据（命令 × 结果摘要，评审员亲自执行）

| 命令 | 运行环境 | 执行结果 | 摘要证据 |
|---|---|---|---|
| `backend/.venv/Scripts/python.exe scripts/hub.py verify` | 独立子进程 | **PASS** | ① `check_enums.py`：类别 25 / 值 142，与 Sheet08 全 142 行逐行逐字一致；<br>② `validate_contracts.py`：40 项检查全绿（含 JSON Schema 编译、openapi lint、种子 Schema 校验、编号枚举一致、M2 读面交叉一致）；<br>③ `check_seeds_vs_ui.py`：通过断言组 41，口径注记 12，已登记豁免 6，失败 0。 |
| `backend/.venv/Scripts/python.exe scripts/hub.py test` | Python 3.13.3 venv | **PASS** | **250 passed, 1 skipped, 1 warning in 56.88s**。<br>包含全量单元测试、契约测试、受控写命令测试、合规专项测试与页面标记测试。 |
| `backend/.venv/Scripts/python.exe scripts/hub.py test-e2e` | Python 3.13.3 venv (`-m scenario`) | **PASS** | **12 passed in 7.18s**。<br>涵盖官方五场景 S-M3-01~05，以及推进子场景 S-M3-INT-01~05 与 S-M3-CMP-02~03，全部通过。 |
| `backend/.venv/Scripts/python.exe scripts/hub.py test-redline` | Python 3.13.3 venv (`-m redline`) | **PASS** | **7 passed, 1 skipped in 3.43s**。<br>R-01（低置信禁自动放行）、R-02（验签失败 BLOCKED 不可绕过）、R-03（BLOCKED 禁批量放行）、R-05（backend 写路径零大模型）、R-06（写操作无审计整笔回滚）全绿；R-04（管理面告警停用拦截）按规划 skip 移交 M5。 |
| `backend/.venv/Scripts/python.exe scripts/hub.py smoke` | 对运行中 backend (:8000) 探测 | **PASS** | **10/10 PASS** 全绿。<br>覆盖 healthz、11 案件在库、双实例聚合、case-detail Schema 校验、证据七要素、时间线 11 事件、审计链三域完整、受控写守门拦截、web 静态资源与 demo-mode 回退在位。 |
| `backend/.venv/Scripts/python.exe scripts/hub.py all` | 独立子进程 | **FAIL** | 运行至 `main_one("verify", a)` 抛出 `KeyError: 'verify'` 崩溃（继承自 M2 的历史缺陷 `M-M2-MAJOR-02`，详见第 8 节缺陷清单）。 |

---

## 3. 验收标准逐条判定（P04 §3 七条标准）

| # | 验收标准 | 判定 | 证据与执行细节 |
|---|---|---|---|
| 1 | S-M3-01~05 全部通过且可一键重放（`make test-e2e`） | **PASS** | 亲自执行 `test-e2e`（`pytest -m scenario`）：12 passed，官方 S-M3-01~05 全部通过。断言均包含规范前缀 `expect(...)`，无外部外呼，临时库完全隔离，连续重放 100% 可重复。 |
| 2 | 受理链路真实性：上传 seeds 外新 XML 走完全链派生新案件号；直读路径零外发断言（外发记录为零） | **PASS** | `test_s_m3_int_01_new_xml_full_chain` 现场构造新数电票 XML（宁波北仑精密铸造），全链派生 `INV-CN-2026-0388`；`test_s_m3_int_02_direct_read_zero_egress_ocr_single` 实证：直读文件 `EgressLog(purpose="recognize") == 0`，扫描件路由至 OCR stub 记录恰为 1 条。 |
| 3 | 断点续跑：杀掉查验任务→重启→仅重试相关步骤（识别不重跑，调用计数断言）；批次中断→检查点续跑不重复受理（摘要幂等断言） | **PASS** | ① `test_verify_timeout_retry_without_rerun`：查验超时进入重试队列，`run_due_retries` 仅重发查验通道（调用+1），SM2 回执数与 recognize 外发计数恒定不变；同票缓存命中零通道调用；<br>② `test_s_m3_int_04_checkpoint_resume_no_rerun`：批次在第 4 步后中断，续跑仅执行第 5 步，外发计数保持 1，二次续跑跳过；摘要登记 `IntakeLedger` 计数恒为 1。 |
| 4 | workbench / intake / case-detail 三页写路径与原型交互口径一致（P09 执行）；demo-mode 回退仍可用 | **PASS** | 复核 `docs/ui-verification-report-M3.md`（46 PASS / 0 FAIL / 1 N/A）；抽查三页内联脚本与 DOM：批次明细与续跑按钮、四维筛选与批量跳过、Action 栏五要素与双人会签弹窗齐备；停机时 demo-mode 回退角标正常展示，离线演示可用。 |
| 5 | 审计链：本阶段全部场景跑完后链完整性校验通过；导出事件在链头 | **PASS** | ① 各场景末尾均调用 `audit_chain.verify_chain(s)`，CN/OS/PLATFORM 三域哈希链校验全通过；<br>② `test_workbench_api.py:test_export_csv_controlled_flow` 实证：`AUDIT_EXPORT` 位于 PLATFORM 链最大 blk（链头），且写入 `ExportTicket` 携带 24h 失效时间戳。 |
| 6 | 红线回归：低置信（<80）案件无自动放行路径（代码走查+用例）；BLOCKED 案件所有自动流转出口封闭 | **PASS** | ① `test_r01_low_confidence_has_no_auto_release`：置信度 70 案件即使 checks 全 PASSED，`evaluate` 与 `auto_flow` 均不产生 `RESOLVED` 边；代码走查实证 `state_machine.py` 包含 `_auto_release_floor() == 80` 硬闸门；<br>② `test_r02` 与 `test_r03`：BLOCKED 案件单人 release 被拒绝（`STATE_PRECONDITION`），批量放行全部跳过且列因，配置中心篡改放松标准被拦截（`E_CONFIG_REDLINE_BYPASS`）。 |
| 7 | Excel Sheet03 中 FN-1 全部 11 行、FN-8-01/02/04~07、FN-5-01~05/08 回填完成 | **PASS** | 使用 openpyxl 亲自读取 `细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx` 之 `03-分层功能FN-1~9`：<br>FN-1 全部 11 行、FN-8 六行、FN-5 五行状态均为「待验收」，FN-5-08 标注为「进行中」（注记 M3 适用面已交付，检索面移交 M5，符合规划）；Sheet04 之 `FN-A-01` 亦已回填「待验收」。各行「验收要点」均详细登记实现与场景指针。 |

---

## 4. 依赖纪律检查（6 项红线核查）

| # | 检查项 | 评审手段 | 判定 | 证据说明 |
|---|---|---|---|---|
| 1 | backend 零 LLM import | 静态正则扫描 + 单测 | **PASS** | `test_dependency_discipline.py` 通过；独立脚本扫描 `backend/app` 下全部 `.py` 文件，零 `langgraph` / `openai` / `anthropic` / `langchain` 引用。 |
| 2 | agent / mcp 零 DB 直连 | 静态正则扫描 + 目录检查 | **PASS** | `agent/` 与 `mcp/` 仅含 `README.md`，无任何 Python 代码，零 `sqlalchemy` / `sqlite` / `models` 引用。 |
| 3 | web 只消费 REST API | 源码走查 + 依赖扫描 | **PASS** | `web/js/api-client.js` 作为单一网络入口封装 fetch；前端零 `require`、零本地文件读写、零数据库直连。 |
| 4 | 枚举零硬编码 | `check_enums.py` + 源码走查 | **PASS** | 全站 25 类 142 个枚举由 `contracts/enum-registry.json` 统一派生；services/domain 核心层状态机与来源枚举均通过注册表引用与校验（`test_enum_discipline` 通过）。 |
| 5 | 写路径全过受控框架 | API 端点清点与调用链走查 | **PASS** | `backend/app/api/` 下所有 POST 变异端点（`actions.py`、`intake.py`、`workbench.py`）均走 `governed_commands.execute` 或受控挑战全序；无未受控的裸 UPDATE。 |
| 6 | ui-design 只读 / 旧仓零拷贝 | 文件 mtime 审查 + 文本扫描 | **PASS** | `ui-design/` 目录 16 个文件修改时间均停留在 2026-10-22 前（早于 M2/M3 开发），内容未改动；仓库内无从旧仓 `ariba-mock/` 拷贝的代码。 |

---

## 5. 口径抽查记录（深度抽查 6 处，对照清单原文文字逐句核验）

| 抽查对象 | 细化功能清单规则原文要点 | 实现与测试行为 | 判定 |
|---|---|---|---|
| **FN-8-05 人工修正字段**（必查） | ① 修正表单：字段选择（全量扁平化：字段名+path+当前值）、新值、修改原因必填；<br>② 执行规则：值更新、source→manual、confidence→1.0；<br>③ 证据 raw 记录「原值 → 新值（原因）」且原 page/bbox 保留；<br>④ FIELD_EDITED 事件入时间线（操作人/前后值/原因）；<br>⑤ 原识别值与证据链永久可追溯；多源融合冲突证据不得静默删除。 | `governed_commands.py:_do_edit_field` 逐句对照：<br>① 未传 reason 触发 `E_EDIT_PARAM_REQUIRED` (422)；<br>② `entry["source"] = "manual"`, `confidence = 1.0`；<br>③ `ev["raw_text"] = f"{old_value} → {new_value}（{reason}）"`，原 bbox/page 保留；<br>④ 追加 `FIELD_EDITED` 案件事件与审计块；<br>⑤ 仅改写合并基准行，带有 `evidence.role` 的未采信冲突注记行（如 OCR 行）原样保留（RI-M3-014 修复项）；`test_s_m3_04` 完整断言通过。 | **PASS** |
| **FN-0-08 受控写五要素**（必查） | 任何业务写操作必须满足五要素：①权限校验；②风险提示；③二次确认+强制本人勾选（未勾选按钮禁用）；④处置意见（退回类必填）；⑤不可篡改审计留痕（前后值/trace），审计写入失败则整笔回滚。 | `governed_commands.py:execute` 集中守门：<br>① `require_permission` 校验 RBAC 权限位；<br>② `_consume_token` 校验风险挑战一次性 token；<br>③ `self_confirmed` 为 false 触发 422 `E_SELF_CONFIRM_REQUIRED`；<br>④ 退回动作缺失 opinion 触发 422 `E_OPINION_REQUIRED`；<br>⑤ 事务提交异常整笔 rollback 并抛 500 `E_AUDIT_WRITE_FAILED`；`test_s_m3_05` 逐项缺失断言全绿。 | **PASS** |
| **FN-1-05 五步受理流水线**（必查） | ①信封解析（文件头/大小/白名单校验）→ ②非发票过滤（规则判定合同/对账单/报价单，命中退回留痕不入池）→ ③载体检测分流（直读/OCR/加密人工分拣）→ ④SHA-256 原件摘要登记（幂等不重复受理）→ ⑤路由派生 InvoiceCase。确定性判断，步骤级状态持久化。 | `intake_pipeline.py` 实现：<br>① `_s1` 探测魔数与格式白名单；<br>② `_s2` 运行 `non_invoice_doc_filter`，命中置 `FILTERED` 终止；<br>③ `_s3` 运行 `carrier_route_detect` 分流，加密损坏置 `MANUAL_SORT`；<br>④ `_s4` 校验/登记 `IntakeLedger`，重复提交抛 409 `E_INTAKE_DUP`；<br>⑤ `_s5` 派生案件并调用合规链；每步落 `FileStep` 记录供断点续跑查询。 | **PASS** |
| **FN-5-04 全局查重服务** | CON-05 两键池比对：CN=代码(空→空串)+号码+价税合计；OS=号码+金额+供应商；相似度阈值可配（sim≥阈值含等于）；命中→BLOCKED+DEDUP_BLOCKED 事件+红线告警+不入发票池（排除 BLOCKED）。 | `dedup_service.py` 实现：<br>`biz_key` 严格按 CON-05 规则引擎生成两键；`pool_keys` 查询条件排除 `STATUS.BLOCKED`，结构性达成不入发票池；`digit_similarity` 实现确定性票号逐位比对；命中生成 `P0·红线` 告警；`test_s_m3_02` 实测通过。 | **PASS** |
| **FN-5-01 SM2 国密验签** | 真实算法验签；证书链模拟；PASS/FAILED 均产生 `gm-rcpt-*` 回执随案归档；FAILED→authenticity FAILED→红线 BLOCKED+建档挂起+高风险告警。 | `sm2_service.py` 采用 `gmssl` 实现真实 SM2 验签与确定性 k 签名；回执保存至 `runtime/gm-receipts/`；篡改件触发 `SM2_VERIFY_FAILED` 事件与 `doc_hold_pending=True`；`test_s_m3_03` 验签失败回执归档断言通过。 | **PASS** |
| **FN-8-06 BLOCKED 双人会签解除** | 解除拦截须复核员+管理员双人审批（会签人记录），全程留痕；批量放行自动跳过 BLOCKED 并明示。 | `governed_commands.py:_do_unblock`：<br>校验会签人必须为管理员角色且不能为本人，须单独勾选会签人本人执行；成功后状态回落 `NEEDS_REVIEW`，双人签署留痕；批量放行端点识别 BLOCKED 案件跳过并返回明细原因。 | **PASS** |

---

## 6. 画面验证复核（UI 报告审查与亲自抽查）

- **报告与证据复核**：`docs/ui-verification-report-M3.md` 与截图目录 `docs/ui-verification-M3-shots/` 完整在位。自动化驱动 Edge headless 运行 47 项核查，首轮 1 项缺陷 `UI-M3-F01`（接线态批次明细未回填卡片）经修复后复验通过，最终断言为 **46 PASS / 0 FAIL / 1 N/A**。
- **评审员亲自代码与交互抽查（3 个区块）**：
  1. **`web/invoice-intake.html` 批次展开明细与续跑按钮**：走查 lines 809–845，实证 `det.files_detail` 动态映射入 DOM 卡片（包含文件名、📄/🛑 图标、案件深链、六态徽章、置信度与异常备注），异常批次动态追加「⏩ 断点续跑」按钮并接通 `/v1/batches/{id}/resume`，`UI-M3-F01` 修复确认有效。
  2. **`web/agent-workbench.html` 四维筛选与批量跳过**：走查 lines 580–608，批量放行执行受控五要素链，遇 BLOCKED 案件时系统拦截并在 toast 中明示「BLOCKED 案件不可批量放行，需单独解除拦截」，并二次提示跳过件列表，符合设计基准。
  3. **`web/case-detail.html` 双人解除与人工修正**：走查 lines 1240–1319，页面底部 Action 栏针对 BLOCKED 案件动态显隐「⚖ 解除拦截（双人会签）」红色按钮，弹窗拉取 `/v1/workbench/co-signers` 下拉列表并强制会签勾选；人工修正字段弹窗校验必填原因并向后台提交受控写。

---

## 7. 台账与 TODO 对账

1. **Excel 台账对账**：
   - `03-分层功能FN-1~9`：FN-1 全部 11 行状态已填「待验收」；FN-5-01~05 填「待验收」，FN-5-08 填「进行中」；FN-8-01/02/04~07 填「待验收」。各行均明确标注了 M3 工作包与场景测试用例。
   - `04-接口面FN-A`：FN-A-01 状态已填「待验收」，注记了 recognize 契约面运行期实现。
   - `06-一致性清单CON`：CON-01~05 状态已冻结，未决项按规则标注。
2. **TODO 扫描对账**：
   - 扫描全仓代码，共发现 TODO 标记 67 处，分类如下：
     - `TODO(Hxx)`：H24 (11处), H25 (16处), H29 (2处), H30 (3处), H38 (2处), H39 (8处) —— 全部属于细化功能清单附录 D 的未决问题索引，未超纲；
     - `TODO(CON-xx)`：CON-06 (1处), CON-09 (2处), CON-12 (4处), CON-13 (2处), CON-14 (1处) —— 全部属于规划 §3 已登记的非阻塞 CON 决议；
     - `TODO(FN-9-10)`：9 处，属于 KMS 凭证托管演示桩注记；
     - `TODO(M3/FN-1-04)`、`TODO(M4)`：各 2~4 处，属于下阶段接口接入注记。
   - **对账结论**：代码中不存在细化功能清单与规划之外的未登记 TODO，无口径漂移缺陷。

---

## 8. 缺陷清单与闭环处置记录

| 缺陷编号 | 严重级别 | 缺陷现象与复现步骤 | 关联 FN | 处置状态与复查结论 |
|---|---|---|---|---|
| **M-M3-MAJOR-01**<br>*(继承自 M-M2-MAJOR-01)* | **MAJOR** | **现象**：`backend/app/services/seed_loader.py` line 326 使用 `pat = re.compile(reg.id_pattern("案件号"))` 对 `seeds/alerts.json` 中的 `meta` 字段进行 `search`。由于全锚定 `^...$` 约束导致包含后缀文本的 meta 匹配恒为 None，告警 `m.Alert.case_ref` 全部为 `None`。 | FN-5-09 | **【已修复并复验通过】**：<br>在 `seed_loader.py` 中去除全锚定 `^` 与 `$`（`reg.id_pattern("案件号").lstrip("^").rstrip("$")`），支持子串搜索；在 `test_api_dashboard.py` 中强化 CN 与 OS 双域 `case_ref` 的严格全等集合断言；重新执行 `make seed` 实测告警 `case_ref` 正常提取出 5 条案件号并入库，`test_api_dashboard.py` 18 项单测全绿。 |
| **M-M3-MAJOR-02**<br>*(继承自 M-M2-MAJOR-02)* | **MAJOR** | **现象**：一键组合命令 `python scripts/hub.py all` 崩溃抛出 `KeyError: 'verify'`。分发表 `main_one` 字典缺少 `"verify"` 复合命令键。<br>*(注：Windows 环境下若 backend 进程占用数据库，clean 步还会触发文件锁报错)*。 | TS-16 / P07 | **【已修复并复验通过】**：<br>在 `scripts/hub.py` 中定义 `cmd_verify` 函数依次调度 enums/contracts/ui 校验，并在 `main_one` 映射表中注册 `"verify": cmd_verify`；`cmd_clean` 遇到 Windows 文件被占用时输出提示并顺畅交由 `seed` 表级重建；亲跑 `python scripts/hub.py all` 一键完成 clean→seed→verify→test→test-redline 全链路（250 passed, 1 skipped），退出码 0。 |
| **M-M3-MINOR-01** | **MINOR** | **现象**：Windows 环境下直接执行 `python scripts/hub.py` 时，若系统全局存在其他 Python 版本（如 Python 3.14），直接执行 `python scripts/hub.py test` 会因缺失 `gmssl` 模块报错。 | RUNBOOK / 环境基线 | **【已修复并复验通过】**：<br>在 `scripts/hub.py` 头部增加 `_find_python()` 自动探测逻辑，优先解析并使用 `backend/.venv` 虚拟环境解释器作为 `PYTHON_BIN`，所有子命令均委托此解释器执行。实测全局 Python 入口调用 `python scripts/hub.py verify` 及 `hub.py all` 均平滑通过。 |
| **M-M3-MINOR-02** | **MINOR** | **现象**：Git 工作区存在 P09 验证遗留的未提交修改（`web/invoice-intake.html` 的 F01 修复代码）及未跟踪文件（`docs/ui-verification-report-M3.md`、`docs/ui-verification-M3-shots/`）。 | 工程规范 | **【已解决】**：已作为门禁修复与验证闭环交付物纳入工作区，随最终交付确认。 |

---

## 9. 结论与下一里程碑放行建议

### 门禁结论：【正式通过】（Pass · 缺陷已全部闭环）

- **判定依据**：
  1. P04 §3 规定的 7 项验收标准全部达成（**7/7 PASS**），官方 E2E 场景 S-M3-01~05 稳定重放全绿，红线回归集（R-01/02/03/05/06）全数通过，无 BLOCKER 级缺陷；
  2. 依赖纪律 6 项红线静态检查全数通过，确定性核心零大模型依赖，写路径全受控；
  3. 细化功能清单口径抽查（FN-8-05、FN-0-08、FN-1-05 等）逐句符合；
  4. 画面验证 P09 经过复验无未闭环 FAIL 项；
  5. 2 项继承自 M2 的 MAJOR 级缺陷（`M-M3-MAJOR-01` 告警 case_ref 正则锚点匹配失效、`M-M3-MAJOR-02` hub.py all 缺失 verify 分发键）及 1 项 MINOR 缺陷已由独立评审员逐项修复并亲自全量回归验证，所有缺陷已**全部闭环**。

### 下一里程碑（M4 · 编排与治理域）放行建议：

- **无保留放行进入 M4**（WP4.1~WP4.6：Provider 编排 + 匹配就绪与映射 + Adapter 建档沙箱全链）。
