# M1 门禁评审报告（FN-0 平台内核）

- **评审日期**：2026-10-26
- **评审会话标识**：P00 + P10 · 独立验收评审（与 R3/R4/R5 实现会话分离，本次仅评审不修复）
- **被评审提交范围**：`d27bb24`（M0 baseline）→ `56aaea1`（G-M0-001）→ `fa520bd`（WP1.1–1.2）→ `37afd14`（WP1.3–1.5）→ `23f00a2`（WP1.6–1.8），工作树干净（`git status` 无未提交改动）
- **评审输入**：实施规划 §2/§3/§4-M1；清单 §2 FN-0-01~15 逐条（现场读）；`contracts/enum-registry.json`；`seeds/*`；`docs/gate-reports/M1-self-check.md`（R3/R4/R5 三段）；Excel `02-全局约定FN-0` / `06-一致性清单CON`
- **环境**：Python 3.14.3 / FastAPI 0.136.3 / SQLAlchemy 2.1.6 / pytest 9.1.1（评审环境实测，非采信自述）

---

## 1. 交付物盘点（工作包 × 存在性 × 完整性）

| 工作包 | 核心文件 | 存在 | 完整性 |
|---|---|---|---|
| WP1.1 技术底座 | `pyproject.toml` / `requirements-dev.txt` / `Makefile` / `app/main.py` / `services/{seed_loader,config_center,persistence}.py` | ✅ | 骨架四子包+tests 齐备；`GET /healthz` 实测 200（status/version/enum_registry_version/database） |
| WP1.2 领域模型与仓储 | `app/domain/{models,registry}.py` / `services/case_repository.py` | ✅ | Case/FieldEvidence/CheckResult/TimelineEvent/ObjectLink/AuditBlock/UserAccount/RoleDef/ConfigItem/Alert/KpiSnapshot/RuleCatalogEntry/ComponentVersion + 接口位（Batch/FileIntake/Provider/RoutingPolicy/MappingRule）齐备；聚合查询 `aggregate_case()` 交付 |
| WP1.3 状态机 | `services/state_machine.py` / `workers/retry.py` | ✅ | 六边+解除规则消费 enum-registry.state_transition；认领子态不扩态；断点续跑钩子；STATUS_CHANGE 双写带 case-machine 版本 |
| WP1.4 哈希链 | `services/audit_chain.py` | ✅ | 12 要素 canonical JSON→链式 SHA-256；WORM ORM 拦截；verify_chain 定位断点 blk#；VerifyRun 登记；trace 统一收口 issuer |
| WP1.5 受控写框架 | `services/governed_commands.py` / `api/actions.py` / `services/errors.py` | ✅ | 五要素全序；9 命令（+publish/rollback=11）；批量逐案校验；edit_field 全规则 |
| WP1.6 规则引擎 | `services/rules.py` / `services/orchestrator.py` | ✅ | 13 条内核规则；容差两套分设；四校验编排器；置信度分档从 registry 解析；验签失败降级标注 |
| WP1.7 发号器与租户 | `services/issuer.py` / `services/tenant.py` | ✅ | 5 域发号+pattern 自校验+seed 播种幂等；TenantContext 必携带/越权拒绝；API 全端点强制 |
| WP1.8 版本化基座 | `services/versioning.py` / config_center 接入 | ✅ | draft/published 双态；v{日期}.{序号}+diff+旧版保留+回滚；POLICY_PUBLISHED 入链；红线项拒绝关闭 |

**结论**：WP1.1–1.8 全部到位，无缺件。P02 §3 最小 API 面（4 读端点 + actions + risk-challenge + healthz）实测路由表齐备。

## 2. 运行证据（命令 × 结果摘要）

| 命令 | 结果 | 摘要 |
|---|---|---|
| `PYTHONIOENCODING=utf-8 python -m app.services.seed_loader`（×2） | **EXIT 0** | 13 类资产入库；两次尾态计数一致（providers6/routing1/taxcodes10/mapping_rules7/versions19/alerts6/kpi2/audit_chains3） |
| `python -m app.services.seed_loader`（默认 cp1252 控制台） | **崩溃→EXIT≠0** | 见缺陷 M-M1-001（seed_loader.py:331 `✅` emoji 在 cp1252 抛 UnicodeEncodeError，数据已写但退出码非零） |
| `python -m pytest -q` | **144 passed** | 30.55s；与自述一致 |
| `python -m pytest --cov=app/domain --cov=app/services` | **TOTAL 94%** | 最低模块 89%（seed_loader/state_machine），models 100% |
| `python tools/check_enums.py` | **通过** | enum-registry 19 类/115 值 与 Sheet08 全 115 行逐字一致 |
| `python tools/validate_contracts.py` | **31 项全绿** | 含 openapi 全量 validator 路径（G-M0-003 闭环）+ 种子交叉一致（0121 走已登记白名单） |
| `python tools/check_seeds_vs_ui.py` | **EXIT=0** | 断言组 39 / 口径注记 12 / 已登记豁免 6 / 失败 0（G-M0-001 闭环） |
| TestClient 冒烟 | 全 200/4xx | healthz 200；list/summary/full/evidence/timeline 200；无租户→400；越权→403 E_TENANT_MISMATCH；不存在→404 CASE_NOT_FOUND |

> 评审未采信自述报告，全部亲跑；144 passed / 94% / 三脚本 EXIT=0 实测复现。

## 3. 验收标准逐条判定（标准 | PASS/FAIL | 证据）

| # | P02 §4 验收标准 | 判定 | 证据 |
|---|---|---|---|
| ① | 状态机 FN-0-02 六条逐条（含触发+附带）；BLOCKED 解除缺会签拒绝；认领不扩状态 | **PASS** | `test_rule1..6`、`test_edges_are_registry_defined_no_redefinition`、`test_claim_substate_does_not_change_status`、`test_unblock_missing_cosigner_rejected` 等亲跑绿 |
| ② | seed 15 事件链校验；篡改→失败并定位 blk#；导出插链头 | **PASS** | `test_seed_chain_verifies/domains_independent/genesis_and_linkage`、`test_tamper_*_detected`（定位 10336/10339/10312/10313）、`test_export_appends_at_chain_head`、`test_worm_orm_{update,delete}_blocked` |
| ③ | 五要素逐项缺失→拒绝（≥5 用例）；批量含 BLOCKED→跳过明细；edit_field 原值可追溯 | **PASS** | `test_element1..5`（权限/AI 主体/凭据缺失/本人勾选/重放/退回必填/审计回滚=7 拒绝）；`test_batch_release_skips_blocked_with_details`（0387 放行 / 0385 BLOCKED 红线跳过 / 0383 VERIFYING 态跳过，DB 核验）；`test_edit_field_traceability_and_rules`（raw_text=`{old}→{new}（reason）`、page/bbox/model_version 保留、provider `人工修正·王莉`、审计 from 含原值、修正后过 Schema） |
| ④ | 最小 API 全响应过 Schema；枚举值 ∈ registry | **PASS** | `test_contracts`、`test_api_readonly`（list 项/summary/full 过 invoice-case.schema、evidence 过 $defs/evidenceEntry、timeline 过 events.schema、404/403/400 错误码） |
| ⑤ | `make seed` 幂等；聚合=种子逐字段（0387/0379/0125 点名） | **PASS（UTF-8 环境下）** | `test_seed_loader::test_rebuild_twice_identical` + `test_case_repository::test_aggregate_full_case_deep_equal_seed[0387/0379/0125]` + `test_aggregate_all_11_cases_deep_equal`；注：裸控制台幂等性受 M-M1-001 影响（EXIT 码层面） |
| ⑥ | `grep -rn "langgraph\|openai\|llm" backend/` 零命中 | **PASS** | 亲跑 EXIT=1（含 __pycache__ 在场；`grep -rll m` 亦零命中）；pyproject 依赖无 LLM；`test_dependency_discipline` 三测（运行时 join 构造违禁词，扫描器不自误报） |
| ⑦ | domain+services 覆盖率 ≥80% | **PASS（94%）** | pytest --cov 实测 |

**七条全 PASS**，其中⑤带环境条件（M-M1-001）。

## 4. 依赖纪律检查（6 项 × 结果）

| 纪律 | 结果 | 证据 |
|---|---|---|
| ① backend 无 LLM import / 无 agent import | **PASS** | grep 零命中；`test_no_agent_mcp_package_imports` |
| ② agent/mcp 不触库 | **PASS（空面）** | `agent/`、`mcp/` 仅 README.md，无代码、无 sqlalchemy/sqlite import |
| ③ web 只消费 REST / ui-design 只读 | **PASS** | `web/` 仅 README（M2 接线）；`ui-design/*.html` mtime 全 ≤2026-10-22，零改动 |
| ④ 枚举/编号从 registry 引用，禁硬编码 | **基本 PASS，1 处偏差** | 状态六态/分档/边经 registry 派生（`test_enum_discipline_no_bare_enum_literals_in_services`、`test_edges_are_registry_defined`）；**例外见 M-M1-002**（link_type 五类硬编码，因 enum-registry 无该类别） |
| ⑤ 写路径全过受控框架 | **PASS** | 路由表实测仅 `api/actions.py` 有业务写；单案/批量/config 三类端点均汇入 `gc.execute` 五要素全序；`risk-challenge` 仅签发一次性 ConfirmToken（要素②③前置，非业务写，不改 case/checks/status，可接受） |
| ⑥ 确定性判断只归规则引擎 | **PASS** | `orchestrator.apply_results` 为 CheckResult+checks_raw 唯一写入口；`edit_field` 不触碰 checks；无 LLM 输出写 checks/status |
| 旧仓零拷贝 | **PASS** | backend 代码/测试无 `ariba-mock`/`invoice-platform` 引用；仅 contracts 文档以"仅参考/历史"措辞提及，符合 P00 §2 |

## 5. 口径抽查记录（FN 编号 | 规则原文要点 | 实现行为 | 判定）

> 抽取 8 处（含两条强制项），逐句对照清单文字。

| FN | 清单原文要点 | 实现行为（文件:行） | 判定 |
|---|---|---|---|
| **FN-0-05/8-05 人工修正原值保留**（强制） | source→manual、confidence→1.0、raw_text 保留"原值→新值（原因）"、原 page/bbox 保留 | `governed_commands.py:224-249`：`entry["source"]="manual"`、`confidence=1.0`、`raw_text=f"{old}→{new}（{reason}）"`、`ev` 仅覆写 raw_text/provider、page/bbox/model_version 原样保留；FIELD_EDITED 双写；审计 `from_state` 含原值+原 Provider | **PASS** |
| **FN-0-02 BLOCKED 双人解除**（强制） | 复核员+管理员会签、全程留痕、解除后按调查结论重新流转 | `governed_commands.py:259-287` + `state_machine.lift():281-297`：缺会签人/同人/非管理员/未勾选四拒绝；仅 BLOCKED；复核员 STATUS_CHANGE 块 + 管理员会签补记块（双块=全程留痕）；lift 默认回落 NEEDS_REVIEW（演示口径注记） | **PASS** |
| FN-0-02 规则2 RECOGNIZED→BLOCKED | 验签 FAILED 红线/查重命中→BLOCKED；建档挂起；其余 Checks 不中止、结论供解除参考 | `state_machine.evaluate():202-203` redline_hit；`_apply_effects():121-122` doc_hold_pending=True；`orchestrator.apply_results():159-166` 红线触发流转同时四项结果全写入 | **PASS** |
| FN-0-10 哈希链 | append-only(WORM)、blk#、链式 SHA-256、完整性校验（校验人/时间登记）、trace 贯穿、双实例各区域独立成链 | `audit_chain.py` canonical 12 要素+sort_keys SHA-256；`before_update/delete` 拦截 13 业务字段；`verify_chain` 返回 bad_blk 定位首个断点+VerifyRun 登记；链域 CN/OS/PLATFORM 分域，blk 全局连续 seed 链头 10343 | **PASS**（trace 全链路贯穿随 M3 受理管线完整化，现阶段案件内 trace 沿用，注记可接受） |
| FN-0-08 五要素/批量/export | 缺一即拒；BLOCKED 不可批量放行；批量逐案校验跳过；导出自审计（条件/行数入链） | `execute():372-397` 权限→凭据→勾选→处置意见顺序；`_consume_token` 一次性+绑定 actor/action/scope；`_do_batch():295-296` BLOCKED 跳过带原因；`_do_export():319-331` 强制 filters+rows，AUDIT_EXPORT 入链头 | **PASS** |
| **FN-0-06 置信度分档 + 低置信禁自动放行** | <80% 低（红）**强制人工、禁止自动放行** | `rules.py:297-330` 分档从 registry 解析、降级标注交付；**但 `state_machine.evaluate():215-216` 的 4 号自动边（NEEDS_REVIEW/INVESTIGATING 四校验全 PASSED→RESOLVED）未校验置信度**：一条因低置信落入 NEEDS_REVIEW 的案件，若四项 Checks 恰好全 PASSED，自动边即产出 RESOLVED，`auto_flow` 可据以自动放行；config `low_confidence_force_human` 仅在配置面拦截关闭，**引擎侧无消费点** | **FAIL（MAJOR-01）** |
| FN-0-13 编号 | INV-{CN\|SG}-2026-NNNN 分实例域、BT/gm-rcpt/QA/ANNO、trace tr-{8hex} | `issuer.py:52-83` 分域计数+`_check` 对 registry id_format pattern 自校验；`seed_counters_from_data` 播种续起（CN 自 0387、SG 段自 0125、gm-rcpt 1042→1043） | **PASS** |
| FN-0-11 双实例/租户强制 | 数据/配置/Provider Key/发票池四隔离；所有查询与写携带租户上下文，缺失即报错 | `tenant.py`+`case_repository`/`governed_commands` instance 强制过滤；`execute():374-383` 缺→E_TENANT_MISSING(400)、越权→E_TENANT_MISMATCH(403)、跨实例批量整批拒绝 | **PASS**（Provider Key 的 KMS 保管属 M5，注记合规） |

## 6. 画面验证复核

**不适用**。M1 为 backend 纯内核（P02 范围明载"不做页面接线（M2）"），`docs/ui-verification-report-M1.md` 缺失属预期（P10 画面验证自 M2 起强制）。G-M0-001 的 seed↔页面交叉脚本仅作为数据口径一致性证据（§2 表 EXIT=0），不等同于画面验证。

## 7. 台账与 TODO 对账

- **Excel `02-全局约定FN-0`（15 行）**：全部回填，状态分布=待验收×13（FN-0-01/02/03/04/05/06/07/08/10/11/12/13 + 06）、未开始×2（FN-0-09 归 M5、FN-0-14 归 M2）、进行中×1（FN-0-15，后台响应 Schema 收尾、页面侧 M2）。每行附【M1 R3/R4/R5】验收要点括注。
  - **无一行自标"已完成"** —— 符合纪律（状态判定权属门禁，实现会话不自封完成）。评审要求"抽 3 条已完成验证"，因台账无"已完成"行，改为**抽验 3 条"待验收"行与实况一致**：FN-0-02（状态机代码+14 测点存在且绿）、FN-0-05（edit_field 全规则在码+测试）、FN-0-08（受控框架五要素+API 接线），**括注描述与交付实况一致，无虚标**。
  - **注意**：FN-0-06 标"待验收"，但本评审 §5 判其自动边守缺失（MAJOR-01），"待验收"状态**不成立**，须降级为"进行中/受阻（M-M1-001…MAJOR-01）"并修正括注。
- **Excel `06-一致性清单CON`**：CON-11 已更正"已随 CON-02 冻结（M0）"+子态字段备注（关闭 G-M0-006）✅；CON-01~05=已冻结；CON-06~14=未收敛，与代码 TODO 一致。
- **M0 挂账闭环**：G-M0-001（脚本 EXIT=0）✅、G-M0-002（CLAUDE.md §7 块 diff 实测 = P00 全文，L65 恢复原文）✅、G-M0-003（requirements-dev.txt + 全量 validator 31 绿）✅、G-M0-006（Sheet06）✅、G-M0-007（git 基线 d27bb24 + 工作包分次提交可 diff）✅、G-M0-008（清单裁决）✅。**G-M0-004/G-M0-005** 属 M2/M3 契约收紧项，M1 未触，不阻塞。
- **代码 TODO 盘点**：`backend/app` 内 TODO 标记 = WP1.5（actions 路由位，已由 37afd14 落地，属陈旧注记，见 M-M1-004）、TODO(M3/FN-1-04) 退回邮件桩、TODO(H39) 数据驻留、TODO(WP1.7) trace（已由 issuer 落地，audit_chain 文档串陈旧，见 M-M1-004）。**全部命中清单/CHANGELOG 登记集**（H24/25/29/38/39、CON-06/09/12/13/14、M3 边界），**无清单外造词 TODO**，口径零漂移。

## 8. 缺陷清单（编号 | 级别 | 复现 | 关联 FN | 处置）

| 编号 | 级别 | 描述 | 复现 | 关联 FN | 处置 |
|---|---|---|---|---|---|
| **M-M1-MAJOR-01** | **MAJOR** | FN-0-06 红线"低置信强制人工、禁自动放行"未在状态机自动边落实：`state_machine.evaluate()` 4 号边（NEEDS_REVIEW/INVESTIGATING→RESOLVED，四校验全 PASSED）不检查 case.confidence；低置信案件落入 NEEDS_REVIEW 后若四 Checks 全 PASSED，`auto_flow` 将自动放行。`low_confidence_force_human` 配置仅在 versioning 拦截关闭、引擎侧无消费点 | `evaluate()` 返回含 `{"to":"RESOLVED","reason":"自动路径全部 Checks 通过"}`，即便 conf<80；`test_rule4_to_resolved_auto_path` 仅以 conf=99 验证，未覆盖低置信 | FN-0-06 / FN-0-02 表 4 / P00 §5 红线 | **有条件放行之条件**：列为 M3 受理管线（`auto_flow` 投产）首个工作包——4 号自动边加低置信守卫（conf<80 或缺阈值→禁自动、强制停留人工）；红线回归补 conf<80 用例。M1 无 live 自动管线，故非 BLOCKER |
| M-M1-001 | MINOR | 裸 Windows 控制台（cp1252）执行 `python -m app.services.seed_loader` 在 seed_loader.py:331 打印 `✅` 抛 UnicodeEncodeError→**退出码非零**（数据已正确入库）；破坏 `make seed && make test` 链与验收⑤"幂等"在默认控制台的 EXIT=0 语义 | 默认 shell 跑 seed→UnicodeEncodeError（本评审复现）；`PYTHONIOENCODING=utf-8` 复跑→EXIT 0 | FN-0-11/§4-M1 验收⑤ | M2 前修复：入口 `sys.stdout.reconfigure(encoding="utf-8")` 或去 emoji；runbook 注记 |
| M-M1-002 | MINOR | 五类 Link 词表（匹配/收货/来自/冲减/包含）硬编码于 `models.py:25`，因 `enum-registry.json` **缺 link_type 类别**；与依赖纪律④"一切枚举从 registry 引用/校验"严格不符（已以"清单原文、不造词"就地注记） | registry categories 无 link；test_contracts 以 `LINK_TYPES ⊆ seen` 断言而非 registry | FN-0-04 / 纪律④ | M2 契约 bump 向 enum-registry 增补 link_type 类别，models 改引用（走 FN-A-07 兼容登记） |
| M-M1-003 | MINOR | 编排器 `authenticity`/`duplicate` 支路对桩通道产出未注册 rule_id 标签（`sm2_verify`/`auth_query`/`tax_id_directory`），绕过 `rules_catalog` 注册制与 `_res()` 枚举校验（直接 dict 赋值，不经 `out()`） | orchestrator.py:92/96/100/109-114 vs rules_catalog 20 项不含此三 id | FN-0-07 / FN-3-05 / WP1.6 注册制 | M3 查重/验真服务本体接线时统一经注册制出口产出；当前桩标签宜注明"通道演示标签，非 catalog 规则" |
| M-M1-004 | MINOR | 陈旧文档注记：`audit_chain.py:8` 仍称 trace"属 WP1.7、此处 secrets 随机"，实则 R5 已收口 issuer；`api/cases.py` 文件头 actions 路由位注记已由 R4 落地 | 阅读比对 | WP1.7（文档） | M2 清理注记（非功能） |
| M-M1-005 | 提示 | `GET /v1/cases/{caseId}?view=summary` 对 full 案件返回完整聚合（契约 allOf 约束所迫），R5 §5.3 已透明登记，M2 引入投影列瘦身 | 代码注记 | P02 §3 / FN-A-02 | M2 处理，不阻塞 |

> **BLOCKER：0**；**MAJOR：1**（M-M1-MAJOR-01）；**MINOR：4**；提示 1。

## 9. 结论

**M1 判定：有条件通过（CONDITIONAL PASS）。**

- **通过面**：WP1.1–1.8 全数交付；P02 §4 七条验收标准亲跑全 PASS（⑤带 UTF-8 环境条件）；144 passed / 覆盖率 94% / check_enums 115 逐字 / validate_contracts 31 绿 / check_seeds_vs_ui EXIT=0 / grep 零命中；依赖纪律六项达标；两条强制口径抽查（原值保留、BLOCKED 双人解除）逐句吻合清单文字；Excel Sheet02 15 行诚实回填无虚标；M0 全部挂账（G-M0-001/002/003/006/007/008）闭环确认；代码 TODO 零清单外造词。
- **放行条件（唯一 MAJOR，限期）**：**M-M1-MAJOR-01** —— 状态机 4 号自动边缺低置信守卫，违反 FN-0-06/P00 §5 红线"低置信强制人工、禁自动放行"。**必须在 M3 受理管线将 `auto_flow` 投产之前**（列为 M3 首个工作包）补引擎侧守卫 + 红线回归用例（conf<80 不得自动 RESOLVED），并在修复前于 Excel Sheet02 FN-0-06 行将"待验收"降级为"受阻（M-M1-MAJOR-01）"。M1 无 live 自动管线，缺陷处于潜伏态，故不构成驳回，但**不得带入 M3 管线接线**。
- **MINOR 汇入 backlog**（不阻塞）：M-M1-001（seed 控制台编码，宜 M2 前修）、M-M1-002（link_type 入 registry，M2 契约 bump）、M-M1-003（编排器桩标签注册制，M3）、M-M1-004（陈旧注记清理，M2）、M-M1-005（summary 瘦身，M2）。

### 下一里程碑（M2）放行建议

内核地基稳固，**可放行进入 M2（读路径垂直切片：case-detail + dashboard + login 接线）**。M2 须：① 落地 M-M1-001/002/004/005 四项 MINOR（seed 控制台编码、link_type 入 registry 并改引用、陈旧注记清理、summary 投影瘦身）；② 配置中心保留键 `__sla_targets` 以双下划线前缀混于普通配置项（`seeds/config.json` 实存、`state_machine.claim()` 消费），M2 接线配置面时宜规范化命名并登记；③ M-M1-MAJOR-01 留至 M3 首包，M2 不强制，但 M2 若引入任何自动流转演示，须显式绕开 4 号自动边以免暴露潜伏缺陷。增量评审约定：M-M1-MAJOR-01 修复时仅重跑状态机单测 + 新增红线回归用例，不必全量复评 M1。

---

*评审员独立执行；所有运行结论以本会话实测命令输出为准（环境 Python 3.14.3 / Windows）。报告落 `docs/gate-reports/M1-gate-report.md`。*
