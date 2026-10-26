# UI 验证报告 · M2（P09 正式画面核验）

> 执行会话：P00 + P09（正式核验会话，消费 RI-M2-005 移交项）。日期：2026-10-26。
> 范围：`web/` 接线三页 case-detail / dashboard-overview / login ×（接线态 + 独立演示态）+ 通用项 G1–G8。
> 纪律：**只验证、只记录、不修复**——本报告所列 FAIL/OBS 均移交后续修复会话或提请用户裁决。
> 结论速览：**通过（修复后复验改判）**——首轮核验 147 项断言 140 PASS / 2 FAIL / 5 OBS；两项 FAIL 已于 2026-10-26 经用户授权修复并回归复验（接线态 131 项 + 演示态 16 项断言 **0 FAIL**，test 171 / verify 41 组 / smoke 10 步全绿），详见 §7。

---

## 1. 验证环境与执行方式

| 项 | 说明 |
|---|---|
| 环境① 接线态 | `hub.py seed && hub.py run`（backend v0.3.0-m2-wp2.3-2.4，SQLite runtime/invoice_hub.db 本会话重灌）；页面经 `http://127.0.0.1:8000/web/`；`body[data-ihub-mode=live]` 实证 |
| 环境② 独立演示态 | **停止 backend** 后 file:// 直接打开 `web/*.html`；另测 RUNBOOK 形态 C 变体（`python -m http.server 8001 -d web`，/healthz 404 触发回落）——两变体均 `mode=demo`+橙角标+内嵌 mock 完整渲染 |
| 对照基准 | `ui-design/` 同名页（三页源码 diff 复核：login **零差异**；dashboard/case-detail diff 仅接线段 40/118 行，与 R2 自检声明一致） |
| 执行方式 | **自动化**：playwright-core 驱动系统 Edge（headless），接线态 130 项断言 + 演示态 15 项 + 变体 2 项；辅以 API 响应 JSON ↔ 页面 DOM ↔ seeds 三方对照；截图 13 张存 `docs/ui-verification-M2-shots/` |
| 断言基准 | `contracts/enum-registry.json` v1.1.0（徽章配色逐值比对 computed style）；`seeds/cases.json`·`kpi.json`（数据锚点）；`tools/ui-consistency-checklist.md` §4 已登记口径例外 |

判定分级：**PASS** / **PASS(seed)** / **FAIL** / **N/A**；OBS=观察项（原型同源或与本里程碑判定无关，不阻塞）。

## 2. 数据锚点核对（页面值 = 聚合计算值）

| 锚点 | seed/API | 页面实测（live） | 页面实测（demo mock） | 判定 |
|---|---|---|---|---|
| CN KPI 四卡 | kpi 快照：128,462 / 86.2% / 0.02%（上限 0.05%）/ 待复核 37+6 高 | 逐值一致 | 一致（内嵌 DATA 同源） | PASS(seed) |
| 「37」口径 | 快照历史基线；live 计数 NEEDS_REVIEW=3/BLOCKED=2（API `kpi.pending.live_*`） | 展示 37（快照） | 同 | PASS(seed)·M2 R1 裁决 1 口径 |
| 红线达标 | 服务真算 0.02≤0.05=within | 红卡+「✔ 未突破红线」 | 同 | PASS |
| CN 环形 | 62/27/11（sum=100 校验） | 一致+中心总量 | 一致 | PASS |
| OS 环形/KPI | 71/19/10；46,208 / 81.7% / 0.03% / 22+4 | 切换后全量联动一致 | 一致 | PASS |
| 7 日趋势 | 三系列×7 点逐值 | 一致 | 一致 | PASS |
| 案件表（CN 5 行） | top_cases=kpi 行源；0387/0386/0385/0384/0383 状态金额一致 | 一致（含行点击深链） | 一致 | PASS |
| 案件表（OS 5 行） | 0125/0124(RECOGNIZED)/0123/0122/**0121** | 与 kpi 行源一致；0121、0124 命中 `known_page_discrepancies` 已登记豁免（R1 裁决） | 一致 | PASS(seed)·豁免在册 |
| 负数金额 | 0384 `¥-8,420.00`、0123 `US$-2,450.00` | 红色 rgb(245,63,63) 实测 | OS 行实测同红 | PASS（G5） |
| 三演示案聚合 | `/v1/cases/{id}?view=full` 逐字段=seeds（0387 11 事件/12 证据/AI 88；0379 8 事件；0125 10 事件/AI 88） | 页面逐字段渲染一致（DOM 文本比对） | 内嵌 CASES=seed 逐字（M0 抽取同源） | PASS |
| dashboard 页面↔API 全字段 | 页内 fetch `/v1/dashboard?instance=` 对照 DOM（total/falseauto/review/donut 图例/top_cases 行/alerts 标题） | 全等 | — | PASS·live 取数实证 |

## 3. 逐页核对清单

### 3.1 case-detail（三演示案逐一）｜截图 01–05、02（深色）

| 区块 | 判定 | 说明与定位 |
|---|---|---|
| 状态徽章+meta 全字段（0387 NEEDS_REVIEW 橙 / 0379 BLOCKED 红 / 0125 INVESTIGATING 橙） | PASS | 文案+computed 色值逐一对 enum case_status；meta 含供应商/金额/PO/渠道/适配/受理时间 |
| SM2 卡（0387 通过绿卡；0379 失败+票面篡改警示+旋转红章 `pv-stamp` 色 rgb(203,38,52)）；VAT 卡（0125） | PASS | 0379 票面横幅「SM2 验签失败 · 疑似篡改 · 案件 BLOCKED」在位 |
| Checks 四条+note（0387 P/NV/P/AV；0379 P/**FAILED**/P/P 红徽章；0125 三 P+AV） | PASS | 结果徽章配色=check_result 枚举 |
| 时间线（0387 11 事件 / 0379 8 / 0125 10；act 码∈registry；actor 四色点、版本 v、🔒 标识；事件序完整） | PASS | 色点数=事件数实测；「M3 后实时追加」N/A（写路径未激活） |
| 字段分组（组数/行数连续还原；★红粗；来源徽章；置信度三档；🔍 按钮） | PASS | 三案各 4 组 12 字段；★字段红标命中（0379/0125 各 2★）；OCR 紫/直读蓝/回执蓝/模型紫 |
| 证据弹窗七要素 | PASS | path/source/conf/值/raw_text/page+bbox/provider+model/rule 全含 |
| 「在原件中定位」红框+脉冲+滚动居中；无坐标字段无按钮 | PASS | `#hl` 尺寸非零+toast；`anchor:null` 字段定位按钮 display:none 实证 |
| 行项目表（CN 8 列×2 案；OS 6 列；0125 运费行黄底唯一；勾稽说明逐案） | PASS | 黄底判断仅命中 Freight 行；CN 案无误高亮 |
| AI 卡（橙边/「LLM 仅建议 · 不自动执行」/模型版本 qwen-finance-v2/置信度 88-94-88/⚖️ 治理脚注） | PASS | 三案全过；采纳→五要素弹窗预填处置意见（含标题+置信度）实证 |
| 不采纳 | PASS | M2 口径=提示不落本地（checklist §4-1 用户裁决登记；置灰+留痕属 M3） |
| Link 图（节点/边色/差异橙虚线/匹配绿实线/冲减=「无」注/GRN 含注记） | PASS | 0379 poState=PASSED 边「匹配」；0387/0125「匹配 · 金额差异」橙；OBS-2 文件名截断 |
| 右栏双 Tab（票面三模板 cn/cn379/os；结构化源文件 0387/0379 XML 含 Signature+回执号；0125 归一化输出含 source/confidence/EvidenceRef） | PASS | 文件名+页数+SHA-256；归档注记 0379「司法取证」/0125「H30 余项」 |
| 案件切换器（3 选项=API switcher 同源）+replaceState ?case=+title 同步 | PASS | 下拉切换→URL/title/全区块联动实测 |
| 深链 ?case=（三案直达 live+demo；9999→CASE_NOT_FOUND 红 banner 回退 0387；FOO-BAD→格式非法；0386→列表级提示；403 分支代码在位） | PASS | §3.1+G3 |
| Action 栏 sticky+四按钮（放行/挂起/退回/人工修正） | PASS | |
| 受控写五要素弹窗（G8：风险提示/权限行「✓ 复核员（王莉）」/强制勾选未勾禁用→勾选变色（放行蓝·退回 danger 红）/处置意见/danger 配色） | PASS | 提交=「M3 激活」提示且**本地时间线零追加**（11 条不变）——与原型 mock 写行为的有意差异经用户裁决登记 |
| 人工修正字段 | PASS（M2 口径） | 弹窗必填校验（新值/原因）实证；「来源变人工+原值保留」N/A（M3） |

### 3.2 dashboard-overview（双实例各一遍）｜截图 06–08

| 区块 | 判定 | 说明与定位 |
|---|---|---|
| KPI 四卡（数值+副文案+红线卡红边+「产品红线指标」角标） | PASS | 双实例逐值=API 聚合 |
| 环形图（三段+scope 徽章+中心总量）/ 折线（3 系列×7 天） | PASS | |
| 案件表 5 行全列（四类徽章/负数红/行点击 `case-detail.html?case=`） | PASS | 置信度徽章 92% 橙、98/99% 绿实测 |
| 告警卡 ×3（展开证据摘要；CN「相似度 100%」「尾差超容差 ±0.06」「须人工确认后执行」；OS「SCH-SG-77410」「结论须人工确认」「冲减」） | PASS | AI 建议「须人工确认」标注在位 |
| 瓷贴 ×4 链接 / 适配状态条 ✓✓◐○✓ 五系统 | PASS | 瓷贴 href=intake/provider/adapter/audit；适配条=adapters seed 同源（静态区块按 R2 口径） |
| 实例切换全量联动（live） | PASS | 五区块全换=API 双实例对照 |
| demo-mode 回落（mock 数据+角标+页面完整可演示） | **PASS**（修复后） | 数据/切换逻辑/深色/负数红均实测可演示；首轮「角标遮挡实例切换」= UI-M2-F01，已修复并复验通过（§7） |

### 3.3 login（演示桩）｜截图 09–10 ｜ web 副本与 ui-design 原型**逐字节零差异**

| 区块 | 判定 | 说明与定位 |
|---|---|---|
| SSO 两按钮→租户只读锁定+绿横幅（「SAML/OIDC claim · 只读，服务端二次校验归属」） | PASS | 横幅色 rgb(0,135,74)、mode 文案、lock class 实测 |
| 锁定态点击租户/账密提交→拒绝 toast | **PASS**（修复后） | 首轮 FAIL=UI-M2-F02（文案已写但原型实现上不可触发）；经用户授权 web 副本单点修正后复验：两条拒绝 toast 均实测可达（§7） |
| 账密手选租户+note（CN=H39 推断标注 / OS=租户四隔离·数据/配置/Provider Key/发票池） | PASS | 双租户 note 逐字实测 |
| 表单校验红字（空账号/空密码）/ 密码显隐 / 记住设备 30 天 / MFA 说明块 / 设计期预留声明+业务边界「仅处理供应商采购发票」/ v1.2-candidate 页脚 | PASS | |
| 登录→dashboard 跳转+toast 要素（租户名+王莉+复核员+MFA 已通过+登录入审计） | PASS | SSO 与账密两路均实测跳转 |

## 4. 通用验证项 G1–G8

| # | 项目 | 判定 | 证据 |
|---|---|---|---|
| G1 | 四类徽章与 enum-registry 一致 | **PASS** | 状态六态：数据现 5 态逐色实测+RESOLVED 常量同源（check_enums 120/120）；来源六枚举：xml_direct/ocr/webhook/model 四枚实测蓝/紫/蓝/紫（qr_code/manual 数据未出现，常量同源）；置信度三档：绿（97/98/99）橙（88/92/94）实测、<80 红为逻辑分支（演示数据无 <80 实例）；主体四色点 system/provider/human/ai 全出现且蓝橙同屏分离 |
| G2 | 抽屉菜单分组/高亮/遮罩/×/Esc；login 无菜单 | **PASS**（OBS-1） | 三页五分组完整；dashboard 高亮=dashboard ✓；case-detail 高亮命中 workbench（原型设计如此，见 OBS）；login 无 `#sb` ✓ |
| G3 | 深链 `?case=` 三演示案直达；`?tab=`；dashboard 行点击传参 | **PASS**（部分 N/A） | 三案 live+demo 均达；行点击 href 带参；`audit-reports?tab=` N/A（M5 页） |
| G4 | 深色模式全页可用 | **PASS** | 三页 live 实测 html.dark+背景切换；dashboard demo 态亦过 |
| G5 | 负数金额红色（0384/0123） | **PASS** | 案件表 computed color=rgb(245,63,63)，live+demo 双态 |
| G6 | 治理口径文案在位 | **PASS**（OBS-7） | 受控写提示（Action 栏⚖️+弹窗权限行）、AI 橙标+「不自动执行」+免责脚注、🔒、设计期预留、H39/H30 标注、v1.2-candidate 页脚（login/dashboard；case-detail 原型无页脚=零改动一致）逐页对照原型通过 |
| G7 | demo-mode 回落 | **PASS**（修复后） | file:// 与 http.server 两变体回落/角标/数据/交互均实证明快；首轮「dashboard 角标遮挡实例切换按钮」（UI-M2-F01）已修复——复验：角标 `pointer-events:none` 且 `top:60px`（header 之下），**真实点击（非 force）切换实例成功**，全量联动+负数红+深色通过 |
| G8 | 写操作确认弹窗五要素 | **PASS** | 见 §3.1 受控 Action 行 |

## 5. FAIL / OBS 登记（两项 FAIL 均已于同日处置——处置记录见 §7）

### FAIL（首轮判定；处置后状态如下）

| 编号 | 页面/环境 | 现象（期望 vs 实际） | 定位 | 归属与建议 |
|---|---|---|---|---|
| **UI-M2-F01** | dashboard-overview · **独立演示态**（file:// 与 http.server 复现一致） | 期望（P09 §1-C/G7）：角标不碍演示操作；实际：`#ihub-demo-badge`（`position:fixed;top:0;left:50%;z-index:9999` 居中横条）覆盖 header 中央，实例切换 seg（btn-cn/btn-os）恰在其中线 → 用户真实点击被吞（含 force 点击实测无效），demo 态无法切换实例 | `web/js/demo-mode.js` `paint()` 角标样式段（M2 接线层新增，**原型无此角标**） | 接线层缺陷，修复路径明确：角标加 `pointer-events:none`（纯展示件）并下移至 `top:56px`（header 之下）或改左上/右上角定位；修复后回归 G7+§3.2 切换行 |
| **UI-M2-F02** | login · 双态一致 | 期望（P09 §3.3）：「锁定态点击租户/账密提交的 toast 口径」；实际：租户按钮组 `.tenant-lock{pointer-events:none}` 吞掉点击、`#btn-login` disabled 且 Enter 隐式提交被抑制 → `pickTenant`/`pwdLogin` 两条拒绝 toast 文案**在 UI 上不可触发**（代码文案与横幅/锁定态本身均正确在位） | `ui-design/login.html`（CSS `.tenant-lock` 与 `enter()` disabled 时序；web 副本**零差异继承**） | **原型自身缺陷 → 提请用户裁决**（P00 §8）：① 按现状修订核验口径（锁定态=点击无效即正确交互，toast 仅属防御代码）；或 ② 在 web 副本单点修正（移除 pointer-events/保留 disabled，使拒绝 toast 可达——须同步登记「口径例外」，因 ui-design 只读）。**本会话未改动任何页面** |

### OBS（观察项，均与原型同源或超出本里程碑判定，不阻塞）

| 编号 | 观察 | 定位 |
|---|---|---|
| OBS-1 | case-detail 抽屉当前页高亮命中 `workbench`（该页脚本 key 如此；case-detail 非九页菜单成员） | `web/case-detail.html:1211`＝原型同处 |
| OBS-2 | Link 图「原件/附件」节点文件名按原型规则 >18 字符截断加「…」（如 `siemens_si-sg-771…`） | linkGraph() 截断三元式 |
| OBS-3 | 左栏卡头 `#m-id`（案件号 span）在原型与副本中均从未赋值渲染，案件号实际显示于面包屑 | case-detail.html:127 与 loadCase() |
| OBS-4 | cn379 票面模板第 2 行「—」单元格 class `border-[#B222222]` 为 7 位无效色值（Tailwind 忽略，边框落默认色）——原型笔误，视觉差异极小 | case-detail.html:765＝原型同处 |
| OBS-5 | demo 态非法 `?case=`（如 9999）不做格式/存在性校验 → `loadCase(undefined)` 抛 SyntaxError、主体空白（原型 boot 同型行为；live 态已有 banner 防护；G3 仅要求三演示案直达） | refreshCase 非 live 早退分支 |
| OBS-6 | 接线态 `favicon.ico` 404（控制台单条资源错误，无 UI 影响） | backend 静态挂载面 |
| OBS-7 | 置信度图例文案「80–95% 中」沿袭 design-system 已知笔误（registry 权威口径 **80–94%**，ADR-0004 附#2 已裁决；徽章阈值逻辑本身正确：≥95 绿/≥80 橙/<80 红） | case-detail.html:158＝原型同处；文案更正属 ui-design 侧遗留（只读面） |

## 6. 结论与遗留项

1. **判定：M2 画面验证 = 通过（首轮 2 FAIL → 同日修复复验后 FAIL 清零，见 §7）。** 接线态三页逐区块与冻结原型一致（131 项断言 131/0，含修复回归项），数据锚点三方相等（页面↔API 聚合↔seeds，含 2 处已登记豁免），独立演示态 16 项全过，**G1–G8 全过**——满足 P09 §4 通过标准（FAIL 清零路径达成，非降级路径）。
2. 两 FAIL 的处置（原「建议路径」均已执行）：
   - **F01 接线层缺陷**（demo-mode.js 角标遮挡）——已修复并回归 demo 态 G7+切换行（§7-①）；
   - **F02 原型自身缺陷**——用户裁决「按照建议进行修复」= 选择 web 副本单点修正路径（非降级）；已修复+口径例外登记于 `tools/ui-consistency-checklist.md` §4-4（§7-②）。
3. 移交事项（不属本会话范围）：
   - M2 R2 遗留「受控 Action 时间线实时追加/人工修正回写」按裁决属 M3——§3.1 已按 N/A+登记例外处理，M3 完成后 P09 复验该两行；
   - `?tab=` 审计深链、其余 9 页全量核验 → M3/M4/M5 批次（P09 组合执行约定）；
   - OBS-4（无效色值）与 OBS-7（80–95 图例笔误）建议并入 ui-design 侧下次勘误清单（只读面，工程侧不动）。
4. 证据包：`docs/ui-verification-M2-shots/01–13`（三案 live/0379 拦截/0125 OS/深链 404 banner/双实例 dashboard/深色×2/login SSO 锁定态/demo 角标三态）；脚本 `~/p09-verify/{live,demo,variant}.mjs` 与 `*-results.json`（工作目录外，可复跑）。
5. 环境复位：验证毕 backend 已重新拉起（`hub.py run`，:8000 接线态恢复），seeds 未改动。

## 7. 处置记录与复验（2026-10-26 同日，用户授权「按照建议进行修复」）

**① UI-M2-F01**（`web/js/demo-mode.js`）：角标 `top:0 → top:60px`（header h-14=56px 之下）、恢复四边圆角、新增 `pointer-events:none`（纯展示件不得拦截交互）；代码注释含缺陷编号。文案/配色/探测逻辑不变。
**② UI-M2-F02**（`web/login.html`，3 处最小修正，ui-design 只读未动）：`.tenant-lock` 移除 `pointer-events:none`（保留降透明+`cursor:not-allowed`）；`enter()` 的 `btn.disabled=true` 改为 `busy` 标志门控，`ssoLogin`/`pwdLogin` 增加守卫防重复提交——两条锁定态拒绝 toast 自此可达。口径例外登记于 `tools/ui-consistency-checklist.md` §4-4（该页与原型不再逐字节一致）。

**复验结果（修复后全量重跑，非抽样）**：
| 态 | 断言 | 结果 |
|---|---|---|
| 接线态 live.mjs | 131 项（含 F02 修复回归 3 项：租户可点击/拒绝 toast×2） | **129 PASS / 0 FAIL / 2 OBS**（OBS 维持原样） |
| 演示态 demo.mjs（backend 停机+file://） | 16 项（含 F01 修复回归 2 项：pointer-events+top、真实点击切换） | **15 PASS / 0 FAIL / 1 OBS** |
| http.server 8001 变体 | 2 页回落抽检 | 均 `mode=demo`+角标+完整数据 ✓ |
| 收工校验 | `hub.py test` 171 passed；`hub.py verify`（enums/contracts/seeds↔ui 41 组）EXIT 0；`hub.py smoke` 10/10 PASS | 全绿 |

**改判**：P09 §4 通过标准达成（涉及页面 FAIL 清零 + G1–G8 全过）→ **M2 画面验证通过**，可提请 P10 门禁。遗留 OBS-1~7 维持移交（原型侧勘误/后续里程碑），不属本判定范围。

*报告人：P09 正式核验会话（自动化+源码复核）· 2026-10-26 · §7 处置复验同会话执行（经用户授权修复）*
