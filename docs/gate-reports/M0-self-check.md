# M0 自检报告（P01 §3 验收标准逐项 · 2026-10-25）

> 执行会话：P00+P01 · M0 契约与决策冻结。WP0.1 人工确认闸门已通过（用户逐项确认五项决议，另裁决 SPI source 冲突，记录于 `docs/adr/0004-con-resolutions.md`）。

## 1. 验收标准逐项结果

| # | 门禁 | 结果 | 证据 |
|---|---|---|---|
| ① | `python tools/check_enums.py`：enum-registry ↔ Sheet08 逐行一致 | **通过** | 19 类 / **115 值**逐字一致（code/label/color_raw/note 四列），类别顺序一致 |
| ② | `python tools/validate_contracts.py`：契约可编译、seeds 全过校验 | **通过（31 项全绿）** | 6 Schema 编译（Draft 2020-12）；openapi 结构化 lint（内部/外部 $ref 可解析、operationId 唯一、webhooks 齐备）；cases 11 案 + routing_policy 过 Schema；编号 pattern、inline enum↔registry、MCP 工具/级别、Webhook 事件一致性全过 |
| ③ | `docs/adr/0001~0004` 齐备且可追溯 | **通过** | 0001/0002/0003 对应实施规划 §1 三条 ADR（背景/备选项/决策/后果）；0004 对应 §3 CON 决议 + 用户确认记录 |
| ④ | 仓库结构 = 实施规划 §2 | **通过** | contracts/backend(app+tests)/agent/mcp/web/seeds/docs/tests(+scenarios) 齐备；增补 `tools/`（P01 WP0.3/0.8 明确要求）与 contracts/ 内 `field-alias.md`、`CHANGELOG.md`（P01 WP0.4/0.6 要求）；backend/app 四子目录齐 |
| ⑤ | 无任何服务代码 | **通过** | backend/app 仅 5 个空 `__init__.py`；tools/ 两脚本为校验工具（P01 产物，非服务代码）；agent/mcp/web/tests/backend/tests 为 README 占位 |
| ⑥ | 旧仓零引用 | **通过** | `grep -r "ariba-mock\|invoice-platform" invoice-hub/` 命中 7 处，全部为「历史参考/纪律说明」性文字（CLAUDE.md/README/ADR-0003/CHANGELOG ②/adapter-contract 沙箱联调四步说明），无代码、无路径引用 |

## 2. WP0.1 确认结果（写入 ADR-0004）

- CON-01（阈值 0.85）/ CON-02（六态唯一 + 建档两态投影 + CON-11 认领子态）/ CON-03（UI/API 路径为准 + 别名表 + Extrinsic cn:* TODO(H25)）/ CON-04（INV-{CN|SG}-2026-NNNN 带域）/ CON-05（两键分离）——**五项全部按建议确认冻结**。
- 冲突裁决：SPI source 词表 → 六枚举为准 + 归一映射（pdf_text→xml_direct、vlm→model、verify_api→webhook），落 `provider-spi.schema.json` + `field-alias.md §6`。

## 3. 阅读现场发现的口径差异登记（事实 vs 推断）

**字面事实（文档原文）**：

| # | 差异 | 两侧原文出处 | M0 处置 |
|---|---|---|---|
| D1 | SPI source 五值注释 vs 六枚举 | api-portal.html §③ ProviderResult 注释 vs 清单 FN-0-05/Sheet08 行 17–22 | 用户裁决六枚举+归一映射（ADR-0004 附#1） |
| D2 | 置信度中档上界 80–95% vs 80–94% | design-system.md §3 vs 清单 FN-0-06/Sheet08 行 32 | 按清单取 80–94（优先级 2>5；页面徽章代码实为 ≥95/≥80 分档，与清单一致） |
| D3 | `header.invoice_date` vs `header.issue_date` | 清单 FN-0-03 行文 vs case-detail.html 页面字段路径/规格旧版 | 按 CON-03「UI/API 为准」落 issue_date（CHANGELOG ①-1 登记） |
| D4 | Sheet09 A.1 表头「10 案件」实为 11 行 | Excel/MD 附录 A.1（0387/0386/0385/0384/0383/0381/0379 + 0125/0124/0123/0122）vs 实施规划 §4-M0「案件 11」 | 按 11 案装载（与实施规划、P01 一致）；MD 表头计数字差留待清单修订 |
| D5 | 路由策略 v2026-10-20.3（provider 页 Header/P01 指定）vs 审计页 POLICY_PUBLISHED .3→.4 | provider-orchestration.html line 108 vs audit-reports.html LOGS blk#10331 | 种子取 .3（P01 口径）；.4 事件逐字保留于 audit_events（时点差异注记） |
| D6 | 0387 状态：cases 基线 NEEDS_REVIEW（A.1/case-detail）vs 审计页 10-21 09:42 放行→RESOLVED | Sheet09 A.1 vs LOGS blk#10342/10343 | cases.json 保持 A.1 基线；审计记录为更晚时点链上事实，两存并注记 |
| D7 | 0379 快照：批次页 RECOGNIZED/99（BT-20261020-004）vs 主数据集 BLOCKED/94 | invoice-intake BATCHES vs Sheet09 A.1 | cases 取终态；batches 保留受理时点快照（字段名 status_snapshot 显性区分） |
| D8 | intake 文件名供应商与 A.1 交叉：BT-004「恒信电子_…_0383.xml」、BT-005「数电票_云栖信息_0381.xml」vs A.1（0383=杭州云栖、0381=苏州恒信） | invoice-intake BATCHES vs Sheet09 A.1 | 两侧原值逐字保留于 batches.json `known_page_discrepancies`；案件主数据以 Sheet09 为准（CON-B4 收敛建议：M2 接线前修页面口径——**此为推断建议，待用户/页面 owner 裁决**） |
| D9 | INV-SG-2026-0121（Johnson Controls）仅见于 dashboard/intake，不在 A.1 11 案 | kpi top_cases + BT-20261020-008 vs Sheet09 A.1 | 不扩 cases.json（P01 固定 11 案）；登记扩展白名单，M1 装载时补列表级 |
| D10 | 税码表：页面 8 行（SG 两档并一行+无通用行）vs Sheet09 10 行 | matching-mapping Tab2 vs Sheet09 A.3 | seeds 按 Sheet09 10 行（P01 指定）；M2 逐区块核对时以页面渲染口径复核 |
| D11 | 0124 状态「RECOGNIZED→VERIFYING」流转记法 | Sheet09 A.1 行 14 | 取终态 VERIFYING（workbench 同源），cases.json notes 注明 |
| D12 | api-portal 页面横幅/调试文案仍指旧契约路径（invoice-platform/ariba-mock contracts）与不带域示例 | api-portal.html line 146/149/273 vs CON-04/ADR-0003 | 页面只读不改；契约侧全部新口径，同步义务登记 CHANGELOG ② |

**推断项（非字面，均已在产物内标注来源/TODO）**：D8 之收敛建议；`detail_level` 分层与 `x-*` 附加字段为本会话落契约时的结构设计（P01 WP0.7「三案详情级、其余列表级」的机器化表达）；config 的 SLA/退避目标值取清单 FN 条目原文数字（FN-1-02/5-04/5-06/7-05/A-03）。

## 4. P00 §7 收工检查单

- [x] 测试/校验通过：check_enums 115/115；validate_contracts 31 项全绿（M0 无服务代码，无 pytest 用例；三演示案件 Schema 自检=验收②内项）；
- [x] 枚举一致性校验通过（对照 contracts/enum-registry.json；inline enum↔registry 由脚本断言）；
- [x] seed 一致性断言通过（案件号/批次/trace/回执/SUP/租户 pattern；alerts/batches/routing 引用交叉核验；Sheet09↔cases 状态/置信度逐案核对=validate ⑤ D7 时点注记覆盖，其余 11 案一致）；
- [x] 依赖纪律自查：backend 无任何 import（仅空 `__init__.py`）；agent/mcp 无代码无 DB 访问；写路径概念仅存于契约描述（受控框架五要素已入 openapi/mcp-tools/adapter 契约文字）；ui-design 未改动（只读核验 mtime 无变化）；
- [x] Excel 回填：M0 无 Sheet03/04 FN 行需回填；**Sheet06 CON-01~05 收敛状态已更新为「已冻结（M0）」**（含结论备注引用 ADR-0004）；
- [x] 文档回写：契约变更记录=contracts/CHANGELOG.md（①②③④ 四条登记）；新决策=docs/adr/0004；H/CON 未决项 TODO 标注齐备（grep "TODO(H24)\|TODO(H25)\|TODO(CON" 见 CHANGELOG 附表）。

## 5. 遗留与移交（M1 入口清单）

1. nextAction.type 枚举定型后按 FN-A-07 兼容登记入 enum-registry（CHANGELOG ③）；
2. invoice_type 机器码统一枚举随 FN-4-01 票种分类规则版本化（CHANGELOG ④）；
3. rules_catalog 四个族级中文标识（行级勾稽/查重规则/容差判定/红线策略）M1 注册时定机器 rule_id；
4. D8 页面文件名交叉、D5 策略版本、D6 时点差异：M2 逐区块核对时与页面 owner 收敛；
5. FN-A-01 备注的 `recognition.request/response.schema.json` 未单列文件（请求/响应已内联于 openapi.yaml components，与实施规划 §2 八文件清单一致）——如 M4/M5 需独立文件再按兼容登记拆分。
