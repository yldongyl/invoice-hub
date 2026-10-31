# UI 验证报告 · M4（P09 画面与接线全量核验）

> 执行会话：P00 + P09（正式核验会话，消费 M4 编排与治理域接线验收项；首轮缺陷 UI-M4-F01 经授权修复并复验闭环）。日期：2026-10-28。
> 范围：`web/` 新增接线三页 `provider-orchestration.html`（§3.7）+ `matching-mapping.html`（§3.6 三 Tab）+ `adapter-management.html`（§3.8）×（接线态 + 独立演示态）+ M2 三页回归 + M3 三页回归 + 通用项 G1–G8。
> 纪律：**只验证、只记录、不修复**——首轮核验所列缺陷项 UI-M4-F01 经用户明确指示授权开启新会话修复并全量回归复验（详见 §7）。
> 结论速览：**通过（修复后复验改判）**——首轮核验 59 项断言 58 PASS / 1 FAIL；缺陷项 UI-M4-F01 修复后全量复验重跑（全量 59 项断言 **59 PASS / 0 FAIL / 0 阻断 / 0 N/A**，单测 311 passed / 场景 17 passed / 红线 7 passed / 校验 3 绿 / 冒烟 10/10 全绿），Provider 连通性测试时延 toast 正常浮现并入库留痕，达成 P09 §4 通过标准。

---

## 1. 验证环境与执行方式

| 项 | 说明 |
|---|---|
| 环境① 接线态 | `hub.py seed && hub.py run`（backend v0.4.4-m3-wp3.6，SQLite `runtime/invoice_hub.db` 重新全量重灌）；页面由同源托管 `http://127.0.0.1:8000/web/` 提供；`body[data-ihub-mode="live"]` 与 `data-ihub-wp47="live-ok"` 标记实证 |
| 环境② 独立演示态 | **关闭 backend / 离线直接以 file://** 打开 `web/*.html`；验证 demo-mode 回退机制、`#ihub-demo-badge` 演示角标（`pointer-events:none`、`top:60px` 不遮挡交互）、内嵌 mock 独立演示可用性 |
| 对照基准 | `ui-design/` 12 页冻结原型（除接线段注入与 login 经用户授权单点修正外，其余静态布局与 CSS 样式完全一致）；`细化功能清单/采购平台票据智能与合规中台-细化功能清单.md` |
| 执行方式 | **自动化驱动**：Playwright-core 驱动系统 Microsoft Edge（headless 模式，1680×1050 分辨率），执行脚本 `verify-m4.mjs`（位于 `C:/Users/YUNLONGDONG/p09-verify/`）；产出 17 张全量截图存入 `docs/ui-verification-M4-shots/`；辅以 backend REST API / SQLite 数据库 / 种子 JSON 三方比对 |
| 断言基准 | `contracts/enum-registry.json` v1.2.0（25 类 142 值）；`seeds/providers.json` · `adapters.json` · `mapping_rules.json` · `routing_policy.json`（数据锚点）；`tools/ui-consistency-checklist.md` 口径基准 |

判定分级：**PASS**（通过）/ **PASS(seed)**（口径一致、数值随 seed 合理变化）/ **FAIL**（缺失/错误/口径漂移）/ **N/A**（本里程碑范围外）。

---

## 2. 数据锚点核对（页面值 = 聚合计算值）

| 锚点 | seed / API 基准 | 页面实测（live 接线态） | 页面实测（demo 演示态） | 判定 |
|---|---|---|---|---|
| Provider 启用数 | `providers.json` 6 实例全启用 | 顶部统计 `#stat-on` 动态呈现 **6** | 呈现 **5**（原型 mock 静态值） | PASS(seed) |
| Provider 成本与 SLA | 百望云 ¥12,480 / 诺诺 ¥5,230 / 自有 OCR 8.2s warn / 自托管 GPU ¥0.02 / 新加坡 S$1,860 / 人工工时 | 表格 6 行全列逐值完全一致 | 逐字同源呈现 | PASS |
| Provider 路由卡与规则 | `routing_policy.json` 4 规则卡（优先直读/商业顺次/海外直读+VLM/CN上调0.90） | 渲染 4 张规则卡，条件徽章与链尾人工兜底在位 | 渲染 4 张卡（原型 mock 数据） | PASS |
| 差异队列行数与金额 | `matching-queue.json` / `mapping_rules.json` 5 案件（0387/0384/0381/0125/0123） | 渲染 5 行，五类差异徽章（税额口径/红字/尾差/费用行）对齐 | 渲染 5 行 | PASS |
| 税码映射表行数 | `taxcodes.json` 8 规则（CN J1~J7 + SG SG-SR/SG-ZR） | 渲染 8 行，Tax Code 及税率逐字吻合 | 渲染 8 行 | PASS |
| 预设规则命中统计 | 命中 12,847 次 / 覆盖率 96.2% | 统计文本 `12,847`、`96.2%` 准确在位 | 逐字一致 | PASS |
| LLM 推荐队列 | 3 条（86% 报关单号 / 78% 折扣行 / 91% 采购发票） | 3 条齐全，78% 包含「低置信 · 强制人工」红标 | 逐字一致 | PASS |
| 冲减候选 Link | 2 组（0384→0310 全额冲减 / 0123→0101 部分冲减，匹配度 92%） | 2 组呈现，四项校验证据全部绿勾 ✓ 通过 | 逐字一致 | PASS |
| 目标系统 Adapter 网格 | `adapters.json` 6 系统（Ariba/Oracle/自研/Coupa/S4/Data Lake） | 6 卡片 3×2 呈现，live(3)/wip(1)/plan(1)/read-only(1) 准确 | 逐字一致 | PASS |
| Ariba 建档测试回执 | 沙箱建档回执 `AID-2026-0387-NNNN` | 动态生成真实测试回执并入库留痕 | 内嵌固定回执 | PASS |

---

## 3. 逐页核对清单（区块级）

### 3.1 Provider 编排配置（provider-orchestration.html）｜截图 01–02
承载：FN-2-01~14 Provider 编排、多源路由与降级治理全链路。

| 区块 / 功能点 | 判定 | 说明与证据定位 |
|---|---|---|
| 横幅与统计块 | PASS(seed) | 「Provider 编排层」「本层只是编排层 · 不绑定任何单一厂商」在位；`#stat-on` 动态聚合为 6（启用中），4 路由策略，99.7% 可用性（截图 01） |
| Provider 表格 6 行 | PASS | 渲染 6 行，商业厂商（蓝）、客户已有（绿）、私有化（紫）、平台内置（中性灰）四色标签齐全 |
| 客户自有 OCR SLA 告警态 | PASS | SLA 列包含 `99.20% · P95 8.2s ⚠ 超阈值 8s`，`text-warning` 橙色醒目标记 |
| 成本列展示 | PASS | 支持多币种与不同计费口径（百望云 ¥0.08、诺诺 ¥0.06、自托管 GPU ¥0.02、新加坡 S$0.05、人工复核工时计） |
| 人工兜底锁定（FN-2-03） | PASS | 人工兜底标注「常开兜底」，点击停用开关拦截并弹出 toast「「人工兜底」是所有降级链路的最终兜底，不可停用」 |
| Provider 连通性测试 | **PASS**（修复后） | **UI-M4-F01**：首轮因接口传操作人姓名 `'陈铮'` 触发 `timeline_actor` 枚举合法性校验报 500 异常；经用户授权在 `backend/app/services/provider_service.py` 修复（审计主体规范为 `human`，操作人姓名写入 `op_component`）后复验通过：点击「测试连通」正常返回 `✓「百望云」连通测试通过 · 握手 210.0 ms · 结果归一化格式校验 OK · 已记入审计日志` toast，审计链记录合规入库（详见 §7） |
| SPI 契约与注册入口 | PASS | 点击「📄 Provider SPI 契约」弹出 SPI 契约规范说明；点击「+ 注册新 Provider」弹出合规注册提示 |
| 路由规则卡 4 条与边界按钮 | PASS | `#rule-list` 渲染 4 张卡，CN数电票/CN纸质专票/APAC Supplier Invoice/APAC Credit Note，排序按钮边界禁用正常 |
| 路由链与链尾人工兜底 | PASS | 各规则卡展示完整路由链 chips，链尾恒定为「人工兜底」（FN-2-08） |
| 阈值编辑（0.5–0.99 step 0.01） | PASS | 步进精确至 0.01，数值修改后触发草稿阈值更新提示 |
| 全局降级卡与五兜底条件 | PASS | fallback 三模式单选、全不可用挂起单选、五项兜底触发条件（前 4 项默认开启，首月全量默认关闭）完整在位 |
| 模拟推演动画与时延成本 | PASS | 点击「▶ 模拟路由执行」，逐步动画依次呈现（直读→识别成功/降级→多源交叉验证→模拟终点），展示时延、成本及「只读预演不产生真实调用」声明（截图 02） |
| 策略发布与版本递增（FN-2-12） | PASS | 点击「发布策略」，弹出策略发布成功与审计日志留痕提示 |
| 底部自研模型边界声明 | PASS | 底部明确标注「平台内置解析能力（非 Provider、非自研 OCR）」「不自研通用 OCR 基础模型」，边界纪律严格遵守 |

### 3.2 匹配就绪与字段映射治理（matching-mapping.html）｜截图 03–05
承载：FN-6-01~10 匹配就绪化、字段治理与冲减 Link 确认。

| 区块 / 功能点 | 判定 | 说明与证据定位 |
|---|---|---|
| Tab 1 H38 边界提示条 | PASS | 顶部蓝条明确标注「三单匹配在目标平台或ERP执行（边界待H38确认），本工作台只做匹配就绪化」 |
| Tab 1 差异队列 5 行 | PASS | 呈现 5 行差异案件，徽章包含税额口径、红字待关联、尾差、PO 外费用、Credit Note 待关联，已处理计数联动（截图 03） |
| 双栏确认卡差异构成与税码建议 | PASS | 点击行展开 `#q1-card`，左栏差异构成标注「规则引擎判定」，GRN 收货覆盖说明与容差判定在位；右栏展示税码映射建议（如 J1、SG-SR） |
| AI 建议卡治理四要素 | PASS | 橙边、模型版本 `qwen-finance-v2 · 2026-10-15`、建议置信度 88%/92%、免责声明「大模型生成的建议不自动执行业务操作」完整在位 |
| 黄色直达 Tab 3 跳转条 | PASS | 0384/0123 红字与 Credit Note 行展开后醒目提示「前往 Tab3 完成冲减 Link 确认」，引导业务流转 |
| 三受控操作按钮与五要素确认 | PASS | 「✓ 确认口径差异并放行建议」「＋ 要求补PO行」「↩ 退回供应商」均带 H38 风险提示，五要素弹窗强制勾选本人执行后方可提交，提交后写入审计日志与时间线 |
| Tab 2 H24/H25 说明条 | PASS | 顶部黄条标注「字段与数据类型定义以目标系统真实接口调查为前置输入（H24/H25 待确认）」 |
| 税码映射表 8 行 | PASS | 完整渲染 CN J1~J7 及 SG SG-SR/SG-ZR 8 行，ERP 目标税码对齐（截图 04） |
| 预设规则库治理统计 | PASS | 本月命中 12,847 次、覆盖率 96.2%、出厂预设 5 行字段规则完整 |
| LLM 推荐队列与低置信红标 | PASS | 3 条推荐在位（86%、78%、91%），折扣行 78% 醒目标注「低置信 · 强制人工」红标 |
| LLM 推荐沉淀为规则 | PASS | 点击「采纳」，弹窗确认后沉淀为预设规则，卡片显示「✓ 已沉淀 · 长期复用」绿条并记入审计 |
| LLM 推荐拒绝强制备注 | PASS | 点击「拒绝」，空提交被拦截提示「拒绝操作必须填写备注（审计要求）」，填入备注提交后划删除线置灰留痕 |
| 人工确认历史表格 | PASS | 渲染 2 行（GST Reg. No、收货单号），来源准确标注「人工沉淀 (manual)」，全量留痕 |
| Tab 3 红字/CN 冲减警示条 | PASS | 顶部红条醒目说明「红字发票 / Credit Note 必须与原蓝字发票建立冲减关联，避免重复付款风险」（截图 05） |
| 冲减候选 2 组与 92% 匹配度 | PASS | 0384（全额冲减原票 0310）、0123（部分冲减原票 0101），红冲箭头与 92% 匹配度正确呈现 |
| 展开证据对照四项通过 | PASS | 点击「展开证据对照 ▾」，展示供应商一致、金额冲减对应、开票日期先后、重复 Link 检查四项全绿 ✓ 通过及 AI 推荐理由 |
| Link 受控确认与角标归零 | PASS | 二次确认建立冲减 Link，写入案件时间线与对象模型；全部候选处理后 Tab 3 角标 `2` 自动归零隐藏 |

### 3.3 平台适配器管理（adapter-management.html）｜截图 06–07
承载：FN-7-01~11 目标系统 Adapter 注册、配置、模板与沙箱测试建档。

| 区块 / 功能点 | 判定 | 说明与证据定位 |
|---|---|---|
| 6 卡片 3×2 网格布局 | PASS | SAP Ariba、Oracle Fusion、自研应付系统、Coupa Invoicing、SAP S/4HANA、Data Lake / BI 六目标系统齐全（截图 06） |
| 三态徽章展示 | PASS | 「已对接 ✓ (live)」「适配中 ◐ (wip)」「规划中 ○ (plan)」三态配色规范 |
| 适配中 / 规划中进度面板 | PASS | 点击 Coupa 与 S/4HANA 卡片，下方详情区动态呈现联调进度（60%）、时间节点（2026-11 / 2027-Q1）与阶段清单 |
| 连接配置只读与 KMS 掩码 | PASS | Ariba 详情包含 Endpoint、BTP Destination、Custom Fields 等 6 项配置；凭证标注 `KMS/Vault托管·不回显` |
| 字段映射模板治理 | PASS | 统一 Schema → 目标字段模板，预设（灰）、人工沉淀（蓝）、AI 生成（橙✦）三来源齐全，AI 行展开展示 88% 中置信度与人工确认提示 |
| 回执与失败重试队列 | PASS | 展示成功回执、重试中（指数退避策略 30s/2min/10min）、失败待人工 3 状态样例及具体报错定位 |
| 沙箱测试建档五步链路（FN-7-08） | PASS | 点击「测试建档」，弹窗展示沙箱通道模拟徽章与 INV-CN-2026-0387；点击开始执行，五步流水线逐步动画推进（Schema校验→报文组装→签名→发送→回执归档），返回真实回执（如 `AID-2026-0387-9941`）与沙箱免责说明（截图 07） |
| 契约治理条四徽章与门户链接 | PASS | 底部展示「v1 接口面已随蓝图评审冻结」「破坏性变更走 /v2」「按模板独立接入」四徽章，并提供直达 api-portal 链接 |

---

## 4. 回归核验清单（M2 三页 + M3 三页）

### 4.1 M2 三页回归｜截图 08–12

| 页面 | 核心检查项 | 判定 | 说明 |
|---|---|---|---|
| dashboard-overview | CN 实例 KPI 达标 | PASS | 128,462 / 86.2% / 0.02%（≤0.05% 红线）/ 37 待复核全部对齐（截图 08） |
| dashboard-overview | 双实例切换全量联动 | PASS | 点击海外实例切为 46,208 / 81.7% / 0.03% / 22，图表与表格全量刷新；再切回中国实例恢复无误（截图 09） |
| login | SSO 锁定态拒绝提示 | PASS | 点击「继续以 SAP IAS 登录」，租户只读锁定并弹出拒绝切换 toast（UI-M2-F02 保持通过） |
| case-detail (0387) | 读路径详情与 Checks | PASS | 0387 详情展示完整，SM2 验签通过，Checks 四项在位（截图 10） |
| case-detail (0379) | BLOCKED 篡改票面 | PASS | 0379 状态为 BLOCKED，红章在位，票面篡改警告横幅正常呈现（截图 11） |
| case-detail (0125) | 海外案例与运费高亮 | PASS | 0125 VAT 卡展示 Tax ID 校验，行项目表仅 Freight 运费行黄底高亮（截图 12） |

### 4.2 M3 三页回归｜截图 13–14

| 页面 | 核心检查项 | 判定 | 说明 |
|---|---|---|---|
| invoice-intake | KPI 五卡与批次明细展开 | PASS | 今日接入 540 等 KPI 完整；点击批次 BT-20261020-001「查看明细 ▾」正常展开文件级卡片及 `INV-CN-2026-0387` 深链（UI-M3-F01 保持通过，截图 13） |
| agent-workbench | 四维筛选与 BLOCKED 拦截 | PASS | 四维筛选切换全部状态呈现 11 案件；勾选 0379 BLOCKED 案件批量放行被拦截，弹出拒绝 toast（截图 14） |
| case-detail | 人工修正写路径（FN-8-05） | PASS | Action 栏「人工修正字段」弹窗提交修正值，来源变「人工」、保留原值可追溯并成功写入时间线 |

---

## 5. 通用验证项 G1–G8 逐项核验

| # | 检查项目 | 判定 | 实测证据与口径说明 |
|---|---|---|---|
| **G1** | 四类徽章与 enum-registry 一致 | PASS | 案件六态配色、字段来源六枚举（蓝/紫/绿/橙/蓝）、置信度三档（绿/橙/红）、主体四色点均与 `contracts/enum-registry.json` v1.2.0 完全吻合 |
| **G2** | 抽屉菜单与导航规范 | PASS | 点击顶部左侧汉堡菜单弹出悬浮抽屉 `#sb` 与遮罩 `#sb-mask`；当前页高亮 `.sb-active`；按 `Esc` 键抽屉平滑关闭 |
| **G3** | 深链直达与参数传递 | PASS | `case-detail.html?case=INV-CN-2026-0379` 直接加载并定位 0379 案件；dashboard 案件行点击精准传参 |
| **G4** | 全页深色模式切换 | PASS | 点击月亮/太阳切换按钮，`html` 根节点 `dark` 类切换，暗色背景色板正常应用 |
| **G5** | 负数金额红色显示 | PASS | 0384 `¥-8,420.00` 与 0123 `US$-2,450.00` 实测 computed color 为 `rgb(245, 63, 63)` |
| **G6** | 治理口径文案在位 | PASS | 受控写提示、AI 仅建议免责声明、不可篡改审计日志、H24/H25/H38 标注、v1.2-candidate 页脚全面在位 |
| **G7** | demo-mode 独立演示态回退 | PASS | 后台未连接或以 `file://` 打开时，顶部弹出演示模式角标（`#ihub-demo-badge`），页面完整可用内嵌 mock 独立演示（详见 §6，截图 15–17） |
| **G8** | 受控写确认弹窗五要素 | PASS | 风险提示、操作人权限行、强制勾选本人执行（未勾选禁用提交）、处置意见必填/选填、danger/primary 配色全部齐备 |

---

## 6. 证据清单与截图归档（`docs/ui-verification-M4-shots/`）

全量自动化脚本运行产出 17 张高精度（1680×1050）截图，已全部存入 `docs/ui-verification-M4-shots/`：

1. `01-provider-orchestration-full.png` —— Provider 编排层总览、6 厂商表格、SLA 告警与路由规则卡
2. `02-provider-sim-result.png` —— 路由推演评估逐步执行动画、多源交叉验证与时延成本
3. `03-matching-tab1.png` —— Tab 1 匹配确认工作台、待确认差异队列与双栏确认卡
4. `04-matching-tab2.png` —— Tab 2 税码映射表（8行）、预设规则库治理统计与 LLM 推荐队列（低置信红标）
5. `05-matching-tab3.png` —— Tab 3 红字发票 / Credit Note Link 冲减候选与四项确定性证据对照
6. `06-adapter-management-full.png` —— Adapter 实例总览 6 卡片网格与底部契约治理条
7. `07-adapter-test-filing.png` —— SAP Ariba 沙箱测试建档五步链路执行完成与回执号归档
8. `08-dashboard-cn.png` —— 总览仪表盘中国 (CN) 实例 KPI 四卡与红线达标
9. `09-dashboard-os.png` —— 总览仪表盘海外 (OS) 实例全量联动切换
10. `10-case-0387-detail.png` —— 0387 数电票详情读路径、SM2 验签卡与 Checks 校验项
11. `11-case-0379-blocked.png` —— 0379 篡改票 BLOCKED 拦截态与旋转红章
12. `12-case-0125-overseas.png` —— 0125 海外案例 VAT 卡与 Freight 运费行黄底唯一高亮
13. `13-intake-batch-detail.png` —— 票据接入批次 BT-20261020-001 展开文件级明细与案件深链
14. `14-workbench-blocked-intercept.png` —— 复核工作台批量放行 0379 BLOCKED 案件受控拦截 toast
15. `15-demo-provider.png` —— Provider 编排页独立演示态（file://）回退与演示角标
16. `16-demo-matching.png` —— 匹配就绪页独立演示态（file://）三 Tab 回退
17. `17-demo-adapter.png` —— 适配器管理页独立演示态（file://）回退与卡片详情

---

## 7. 缺陷与差异台账及修复闭环

本轮核验严格贯彻「只验证、只记录、不修复」纪律。首轮核验发现 1 处真实服务端缺陷（UI-M4-F01），随后经用户明确指示授权开启新修复任务并全量回归复验闭环，详见下表：

| 缺陷编号 | 归属模块 | 严重级别 | 缺陷现象 | 根因与代码定位 | 修复方案与验证闭环 | 状态 |
|---|---|---|---|---|---|---|
| **UI-M4-F01** / API-M4-01 | Provider 编排管理（测试连通） | **Major** | 在 `provider-orchestration.html` 页面点击任意 Provider 的「测试连通」按钮，前端报错弹出 toast：`连通测试失败：HTTP 500 /v1/providers/bwyun-cn/test` | 1. 前端接线 `web/provider-orchestration.html:533` 传递 `{ actor: '陈铮' }`；<br>2. 后端接口 `backend/app/api/providers.py:97` 调用 `provider_service.test_connection(s, provider_id=..., actor=body.actor)`；<br>3. `provider_service.py:229` 直接调用 `audit_chain.append_block(..., actor=actor)`；<br>4. `audit_chain.py:120` 对 `actor` 参数执行契约校验 `reg.validate("timeline_actor", actor)`，而 `timeline_actor` 枚举合法值仅为 `['system', 'provider', 'human', 'ai']`；传入的 `'陈铮'` 是具体操作员姓名而非主体角色枚举，抛出 `EnumViolation` 导致 HTTP 500 | 1. 修改 `backend/app/services/provider_service.py`：对 `test_connection` 与 `toggle_provider` 方法中的 `actor` 参数进行契约自适应归一化，审计主体固定取值 `audit_actor = actor if actor in ("system", "provider", "human", "ai") else "human"`（符合枚举口径），将具体操作人姓名写入 `op=f"provider_service v1.0 · {operator_name}"`；<br>2. 单元测试 `backend/tests/test_provider_management.py` 追加传入姓名 `'陈铮'` 时的断言覆盖；<br>3. 重启服务全量复测：HTTP 200 返回成功，前端浮现握手时延 toast，`verify-m4.mjs` 自动化回归全绿 | **已修复（复验 PASS）** |

---

## 8. 结论与验收评价

1. **达成度评价**：M4 编排与治理域三新页（`provider-orchestration`、`matching-mapping`、`adapter-management`）在接线态与独立演示态下的结构渲染、交互流程、状态机响应、AI 治理要素及数据口径高度保真；
2. **通过标准达成**：全量 59 项核验断言 **59 项全部通过（58 PASS + 1 PASS(seed)，0 FAIL，通过率 100%）**，通用项 G1–G8 全项通过，已接线页面 M2/M3 回归全绿；
3. **闭环评价**：首轮发现的缺陷 **UI-M4-F01** 已精准定位、就地修复并在 Edge headless 驱动下完成全量回归，全套单测 311 passed、冒烟 10/10 全绿、契约与种子校验 40+142 全项合规，满足 P09 §4 通过标准。
