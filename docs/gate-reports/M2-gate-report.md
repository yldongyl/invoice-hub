# M2 门禁评审报告

- **评审日期**：2026-10-26（评审会话：P00+P10 独立验收，与实现会话分离）
- **被评审提交范围**：`78c448e..bda4e54`（invoice-hub 仓库，main 分支，共 11 个提交：M1 门禁入账 78c448e → M2 契约 6b9be5a → MINOR 闭环 52ab0d3 → WP2.1 8b661eb → WP2.2 3cbdcde → R1 收工 181b115 → WP2.3 4b6349b → WP2.4/P07 38c29e3 → R2 收工 a624906 → P09 核验 77d889c → F01/F02 修复复验 bda4e54=HEAD）
- **评审依据**：实施规划 §4-M2 验收小节；P03 §4 验收标准六条；清单 MD §2.5/§3.3/§3.8 相关 FN 条目（现场读）；P10 全步骤
- **环境注**：invoice-hub 为独立 git 仓；`ui-design/` 与 Excel 在仓外（见 §4-⑤ 方法替换说明）。评审前存在两个遗留开发进程（:8000 实例与 :8731 孤儿实例，后者即 RI-M2-003 记录的句柄占用进程）——均已停止、全链由本会话亲跑重建，评审毕恢复 :8000 接线态。

---

## 1. 交付物盘点（工作包 × 存在性 × 完整性）

| 工作包 | 交付物 | 存在性 | 完整性判定 |
|---|---|---|---|
| WP2.1 后台读 API | `backend/app/services/dashboard.py`、`api/cases.py`（view=full/switcher/列表投影瘦身）、`api/dashboard.py` | ✅ | 聚合口径=快照表源+库内真算（用户裁决 1 落地，禁透传禁硬编码在头注与 CHANGELOG ⑦ ④ 双登记）；`?field=` 证据过滤实测可用 |
| WP2.2 告警与深链 | `/v1/alerts`、`/v1/cases/{id}/exists`（404/403/400 三态）、深链 tab 词汇 | ✅ | 数据面在位；**但告警 case_ref 解析失效（缺陷 M-M2-MAJOR-01，§8）** |
| WP2.3 web 运行时与三页接线 | `web/` 12 页副本、`js/api-client.js`、`js/demo-mode.js`、`main.py` StaticFiles `/web` 挂载+根 307 | ✅ | 9 页与原型逐字节零差异（亲验 diff）；dashboard/case-detail diff 仅接线段（40/118 行，亲验）；login 含 §4-4 授权例外 3 处（亲验为最小修正）|
| WP2.4 一致性验收工具 | `tools/ui-consistency-checklist.md`（§3 区块表+§4 例外登记+§5 核验脚本说明） | ✅ | screenshot-diff 未建——RI-M2-005 注明（环境无 Playwright，P03 §2-WP2.4 允许），以 Edge headless 自动化+13 截图替代，可接受 |
| P07 运行基线（随 R2） | 根 `Makefile`+`scripts/hub.py`、`tools/smoke.py`、`docs/RUNBOOK.md`、`backend/uv.lock`、pyproject 收尾 | ⚠️ | 各单项命令实测可用；**`all` 组合入口崩溃（缺陷 M-M2-MAJOR-02，§8）** |
| 画面验证 | `docs/ui-verification-report-M2.md` + `docs/ui-verification-M2-shots/01–13` + `tools/ui-consistency-checklist.md` B 列回填 | ✅ | 报告与证据齐备（§4-3 有一处未更新陈述，缺陷 M-M2-003）|
| 自检 | `docs/gate-reports/M2-self-check.md`（R1+R2 两段）+ `run-issues.md`（RI-M2-001..007） | ✅ | 与实况核对一致处见 §3/§8；两处自述夸大/滞后注记 |
| 契约回写 | `contracts/` v1.1.0：enum-registry（link_type +5）、dashboard/alerts/case-read 三响应 Schema、`seeds/adapters.json`、CHANGELOG ⑦ | ✅ | validate_contracts F 段 40 项全绿（亲跑）；openapi.yaml 北向零改动声明经 diff 面确认 |

**缺件**：无。Excel Sheet03 FN-5-09 行状态回填缺失（缺陷 M-M2-005，评审会话已按 P10 §3 MAJOR 处置要求补注，见 §9）。

## 2. 运行证据（命令 × 结果摘要，本会话亲跑）

| 命令 | 结果 | 摘要 |
|---|---|---|
| `python scripts/hub.py all`（venv 3.13.3） | **FAIL** | clean ✓ → seed ✓（20 类/226 行，UTF-8 控制台正常=M-M1-004 闭环实证）→ **verify 步 `KeyError: 'verify'` 崩溃**（hub.py:155 分发表无复合命令 `verify`）→ test 未及执行 |
| `hub.py verify`（三脚本依次） | PASS | check_enums **120/120 逐行逐字**（v1.1.0，Sheet08 同步）；validate_contracts **40 项全绿**（含 F 段交叉断言）；check_seeds_vs_ui **41 组/12 注记/6 豁免/0 失败** |
| `pytest -q`（venv 3.13.3） | PASS | **171 passed**（与 R1/R2 自述一致），含 test_dependency_discipline（.venv 排除修复 RI-M2-001 生效） |
| `hub.py run` + `hub.py smoke` | PASS | **10/10 PASS**（healthz→11 案在库→双实例聚合→三案 Schema→证据七要素→时间线 11 事件 act ∈ registry→审计链三域→受控写拒绝 E_*→静态可达→demo-mode 在位） |
| P09 核验脚本复跑 `live.mjs`（Edge headless，131 项） | PASS | **129 PASS / 0 FAIL / 2 OBS**（OBS=OBS-1/OBS-2 原型同源项，与报告一致）；含 F02 修复回归 3 项实测通过 |
| `demo.mjs`（backend 停机后 file://，16 项） | PASS | **15 PASS / 0 FAIL / 1 OBS**（OBS-5 demo 态非法深链白屏）；与报告 §7 复验数字吻合 |
| `variant.mjs`（http.server 8001 变体） | PASS | 两页回落 `mode=demo`+橙角标+数据在位（128,462 / INV-CN-2026-0387） |
| 副作用管理 | — | 复跑覆盖了 7 张已提交截图证据，已 `git checkout --` 恢复至 `bda4e54` 原状；工作树 clean、runtime DB 为本会话 clean→seed 重建 |

## 3. 验收标准逐条判定（P03 §4 + 规划 §4-M2）

| # | 标准 | 判定 | 证据 |
|---|---|---|---|
| ① | 一致性核对清单三页 100%（差异须修复或报告说明获认可） | **PASS** | 本会话亲跑 live 131 项 0 FAIL、demo 16 项 0 FAIL；2 项首轮 FAIL（F01/F02）修复+复验+例外登记链路完整（§6）；OBS 全部为原型同型行为或已登记例外，判定口径成立 |
| ② | demo-mode：停 backend 后三页完整演示（回落 mock+角标） | **PASS** | 本会话亲停 backend 复跑：file:// 与 http.server 两变体均回落+橙角标「演示模式（未连接后台）」+KPI 三案数据完整+实例切换真实点击可通（F01 修复回归实证）+深色可用；login 静态页零依赖 |
| ③ | 深链：0379 直达；不存在→友好 404；行点击传参 | **PASS** | API 实测 200/`CASE_NOT_FOUND` 404/`E_TENANT_MISMATCH` 403/`E_DEEPLINK_TAB_INVALID` 400；live.mjs G3 三案直达（live+demo）、9999 红 banner 回退 0387、FOO-BAD 格式分支、行点击 href 带参全过。demo 态非法 `?case=` 白屏=OBS-5（原型同型行为，live 态已防护，不违 P09 §3.3 判定，移交注记见 §8） |
| ④ | API 契约全过校验；聚合值与 seed 手工核算一致 | **PASS**（附 MAJOR 缺陷注） | 40 项 validate+契约测试全绿；**评审员独立手工核算**：CN KPI 128,462/86.2/0.02%≤0.05%（红线布尔真算）/37+6 与 kpi.json 逐字等值；live 计数自 cases.json 独立数出 NEEDS_REVIEW=3（0381/0384/0387）、BLOCKED=2（0379/0385）=API `kpi.pending.live_*`；donut CN 62+27+11、OS 71+19+10 合计=100；OS 全量联动逐值等值；Top5 行源=kpi seed 逐字（含 0124/0121 两处已登记豁免，exemptions_applied 输出在册）。唯告警 case_ref 数据语义失效（M-M2-MAJOR-01，schema 允许 null 故契约校验仍过——契约合规≠口径实现正确，录 MAJOR） |
| ⑤ | 依赖纪律：web 无 DB/FS；ui-design git status 零改动 | **PASS** | 6 项静态检查全过（§4）；注：`ui-design/` 在本仓之外无法执行 git status——替换验证=①12 页 mtime ≤2026-10-22 早于 M2 全部工作日；②零接线痕迹（无 api-client/demo-mode/ihub-mode 引用，`/v1/` 命中均为原型文档文案）；③web 副本 diff 审查（9 页 ZERO-DIFF+2 页接线段+login 授权例外 3 处）——三重证据判定零改动成立 |
| ⑥ | E2E 冒烟：`make run` 后 healthz→dashboard→三案→证据→时间线走通 | **PASS** | smoke 10/10（步骤 01/03/04/05/06 即该链路）亲跑通过；`test-e2e` 为 M3 场景集占位（hub.py 明示注记，规划 §4 允许） |

**规划 §4-M2 验收小节**（同 seed 逐区块一致/demo-mode 回落/深链与实例切换）：①②③ 覆盖，判定同上，**PASS**。

## 4. 依赖纪律检查（6 项 × 结果）

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | backend 零 LLM import | **PASS** | grep（langgraph/openai/anthropic 大小写不敏感 import 面）零命中 + `test_dependency_discipline` 通过（.venv 扫描边界修复 RI-M2-001 生效） |
| 2 | agent/mcp 零 DB 直连 | **PASS** | 两目录仅 README（M5 实装），无代码可违；grep sqlalchemy/sqlite/get_engine 零命中 |
| 3 | web 只消费 REST | **PASS** | `js/api-client.js` 单一 fetch 封装同源；web JS 无 require/localStorage/indexedDB/文件访问（grep 零命中） |
| 4 | 枚举零硬编码抽查 | **PASS**（带观察） | link_type 已改 registry 引用+装载逐行校验（M-M1-002 闭环亲验：models.link_types()/seed_loader:140）；state_machine 六态命名空间由 registry 派生+边表镜像测试；confidence_band ≥95/80–94/<80=registry 原文；OBS：dashboard.py:65 以 `NEEDS_REVIEW`/`BLOCKED` 字面量入 SQL 过滤（值与 registry 全等、行为经 test 钉住，但无装载期 reg.validate——同 M1 已收口模式，建议 M3 顺手加引用式） |
| 5 | 写路径全过受控框架 | **PASS** | 全仓路由清点：POST 仅 actions.py 7 条（risk-challenge×4 + actions×3），全部经 `governed_commands`；**M2 区间 `git diff --stat` 对 actions.py/governed_commands.py 零改动**；M2 新增端点全为只读 GET；smoke 08 实证无凭据 release 被受控拒绝（E_CONFIRM_INVALID） |
| 6 | ui-design 只读 / 旧仓零拷贝 | **PASS**（带注记） | ui-design 零改动三重证据（§3-⑤）；旧仓引用 grep：代码面零拷贝；`web/api-portal.html`/`web/demo-landing.html` 文案含 `ariba-mock/`、`invoice-platform/contracts/` 路径字样系原型原文逐字继承（页面 M5 接线，届时须口径处理——录 OBS）；`contracts/adapter-contract.schema.json` 仅「历史 ariba-mock 仅参考」注记，合规 |

红线面：错误自动放行率红线对照为真算（parse 数值比较非字符串）、`no_relax_note`「不允许以放松校验换取自动化率」随响应下发、受控写拒绝生效——无配置绕过路径引入。

## 5. 口径抽查记录（7 处，FN | 规则原文要点 | 实现行为 | 判定）

| FN | 规则原文要点 | 实现/实测行为 | 判定 |
|---|---|---|---|
| **FN-3-02**（必查） | 弹窗七要素：Schema 路径/来源徽章/置信度徽章/识别值大字/原文片段（引号包裹）/页码坐标/Provider/模型版本/规则命中，缺一即黑盒 | `case-detail.html:1075-1093` openEv 渲染 9 个信息位全覆盖，raw_text 以中文引号包裹（:1088 `“${e.raw}”`）；API 面 0387 evidence 12 条逐条含 page/bbox/raw_text/rule/model_version/provider+source/confidence；smoke 05 即此断言 | **PASS** |
| **FN-0-15**（必查） | 四类徽章全站唯一（design-system 基准）；负数红；AI 橙/系统蓝/danger 红不混用；演示数据 v1.2-candidate 标注 | confidence_band registry=「≥95 绿/80–94 橙/<80 红」；live.mjs 逐 computed color 断言（状态六态/来源六枚举/主体四色）0 FAIL；负数 0384/0123 实测 rgb(245,63,63)；AI LLM_ADVICE 橙标与 system 蓝标分离断言过；「80–95%」图例文案=原型笔误 OBS-7（ADR-0004 附#2 已裁权威口径 80–94%，徽章逻辑正确）；v1.2-candidate 页脚在位 | **PASS**（OBS-7 沿袭登记合理） |
| FN-3-01 | 证据随字段存储八属性；全量+按字段精确过滤 | `GET /v1/cases/{id}/evidence?field=header.invoice_no` 实测精确命中 1 条、全属性返回；项级过 invoice-case $defs/evidenceEntry | **PASS** |
| FN-5-09 读侧 | 每条告警携带证据摘要（规则 ID+版本/来源 Provider/AI 建议+置信度+人工确认约束）；告警计数供 Header 角标 | 证据摘要三要素实测齐备（platform-dedup-rule v2.3/百望云 Provider/置信度 94%+「须人工确认后执行，系统不自动写回」；`ai_advice_marked` 真实校验仅 SM2 案为 true）；`/v1/alerts?instance=` 可直接消费计数；**但 schema 描述「case_ref=从 meta 解析的案件引用」失效：seed_loader 用全锚定 `^INV-…$` 对 meta 行做 `re.search`，六条告警 case_ref 恒 null**（0385/0381 的 meta 明含案件号；引用存在性交叉校验因此空转；test_api_dashboard:162 子集断言在空集上恒真） | **FAIL→MAJOR**（M-M2-MAJOR-01） |
| FN-8-11 | KPI 四卡：总处理量（+环比、直读占比）/Touchless（STP Accuracy 口径）/错误自动放行率（红线高亮+上限对照+连续达标天数）/待复核（BLOCKED 计数+平均等待+SLA）；双实例全量联动；与 audit Tab2 同源 | 四卡数值/副文案逐字=kpi seed（含 STP Accuracy 口径文案、红线成对呈现）；快照+live 双口径在 reconciliation 注记透明（「37 历史基线 ≠ live」）；donut sum=100 真算；实例切换全量联动实测；「连续达标天数」「平均等待/SLA 判定」两子项原型即无、seed 无数据源——沿 M0 冻结页面口径未呈现，M2 一致性验收不受损，**录 OBS 建议 M5 与 FN-8-12 同源聚合时一并收口** | **PASS**（OBS 登记） |
| FN-0-14 | 深链词汇 `?case=` 全站统一、`?tab={log|sla|arch}`；后台支持按 ID 直达、URL 可分享可审计 | tab 词汇经 case-read schema 内联+F 段断言；exists API 404/403/400 亲测；replaceState+title 同步 live.mjs 断言过；瓷贴/行点击 href 带参 | **PASS** |
| FN-3-08/09 | 右栏双 Tab：CN=XML 含 Signature+验签回执；OS=归一化输出每值节点带 source+confidence+EvidenceRef+「缺 XML 原件说明」显性；文件卡 名+页数+SHA-256+归档注记 | 0125 source_xml 实测含显式注释头「无 XML 原件·OCR 归一化」+逐值节点 source/confidence 属性+EvidenceRef；0379 XML 含 Signature 与 gm-rcpt 回执号；文件卡 display/pages/sha256/note 随 full 聚合返回（0379「司法取证」/0125「H30 余项」逐字） | **PASS** |

## 6. 画面验证复核（涉及页 × 结论）

- **报告完备性**：`docs/ui-verification-report-M2.md` 在位（非缺失），13 张截图证据包在位——无评审阻塞项。
- **复跑实证**：本会话不停脚本原样复跑三态：**live 131 项（129P/2OBS/0F）、demo 16 项（15P/1OBS/0F）、http.server 变体 2 页回落**——与报告 §7 复验记录逐项吻合（2 OBS=F02 回归外的 OBS-1/OBS-2 原型同源项，报告如实登记）。
- **FAIL 处置合理性复核**：
  - **UI-M2-F01**（demo-mode 角标遮挡实例切换）——接线层缺陷，修复=纯展示件 `pointer-events:none`+下移 60px，本会话真实点击（非 force）切换实例亲验通过（demo.mjs 回归项）→ 处置成立；
  - **UI-M2-F02**（登录锁定态拒绝 toast 不可达）——根因在原型自身（`.tenant-lock`/`disabled` 吞点击），按 P00 §8 提请用户裁决走「web 副本单点修正」路径，diff 亲验仅 3 处最小修正（CSS 1 处+busy 门控 2 处，注释含缺陷编号），例外登记于 checklist §4-4，ui-design 零改动 → 处置成立（非降级）。
- **N/A 项处置复核**：「时间线实时追加」「人工修正回写」判 N/A（M3 写路径激活，用户裁决「Action 指向待 M3」）；`?tab=` 审计页判 N/A（M5 页）——均有裁决/规划依据，成立。
- **亲自抽查 3 区块**（报告外独立验证）：①证据弹窗九信息位源码+API 双证（§5-FN-3-02）；②OS 归一化源文件值节点属性+缺原件说明显性（§5-FN-3-08/09）；③告警卡证据摘要三要素+case_ref 字段语义（§5-FN-5-09，发现 MAJOR）。另登录 13 行 diff 逐行审读（§4-6）。
- **不一致注记**：报告 §3.3 标题行「web 副本与 ui-design 原型逐字节零差异」为首轮核验时点陈述，未随 §7 修复更新（现状=3 处授权例外，checklist §4-4/图例已正确记载）→ 缺陷 M-M2-003（MINOR，报告文内自相矛盾一处）。

## 7. 台账与 TODO 对账

- **Excel Sheet03**：M2 七行（FN-3-01/02/03/08/09、FN-8-03/11）状态=**待验收**、验收要点含【M2 R1】/【M2 R2】括注——与实况相符（评审通过即转已完成，见 §9 处置）；Sheet02 FN-0-14/15=待验收，相符。抽 3 行验证（FN-3-02/3-09/8-11）括注内容与本评审实测一致，无「已完成」虚标行。
- **Excel Sheet03 FN-5-09 未回填**（状态仍「未开始」）：读侧 API 实际已部分交付（§5），属 P00 §7「台账回填」遗漏 → 缺陷 M-M2-005（MINOR）。**本评审已按 P10 §3 MAJOR 处置规则将 M-M2-MAJOR-01 注记补登至 FN-5-09 行**（状态改「进行中」+验收要点括注，xlsx 备份 `~/M2-gate-xlsx-backup.xlsx`）。
- **TODO 对账**：全仓标记集 = {H24, H25, H29, H38, H39} ∪ {CON-06, CON-09, CON-12, CON-13, CON-14}，全部在 P00 §6 许可集内且逐项登记于 `contracts/CHANGELOG.md` 未决表（60-69 行）→ **无清单外 TODO，无口径漂移**。M2 区间新增仅 `TODO(H39)` ×2（租户数据驻留推断标注+login note 同源），合规。H30 余项以页面文案注记（清单附录 D 在册条目），非 TODO 标记面。
- **契约变更记录**：CHANGELOG ⑦（COMPAT v1.1.0）完整登记 link_type 增补/三响应 Schema/adapters 种子/聚合口径裁决/北向零改动声明——本次抽查文件与登记相符。

## 8. 缺陷清单

| 编号 | 级别 | 现象与复现 | 关联 FN | 处置 |
|---|---|---|---|---|
| **M-M2-MAJOR-01** | MAJOR | 告警 `case_ref` 恒 null：`seed_loader.py:293-297` 取 enum-registry 案件号 pattern（全锚定 `^…$`）对 `meta` 做 `re.search`，锚定使含前后文的 meta 永不命中→`alerts-response.schema.json` 描述的「从 meta 解析」不成立→`dashboard.py:86` 引用存在性交叉校验对真实数据空转→`test_api_dashboard.py:162` 子集断言在空集恒真。复现：`GET /v1/alerts?instance=cn`（0385/0381 的 meta 明含案件号而 case_ref=null）；R1 自检「alerts 引用案件存在性=服务侧真实校验」因此项失真 | FN-5-09（读侧）、CON-B5 精神（可审计引用） | **M3 首个工作包**：改子串提取（去锚定/边界匹配，仍源自 registry）+非空断言测试补盲（对 0385/0381/0122 等逐案钉死）；Excel FN-5-09 行已注记（评审补登） |
| **M-M2-MAJOR-02** | MAJOR | 一键入口崩溃：`hub.py all` 于 verify 步 `KeyError: 'verify'`（`main_one` 分发表仅收录复合子命令，`main` 的 verify/all 组合分支未注册进 dispatch）。RUNBOOK:72 与 Makefile:59、hub.py docstring 均文档化为「离线全量校验」可用，实测必崩。复现：`python scripts/hub.py all`（本会话亲测；单项 clean/seed/verify/test 全可用） | P07 交付面（随 R2 入账，无直接 FN） | **M3 首个工作包**：`main_one` 补 `verify`/`all` 复合分发（3 行）+一条 `hub.py all` 退出码断言入 run-issues 回归 |
| M-M2-003 | MINOR | 画面报告自相矛盾：§3.3 标题行仍称 login「web 副本与原型逐字节零差异」，与 §7-F02 修复（3 处例外）冲突；checklist 图例/§4-4 已正确记载，唯报告未更新 | P09 报告 | backlog：报告随 M3 批次修订一行注记 |
| M-M2-004 | MINOR | `registry.py:25` docstring 陈旧：「19 类/115 值，v1.0.0 冻结」，现值 20 类/120 值/v1.1.0（M2 契约 ⑦ 升版后未刷注释） | FN-0-15 周边文档 | backlog：注释修正 |
| M-M2-005 | MINOR | Excel Sheet03 FN-5-09 未回填（读侧 API 已部分交付，状态仍「未开始」）——P00 §7 收工单第 5 项执行遗漏 | FN-5-09 | 本评审已代补 MAJOR 注记（§7），M3 会话复核文字 |
| OBS-集合 | 观察 | ①FN-8-11「连续达标天数」「平均等待/SLA」子项原型/seed 无源未呈现，建议 M5 与 FN-8-12 同源聚合收口；②demo 态非法 `?case=` 白屏（OBS-5，原型同型，live 已防护）建议 M3 接线顺手加格式校验；③`dashboard.adapter_status` API 字段未被页面消费（适配条静态=seed，check_seeds_vs_ui 防漂移，R2 口径已登记）；④`web/api-portal.html`/`demo-landing.html` 文案含旧仓路径字样（原型继承，M5 接线时口径处理）；⑤`ui-design/` 在 git 仓外，P03 验收⑤「git status 零改动」不可直接执行——本评审以 mtime+零接线痕迹+副本 diff 三重证据替代（建议 RUNBOOK 固化替代验证法）；⑥`ui-verification-M2-shots` 仅存首轮证据（13 张未含修复后回归图，回归断言以脚本结果为准——P09 报告 §7 数字与本会话复跑吻合） | 多 | 汇入 backlog，不阻塞 |

## 9. 结论

**M2 门禁判定：有条件通过。**

- P03 §4 验收标准六条 **6/6 PASS**（规划 §4-M2 验收三要点全覆盖）；一致性/契约/聚合核算/依赖纪律/画面验证均经本评审会话**独立亲跑复核**，自述数字（171 passed、120/120、40 项、41 组、10/10、131+16 断言 0 FAIL）全部复现成立。
- 放行条件（**M3 首个工作包，未完成不得顺延**）：**M-M2-MAJOR-01**（case_ref 解析修复+测试补盲）、**M-M2-MAJOR-02**（`hub.py all` 分发修复）。两缺陷均局部可修、不触红线、不破坏 demo 演示与页面一致性，故不构成 BLOCKER。
- MINOR×3（M-M2-003/004/005）汇入 backlog；OBS 集合移交对应里程碑。Excel Sheet03 FN-3-01/02/03/08/09、FN-8-03/11 及 Sheet02 FN-0-14/15 由「待验收」转「已完成（M2 验收通过）」——该状态刷新随 M3 首个收工提交执行（评审会话不改代码仓）。
- **下一里程碑放行**：M3（受理与写路径）可开工；开工顺序约束：MAJOR-01/02 置于 WP3.1 之前或同批；M1 遗留 M-M1-003（RI-M2-004）照旧在 M3 查重/验真接线中关闭；写路径激活后须按裁决复验 P09 case-detail 两行 N/A 项（时间线实时追加/人工修正回写）。
- 桩纪律复核：本里程碑无新桩引入（税局通道/SM2/Provider 桩面属 M3+）；SSO/MFA 登录为演示桩且页面口径不变（亲验 G 系列 PASS）。

---

*评审会话：P00+P10 · 独立验收评审员（未参与实现）· 亲跑证据见 §2/§6 · 工作树已复原（`git status` clean、截图证据包回滚至 bda4e54 原状、:8000 接线态恢复、xlsx 备份于会话外）*
