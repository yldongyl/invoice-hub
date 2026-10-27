# M3 自检报告 · 会话（P00+P04 · WP3.1–WP3.2 受理流水线 + 通道与批次）

> 执行会话：P00+P04 · 范围经用户确认 = **WP3.1（五步受理流水线）+ WP3.2（通道与批次管理）**，WP3.3 合规服务及之后工作包**不在本会话**（用户指令「只执行 WP3.1–3.2」）。前置：M2 门禁通过（P09 修复复验全绿，commits 至 bda4e54）。
> 提交序：`16a6423` 契约 v1.2.0 增补 → `08942b0` WP3.1 流水线 → `184fc00` WP3.2 通道与批次（含 §6 走查后的 runtime 重置复验）。

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

*自检结论：**WP3.1+WP3.2 验收标准（本会话范围）全部达成**；M3 门禁整体验收待 WP3.3~3.6 完成后按 P04 §3 七项执行。*
