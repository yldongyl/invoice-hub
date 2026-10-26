# M2 自检报告 · 会话 R1（P00+P03 · WP2.1–WP2.2 后台读 API，含 M1 门禁 MINOR 落地）

> 执行会话：P00+P03 · M2 读路径垂直切片第一段。范围经用户确认 = **WP2.1（后台读 API）+ WP2.2（告警与深链数据）**，web 接线（WP2.3）与一致性验收工具（WP2.4）**不在本会话**。前置门禁：M1 **有条件通过**（docs/gate-reports/M1-gate-report.md，2026-10-26，78c448e 入账）——其放行要求 ①「M2 须落地 M-M1-001/002/004/005 四项 MINOR」经用户确认全部纳入本会话并完成；M-M1-MAJOR-01 按门禁约定留至 M3 首包，本会话未引入任何自动流转演示。

---

## 1. 口径裁决记录（用户确认 2026-10-26，动工前）

| # | 裁决点 | 结论 | 登记 |
|---|---|---|---|
| 1 | dashboard「真实聚合计算」口径 | **快照表源 + 交叉核算**：历史累计基线值（总处理量/Touchless/放行率与待复核展示值/环形占比/7 日趋势）以库内 `kpi_snapshots` 表为权威源（演示基线，kpi.json 入库即数据源）；可核算项一律对 cases/alerts/adapters 表真算——红线达标布尔（rate≤limit 数值解析）、donut 合计=100 校验、live NEEDS_REVIEW/BLOCKED 计数、Top5 逐案机读字段交叉（豁免仅认库内 `known_page_discrepancies` 登记条目，未登记差异抛 E_AGGREGATION_MISMATCH）、告警 AI 建议必含「人工确认」真实校验、适配 glyph 从 registry code 文本派生。**禁** seeds 文件透传与硬编码字面量（服务不读任何 seeds JSON，只读 DB） | CHANGELOG ⑦ ④；`services/dashboard.py` 头注 |
| 2 | M1 门禁 4 项 MINOR | 全部纳入本会话（001/002/004/005），其中 002 的契约 bump 与新端点契约登记同批完成 | §2 |
| 3 | switcher 跨实例口径 | P03「三演示案件」= 0387/0379（CN）+ 0125（OS）跨实例。四隔离①强制 instance 过滤，故 `GET /v1/cases?view=switcher` **按实例返回本域 full 案件**（CN→2 案、OS→1 案，load_seq 原序），页面三案由前端双请求合并——数据强制不破纪律（WP2.3 接线按此实现） | `test_api_readonly::test_switcher_view` |

## 2. 交付清单（按提交）

| 提交 | 工作包 | 内容 |
|---|---|---|
| `78c448e` | 基线 | M1 门禁评审报告入账（评审会话落盘未提交件） |
| `6b9be5a` | M2 契约 v1.1.0 | **M-M1-002 契约面**：enum-registry 增 `link_type` 5 值（v1.0.0→1.1.0，词表=清单 FN-0-04 原文），Excel Sheet08 同步追加 5 行（115→120），check_enums 类别映射/总量更新；新增 `dashboard-response/alerts-response/case-read` 三响应 Schema（内部读面契约，**北向 openapi.yaml 零改动**）；`seeds/adapters.json`（5 条，§4.3「Adapter 状态清单」）；validate_contracts SCHEMA_FILES+3、新增 **F 段**交叉断言（31→40 项）；CHANGELOG ⑦（COMPAT） |
| `52ab0d3` | M-M1-001/002/004 | `models.link_types()` 运行时 registry 引用+装载逐行校验（禁硬编码常量，测试镜像断言 registry 同源）；seed_loader 控制台 cp1252 下 stdout UTF-8 reconfigure（裸 `python -m app.services.seed_loader` EXIT=0 实测）；AuditBlock 死 import secrets 清理、audit_chain 头注更新（trace 已收口 issuer）、cases.py 文件头重写；Case.load_seq、Adapter 模型、known_page_discrepancies 入 SeedMeta（豁免判定库内化） |
| `8b661eb` | WP2.1 服务/投影 | `services/dashboard.py`（聚合口径见裁决 1；top_cases 机读字段=caseId/status/amount/supplier/conf/provider/风险存在性，risk.t/region 为展示文案不交叉断言——M0 冻结页面口径）；**M-M1-005** `summary_of` 列表投影瘦身（full 案件不再内嵌全量聚合，列表非北向面、形态收敛登记 CHANGELOG ⑦）；`GET /v1/cases?view=switcher`；深链解析/告警 builder 共享件；errors +E_DEEPLINK_TAB_INVALID/+E_AGGREGATION_MISMATCH |
| `3cbdcde` | WP2.2 路由 | `/v1/dashboard`、`/v1/alerts`（FN-5-09 读侧）、`/v1/cases/{id}/exists`（?case= 404/?tab= 400，越权 403 先行）；instance 小写演示口径归一；main.py 挂载，APP_VERSION 0.3.0-m2-wp2.1-2.2；`test_api_dashboard.py` 22 项 + switcher/投影测试 |

**case-detail 全量视图**：M1 `aggregate_case` 已逐字段=seeds（11/11 案深比对，R3 交付），本会话复核 = 契约校验保持（`test_api_readonly::test_get_case_full_passes_schema`）；view=summary 维持完整聚合以守 openapi v1 承诺（M-M1-005 的 web 性能诉求由列表投影满足，双向口径均在 CHANGELOG ⑦ 透明登记）。

## 3. P03 验收标准判定（本会话范围项）

| # | 标准 | 判定 | 证据 |
|---|---|---|---|
| ① | 页面一致性核对清单 | **本会话不适用**（WP2.3 接线后执行；本会话交付其数据口径基准，check_seeds_vs_ui 已把新增数据面（adapters/switcher）纳入脚本断言 39→41 组） | — |
| ② | demo-mode | 不适用（WP2.3） | — |
| ③ | 深链 | **通过**：`/exists` 不存在→404 CASE_NOT_FOUND（含 `test_exists_404_for_unknown_case`）、越权→403、?tab= 非法→400、合法→200 三态 | test_api_dashboard 深链 4 测 |
| ④ | API 契约 | **通过**：dashboard/alerts/switcher/exists/列表投影 全响应过对应 contracts Schema（`test_api_dashboard` + conftest 新 fixtures）；聚合与 seed 手工核算一致——KPI 三卡抽查见 §4 | 40 项 validate + pytest 契约测试 |
| ⑤ | 依赖纪律 | **通过**：本会话零 web/agent/mcp 改动；新增端点全部只读 GET（无写路径）；`grep -rn "langgraph\|openai\|llm" backend/` 亲跑零命中（大小写敏感口径，大写治理文案为清单原文）；ui-design/ 只读零改动 | §5 收工单 |
| ⑥ | E2E 冒烟 | 部分（healthz/dashboard 数据/三案详情/证据/时间线由 TestClient 走通；make run 级脚本冒烟属 WP2.3 部署形态） | test_api_* 全链 |

## 4. KPI 三卡手工核算过程（P03 验收④ 实证，测试逐值断言）

| 卡 | seed 基线 | 核算公式（服务真算） | 库内输入（手工列举） | 结果 |
|---|---|---|---|---|
| ① 错误自动放行率 | CN `0.02%`/上限 `0.05%`；OS `0.03%` | `within = parse(rate) ≤ parse(limit)` | kpi_snapshots 快照字段数值解析（非字符串比较） | CN true（0.02≤0.05）、OS true ✓ 红线未突破 |
| ② 待复核 | 展示 `37`（历史全量口径）+「6 个高风险」 | live 计数 `SELECT count(*) WHERE instance=? AND status IN (NEEDS_REVIEW/BLOCKED)` | CN 实例 7 案：NEEDS_REVIEW=0387/0384/0381、BLOCKED=0385/0379；OS 4 案：NEEDS_REVIEW=0123、BLOCKED=0122 | live_needs_review CN=3/OS=1、live_blocked CN=2/OS=1 ✓ |
| ③ 环形分布 | CN 62/27/11、OS 71/19/10 | `sum(values)==100` 真算校验（不等即 500） | kpi_snapshots.donut | 两实例合计均=100 ✓（reconciliation.donut_sum_100=true） |

Top5 交叉核算全表预演记录（动工前 2026-10-26）：10 行中 8 行机读字段全对齐；`INV-SG-2026-0124`（RECOGNIZED vs VERIFYING）与 `INV-SG-2026-0121`（不在主数据集）命中已登记豁免 2 条 → `reconciliation.exemptions_applied` 输出摘录；未登记差异注入测试（conf 改 42）确认 500。

## 5. P00 §7 收工检查单（R1）

- [x] **全部测试通过**：`pytest` **165 passed**（144 基线全数回归 + 21 新增/增强：link_type registry 同源镜像 1 项、装载断言增强 test_counts 1 项（含 adapters/SeedMeta/load_seq）、switcher 投影 2 项、dashboard/alerts/exists API 契约与核算 17 项）；三脚本全绿复跑（见 §6 命令输出）；domain+services 覆盖率 **94%**（≥80%）。
- [x] **枚举一致性**：`check_enums.py` **120/120 逐行逐字**（v1.1.0 含 link_type 增补行，Excel Sheet08 同步）；link_type/adapter_status 运行期经 registry 引用；告警展示级 danger/warning 经 validate F 段 ⊆ color_tokens 断言。
- [x] **seed 一致性**：`make seed` 幂等保持（test_rebuild_twice_identical 含 load_seq/adapters 新列）；`check_seeds_vs_ui.py` **EXIT=0**（断言组 39→41：新增 adapters↔页面状态条、switcher↔full 案件序 两组）；alerts/adapters 引用案件存在性=服务侧真实校验。
- [x] **依赖纪律自查**：backend 零大模型引用（grep 亲跑 + test_dependency_discipline）；agent/mcp 未触；**本会话新增 API 全为只读 GET**（写路径零变化，仍仅 actions/risk-challenge 经受控框架）；web 无改动。
- [x] **Excel Sheet03 回填**：FN-3-01/02/03/08/09、FN-8-03/11 七行已刷（待验收×3=后台面完整交付；进行中×4=数据侧交付、页面呈现归 WP2.3，验收要点逐行括注【M2 R1】）。
- [x] **文档回写**：契约变更 → `contracts/CHANGELOG.md` **⑦（COMPAT v1.1.0）**；口径裁决登记 CHANGELOG ⑦ ④+本报告 §1（属实现口径非架构级，未开新 ADR）；无 CON 收敛（未决 CON 照旧 TODO 注记，本会话未触）。

## 6. 命令可复现（收工终验）

```text
cd backend && make seed && make test            # seed EXIT=0（UTF-8 修复后裸控制台可用）；167 passed
python -m pytest --cov=app/domain --cov=app/services   # TOTAL 94%
python tools/check_enums.py                      # 120/120（v1.1.0）
python tools/validate_contracts.py               # 40 项全绿（含 F 段）
python tools/check_seeds_vs_ui.py                # EXIT=0：41 组/12 注记/6 豁免/0 失败
grep -rn "langgraph|openai|llm" backend/          # 零命中（大小写敏感）
```

## 7. 遗留与移交（WP2.3/2.4 入口）

1. **web 三页接线（WP2.3）**：数据契约全部就绪——dashboard 一次返回联动全量、case-detail `view=full`（含 source_xml/paper_template/file/ai/links/items 逐字）、切换器双实例合并、`/exists` 供 `?case=` 友好 404、demo-mode 回退基准=页内 DATA/CASES 常量仍逐字可用。
2. **case-detail Action 按钮口径（P03 §0 二选一）**：建议接线时选「保留 UI + 指向待 M3 激活」——受控写五要素框架与 M1 actions API 已可用，但 FN-8-04 时间线实时追加/徽章流转的端到端语义在 M3 受理管线后才完整；由 WP2.3 会话裁决并报告注明。
3. M1 门禁 §9-M2 其余事项：`__sla_targets` 双下划线键规范化（配置面，WP2.3 接线配置时处理）、时间线双口径展示对齐（R4 §4.5 遗留，M2 接线期）。
4. 聚合服务的 live 计数语义已在响应注记（pending 展示值=历史基线 ≠ live）——若产品后续要求 37 亦为实时口径，须补历史明细种子并走契约收紧（G-M0-004 类），非本会话范围。
5. 深链 `audit-reports.html?tab=` 词汇以 case-read.schema 内联承载并 F 段断言；audit Tab1 告警计数（Header 角标 FN-5-09）读侧可由 `/v1/alerts?instance=` 直接消费。

---

*会话 R1 自检 · 2026-10-26 · 提交链：78c448e → 6b9be5a → 52ab0d3 → 8b661eb → 3cbdcde →（收工材料随本报告提交）。*
