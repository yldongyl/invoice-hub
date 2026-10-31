# invoice-hub · RUNBOOK（运行手册 · P07 终验版 · 2026-10-28）

全球采购平台票据智能与合规中台 —— 干净环境一键启动全栈并冒烟验证的操作基准。

**当前里程碑状态：M5 全功能收口终验完毕（全栈生产就绪态）**：
- `backend/` 确定性核心服务（FastAPI 端口 8000，同源静态托管 `web/`，零 LLM 依赖）；
- `agent/` LangGraph Agent 域服务（端口 8001，多意图对话与主动调查编排，零 DB 直连）；
- `mcp/` MCP Server 网关服务（端口 8002，streamable-http 协议，6 项标准工具与 OAuth2 双 scope）；
- `web/` 12 页面运行副本全量接线打通真实 API，并保留 `demo-mode.js` 离线回退能力；
- 双向契约校验（契约↔种子、枚举↔台账、UI↔契约、API 门户同步）与 8 大 Demo 场景回放全部可用。

---

## 1. 前置条件与安装

| 项 | 要求 |
|---|---|
| Python | **≥3.11**（`pyproject.toml requires-python`；本仓在 3.13 与 3.14 实测全量通过） |
| pip 流 | `cd backend && pip install -r requirements-dev.txt`（运行+测试+校验全量） |
| uv 流（推荐，精确重现） | 安装 uv 后：`cd backend && uv sync --extra dev`（按 `uv.lock` 锁定包，自动建 `.venv/`；后续命令用 `uv run python scripts/...` 或激活 venv） |
| 零外部服务强依赖 | 默认 **SQLite**（`runtime/invoice_hub.db`）+ **本地目录**对象存储 + **进程内**队列；无需预装 PostgreSQL/MinIO/Redis 即可完成全链路运行与冒烟 |

**Windows / macOS / Linux 差异说明**：
- Windows Git-Bash 通常无原生 `make` → 直接使用等价入口 `python scripts/hub.py <command>`（Makefile 仅为薄封装）；`scripts/hub.py` 内置自动解析 `backend/.venv` 虚拟环境解释器，避免依赖缺失；
- Windows 控制台默认 cp1252：仓库内所有 CLI 入口（seed_loader/tools/smoke/hub.py）已强制 stdout UTF-8 输出；手工执行 pytest 乱码可设置 `set PYTHONIOENCODING=utf-8`；
- 路径含空格（如本仓 `Virtual Project Part2`）已实测全链路平滑兼容。

**组件切换（可配置，ADR-0002 PoC 口径）**：

| 组件 | 默认 | 切换方法 |
|---|---|---|
| 数据库 | SQLite `runtime/invoice_hub.db` | 环境变量 `INVOICE_HUB_DATABASE_URL=postgresql+psycopg://user:pwd@host:5432/invoice_hub`（需 `pip install psycopg[binary]`），切换后重跑 seed |
| 对象存储 | 本地目录桩：受理原件内容寻址落 `runtime/objects/intake/{2hex}/{sha256}`（`app/services/object_store.py`） | MinIO / S3：经 S3 兼容 endpoint 替换 `object_store.py` 单点实现（业务代码不感知底层路径规则） |
| 队列 | 进程内（`app/workers/retry.py` 演示口径登记式；受理步骤态落 `file_steps` 表） | Redis：独立 Celery / Redis Queue worker 消费对应 FN-9-07 |

---

## 2. 首次启动流程（干净 clone / 环境从零启动）

```text
① 安装依赖          cd backend && uv sync --extra dev        （或 pip install -r requirements-dev.txt）
② 种子装载          python scripts/hub.py seed                （幂等重建，23 类资产 / 244 行）
③ 启动全栈          python scripts/hub.py run                 （backend 8000，同源托管 web/）
④ 打开页面          http://localhost:8000/                    （根路径自动 307 重定向至登录页；登录后进入总览仪表盘）
⑤ 冒烟验证          python scripts/hub.py smoke               （另开终端执行，十步逐项验证 10/10 PASS）
⑥ 启动可选服务      python scripts/hub.py run-agent           （端口 8001，LangGraph Agent 域）
                    python scripts/hub.py run-mcp             （端口 8002，MCP Server 网关）
```

浏览器控制台检查接线态：`document.body.dataset.ihubMode === 'live'`（无演示角标，连接真实后端）。

---

## 3. 三种运行形态

| 形态 | 启动方式 | 表现与特性 |
|---|---|---|
| **A 全栈（接线态）** | `hub.py run`（+ 可选 `run-agent` / `run-mcp`），浏览器打开 `http://localhost:8000/` | 根路径进入登录页；登录成功后 12 个页面全部走 `/v1`、`/api` API，真实消费后端数据与状态流转；`demo-mode.js` 探测 `/healthz` 成功，设置 `ihubMode='live'`，隐藏演示角标 |
| **B 仅核心（Core API 态）** | 仅启动 `hub.py run`（不依赖前端页面或 Agent/MCP） | 完整提供 RESTful API，用于系统集成、自动化测试与第三方调用；`/healthz` 返回 ok；`/v1/dashboard`、`/v1/cases` 等全量端点可用 |
| **C 独立演示（demo-mode 回退态）** | **不启动 backend**：双击 `web/*.html`（`file://` 协议）或启动独立静态服务器（`python -m http.server 8001 -d web`） | 页面顶部常驻橙色角标「演示模式（未连接后台）· 页面显示内嵌种子数据（L2 演示口径）」；页面平滑回退至内嵌 mock 数据（与 seed 严格同源），所有卡片、图表、案件详情与弹窗均可完整走查交互 |

---

## 4. 端口与进程表

| 进程 | 启动命令 | 默认端口 | 状态与说明 |
|---|---|---|---|
| backend（含 web 静态托管） | `make run` / `python scripts/hub.py run` | **8000** | ✅ 生产就绪；FastAPI 同源托管 `web/`，根路径 307 重定向至登录页 |
| agent（LangGraph） | `make run-agent` / `python scripts/hub.py run-agent` | **8001** | ✅ M5 实装；三意图对话图编排、主动调查取证，严格零 DB 直连 |
| mcp（MCP streamable-http） | `make run-mcp` / `python scripts/hub.py run-mcp` | **8002** | ✅ M5 实装；6 项标准工具（4 只读 + 2 受控写），OAuth2 双 scope 鉴权 |
| workers | 随 backend 进程内挂载或 `make run-workers` | — | 受理流水线（步骤态落库）+ 断点续跑登记；通道 Job 手动触发见 §5.1 |

---

## 5. 常用命令表（Makefile ↔ scripts/hub.py 完全等价）

| 命令 | 等价 CLI | 作用与说明 |
|---|---|---|
| `make seed` | `python scripts/hub.py seed` | 全量种子装载（幂等重建：23 类资产 / 244 行，哈希链与编号计数器播种） |
| `make run` | `python scripts/hub.py run [--port 8000] [--reload]` | 启动 backend 核心服务 |
| `make run-agent` | `python scripts/hub.py run-agent [--port 8001]` | 启动 LangGraph Agent 服务（端口 8001） |
| `make run-mcp` | `python scripts/hub.py run-mcp [--port 8002]` | 启动 MCP Server 网关（端口 8002） |
| `make test` | `python scripts/hub.py test` | 全部测试套件（M5 终验态 371 passed，1 skipped，0 failure） |
| `make test-e2e` | `python scripts/hub.py test-e2e` | E2E 场景断言测试（`pytest -m scenario`） |
| `make test-redline`| `python scripts/hub.py test-redline` | 红线回归测试集（`pytest -m redline`，P08 §1.4 必跑项） |
| — | `python scripts/demo_replay.py` | 蓝图 §13.2 八大 Demo 场景端到端自动化回放走查 |
| `make smoke` | `python scripts/hub.py smoke [--base URL]` | 十步冒烟检查（必须先启动 backend） |
| `make verify-enums` | `python scripts/hub.py verify:enums` | 枚举注册表与 Excel Sheet08 142 行逐字严格核对 |
| `make verify-contracts` | `python scripts/hub.py verify:contracts` | 契约 Schema 语法结构与种子合法性交叉校验（40 项全绿） |
| `make verify-ui` | `python scripts/hub.py verify:ui` | 种子数据与原型页面一致性交叉校验 |
| — | `python tools/verify_portal_sync.py` | API 门户页面与 contracts 机器可读契约同步性校验 |
| `make verify` | `python scripts/hub.py verify` | 顺序执行 enums、contracts、ui 三项静态校验 |
| `make clean` | `python scripts/hub.py clean` | 数据重置：删除 `runtime/invoice_hub.db` 数据库 |
| `make all` | `python scripts/hub.py all` | 离线完整流水线：clean → seed → verify → test → test-redline |
| `make intake-demo` | `python scripts/hub.py intake:demo-drop` | 投放信箱与 DOX 样例件（XML 发票、框架合同、UBL 发票、Order Response） |
| `make intake-mailbox` | `python scripts/hub.py intake:poll-mailbox` | 手动触发供应商邮箱通道拉取 Job（15 分钟 Job 演示等效） |
| `make intake-dox` | `python scripts/hub.py intake:poll-dox` | 手动触发 SAP DOX 桥接通道拉取 Job |

### 5.1 通道桩操作基准（演示口径 · 手动触发即 15 分钟 Job 等效）

**目录约定**（本地模拟，不发起真实外部网络呼叫，均在 `runtime/` 下自动创建）：

| 通道 | 投递（进） | 处理存档 | 回执/退回（出） |
|---|---|---|---|
| 供应商邮箱 | `runtime/mailbox/inbox/*.json`（信封：from/subject/attachments[{name,content_b64}]） | `runtime/mailbox/processed/` | `runtime/mailbox/outbox/reject-*.json`（非发票退回通知模板渲染） |
| SAP DOX（海外） | `runtime/dox/inbox/*.json`（传输信封：participant_id/document_type/name/content_b64） | `runtime/dox/processed/` | `runtime/dox/rejected/`（参与方 ID 核对不符或业务退回） |
| Webhook 回调 | — | — | `runtime/webhook-outbox/evt-*.json`（含 X-Signature HMAC 演示头） |

**通道走查演示步骤**：
```text
python scripts/hub.py intake:demo-drop        # ① 投放样例文件
python scripts/hub.py intake:poll-mailbox     # ② 触发邮箱拉取 Job → 输出处理批次
python scripts/hub.py intake:poll-dox         # ③ 触发 DOX 拉取 Job → 输出处理批次
# 接口核验：GET /v1/batches · GET /v1/intake/kpi · 页面查看 /web/invoice-intake.html
```

---

## 6. 冒烟检查（make smoke 十步）

针对运行中后端执行标准化冒烟套件（`python scripts/hub.py smoke`），顺序执行以下 10 步断言：
1. **01 healthz**：`GET /healthz` 返回 HTTP 200 且 `status == "ok"`；
2. **02 seed 装载断言**：`GET /v1/cases` 确认 CN（7 案）+ OS（4 案）共 11 案件全部在库；
3. **03 dashboard 聚合**：双实例 KPI 数值非空、红线对照布尔值为布尔类型、Top 5 案件列表完整、告警与适配器状态正常；
4. **04 case-detail 三案聚合**：`0387`、`0379`、`0125` 三案全量聚合数据通过 `invoice-case.schema.json` 模式校验；
5. **05 证据查询**：`0387` 案 `total.gross_amount` 字段证据七要素（page、bbox、raw_text、rule、model_version、provider 等）齐备无缺失；
6. **06 时间线查询**：`0387` 案 11 个事件码全部收录于 `enum-registry.json` 的 `timeline_event` 规范枚举词汇中；
7. **07 审计链完整性**：底层哈希链重验函数 `verify_chain` 验证 CN、OS、PLATFORM 三域全部绿灯；
8. **08 受控写拒绝路径**：向 `/actions/release` 发送缺少有效 `confirm_token` 的请求，验证五要素守门框架严格拦截（返回 4xx 并携带标准受控错误码）；
9. **09 web 静态可达**：根路径重定向可达、登录页/总览页面 200、共享脚本 `auth-guard.js` / `api-client.js` 可达；
10. **10 demo-mode 回退在位**：`demo-mode.js` 逻辑完备（包含 `/healthz` 探针和角标注入逻辑），关键页面均包含接线与回退标志。

---

## 7. 桩做边界清单（演示口径 · P00 §6 / 实施规划 §6）

| 域 | 桩做方式 | 代码/演示位置 | 说明 |
|---|---|---|---|
| **商业 Provider**（百望云/诺诺/海外 e-invoicing 等） | SPI stub（按 provider-spi.schema 返回归一化结果并模拟时延成本） | `backend/app/services/providers/`；`seeds/providers.json` | 6 实例已就绪；支持配置中心热切换、健康探测与动态故障降级（M4 实装） |
| **SM2 验签** | **算法真实（gmssl 库 SM2+SM3），证书链模拟**（演示 CA 固定密钥对，`TODO(FN-9-10/FR-L1-05)`） | `backend/app/services/sm2_service.py` | 验签回执 `gm-rcpt-*` PASS 与 FAILED 均生成并随案归档至 `runtime/gm-receipts/`；验签失败强制入 BLOCKED 红线 |
| **税局授权查验** | **模拟通道激活**（模式：pass/timeout/off）；超时转 NOT_VERIFIED 触发指数退避重试 | `backend/app/services/verify_channel.py`；`app/workers/retry.py` | 同票缓存去重计费，外呼登记 `EgressLog` 审计台账 |
| **SAP DOX / 邮箱通道** | DOX 桥接桩（目录投递，参与方 ID 与信封校验真实执行）；邮箱本地信箱模拟 15 分钟定时 Job | `backend/app/services/channels_ops.py` | 手动触发 CLI 命令等效定时拉取，原件内容寻址落盘 |
| **Ariba / ERP 建档** | 沙箱网关 stub（五步链路真实执行、回执模拟） | `backend/app/services/adapter_service.py` | Schema 校验 → 报文组装 → 签名 → 发送 → 回执归档全链路执行；支持 Ariba cXML 及多种目标适配器 |
| **SSO / MFA / KMS** | 演示桩 + 真实校验引擎 | `backend/app/services/identity_service.py`；`rbac_service.py`；`platform_config_service.py` | 4×7(8) 动态权限矩阵实装；SSO 服务端二次校验真实；用户强制 MFA；KMS 凭证全掩码（`****xxxx`）与轮换留痕 |
| **LLM / Agent 域** | LangGraph Agent 服务（M5 实装）；backend 零大模型依赖 | `agent/conversation_graph.py`；`agent/investigation_graph.py` | 真实调度 backend 内部 API，蓝标查询与橙标 AI 线索严格分离，免责声明齐备，对话零写操作 |
| **监控自探针** | 6 大核心服务状态监控与 24 小时趋势序列 | `backend/app/services/monitoring_service.py` | `/healthz` 作为外部探针，平台管理页呈现聚合指标 |
| **数据驻留** | 境内外双实例隔离，数据不出境 | `backend/app/services/tenant.py`；`tenant_service.py` | 标注 `TODO(H39)` 推断标记；双实例独立成链、分池存储 |

---

## 8. 故障排查与运维指南

| 常见症状 | 根本原因与解决方案 |
|---|---|
| **端口 8000 占用**（`[Errno 10048]` / `address already in use`） | 存在未退出的旧 backend 进程。执行 `netstat -ano \| grep 8000` 找出 PID，使用 `taskkill /PID <pid> /F`（Windows）或 `kill -9 <pid>`（POSIX）释放端口；或启动时指定其他端口：`python scripts/hub.py run --port 8010`（此时 smoke 需加 `--base http://127.0.0.1:8010`）。 |
| **`ModuleNotFoundError: No module named 'app'`** | 必须使用虚拟环境解释器并在 `backend` 目录下执行。建议始终通过顶层 `python scripts/hub.py <command>` 执行，脚本会自动解析 `.venv` 解释器并切换正确的当前工作目录。 |
| **seed 装载报错 `EnumViolation`** | 种子文件修改引入了超出枚举注册表定义的值。请对照 `contracts/enum-registry.json` 修正或按变更流程更新枚举。 |
| **seed 装载报错 `种子链自检失败 @ blk#N`** | `seeds/audit_events.json` 内容或格式被修改导致哈希链校验断裂。执行 `git checkout -- seeds/` 还原种子后重跑 `python scripts/hub.py seed`。 |
| **`make clean` 提示文件被占用（WinError 32）** | Windows 下后台服务尚未停止导致 `invoice_hub.db` 文件句柄被锁定。无需强删文件，直接执行 `python scripts/hub.py seed` 即可通过 SQLAlchemy 执行表级 `DROP TABLE / CREATE TABLE` 幂等重建并恢复演示基线。 |
| **访问业务页被跳回登录页** | live 后端可达时 `web/js/auth-guard.js` 会强制校验会话。请先访问 `http://localhost:8000/` 登录；账号密码演示可用 `王莉` / 任意非空密码 / MFA `123456`，SSO 按钮会调用后端 SSO 演示接口并锁定租户。 |
| **前端页面显示「演示模式（未连接后台）」** | 前端无法连通 `/healthz` 端点（常见于直接从文件系统 `file://` 打开或未启动 backend）。启动 `python scripts/hub.py run` 后刷新页面即可自动切换为 `live` 状态。 |
| **页面风格消失 / 像裸 HTML** | Tailwind 已本地构建为 `/web/css/invoice-hub.css`，页面不再依赖外网 CDN。若样式缺失，先检查 `http://localhost:8000/web/css/invoice-hub.css` 是否 200；若文件不存在或主题类缺失，在 `invoice-hub/` 下执行 `npm install`（首次）与 `npm run build:css` 后重启/刷新页面。 |
| **依赖纪律检查误报（包含 `llm` 等子串）** | 扫描时误将 `.venv` 安装依赖目录或测试函数名称纳入。严格遵守扫描过滤：`grep -rn "langgraph\|openai\|llm" backend/ --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__`。 |

---

## 9. 数据重置方法（恢复纯净演示态）

```text
python scripts/hub.py clean   # 清理数据库（若文件被占用，直接执行下一步 seed 亦可）
python scripts/hub.py seed    # 表级幂等重建：23 类资产 / 244 行，哈希链与编号计数器播种
```
重置后所有数据严格恢复至 M0 冻结口径（如 0379 BLOCKED、0387 NEEDS_REVIEW 等演示六态分布）。
若需同时清理运行期生成的外部附件与投递件，可手动删除以下临时目录（重新执行通道 Job 时将按需自动重建）：
```text
rm -rf runtime/objects runtime/mailbox runtime/dox runtime/webhook-outbox runtime/gm-receipts
```

---

## 10. TODO(H/CON) 扫描汇总（与代码实态 100% 一致 · M5 终验扫描）

代码全局扫描命令：
```text
grep -rn "TODO(" backend/app agent mcp web/js --include=*.py --include=*.js
```

全库现存 9 处演示口径及规范标注（无遗漏、无失效）：
1. `backend/app/services/channels_ops.py:9`：`TODO(FN-9-10)`（X-Signature / 回调 HMAC 演示密钥，正式实现需对接 KMS 托管）；
2. `backend/app/services/channels_ops.py:91`：`TODO(FN-9-10)`（真实凭证 KMS 托管注记）；
3. `backend/app/services/governed_commands.py:213`：`TODO(M3/FN-1-04)`（生成退回邮件通知·演示桩通道注记）；
4. `backend/app/services/intake_pipeline.py:418`：`TODO(M4)`（OCR stub 识别正式接入 SPI 契约）；
5. `backend/app/services/recognize.py:7`：`TODO(FN-9-10)`（API 密钥 HMAC 校验，正式实现需对接 KMS 托管）；
6. `backend/app/services/sm2_service.py:6`：`TODO(FN-9-10/FR-L1-05)`（SM2 证书链模拟，正式实现需对接证书链管理与 KMS）；
7. `backend/app/services/sm2_service.py:28`：`TODO(FN-9-10 / FR-L1-05)`（演示 CA 固定密钥对注记）；
8. `backend/app/services/sm2_service.py:113`：`TODO(FN-9-10/FR-L1-05)`（验签回执随案归档与证书链模拟注记）；
9. `backend/app/services/tenant.py:40`：`TODO(H39)`（数据驻留细则推断标注）。

其余架构未决项均已登记收敛于 `contracts/CHANGELOG.md` 及 Excel 工作台账。
