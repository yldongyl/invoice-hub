# UI 一致性核对清单 · M2 接线三页（P03 §3 / WP2.4）

> 用途：同 seed 数据下，`web/` 接线页 vs `ui-design/` 原型逐区块核对（可人工勾选）。
> 执行依据：实施规划 §4-M2 验收①「三页渲染与原型逐区块一致」；P03 §4 验收①。
> 本表 R1 自查（2026-10-26 会话 R2）= 后台数据面（WP2.1/2.2 已交付）+ 接线代码面（WP2.3）的**数据层与静态审查**；
> 正式浏览器逐区块核验已于 2026-10-26 P09 会话执行完毕（Edge headless 自动化，接线态 131 项+演示态 16 项断言），结果见 docs/ui-verification-report-M2.md；本表 B 列已全部勾选。
>
> 验证方法图例：
> - 【S/契约】seeds↔API↔契约测试断言（`pytest` 165 项 + `tools/check_seeds_vs_ui.py` 41 组，可复跑）
> - 【R/审查】web 副本 vs ui-design 原页 diff 审查（`diff` 零差异 或 diff 仅含接线段；R2 时点 10 页 ZERO-DIFF；P09 修复后 login 存 §4-4 例外差异，其余 9 页维持零差异）
> - 【B/浏览器】正式核验已由 P09 会话以 Edge headless 自动化执行（playwright-core），live+demo 双态，结果见 docs/ui-verification-report-M2.md
> - 截图证据：`docs/ui-verification-M2-shots/01–13`（P09 会话产出，替代原 screenshot-diff 计划）

## 1. case-detail.html（三案逐一：0387 / 0379 / 0125）

| 区块 | 核对点 | 方法 | R1 自查 | B 正式 |
|---|---|---|---|---|
| 状态徽章 | 六态配色与徽章文案（STATUS 常量未动）| R/审查+S/case_status 枚举 | ✅ diff 仅接线段；API status=seed | ☑ |
| meta 全字段 | region/ext/type/po/supplier/supId/amount/received/channel/adapter + SM2 卡（0387 通过/0379 失败红章）+ VAT 卡（0125）| S/聚合逐字=seed；R/meta 区零改动；adapter 键映射（supplier_id→supId 等 13 键全列）| ✅ | ☑ |
| Checks 四条+note | 四校验项+结果+判定说明 | S/checks_raw=seed；CHECK_ORDER 四键全覆盖 | ✅ | ☑ |
| 时间线 | 全事件 actor 色点/act 码/版本 v/🔒 | S/timeline 逐字=seed（events.schema）；ACTOR 常量未动 | ✅ | ☑ |
| 字段分组 | ★红粗/来源徽章/置信度三档/🔍 按钮 | S/evidence flat 数组 group 连续还原=页面 groups（M0 抽取同源，check_seeds_vs_ui 已断言）；star/anchor/confidence×100 映射 | ✅ | ☑ |
| 证据弹窗 | 七要素（path/source/conf/值/raw_text/page+bbox/provider+model/rule）| S/evidenceEntry $defs required（smoke 05 实证七要素齐备）；openEv/ev-modal diff 零触碰 | ✅ | ☑ |
| 原件定位 | 红框+脉冲+滚动居中（pv 锚点）| R/locate() 与 anchor 值零改动；无坐标字段 anchor=null 不显示入口（数据侧）| ✅ | ☑ |
| 行项目表 | CN 8 列/OS 6 列/运费行黄底/勾稽说明 | S/items.columns+note=seed；src↔note、head↔columns、rows 映射；黄底判断（运费/Freight）零改动 | ✅ | ☑ |
| AI 卡 | 橙边/仅建议标签/模型版本/置信度/治理脚注/采纳-不采纳按钮 | S/ai_raw=seed；R/卡片 HTML 未动；采纳弹五要素窗、提交=M3 提示（用户裁决 2026-10-26，见 §4）；不采纳=提示不落本地 | ✅ | ☑ |
| Link 图 | 节点/边色/差异橙虚线/冲减关系 | S/links_raw=seed；adapter 还原页面短键形（inv/sup/poState/grn 带注记/credit/files）；linkGraph 函数零改动 | ✅ | ☑ |
| 右栏双 Tab | 票面三模板（cn/cn379/os）/XML 含 Signature·回执/归一化输出带 source+confidence+EvidenceRef | S/paper_template+source_xml=seed 逐字（1753 行内）；switchTab/模板函数零改动 | ✅ | ☑ |
| SHA-256 与归档注记 | 文件卡 display/note（0379 司法取证、0125 H30 余项）| S/file_raw=seed；pdf↔display、note 映射 | ✅ | ☑ |
| 案件切换器 | 三案（号+票种+状态）+replaceState(?case=)+title 同步 | S/switcher API=三 full 案（load_seq 序）；页面静态 option 与 API 数据一致（check_seeds_vs_ui 41 组含切换器断言）；replaceState 行零改动 | ✅ | ☑ |
| 深链 ?case= | 直达 + 不存在→友好 404 | S/exists+404 CASE_NOT_FOUND（test_api_dashboard）；页内 banner 逻辑（refreshCase 404/403/格式非法/列表级四分支）| ✅ | ☑ |

## 2. dashboard-overview.html（双实例各一遍）

| 区块 | 核对点 | 方法 | R1 自查 | B 正式 |
|---|---|---|---|---|
| KPI 四卡 | 128,462/86.2%/0.02%/37+6 等 seed 口径数值与副文案 | S/dashboard API=kpi.json（快照表）逐字；mapApiToPage 全字段覆盖；渲染函数零改动 | ✅ | ☑ |
| 红线卡高亮 | 上限对照+连续 90 天文案+danger 样式 | S/within_redline 真算（rate≤limit）；样式/静态文案零触碰 | ✅ | ☑ |
| 环形图 | 三段+中心总量+scope 徽章+注释行 | S/donut+donut_scope=seed（sum=100 服务校验） | ✅ | ☑ |
| 折线 | 三系列×7 天数据点 | S/trend_7d=seed；SVG 手绘函数零改动 | ✅ | ☑ |
| 案件表 5 行 | 全列（负数红/四类徽章/行点击深链）| S/top_cases=kpi seed 行源+逐案交叉核算（豁免纪律）；onclick `case-detail.html?case=` 零改动；confBadge/STATUS 未动 | ✅ | ☑ |
| 告警卡 ×3 | 展开证据摘要+「须人工确认」标注 | S/alerts=kpi/alerts seed 逐字（evidence HTML 内嵌）；ai_advice_marked 校验在服务侧 | ✅ | ☑ |
| 瓷贴 ×4 | 链接与文案（静态）| R/区块零改动 | ✅ | ☑ |
| 适配状态条 | ✓✓◐○✓ 五系统 | S/adapters.json=页面 5 行逐字（check_seeds_vs_ui 新增断言组）；HTML 静态区块零改动 | ✅ | ☑ |
| 实例切换联动 | cn/os 全量换数据 | S/双实例 API 各自一致；switchInstance async 化后仍渲染同五区块 | ✅ | ☑ |
| demo-mode | 停 backend 回落 mock+角标 | R/DATA 常量保留；loadData 失败回退；角标文案「演示模式（未连接后台）」在位（test_api_web/smoke 10）| ✅ | ☑ |
| 深色模式 | 全页切换 | R/toggleDark 零改动 | ✅ | ☑ |

## 3. login.html（演示桩）

| 区块 | 核对点 | 方法 | R1 自查 | B 正式 |
|---|---|---|---|---|
| 整页 | 品牌封面/SSO 两按钮→租户只读锁定+绿横幅/账密手选租户+H39 四隔离注记/表单校验红字/MFA 说明块/设计期预留声明/登录→dashboard 跳转/锁定态拒绝 toast（§4-4 修复后可达）| R/**web/login.html 与 ui-design/login.html 原逐字节零差异**（diff 实证）——自 P09 F02 修复起存在 3 处有意差异（见 §4-4，用户授权）；无真实认证 | ✅ | ✅（2026-10-26 正式核验）|

## 4. 口径注记（验收①的例外登记）

1. **受控 Action 按钮**（用户裁决 2026-10-26，P03 §0 二选一）：M2 保留五要素弹窗 UI，提交为「M3 激活」提示、**不修改页面数据**——与原型 mock 写行为（原型页本地追加时间线）存在**有意差异**；M3 接线 `POST /v1/cases/{id}/risk-challenge`+`/actions/{action}` 后恢复行为一致。正式核验时此两项按本口径勾选。
2. 时间线 `t` 双口径（运行期 ISO vs 页面 MM-DD HH:MM:SS）：M2 详情数据=seed 逐字（页面口径），运行期新事件追加格式属 M3（R4 遗留 4.5，登记 run-issues）。
3. 其余 9 页（M3-M5 接线批次）：副本与原型零差异，当前即原型口径。
4. **P09 修复例外（2026-10-26，用户授权「按照建议进行修复」）**：
   - **UI-M2-F02**（web/login.html 与 ui-design/login.html 自此不再逐字节一致，diff 共 3 处，均为使 §3.3「锁定态拒绝 toast」可达的最小修正）：① `.tenant-lock` 移除 `pointer-events:none`（保留降透明+`cursor:not-allowed`）；② `enter()` 的 `btn.disabled=true` 改为 `busy` 标志门控（`ssoLogin`/`pwdLogin` 增加 `busy` 守卫防重复提交）；③ 相应注释。动机=原型自身缺陷（文案承诺 toast、CSS/禁用令其不可达）；ui-design 只读不改，口径例外于此登记。**修复后 §3.3 该行判 PASS**（B 列已勾）。
   - **UI-M2-F01**（共享件 `web/js/demo-mode.js`，不属页面 diff 面）：演示角标自 `top:0` 下移至 `top:60px`（header h-14 之下）并加 `pointer-events:none`——独立演示态实例切换真实点击不再被吞；角标文案/配色/回落逻辑不变。
5. demo 态非法 `?case=` 白屏（OBS-5）与 Link 图文件名截断（OBS-2）等为**原型同型行为**，不在例外之列——live 态深链已有 banner 防护。

## 5. 执行方法（正式核验会话）

```text
make seed && make run
形态①：浏览器打开 http://localhost:8000/web/login.html → 登录进 dashboard（对照 §2 逐区块，body data-ihub-mode="live"，无角标）
形态②：停 backend 再开 http://localhost:8000/... → 顶部出现「演示模式（未连接后台）」角标、数据仍全量呈现（§2 demo-mode 行）
形态③：file:// 双击 web/dashboard-overview.html 与 case-detail.html → 同形态②（RUNBOOK §3）
浏览器④：case-detail?case=INV-CN-2026-0379 直达；?case=INV-CN-2026-9999 → 红色 banner 回退 0387；切换器三案；行点击/告警展开/原件定位/双 Tab/深色逐一勾 §1-§2
```
