# M3 自检报告 · 会话（P00+P04 · WP3.1–WP3.2 受理流水线 + 通道与批次）

> 执行会话：P00+P04 · 范围经用户确认 = **WP3.1（五步受理流水线）+ WP3.2（通道与批次管理）**，WP3.3 合规服务及之后工作包**不在本会话**（用户指令「只执行 WP3.1–3.2」）。前置：M2 门禁通过（P09 修复复验全绿，commits 至 bda4e54）。
> 提交序：`16a6423` 契约 v1.2.0 增补 → `08942b0` WP3.1 流水线 → `184fc00` WP3.2 通道与批次 → `f61c01e` WP3.3 合规服务（会话二，含 §10 走查后的 runtime 重置复验；本文件收工节随 WP3.3 收工提交入账）。

---

## 1. 口径裁决与契约变更记录（动工前复述经用户确认「按建议继续」）

| # | 裁决点 | 结论 | 登记 |
|---|---|---|---|
| 1 | 受理域枚举缺位 | enum-registry **v1.1.0→v1.2.0** 兼容增补 5 类 22 值：`intake_channel`（四值逐字=seeds/页面词汇）/`carrier_route`（FN-2-14 recognition_path 子集，L3 留 M4）/`pipeline_step_status`/`intake_file_disposition`（机器态）/`non_invoice_doc_type`（含 Order Response，FN-1-04 原文）；Excel Sheet08 同步追加 22 行（120→142），check_enums 25 类/142 值通过 | CHANGELOG ⑧ |
| 2 | 受理提交受控定性 | FN-1-08 门户上传=业务写 → governed_commands 新动作 **`intake`**（五要素全序复用框架）；权限位「受理提交」= RBAC 矩阵第 8 位（FN-9-02 明示「基线，可版本化变更」；管理员/运营=1，复核员/审计只读=0；platform-admin 页面 7 位展示口径属 ui-design 只读，web 同步留 M5 接线注记） | CHANGELOG ⑧「随登记裁决」；users_roles v1.1.0 |
| 3 | API 通道（recognize）受控形态 | 机器提交以 **AppKey+HMAC 签名（演示桩）+ SHA-256 入审计 + 两键幂等** 承载要素①⑤；risk-challenge/本人勾选不适用机器通道（MCP invoices.recognize 的 confirm_token 全序属 M5/FN-A-04）。openapi v1 FROZEN **零改动**（新内部端点不入北向面，同 M2 ⑦ 口径） | recognize.py 头注；CHANGELOG ⑧ |
| 4 | 案件派生边界 | 派生案件 **detail_level=full、status=RECOGNIZED**；四槽位 checks 以 NOT_VERIFIED 占位（note 明示「合规服务 WP3.3 未激活」，经 orchestrator.apply_results 唯一写入口写入）；**本会话不接自动流转/红线判定**（auto_flow 留 WP3.3 接线）；低置信无自动放行出口以 test_recognized_case_has_no_auto_release 常驻补强 | 代码头注；§4 红线回归 |
| 5 | 直读抽取深度 | 流水线⑤只做受理派生所需关键字段（票号/日期/购销方/三金额/行项目）；完整 23 字段+票面 Schema 校验归 FN-2-01（M4）；OFD=zip 内嵌 XML 演示口径、PDF 文本层=流解压+正则演示口径，不可行即 L4 人工分拣**不造数** | intake_parsers.py 头注 |
| 6 | 断点续跑语义 | 步骤级 FileStep 持久化（步边界提交=检查点）；resume 跳过 DONE/SKIPPED；**识别不重跑**以 EgressLog 外发计数断言（stub OCR 仅⑤执行一次）；摘要幂=intake_ledger 唯一键 (sha256, target_doc_ref缺省"") | S-M3-INT-04 |
| 7 | 批次发号碰撞 | BT-YYYYMMDD-NNN 不含实例段，CN/OS 分域计数同日可同号 → create_batch 增加全局唯一检查+域内重发（≤16 次）防御 | intake_pipeline._next_batch |
| 8 | KPI 口径 | 页面锚点（540/23/7/98.7/1.8s/P95 3.6s/分时柱）= channels.json seed 权威源（M2 快照源纪律同源）；runtime 段对运行期批次真算（渠道计数/过滤细分/待分拣含加密/成功率/均值+P95 时延 accepted→digest/分时增量合并） | intake_kpi.py 头注 |
| 9 | 成功率分子口径 | 非发票退回（FILTERED）计入「受理处置成功」——FN-1-09 原文=受理登记成功/接入总量，退回是登记成功的处置结论而非失败；仅 FAILED 计失败（RI-M3-004） | intake_kpi.compute 注释 |
| 10 | 无案件时的 API 语义 | recognize 遇 非发票/人工分拣 **返回 400 Error{code=E_NON_INVOICE\|E_MANUAL_SORT}**——AcceptedResponse 契约要求合法 caseId，不可伪造空串（S-M3-02 类场景由 WP3.3 查重事件另行承载） | recognize.handle |

**桩纪律（P00 §6）全清单**：邮箱=本地信箱目录 15 分钟 Job 手动触发等效；DOX=目录投递（参与方核对/信封校验真实执行、回执模拟）；Webhook=outbox 落盘即 delivered；签名/AppKey/KMS=演示桩（TODO(FN-9-10)×3）；OCR=M4 前 stub Provider（合成值显式标注 source=ocr）；对象存储=本地内容寻址目录（ADR-0002）。

## 2. 交付清单（按提交）

| 提交 | 工作包 | 内容 |
|---|---|---|
| `16a6423` | 契约 v1.2.0 | enum-registry 5 类 22 值 + Sheet08 22 行 + check_enums（25 类/142 值）+ seeds/channels.json（渠道配置/KPI 锚点/受理规则 v2026-10-20.2 载荷）+ users_roles 第 8 位 + rules_catalog v1.1.0（非发票过滤/载体检测分流两条机器条款，附录 C 冻结 20 条逐字保留）+ seed_loader channels 段（ConfigItem channel:* + AssetRevision channel_config/intake_rules + SeedMeta intake_kpi_baseline）+ 陈旧断言×3（enum 版本/配置项 12/规则 22） |
| `08942b0` | WP3.1 | object_store（内容寻址+可测目录）/intake_parsers（魔数探测/EInvoice/UBL 极简/PDF 文本层）/rules 两规则实装/intake_pipeline 五步驱动+FileStep+IntakeLedger+RequestIdLedger+EgressLog+案件派生（发号/证据/占位 checks/时间线+审计双写）/resume_batch+retry_file_failed_steps/单测 12 项 |
| `184fc00` | WP3.2 | channels_ops（渠道读/掩码、签名校验、限流、幂等台账、Webhook outbox、**poll_mailbox/poll_dox 桩**）/recognize（200/202/400/401/409/重放，契约形态）/batch_ops/intake_kpi/api/intake（recognize+上传全序+批次+KPI+渠道+规则徽章+Job 端点）/governed intake 动作+受理内核/actions.py 面收敛/main 挂载 0.4.0/hub 命令×3+Makefile×3/pyproject（python-multipart+marker）/RUNBOOK §1/4/5.1/7/8/9/10/场景 5 条+README 台账/测试 30 项 |
| `f61c01e` | WP3.3（会话二） | 合规服务六件套（sm2_service/verify_channel/tax_directory/dedup_service/fusion_service/compliance_service）+流水线⑤合规链接线+占位 checks 退役；seeds：config +3 键（版本保持）、tax_directory.json；models +VerifyCache；依赖 +gmssl（uv.lock 47）；测试：专项 9+场景 S-M3-CMP-02/03+存量预期更新（W7）；RUNBOOK §1/§7/§10 刷新；CHANGELOG ⑨；详见 §8~§11 |

## 3. P04 验收标准判定（本会话范围项）

| # | 标准 | 判定 | 证据 |
|---|---|---|---|
| 1 | S-M3-01~05 一键重放 `make test-e2e` | **部分通过**：受理侧 5 场景 S-M3-INT-01~05 全绿（`pytest -m scenario` 5 passed）；P04 定义的 S-M3-01~05 全链五场景依赖 WP3.3/3.4 合规与工作台，属 WP3.6 后续会话（README 台账标 ⏳） | test_scenarios_m3_intake.py；tests/scenarios/README.md |
| 2 | 受理链路真实性 | **通过**：现场造新 XML（seeds 外，宁波/佛山/苏州供应商）经上传 API/recognize/邮箱 Job 三入口走全链生成新案件号（INV-CN-2026-0388 续发、OS 域 0126 续发）；直读路径零外发断言（EgressLog=0）+OCR 路由恰 1 条对照 | S-M3-INT-01/02；RUNBOOK §5.1 实机走查（§6） |
| 3 | 断点续跑 | **通过**：中断（fail_after_step 模拟 kill）→resume 仅续做未完成步；识别不重跑=外发调用计数断言=1；批次中断不重复受理（台账唯一键+ledger case 回填） | S-M3-INT-03/04；test_intake_pipeline 两项中断续跑测 |
| 4 | 三页接线一致 | **本会话不适用**（WP3.5 接线；本会话交付数据面与交互全序 API） | — |
| 5 | 审计链 | **通过**：全部场景跑完后 CN/OS/PLATFORM 三域 verify_chain ok；受理事件（CHANNEL_RECEIVED/CARRIER_ROUTED/XML_PARSED/OCR_RECOGNIZED/INBOUND_ACCEPTED）+受控命令块+渠道配置 POLICY_PUBLISHED 均入链；trace 贯穿（案件 meta↔块 trace 4 块对齐） | S-M3-INT-01；test_channel_config_publish_controlled |
| 6 | 红线回归 | **通过（范围口径）**：派生案件（含 stub 低置信 82<85 阈值）evaluate/auto_flow 无 →RESOLVED 自动边、本会话无任何放行写入口（case 动作端点未触）；占位 checks 全 NOT_VERIFIED 不伪装结论 | test_recognized_case_has_no_auto_release |
| 7 | Excel Sheet03 FN-1 全 11 行回填 | **完成**（§7） | xlsx 已写 |

## 4. 关键实现注记

- **步骤级状态**：`file_steps`（batch_id,file_seq,step_no 唯一）每步 PENDING→RUNNING→DONE/FAILED，detail_raw 存规则命中/分流/摘要/案件号；批次状态机 受理中→识别中→已完成/部分异常 由 `recompute_batch` 归并推导（batch_status 写入即经别名校验）。
- **两键幂等分离（CON-05/06）**：传输键 `request_id_ledger`（X-Request-Id，TTL=渠道配置幂等键有效期，重放返回首发形态）；业务键 `intake_ledger`（sha256+target_doc_ref 唯一约束，缺省目标以空串参与）。
- **外发台账（FN-5-08 演示承载）**：`egress_log` 每外发一行（provider_id/purpose/payload_digest/bytes_out/note）；直读=零、OCR stub=1、Webhook outbox=1 均为断言对象；「数据最小外发」注记在渠道卡/流水线文案与代码三处同源。
- **受控受理全序实测**：缺 token→428 E_RISK_NOT_SHOWN；换清单字节→428 E_CONFIRM_INVALID（scope=name:size 摘要绑定）；无勾选→422；复核员提交→403（受理提交位缺失）；重复提交→409 指认既有案件。
- **配置发布联动**：channel:* 键经既有 /v1/config actions publish → versioning 资产域路由 channel_config（v2026-10-20.1 基线→发布 v{日}.{序}、diff、POLICY_PUBLISHED 入链、ConfigItem 同步生效、读取端 config_version 联动）。
- **APP_VERSION 0.4.0-m3-wp3.1-3.2**；pyproject 版本同步；uv.lock 含 python-multipart（45 包）。

## 5. P00 §7 收工检查单

- [x] **全部测试通过**：`pytest` **213 passed**（171 基线 + 12 流水线单测 + 25 API 测 + 5 场景）；`pytest -m scenario` 5 passed；`make test-e2e` 一键重放；smoke 10/10 PASS（v0.4.0 运行态实测）。
- [x] **枚举一致性**：check_enums **142/142** 逐行逐字（v1.2.0，25 类）；validate_contracts、check_seeds_vs_ui（41 组，EXIT=0）全绿；运行期渠道/载体/步骤态/处置/非发票类型写入即 registry 校验。
- [x] **seed 一致性**：`make seed` 幂等重建 **22 类资产/233 行**；test_rebuild_twice_identical 通过；channels 段装载即校验（intake_channel/batch_status/编号 pattern）；seed 库↔seeds 逐字段断言保持（test_case_repository 不受新列影响）。
- [x] **依赖纪律自查**：backend 零大模型引用（test_dependency_discipline 含新文件全量扫描；RI-M3-001/005 两处命名/类型修正）；agent/mcp/**web 零改动**（本会话未做接线）；写路径全经受控框架（intake 动作/channel publish 复用既有 risk-challenge→execute 全序；流水线内部仅新增受理写，无旁路 UPDATE）；ui-design/ 只读零改动。
- [x] **Excel Sheet03/04 回填**：FN-1-01~11 **十一行=待验收**（01/04 桩触发方式、03/08 受控全序、05/07 流水线与断点续跑、09 KPI 口径、10 版本徽章、11 发布链复用逐项括注【M3 WP3.1/3.2】）；Sheet04 **FN-A-01=待验收**（recognize 契约面运行期实现注记）；Sheet08 追加 22 行与 CHANGELOG ⑧ 一致。
- [x] **文档回写**：contracts/CHANGELOG **⑧（COMPAT v1.2.0）**；seeds 版本注记（users_roles v1.1.0 / rules_catalog v1.1.0 / channels v1.0.0）；RUNBOOK §1/§4/§5+§5.1/§7/§8/§9/§10 刷新；run-issues **RI-M3-001~007**（全部已闭）；无新 ADR（裁决登记 CHANGELOG ⑧+本报告 §1，属实现口径非架构级）。

## 6. RUNBOOK 实机走查记录（§5.1 通道桩手动触发 · 2026-10-27 v0.4.0）

```text
hub.py seed → 22 类资产；hub.py run → smoke 10/10 PASS
hub.py intake:demo-drop（信箱 1 封 2 附件；DOX 2+1 件）
POST /v1/intake/jobs/mailbox:poll → BT-20261027-001 files=2 已完成
    · 数电票_青岛海纳_24442000009991.xml ACCEPTED → INV-CN-2026-0388（五步全 DONE）
    · 框架合同_青岛海纳_HT-2026-0918.xml FILTERED（合同）· steps 3/4/5 SKIPPED · outbox 退回通知在位
POST /v1/intake/jobs/dox:poll     → BT-20261027-002 files=2 已完成
    · SingaporeComponents_INV-88031.xml（UBL）→ INV-SG-2026-0126（OS 发号域续发）
    · OR-confirm-88031.json（Order Response）FILTERED · 已退回注记
GET /v1/cases/INV-CN-2026-0388 → RECOGNIZED · provider=XML 直读（免 Provider）· trace 贯穿 · 时间线四事件序
GET /v1/intake/kpi → runtime files_in=4 / merged 544 / 过滤细分含 Order Response / 加密计数 0
GET /v1/intake/rules/version → 受理规则版本 v2026-10-20.2 · 已发布
GET /v1/intake/channels → 4 渠道 · 密钥泄漏检查通过（掩码）
```
走查后已 `hub.py seed` 恢复初始演示态并清理 runtime 通道目录残留（对象库/信箱/DOX/outbox）。
注：RI-M3-007 环境项——走查前 8000 端口被 M2 会话遗留进程（v0.3.0）占用导致 404/静默 bind 失败，taskkill 后复验；走查以 v0.4.0 为准。

## 7. 遗留与后续会话建议

1. **WP3.3 合规服务**是下一块多米诺：查重池（rules.dedup 注记 pool_keys 接线位）/SM2 验签/查验超时重试（workers/retry 既有钩子）/多源融合/勾稽实跑——届时把占位 checks 经 orchestrator 真跑覆盖，auto_flow 在⑤后接线，S-M3-01/02/03 场景补全。
2. **recognize 真异步**：现同步驱动 stub（P95<3s 语义演示）；真实后台任务+回调重试消费者随 M4 Provider 编排接线。
3. web 三页接线（WP3.5）执行 P09 画面验证时，KPI 条/渠道卡/批次列表/规则徽章数据端点已就绪（§5.1 走查即其口径基准）。
4. 平台渠道差异：DOX 非发票在传输层退回（信封 document_type），仍入批次文件行留痕（FN-1-06 过滤计数同源）——P09 验证按此口径核对。

---

# 续 · WP3.3 合规服务（P04 · SM2/查验/名录/查重/融合/勾稽，2026-10-27 会话二）

> 范围经用户确认 = **仅 WP3.3**（WP3.4 工作台及之后不实施）。动工前复述经确认。前置：WP3.1/3.2 已交付（`16a6423`/`08942b0`/`184fc00`）。

## 8. WP3.3 口径裁决与实现注记

| # | 裁决点 | 结论 | 登记 |
|---|---|---|---|
| W1 | SM2「算法真实、证书链模拟」落地 | 依赖 **gmssl**（纯 Python SM2+SM3，无 FFI，符合 ADR-0002 零外部强依赖）；演示 CA=仓内固定密钥对+序列（正式证书链管理 FR-L1-05 阶段一 + TODO(FN-9-10)）；**确定性签名 k**（内容摘要派生）保证同文同签→摘要幂等断言成立（RI-M3-008）；PASS/FAILED 均发 `gm-rcpt-*` 回执，落 `runtime/gm-receipts/` + `meta.sm2` + 时间线 + 审计块四处随案归档 | CHANGELOG ⑨；sm2_service.py 头注 |
| W2 | 授权查验与验签的关系 | CN 链=SM2 验签（原件可信性）**+**授权查验（真伪）两事实合并写 authenticity 一槽（note 合叙，0387 案口径）；验签 FAILED 短路红线、不再外呼查验（FN-0-09 模型/渠道不得互翻）；查验模式=config 三态 pass/timeout/off（演示桩，运行期可注入） | compliance_service；verify_channel 头注 |
| W3 | 「识别不重跑」断言载体 | 三计数：SM2 回执文件数、`EgressLog(purpose=recognize)` 数、查验通道调用数（`verify_channel.calls()` 演示台账）；重试执行器 `run_due_retries` 只重发查验（+1 查验外发），前两者恒定 | test_verify_timeout_retry_without_rerun |
| W4 | 查重相似度边界语义 | **sim≥阈值含等于判命中**（与 tolerance_check「恰等容差内」同口径）；模糊命中附加条件=金额全等（键含价税合计）；默认阈值 1.0=仅硬命中——行为与 CON-05「重复票」定义不冲突，调低阈值属配置变更（受控发布面可改）；池=同实例非 BLOCKED 案件（**不入发票池**结构性达成，断言正向） | dedup_service；FN-5-04 台账行 |
| W5 | 融合最小实现边界 | 仅 XML×OCR-stub 两源关键金额字段比对；一致=互证标注+OCR 证据行；冲突=降级(policy.degrade_to)+双方证据留存+auto_flow(conflict)→NEEDS_REVIEW；采信方向=priority 首元素（用例实证反转）；**不静默取舍**。多版式/二维码合并与融合规则版本化 UI 属 M4 | fusion_service 头注 |
| W6 | 无案件的重复受控定性 | 同文件重提=摘要幂等 409（WP3.1 既有）；**异字节同票面**=合规链查重红线 BLOCKED（本会话）——两类留痕分离且互不替代，测试双断言 | test_dedup_cn_two_key / S-M3-CMP-02 |
| W7 | 占位 checks 退役 | WP3.1 的 NOT_VERIFIED 占位随合规接线**移除**（真实四槽位由 apply_results 首写）；受影响的 12 项存量预期同步更新（含「零外发」限定为 purpose=recognize——授权查验必要外发单列 purpose=verify，口径变更登记于此避免误读） | §9 检查单 |
| W8 | 名录数据 | 演示数据源 `seeds/tax_directory.json`（5 条，入 SeedMeta）；OS 案件无统一验签体系→名录命中即 authenticity 依据并明示（FN-5-03 原文）；UEN 格式不符但名录命中的组合如实呈现（fmt ✗ + HIT） | CHANGELOG ⑨ |

## 9. WP3.3 收工检查单（会话二）

- [x] **全部测试通过**：`pytest` **224 passed**（213 基线 + 9 合规专项 + 2 新场景 S-M3-CMP-02/03）；`pytest -m scenario` **7 passed**；三校验全绿（142 枚举/40 契约/41 交叉组）。
- [x] **P04 指定完成条件逐项**：①SM2 FAILED→authenticity FAILED→BLOCKED 红线链+**失败回执归档断言**（回执文件存在+result=FAILED+doc_hold_pending+告警+链完整）；②超时→NOT_VERIFIED→单独排定重试+**识别不重跑调用计数**（W3 三计数）；③CON-05 **两套业务键构造断言**（CN `|no|gross` 空代码段型 / OS `no|gross|supplier` 型）+**相似度阈值边界三用例**（0.9 恰等命中/0.8 不命中/异额不触发+P95 200ms 内）+命中→DEDUP_CHECK/DEDUP_BLOCKED+**不入池断言**；④多源冲突（0381 口径）→OCR_CROSS_CHECK_CONFLICT+降级 82+NEEDS_REVIEW+**采信规则配置化**（priority 反转用例）+一致互证路径；勾稽实跑超容差转人工。
- [x] **枚举一致性**：零新增枚举（事件码 30 码全复用；alert_level 引用 code）；check_enums 142/142 保持。
- [x] **seed 一致性**：`make seed` 幂等（新增 tax_directory 装载段+config items 12→15 项断言更新）；check_seeds_vs_ui 41 组通过；seeds/config.json 版本号**保持 v2026-10-21.2**（避免 test_versioning/页面耦合断裂，新键注记 CHANGELOG ⑨）。
- [x] **依赖纪律**：backend 零 LLM（grep+门禁测）；门禁有效拦截并修复一处散落 `BLOCKED` 字面量（RI-M3-009）；agent/mcp/web 零改动；checks/status 写入全部经 orchestrator/state_machine 唯一通道（合规服务不直写投影）；名录/通道/CA 桩均注记「演示口径」。
- [x] **台账回填**：Sheet03 **FN-5-01~05 + FN-4-02/03 七行=待验收**（逐项括注【M3 WP3.3】与用例指针）；Sheet08/04 无新增改动。
- [x] **文档回写**：CHANGELOG **⑨（COMPAT 依赖与配置基线，契约文件零改动）**；run-issues **RI-M3-008~010**（已闭）；RUNBOOK 走查记录§6 追加；ADR 无新增（依赖选型注记随 CHANGELOG）。

## 10. WP3.3 实机走查记录（v0.4.1 · HTTP 链）

```text
hub.py intake:demo-drop → mailbox:poll → BT-…：数电票_青岛海纳 ACCEPTED
GET /v1/cases/INV-CN-2026-0388 → checks：authenticity PASSED（SM2 PASS+查验 pass 合叙）/
    duplicate PASSED（池无命中）/ supplierMatch、poMatch 如实 NOT_VERIFIED
meta.sm2 = {ok:true, receipt_no:"gm-rcpt-1043"} · runtime/gm-receipts/gm-rcpt-1043.json 在档（seed 1042 续发）
时间线：… INBOUND_ACCEPTED → SM2_VERIFY → DEDUP_CHECK(+PO) · 三域链 verify ok
二次异字节同票面件上传 → INV-CN-2026-0389 BLOCKED + DEDUP_BLOCKED + 批次行 bad；
红线告警（展示级 danger/分发级 P0·红线 双轨）经 GET /v1/alerts 读侧可消费（RI-M3-011 回归点）
批量放行混入 BLOCKED → skipped 列因「不可批量放行」processed=0；解除缺会签 → 409
篡改件（签名后改金额）→ SM2_VERIFY_FAILED + 失败回执 FAILED 在档 + doc_hold_pending
```
走查后 `hub.py clean && seed` + 清 runtime 通道/回执目录，恢复初始演示态（回执文件为运行态产物，seed 基线不含）。

## 11. 遗留与后续（更新）

1. **WP3.4/3.5**：工作台队列/受控 Action 接线与三页写路径（P09 画面验证范围含本会话新增的 timeline 合规事件与 SM2 卡数据面）。
2. **SM2 卡数据面就绪**：case-detail 的 meta.sm2/回执号/时间线事件已真实产生（原为 seed 静态）——WP3.5 接线直接消费。
3. 红线告警「不可停用+关闭拦截留痕」与分发渠道 = FN-9-08/M5；`run_due_retries` 接入真实调度（定时触发）属 FN-9-07 队列面板。
4. S-M3-01（放行→RESOLVED 全链留痕）尚缺工作台放行入口（WP3.4），场景台账已标 🔄。

---

*自检结论：**WP3.1+WP3.2+WP3.3 验收标准（各会话范围）全部达成**；M3 门禁整体验收待 WP3.4~3.6 完成后按 P04 §3 七项执行（含 workbench/case-detail 画面验证与 S-M3-01~05 全量场景）。*
