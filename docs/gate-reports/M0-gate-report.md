# M0 门禁评审报告

- **评审日期**：2026-10-25
- **评审会话标识**：P00+P10 · 独立验收评审（M0，与实现会话分离；评审员非实现者，只评审不修复）
- **被评审提交范围**：`invoice-hub/` 当前工作区快照（M0 产物落盘时窗 2026-10-25 18:14–21:04）。**注**：项目根非 git 仓库，P00 §8 的 commit message 规范与工作包提交记录无法核验（登记为环境项 G-M0-007，不阻塞本门禁）
- **评审输入**：P01-M0 提示词全文、实施规划 §1/§2/§3/§4-M0、清单 MD §2（FN-0-01~15）/§3.10（FN-A-01~09）/§5.2/附录 A~D、`docs/gate-reports/M0-self-check.md`、Excel Sheet06/08/09（openpyxl 实读）、`ui-design/` 相关页面口径
- **画面验证报告**：M0 不适用（P10 §1 约定 ui-verification-report 自 M2 起要求，M0 无画面接线，**非阻塞项**）

---

## 1. 交付物盘点（工作包 × 存在性 × 完整性）

| 工作包 | 要求产物 | 存在性 | 完整性判定 |
|---|---|---|---|
| WP0.1 CON 决议复核 | 用户确认记录 → `docs/adr/0004-con-resolutions.md` | ✅ | 五项决议逐条含结论/细则/落点；另载 2 处口径冲突裁决（SPI source 词表、置信度 80–94）；Sheet06 五条状态列已回写（§7 实核） |
| WP0.2 仓库骨架 | 实施规划 §2 全部目录 + 根 README + CLAUDE.md + ADR-0001~0003 | ✅ | contracts/backend(app 四子包+tests)/agent/mcp/web/seeds/docs(adr+gate-reports)/tests(scenarios) 齐备；增补 `tools/`、`contracts/field-alias.md`、`contracts/CHANGELOG.md`、`contracts/routing-config.schema.json` 均为 P01 WP0.3~0.6 明确要求，判定合规；README 含定位/边界/目录/文档树/快速开始占位（✅）；**CLAUDE.md 与 P00 存在 1 行差异（见缺陷 G-M0-002）** |
| WP0.3 枚举注册表 | `enum-registry.json`（Sheet08 115 行机器可读化）+ `tools/check_enums.py` | ✅ | 19 类 / 115 值；附 pattern/color/access/min-max 等机器字段且脚本声明不参与逐字比对（口径透明）；脚本为真实逐行逐字四列比对（评审员审阅源码确认，非摆设） |
| WP0.4 核心 Schema | invoice-schema / invoice-case.schema / field-alias.md + 三演示案件自检 | ✅ | 分区 Core/CN/EU/US/APAC/Customer（x-extension-families，H24/H25 未决处不冻结虚构路径）；evidence 子结构严格 FN-0-05 六要素；items CN8/OS6 口径；别名表含规格 v0.3 §4 全量对照 + Extrinsic cn:* + §6 SPI 归一映射（H25 标注）；三演示案件 full 过 Schema（脚本断言，§2 亲验） |
| WP0.5 接口契约 | openapi.yaml / events.schema.json / mcp-tools.json | ✅ | 详见 §5 抽查 S7~S9 |
| WP0.6 南向/东向契约 | provider-spi / routing-config / adapter-contract / CHANGELOG.md | ✅ | adapter-contract 含 cXML 1.2.040 骨架 + 三条基础映射 + `TODO(H24)`/`TODO(H25)`；CHANGELOG 四条登记（① FROZEN / ② SYNC 页面升域义务 / ③④ COMPAT 预留）+ TODO 附表 |
| WP0.7 种子数据 | seeds/ 13 文件 | ✅ | cases 11（A.1 案件号集合逐一对应，无缺无增）/ providers 6（human-fallback lock=true）/ routing_policy 4 规则+5 兜底+版本 v2026-10-20.3 / taxcodes 10 行 v1.4 / mapping_rules 5+3+2 / batches 9 / audit_events 15（链头 blk#10343）/ alerts 3+3 / kpi 双实例 / config（0.85/±0.06/±S$50/低置信强制人工）/ users_roles 4 用户×7 权限 / rules_catalog 20 / versions 19——数量与内容口径全部与附录 A/B/C、Sheet09 对上 |
| WP0.8 自检脚本 | `tools/validate_contracts.py` | ✅ | A 编译 6 Schema / B openapi lint / C seeds 过 Schema / D 编号与 inline enum↔registry / E 种子交叉——评审员审阅源码确认为真实断言（含"禁止空 Schema 掩盖"防御逻辑） |

**缺件判定：无缺件。** 另核 `docs/gate-reports/M0-self-check.md` 存在（P10 §1 要求的实现自述输入，齐备）。

## 2. 运行证据（评审员亲自运行，不采信自述）

| 命令 | 退出码 | 结果摘要 |
|---|---|---|
| `python tools/check_enums.py` | **0** | `enum-registry v1.0.0 类别 19 / 值 115`；`Sheet08 数据行 115`；`✅ 全 115 行逐行逐字一致` |
| `python tools/validate_contracts.py` | **0** | `✅ 全绿：31 项检查通过`——6 Schema Draft 2020-12 编译；openapi **结构化 lint**（注：本环境无 openapi-spec-validator，走脚本内置离线兜底路径，见缺陷 G-M0-003）；cases 11 案 + routing_policy 过 Schema；编号 pattern（35 案件号/9 批次/18 trace/2 回执/3 SUP）；inline enum↔registry 等式 8 组；MCP 工具名/级别、Webhook 事件一致；种子交叉一致（0121 走已登记白名单） |
| `grep -rn "ariba-mock\|invoice-platform" invoice-hub/` | — | 命中 10 行 / 7 个文件（CLAUDE.md、README、ADR-0003、CHANGELOG ②、adapter-contract 四步说明、self-check、tests/scenarios README），**全部为纪律/历史参考说明性文字**，无代码、无 contracts 路径引用——与自述一致（自述按 7 处计为文件数） |
| `diff` CLAUDE.md ↔ P00 提示词正文 | — | **仅 1 行差异**（收工检查单第 6 条 `contracts/` 变更记录 → `contracts/CHANGELOG.md`），见缺陷 G-M0-002 |
| 空占位核验 | — | `backend/app` 5 个 `__init__.py` 均 **0 字节**；backend/tests、agent、mcp、web、tests/scenarios 仅 README 占位——无任何服务代码 |
| ui-design 只读核验 | — | 12 页 HTML + design-system.md + 映射 MD mtime 全部为 10-21/10-22（早于 M0 工作窗口 10-25），零改动 |
| 旧仓零拷贝（替代检查） | — | 根目录 `ariba-mock/`、`invoice-platform/` 已不存在，归档为 `旧资产.zip`（10-25 17:38，164 条目，含两旧仓）；zip 内文件名与新 `contracts/` **零重叠**；新仓除 2 个工具脚本外无任何代码可比对，脚本注释/风格为新写——判定无拷贝痕迹。**附注**：旧仓由谁归档/删除未经评审会话确认，请用户核实（见 §9 附注） |

## 3. 验收标准逐条判定

### 3.1 P01 §3 六条（提示词标注"门禁评审 P10 依据"）

| # | 标准 | 判定 | 证据 |
|---|---|---|---|
| 1 | check_enums 通过（115 行逐行一致） | **PASS** | 本报告 §2 亲跑 EXIT=0；脚本源码审阅为四列逐字+顺序+总量断言 |
| 2 | validate_contracts 通过（契约可编译、种子全过校验） | **PASS** | §2 亲跑 31 项全绿（openapi lint 为结构化兜底口径，G-M0-003 备忘） |
| 3 | ADR-0001~0004 齐备且与实施规划 §1/§3 可互相追溯 | **PASS** | 四件齐备；0001/0002/0003 逐条对应规划 §1 三行（状态栏均回指"2026-10-22 用户确认，见实施规划 §1"，含背景/备选项/决策/后果四段）；0004 对应规划 §3 五决议（结论逐字一致：0.85/六态唯一+投影+认领子态/UI-API 路径/带域案件号/两键分离）并反向引用规划 §3；Sheet06 备注列指向 ADR-0004 |
| 4 | 仓库结构 = 实施规划 §2；CLAUDE.md = P00 内容 | **结构 PASS / CLAUDE.md 基本达成** | 结构逐目录核对见 §1（增补项均有 P01 出处）；CLAUDE.md 存在 1 行未登记措辞细化 → 缺陷 G-M0-002（MINOR，文案级偏差，语义与 P00/WP0.6 落点一致） |
| 5 | 无任何服务代码（backend/app 仅空 `__init__.py`） | **PASS** | §2 空字节核验；tools/ 两脚本为 P01 WP0.3/0.8 产物（校验工具非服务代码） |
| 6 | 旧仓零引用（仅允许说明性文字） | **PASS** | §2 亲跑 grep，10 行命中全为纪律/历史说明 |

### 3.2 实施规划 §4-M0 验收四条

| # | 标准（规划原文） | 判定 | 证据 |
|---|---|---|---|
| ① | 契约结构自检通过（JSON Schema 可编译、openapi 可 lint） | **PASS**（附口径注记） | 6 Schema 编译全过；openapi 结构化 lint 通过；全量 validator 未在评审环境启用（G-M0-003） |
| ② | enum-registry 与 Sheet08 逐行一致（脚本比对） | **PASS** | 亲跑 115/115 |
| ③ | **seeds 案件数据与 UI 12 页出现的案件字段逐案一致（脚本断言）** | **部分达成 → MAJOR 挂账（G-M0-001，用户裁决采建议 A，见 §10）** | 已达成部分：11 案与 Sheet09/A.1 逐案核对（状态/置信度/金额/Provider/风险标签抽查 0387/0379/0125/0125-workbench 徽章均一致）；页面↔种子不一致项（D8 文件名交叉、D9 0121、D10 税码行数、D5/D6/D7/D11 时点口径）均已登记 `known_page_discrepancies`/自检 §3。**未达成部分**：规划明文要求"脚本断言"，仓库内无 seeds↔ui-design 交叉校验脚本（validate_contracts E 段仅做种子间交叉，不解析页面）；且 D8 属页面侧数据错误，只读纪律下 M0 无法"逐案一致"清零。注：P01 §3 六条（自称门禁依据）未含此项——规划 §4-M0 ③ 与 P01 §3 的口径冲突已由用户裁决（采建议 A：脚本列 M1 首个工作包，交付跑绿时本项补核闭环；Excel Sheet00 已挂账标注） |
| ④ | ADR/CON 决议可追溯 | **PASS** | 同 3.1 #3 |

## 4. 依赖纪律检查（6 项 × 结果）

| 纪律 | 结果 | 证据 |
|---|---|---|
| 1 backend 零 LLM import | **PASS** | backend 下仅 0 字节 `__init__.py`，无 import 可言；grep langgraph/openai/anthropic/llm 全域零命中（tools 脚本除外，仅 stdlib+openpyxl/jsonschema） |
| 2 agent/mcp 不直触 DB | **PASS** | 两目录仅 README 占位，无代码 |
| 3 web 只消费 REST / ui-design 只读 | **PASS** | web/ 仅 README；ui-design mtime 零改动（§2） |
| 4 枚举单一来源 | **PASS** | 契约 inline enum 与 registry 的等式由 validate D 段脚本断言（8 组全过）；mcp-tools/events/case-schema 均显式声明"引用 enum-registry" |
| 5 写路径全过受控框架 | **PASS（契约层）** | M0 无运行写路径；受控五要素已入契约文字：openapi `x-controlled-write`、mcp-tools `write_tools_require_human_confirm_token`+confirm_token/operator 必填+REJECT 备注必填（FN-0-08 ④ 吻合）、adapter 幂等重试防重复建档 |
| 6 ui-design 零改动 / 旧仓零拷贝 | **PASS** | §2 mtime + zip 文件名零重叠 + 无代码可拷贝 |

## 5. 口径抽查记录（11 处深抽，对照清单 MD 原文）

| # | FN 编号 | 规则原文要点 | 实现行为/产物内容 | 判定 |
|---|---|---|---|---|
| S1 | FN-0-02 | 六态名称/中文/色系/语义；6 条流转含触发与附带动作；BLOCKED 解除=复核员+管理员双人会签 | case_status 六值逐字对齐（蓝/橙/绿/红+语义）；state_transition 6 值触发条件与附带动作逐条对齐（含"其余 Checks 不中止""高风险 30 分钟认领""只读取证"）；`BLOCKED→解除` 双人审批会签在案 | ✅ |
| S2 | FN-0-05 | 每字段=值+证据；source 六枚举；evidence{page,bbox,raw_text,rule,model_version,provider}；bbox 允许"—（XML 节点）"与跨源写法 | evidenceEntry required=[field,value,source,confidence,evidence]，evidence 六要素全 required；bbox 类型 array\|string\|null 且 note 载明特殊值；人工修正三规则（manual/1.0/原值保留）写入 description 并引 FN-8-05 | ✅ |
| S3 | FN-0-06 | ≥95 绿 / 80–94 橙 / <80 红强制人工禁自动放行 | confidence_band 三档含 min/max（95/80–94/0–79）；"<80"档 note 原文"强制人工，禁止自动放行"；config.low_confidence_force_human=true 且注记红线不可被配置绕过（P00 §5）；80–94 取清单（design-system 80–95 判笔误，ADR-0004 附#2 裁决） | ✅ |
| S4 | FN-0-07 | 四校验项 supplierMatch/authenticity/duplicate/poMatch；结果四枚举；相互独立；BLOCKED 不中止；每项附 note；模型输出不得写入 checks | checks 四键 required + checkResult{result∈四枚举, note} required；schema description 载明"BLOCKED 不中止/非模型判定"；0387 样例四校验结果与 A.1 风险（AMOUNT_VARIANCE）吻合 | ✅ |
| S5 | FN-0-10 | 事件模型 {t,a,act,d,x,v}；事件码清单 29 项；append-only 链式 SHA-256、blk#、trace 贯穿；组件版本号 | events.schema 六键（x/v 可选，见 G-M0-004）；timeline_event 集合与 MD 29 项**集合全等**（评审员亲跑 diff）；audit_events 15 条含 blk#/hash/trace、链头 blk#10343 与附录 A.5"链头 blk#10343 导出递增"一致；种子 timeline 34/34 事件带 v | ✅（附 G-M0-004） |
| S6 | FN-0-13 + CON-04 | 案件号 INV-{CN\|SG}-2026-NNNN、批次、trace、gm-rcpt-NNNN、SUP-NNNNN、租户、QA、ANNO、SHA-256 摘要 | id_format 10 值全载 + pattern 附加字段；openapi/case-schema/mcp 参数四处 pattern 一致（\d{4} 年份为机器泛化，label 保留 2026 原文）；seed 35 案件号全匹配带域格式；0379 回执 gm-rcpt-1042、0387 回执 gm-rcpt-0931 与附录 A.1/FN-0-13 示例逐字一致 | ✅ |
| S7 | FN-A-01/02/03 | 请求 file{ref,mime_type,sha256}/instance/doc_type_hint?/po_ref?/callback_url?/options{sync_fast_path_only,verify_authenticity}+multipart；同步仅直读快速路径 P95<3s；响应=完整 InvoiceCase；GET cases?view / evidence?field；Webhook 四事件+X-Signature HMAC+X-Event-Id+退避≤8 | openapi 逐字段对齐；200=完整案件聚合、202=caseId+trace+callback、409=幂等命中返回既有案件（两键语义分列 CON-05/06）；webhooks 四事件引用统一信封，blocked/resolved/failed 的 payload 键（blockReason/ruleId/evidenceRef；resolution/operator/actionTrailRef）逐字对齐 FN-A-03 | ✅ |
| S8 | FN-A-04 | 6 工具=4 只读+2 受控写（confirm_token+operator）；OAuth2 client_credentials+双 scope；写工具强制 confirm；AI 禁止静默写 | mcp-tools.json 六工具名/参数与清单逐一对应；scope 绑定、`write_tools_require_human_confirm_token:true`、confirm_token 定义含"人类会话签发/一次性/绑 caseId+action/缺失拒绝并审计"；case.action 注记"BLOCKED 不可批量放行、双人解除不属本工具单动作"（FN-0-08/8-06 吻合）；与 registry.mcp_tool access 一致性脚本断言通过 | ✅ |
| S9 | FN-A-05 / FN-2-13 + ADR-0004 附#1 | SPI 三方法（capabilities/recognize/verify）；ProviderResult=fields[{name,value,confidence,source,bbox,raw_text,model_version}]+meta{provider_id,latency_ms,cost}；source 六枚举归一（pdf_text→xml_direct、vlm→model、verify_api→webhook） | provider-spi.schema.json 三方法+两 Payload+ProviderResult/VerifyResult 齐备；fields 七要素中 required 六项，**bbox 未 required**（与自身 rules 文字"缺一即黑盒"存在松紧张力，G-M0-005）；source 约束六枚举 + source_vocabulary_note + field-alias §6 映射三处一致（裁决落地完整）；VerifyResult 回执 gm-rcpt pattern、FAILED→BLOCKED 红线、超时→NOT_VERIFIED→重试入文，"演示口径模拟通道"标注在位（P00 §6 桩纪律） | ✅（附 G-M0-005） |
| S10 | FN-A-06 + H24/H25 | cXML 1.2.040 骨架（Header 三方 Credential/InvoiceDetailHeader/Total/Tax/OrderReference）；三条基础映射；Extrinsic cn:*；开发流程四步 | adapter-contract 骨架五节点齐备、map-1/2/3 与清单逐条对应（含税负数口径、tax_code_mapping v1.4、缺省 non-PO）；cn_field_carriage=`Extrinsic name="cn:*"` + `TODO(H25) 阻塞级待确认`；四步流程在案（FN-7-10）；CON-06 两层幂等对照承载 | ✅ |
| S11 | FN-0-12 + CON-01/02/03/05 | 版本化资产口径（策略 v2026-10-20.3、配置 v2026-10-21.2、映射表 v1.4、契约 v1 FROZEN）；CON-01 0.85/0.75 历史默认；CON-02 投影+认领子态；CON-05 两键 | routing_policy version=v2026-10-20.3 state=published；taxcodes v1.4 行级版本；config 六项含 0.85（0.75 历史默认注记）/±0.06/±S$50 分设（TODO(CON-12) 在位）；case-schema meta 含 claimed_by/claimed_at/claim_lock_expire_at/doc_hold_pending/document_created_receipt（CON-02/11 决议机器化）；field-alias §7 两键分离对照 | ✅ |

## 6. 画面验证复核

**不适用**：M0 为纯契约/数据/决策冻结，无 UI 接线；P10 §1 规定 `docs/ui-verification-report-M{x}.md` 自 M2 起为评审输入，M0 缺失**不构成阻塞**。本次仅做页面口径**来源性**抽核（S6 回执号、S11 策略版本、0125 风险标签与 workbench 页面 badge 逐字比对等，见 §5），为 M2 逐区块核对建立基线。

## 7. 台账与 TODO 对账

- **Excel Sheet06（openpyxl 实读）**：CON-01~05 收敛状态=**已冻结（M0）**，备注列含 2026-10-25 用户确认与 ADR-0004/落点引用 ✅（P01 §4 要求满足）；CON-06~14=未收敛 ✅。⚠️ **CON-11 行仍为"未收敛"**——但实施规划 §3 注与 ADR-0004 决议二均载明"认领态随 CON-02 一并处理（NEEDS_REVIEW 子态字段）"，且 case-schema 已实装三字段，台账未同步登记该结论 → 缺陷 G-M0-006（MINOR）。
- **Sheet03/04**：M0 无对应 FN 实现行，无需回填（P01 §4 明文），与实况一致。
- **Sheet08/09**：已由 check_enums（08 逐字 115/115）与 seeds 核对（09：11 案/6 Provider/10 税码/15 审计）覆盖。
- **TODO 扫描（亲跑）**：`TODO(H24)×9、TODO(H25)×13、TODO(H29)×1、TODO(H38)×1、TODO(H39)×2、TODO(CON-06/09/12/13/14)各 1~2`——全部落于清单附录 D 与 §5.2 索引内，**无清单外造词 TODO（无口径漂移）**。未标 TODO 的 CON 项核查：CON-07（规格侧 FR 化，责任=规格文档非代码）、CON-08（已随 M0 evidence 契约补齐实质关闭）、CON-10（其本身=H24/H25，已按 H 标注承载并在 adapter 文内点名）——判定合理。CHANGELOG"TODO 未决项登记"附表与实测逐一对上。
- **契约变更登记**：CHANGELOG ①~④ 覆盖 M0 全部冻结与同步义务（issue_date 裁决、SPI 归一、80–94、页面升域、nextAction/invoice_type 兼容预留）；无未登记变更。

## 8. 缺陷清单

| 编号 | 级别 | 描述 | 复现/证据 | 关联 FN | 处置 |
|---|---|---|---|---|---|
| **G-M0-001** | **MAJOR** | 实施规划 §4-M0 验收③ 要求"seeds 与 UI 12 页案件字段逐案一致（**脚本断言**）"未交付专用脚本；数据一致达成部分以人工核对+差异登记（D4~D12、known_page_discrepancies）承载。规划③与 P01 §3 六条（自称"门禁评审依据"）在此项上口径不一致 | 检索 `tools/`、全仓无解析 ui-design 页面常量做交叉断言的脚本；validate_contracts E 段仅种子间交叉 | FN-0-01/CON-B4/实施规划 §4-M0③ | **用户已裁决采建议 A（2026-10-25，见 §10 条目 3）**：`tools/check_seeds_vs_ui.py` 列为 **M1 首个工作包**（解析 12 页 CASES/BATCHES/LOGS/KPI 等 JS 常量与 seeds 逐案交叉断言，D8 类页面既有错误对照 known_page_discrepancies 作已登记豁免输出）；已同步标注 Excel Sheet00「M0 门禁评审挂账」行。该项**交付并跑绿前，M1 其余工作包不得收工**（增量评审仅重跑本项） |
| G-M0-002 | MINOR | `CLAUDE.md` 与 P00 正文仅第 59 行不一致（"契约变更 → `contracts/` 变更记录"细化为 "`contracts/CHANGELOG.md` 变更记录"）；语义与 WP0.6 落点一致但违反验收④"内容 = P00 全文"的字面要求，且自检报告未披露该偏离 | `diff` 输出仅 1 处（本报告 §2） | P01 WP0.2/验收④ | 汇入 backlog：M1 会话二选一——恢复 P00 原文，或在自检/CHANGELOG 补一行偏离登记（建议前者，保持基线严格等式） |
| G-M0-003 | MINOR | 校验工具依赖未落任何清单（openpyxl/jsonschema/referencing/PyYAML 需预装否则脚本以退出码 2 失败；`openapi-spec-validator` 评审环境缺失致 openapi lint 实际走结构化兜底路径，全量规范校验未执行） | validate_contracts B 段输出为"结构化 lint"分支；仓内无 requirements/dev 清单 | FN-A-08/TS-18 | M1 runbook 补 `requirements-dev.txt` 并在全量环境跑一次完整 validator；结果登记 CHANGELOG |
| G-M0-004 | MINOR | `events.schema.json` 中 `v`（组件版本号）为可选，而 FN-0-12 明文"每条时间线事件带 v"；M0 种子覆盖 34/34 但契约允许后续缺省（漂移风险） | schema required=[t,a,act,d]；`x` 允许 null 属页面口径合理、`v` 宜收紧 | FN-0-10/12 | 建议随 M1 状态机契约 bump 将 v 改为 required（或 null 需显式豁免登记）；FN-A-07 兼容变更入 CHANGELOG |
| G-M0-005 | MINOR | `provider-spi.schema.json` 的 `fields[].bbox` 不在 required，与同文件 rules 文字"字段级证据（bbox/raw_text/model_version）必填，缺一即黑盒"存在松紧不一致（XML 直读族应使用"—（XML 节点）"特殊值而非缺键） | schema required=[name,value,confidence,source,raw_text,model_version]，bbox 可缺 | FN-2-13/FN-0-05 | M1 stub Provider 实装前统一：bbox required（允许字符串特殊值/null），契约走兼容登记 |
| G-M0-006 | MINOR | Sheet06 CON-11 行收敛状态仍为"未收敛"，与 ADR-0004 决议二（认领=NEEDS_REVIEW 子态，已冻结）不一致 | Excel 行 26 状态列；对照 ADR-0004 决议二、case-schema meta.claimed_* | CON-11/CON-02 | M1 会话回写 Sheet06：状态改"已随 CON-02 冻结（M0）"+结论备注 |
| G-M0-007 | MINOR（环境） | 项目根无 git 仓库：P00 §8 提交规范、"每工作包一提交"、门禁报告的 commit 区间均无法核验；旧仓 `ariba-mock/`、`invoice-platform/` 已不在原位（归档为 `旧资产.zip`，10-25 17:38） | `git` 不可用；根目录列表 | P00 §8/ADR-0003 | **归档动因已由用户确认（2026-10-25，见 §10）：旧系统本次构建不予考虑，归档为有意处置**——本项就旧仓部分**关闭**；git 缺失部分建议保留：用户择机 `git init` 并以 M0 产物作基线提交 |
| G-M0-008 | MINOR（文档冲突） | 清单 FN-A-01 备注指定机器契约文件 `contracts/recognition.request/response.schema.json`，实现依实施规划 §2 八文件清单将请求/响应内联于 openapi.yaml components（自检 §5.5 已声明该取舍并给出后续拆分路径）——两上游文档不一致 | 清单 §3.10 FN-A-01 备注 vs 实施规划 §2 目录树 vs openapi.yaml components | FN-A-01/FN-A-07 | **已关闭（2026-10-25 用户裁决采建议 A，见 §10）**：清单 MD §3.10 FN-A-01 备注与 Excel Sheet04 F5 已按"M0 冻结口径=内联 openapi components、独立文件需求走 FN-A-07 兼容拆分"修订并附裁决注记 |

**无 BLOCKER**：P01 §3 六条全部实判达成（④含 MINOR 偏离）；两脚本亲跑全绿；纪律六项无违例；红线相关口径（80–94 强制人工、验签失败→BLOCKED、BLOCKED 不可批量放行、confirm_token）在契约层全部落文且无被绕过通道。

## 9. 结论

### **有条件通过**（附 MAJOR 清单与期限）

**理由**：
1. M0 的核心目的——"后续所有里程碑的地基"（契约/枚举/种子/决策四件套）经独立重跑与 11 处深抽，机器可读一致性、口径可追溯性、桩与偏离标注纪律均达标；实现自述的每一条"通过"均可被本次独立证据支撑。
2. 唯一未闭环项 G-M0-001 属**验收方法缺件**（脚本断言未交付）而非数据本身不一致（逐案实核通过），且根源含规划/P01 文档口径冲突，按 P10 §3 定级 MAJOR 而非 BLOCKER。

**放行条件（用户已裁决采建议 A · 2026-10-25）**：
- G-M0-001：`tools/check_seeds_vs_ui.py` 作为 **M1 首个工作包**交付并跑绿（Excel Sheet00 已挂账标注）；交付前 M1 其余工作包不得收工。规划 §4-M0 验收③ 在该脚本交付时视为补核闭环。

**MINOR 处置**：G-M0-002~006 汇入 backlog，建议随 M1 收工检查单顺带关闭（002/006 为文字级，003 为环境项，004/005 为契约收紧随 M1 版本 bump）；G-M0-007（旧仓归档部分）与 G-M0-008 已随用户裁决关闭（见 §10）。

**下一里程碑（M1 · FN-0 平台内核）放行建议**：可开工。M1 直接消费面（enum-registry/invoice-case.schema/events.schema/state_transition/config/cases.json）已冻结且校验常绿；开工会话注意四点：**⓪ 首个工作包=G-M0-001 挂账项 `tools/check_seeds_vs_ui.py`（裁决 A，交付跑绿后其余工作包方可收工）**；① 状态机实现须逐条消费 state_transition 六值（勿在代码内重写触发条件）；② nextAction.type 定型后按 CHANGELOG ③ 走兼容登记入 registry；③ seed 装载的三演示案件 detail_level=full 为 M1 契约测试锚点，勿改种子。

---

## 10. 裁决增补（2026-10-25 用户回复，评审会话记录）

| # | 用户裁决 | 处置 | 状态 |
|---|---|---|---|
| 1 | **G-M0-007**：`ariba-mock/`、`invoice-platform/` 为旧系统工程，本次构建基于新的产品定位与蓝图文档重新建设，**不予考虑**，已归档（`旧资产.zip`）为有意处置、暂时废弃 | 归档疑点解除，与 ADR-0003"旧仓只读不复用"纪律一致（物理归档不改变纪律口径）；`git init` 基线提交建议保留供用户择机执行 | 关闭（git 部分转 runbook 备忘） |
| 2 | **G-M0-008**：按评审建议 A 执行——修订清单 FN-A-01 备注为"请求/响应内联 `contracts/openapi.yaml` components"口径 | 已落实三处：① 清单 MD §3.10 FN-A-01 备注列修订并附裁决注记；② Excel Sheet04 F5 同步修订（写后复核 Sheet06 状态列与 Sheet08 115 行无损）；③ 本报告 §8 缺陷行关闭。契约本身无变更，无需 CHANGELOG 登记 | 关闭 |
| 3 | **G-M0-001**（规划验收③ vs P01 六条口径冲突） | 用户裁决采**建议 A**（2026-10-25）：脚本列为 M1 首个工作包；已同步标注 Excel Sheet00「M0 门禁评审挂账」行，本报告 §3.2③/§8/§9 随之更新 | 挂账转 M1（M0 结论维持**有条件通过**，条件唯一且路径明确） |

---
*评审员：独立验收会话（P00+P10）· 本报告由亲跑命令与逐文件取证生成，全部证据可复现。增补 §10 记录 2026-10-25 用户裁决。*
