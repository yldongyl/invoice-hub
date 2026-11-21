# invoice-hub · 全球采购平台票据智能与合规中台

> **工程定位**：将不同国家、格式、渠道、Provider 输出的**供应商采购发票**（PO/non-PO、数电票、增值税票、海外 Supplier Invoice / Credit Note / Debit Note），统一转成采购平台/ERP 可用、可信、可审计、可匹配的数据。
> **业务边界外**（禁止出现任何入口/文案/代码）：员工报销、差旅餐饮票、销项开票、税务申报、银行对账、资金支付。

当前里程碑：**M5 · 全功能收口终验完毕（全栈生产就绪态）**。

- `backend/`：确定性核心服务（FastAPI 端口 8000，同源静态托管 `web/`，零 LLM 依赖）；
- `agent/`：LangGraph Agent 域服务（端口 8001，多意图对话与主动调查编排，零 DB 直连）；
- `mcp/`：MCP Server 网关服务（端口 8002，streamable-http 协议，6 项标准工具与 OAuth2 鉴权）；
- `web/`：12 页面运行副本全量接线真实 API，保留 `demo-mode.js` 离线演示回退。

## 目录说明

```text
invoice-hub/
├── contracts/            # 机器可读契约（唯一事实源，M0 冻结）
│   ├── openapi.yaml                 # 集成 API（FN-A-01/02/03）
│   ├── invoice-case.schema.json     # 案件聚合（FN-0-01/05/07）
│   ├── invoice-schema.json          # 统一 Schema 字段路径（FN-0-03 · CON-03 决议）
│   ├── enum-registry.json           # 全站枚举注册表（Excel Sheet08，FN-0-15）
│   ├── events.schema.json           # 时间线事件模型 + Webhook 四事件（FN-0-10 / FN-A-03）
│   ├── mcp-tools.json               # MCP 6 工具与权限级别（FN-A-04）
│   ├── provider-spi.schema.json     # 南向 SPI 三方法 + ProviderResult 归一化（FN-A-05）
│   ├── routing-config.schema.json   # 路由/降级策略配置（FN-2-08/10 · FN-A-05）
│   ├── adapter-contract.schema.json # 东向 Ariba cXML 建档契约骨架（FN-A-06）
│   ├── field-alias.md               # 规格 v0.3 旧命名 ↔ 新路径对照（CON-03/05）
│   └── CHANGELOG.md                 # 契约变更记录账本（FN-A-07）
├── backend/              # 确定性核心（FastAPI 8000，零 LLM 依赖，同源静态托管 web/）
├── agent/                # LangGraph Agent 域（端口 8001，三意图图编排与主动调查，只调 backend API）
├── mcp/                  # MCP Server（端口 8002，6 工具 = 4 只读 + 2 受控写）
├── web/                  # ui-design 12 页的接线副本（已接通 live API，保留 demo-mode 离线回退）
├── seeds/                # 种子数据（23 类资产 / 244 行，前后台同源基线）
├── docs/                 # adr/ + gate-reports/ + RUNBOOK.md（运行手册）
├── scripts/              # 运行入口 hub.py（与 Makefile 等价，跨平台支持 Windows）
├── runtime/              # 运行时数据（SQLite DB、对象存储桩、通道收件箱、日志）
├── tests/                # 单元测试、契约测试、E2E 场景测试（pytest -m scenario/redline）
└── tools/                # 自检脚本：check_enums.py、validate_contracts.py、smoke.py 等
```

## 文档树与单一事实源（冲突时优先级从高到低）

| 优先级 | 文档 | 路径 |
|---|---|---|
| 1 | 机器可读契约 | `invoice-hub/contracts/` |
| 2 | 细化功能清单 MD | `../细化功能清单/采购平台票据智能与合规中台-细化功能清单.md` |
| 3 | 实施规划 MD | `../细化功能清单/invoice-hub实施规划.md` |
| 4 | 细化功能清单 Excel | `../细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx` |
| 5 | UI 设计基准（只读） | `../ui-design/*.html`（12 页）+ `design-system.md` |

## 快速开始与工程启动

完整运行与运维操作详见 [docs/RUNBOOK.md](docs/RUNBOOK.md)。本仓所有运行与测试命令均支持 `python scripts/hub.py <command>` 与 `make <command>` 双入口（Windows 环境下无 make 时可直接通过 `python scripts/hub.py` 执行，脚本内置自动解析 `backend/.venv` 虚拟环境解释器）。

### 1. 环境准备

- **Python**：≥ 3.11（推荐 Python 3.12 / 3.13）
- **零外部服务强依赖**：默认开箱采用 **SQLite**（`runtime/invoice_hub.db`）+ 本地目录对象存储 + 进程内队列，无需预装 PostgreSQL / MinIO / Redis 即可全栈运行。
- **安装依赖**：
  ```bash
  cd backend
  # 方式 A：uv 流（推荐）
  uv sync --extra dev

  # 方式 B：pip 流
  pip install -r requirements-dev.txt
  cd ..
  ```

### 2. 标准启动流程（核心五步，Web + API 全可用）

```bash
# ① 装载种子数据（幂等初始化：装载 23 类资产 / 244 行种子数据，初始化哈希链与编号计数器）
python scripts/hub.py seed

# ② 启动全栈核心服务（FastAPI 端口 8000，同源静态托管 web/ 12 页面）
python scripts/hub.py run

# ③ 浏览器访问
# 打开 http://localhost:8000/
# 根路径自动 307 重定向至登录页；演示账号：王莉 / 密码任意 / MFA 验证码：123456
# 登录后进入总览仪表盘，控制台打印 ihubMode='live'，已直连真实后端

# ④ 冒烟检查验证（另起终端执行，十步全绿 PASS）
python scripts/hub.py smoke

# ⑤（可选）启动扩展服务（见下节「全功能三服务态」）
python scripts/hub.py run-agent   # 端口 8001：LangGraph Agent 域（多意图对话与主动调查）
python scripts/hub.py run-mcp     # 端口 8002：MCP Server 网关（6 项标准工具）
```

> **提示**：若系统环境已配置 `make`，上述命令亦可直接使用 `make seed`、`make run`、`make smoke` 等等价执行。

### 2.5 全功能三服务态（backend + agent + mcp，支撑全量测试）

启用 Agent 域与 MCP 网关的完整链路需三个服务同时在线，**三个终端**分别执行：

```bash
# 终端 1 —— backend（端口 8000）。⚠️ 全功能态必须关闭服务端登录门禁：
# Agent/MCP 的 BackendClient 按设计只携带自身鉴权（MCP OAuth2），不携带 web 会话票据，
# backend 的 /v1 与 /api 门禁（app/main.py auth_gate）会使其跨服务只读调用返回 401→空结果。
# 演示口径：INVOICE_HUB_DISABLE_AUTH=1 放开该门禁（web 登录流程与页面守卫不受影响，实测 smoke 十步仍全绿）。
INVOICE_HUB_DISABLE_AUTH=1 python scripts/hub.py run
#   cmd.exe 写法：set INVOICE_HUB_DISABLE_AUTH=1 && python scripts/hub.py run
#   PowerShell 写法：$env:INVOICE_HUB_DISABLE_AUTH="1"; python scripts/hub.py run

# 终端 2 —— agent（端口 8001，LangGraph 域，零 DB 直连，只调 backend API）
python scripts/hub.py run-agent

# 终端 3 —— mcp（端口 8002，streamable-http，6 工具 = 4 只读 + 2 受控写，OAuth2 双 scope）
python scripts/hub.py run-mcp
```

三服务在线后的功能核验（另起终端）：

```bash
# 探活三连
curl http://127.0.0.1:8000/healthz   # {"status":"ok",...}
curl http://127.0.0.1:8001/healthz   # {"status":"healthy","service":"invoice-hub-agent","model":"qwen-finance-v2",...}
curl http://127.0.0.1:8002/healthz   # {"status":"healthy","tools_count":6,...}

# Agent 对话（意图分类→只读工具链→蓝标查询/橙标 AI 线索分离→免责声明→trace）
curl -X POST http://127.0.0.1:8001/v1/agent/chat -H "Content-Type: application/json" -d '{"query":"查一下案件 0387 的状态","actor":"王莉"}'

# MCP 握手：签发 OAuth2 令牌（演示凭证，scope 仅认 invoice.read / invoice.write.controlled）
TOKEN=$(curl -s -X POST http://127.0.0.1:8002/oauth/token -H "Content-Type: application/json" \
  -d '{"grant_type":"client_credentials","client_id":"joule-agent-client-01","client_secret":"sec-demo-9f8a32b1","scope":"invoice.read invoice.write.controlled"}' \
  | python -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
# 只读工具实调（应返回真实种子案件投影）
curl -s -X POST http://127.0.0.1:8002/mcp/v1/tools/call -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"name":"case.search","arguments":{"status":"NEEDS_REVIEW"}}'
# 受控写工具缺 confirm_token → 428/E_CONFIRM_TOKEN_REQUIRED 强制拒绝（AI 禁止静默写）
```

> 环境变量速查（均有默认值，可覆盖）：`INVOICE_HUB_DISABLE_AUTH`（全功能态置 1）、`INVOICE_HUB_BACKEND_URL`（agent/mcp → backend，默认 `http://127.0.0.1:8000`）、`INVOICE_HUB_MODEL_NAME` / `INVOICE_HUB_MODEL_VERSION`（演示口径 `qwen-finance-v2` / `2026-10-15`）、`INVOICE_HUB_MCP_HOST` / `INVOICE_HUB_MCP_PORT`（默认 `0.0.0.0:8002`）、`INVOICE_HUB_CLIENT_ID` / `INVOICE_HUB_CLIENT_SECRET`（MCP OAuth2 演示凭证）、`INVOICE_HUB_DATABASE_URL`（切 PostgreSQL，见 RUNBOOK §1）。
>
> Agent/MCP 域**零 LLM 外呼强依赖**：模型客户端为可替换演示实现（审计留痕/版本/置信度齐备），无需配置任何 API Key 即可全功能运行。
>
> **2026-11-16 修复**：`run-agent` / `run-mcp` 此前在 uvicorn 以 `backend/` 为工作目录时无法导入顶层 `agent`/`mcp` 包（`ModuleNotFoundError`）；`scripts/hub.py` 现自动为二者注入 `PYTHONPATH=仓库根;backend`，开箱即用。

### 3. 三种运行形态

| 形态 | 启动方式 | 特性说明 |
|---|---|---|
| **A. 全栈接线态（推荐）** | `python scripts/hub.py run`，访问 `http://localhost:8000/`；**全功能三服务态**再叠加 `run-agent` + `run-mcp` + `INVOICE_HUB_DISABLE_AUTH=1`（见 §2.5） | 12 个页面全部走真实 `/v1`、`/api` RESTful API，消费后端数据与状态机流转；全功能态下 Agent 对话（8001）与 MCP 工具网关（8002）同步在线。 |
| **B. 核心 API 态** | 仅启动 `python scripts/hub.py run` | 供系统集成调用、自动化测试或 MCP/Agent 消费，健康探针为 `/healthz`。 |
| **C. 离线演示态（回退）** | **不启动后端**，直接浏览器打开 `web/*.html` 或 `python -m http.server 8001 -d web` | 前端探测到后端不可达时触发 `demo-mode.js` 回退，页面右上角常驻橙色角标，以同源内嵌数据支持完整演示交互。 |

### 4. 常用管理与验证命令

| 操作 | 命令（CLI 入口） | 等价 Makefile | 说明 |
|---|---|---|---|
| 种子装载 | `python scripts/hub.py seed` | `make seed` | 数据库表级幂等重建与初始种子装载 |
| 服务启动 | `python scripts/hub.py run` | `make run` | 启动 backend 确定性核心（端口 8000；全功能态加 `INVOICE_HUB_DISABLE_AUTH=1`，见 §2.5） |
| 启动 Agent | `python scripts/hub.py run-agent` | `make run-agent` | 启动 LangGraph Agent 服务（端口 8001） |
| 启动 MCP | `python scripts/hub.py run-mcp` | `make run-mcp` | 启动 MCP Server 网关（端口 8002） |
| workers 说明 | `python scripts/hub.py run-workers` | `make run-workers` | 受理流水线随 backend 进程内挂载（独立 worker 进程属 M3+ 评估） |
| 冒烟检查 | `python scripts/hub.py smoke` | `make smoke` | 运行中实例十步端到端冒烟断言（需先 `run`） |
| 全量测试 | `python scripts/hub.py test` | `make test` | 全部 pytest 套件（单元+契约+场景+红线，进程内免起服务） |
| E2E 场景测试 | `python scripts/hub.py test-e2e` | `make test-e2e` | 场景断言测试（`pytest -m scenario`，17 条：M3×5+M4×5+M5×7） |
| 红线回归集 | `python scripts/hub.py test-redline` | `make test-redline` | 关键红线断言回归集 R-01~R-06（`pytest -m redline`） |
| Demo 场景回放 | `python scripts/hub.py demo-replay` | `make demo-replay` | 蓝图 §13.2 八大 Demo 场景端到端回放走查 |
| 静态校验 | `python scripts/hub.py verify` | `make verify` | 依次执行四项：enums / contracts / ui / contracts-sync |
| 通道桩·投放 | `python scripts/hub.py intake:demo-drop` | `make intake-demo` | 投放演示信箱/DOX 样例件（XML 发票+非发票+UBL+Order Response） |
| 通道桩·邮箱 Job | `python scripts/hub.py intake:poll-mailbox` | `make intake-mailbox` | 手动触发邮箱拉取（15 分钟定时 Job 演示等效） |
| 通道桩·DOX Job | `python scripts/hub.py intake:poll-dox` | `make intake-dox` | 手动触发 SAP DOX 桥接拉取 |
| 数据重置 | `python scripts/hub.py clean` | `make clean` | 清除 `runtime/invoice_hub.db` SQLite 数据库 |
| 全量离线流水线 | `python scripts/hub.py all` | `make all` | clean → seed → verify → test → test-redline 一键离线门禁 |

### 5. 全量测试矩阵（离线套件 + 在线验证两层口径）

| 层 | 命令 | 前置 | 覆盖与实测基线 |
|---|---|---|---|
| 静态一致性 | `hub.py verify` | 无（不依赖服务与数据库） | 四项门禁：枚举↔Excel 台账逐字、契约 Schema↔种子 40 项、seeds↔ui-design 页面、api-portal↔contracts 同步+破坏性变更检测 |
| 全量 pytest | `hub.py test` | 仅依赖已安装环境 | 单元+三层契约+17 场景+红线全集，**全部进程内 TestClient 驱动，无需预启任何服务**（2026-11-16 实测 454 passed / 0 failed，约 3.5 min） |
| 场景子集 | `hub.py test-e2e` / `hub.py test-redline` | 同上 | S-M3×5 + S-M4×5 + S-M5×7；红线 R-01~R-06 零 skip |
| Demo 回放 | `hub.py demo-replay` | 同上 | 蓝图 §13.2 八大演示场景走查对照表 |
| 在线冒烟 | `hub.py smoke` | **需 `run` 已启动**（全功能联测建议按 §2.5 三服务态并带 `INVOICE_HUB_DISABLE_AUTH=1`） | 十步断言 10/10 PASS（healthz/seed 11 案/dashboard/三案聚合 Schema/证据七要素/时间线枚举/哈希链/受控写拒绝/web 可达/demo-mode 回退） |
| 通道桩走查 | `hub.py intake:demo-drop` → `intake:poll-mailbox` → `intake:poll-dox` | 需 `run` 已启动 | 邮箱/DOX 双通道受理成批；核验 `GET /v1/batches`、`/v1/intake/kpi` 与受理页 |
| Agent/MCP 联测 | §2.5  curl 三连 | 需三服务在线 | agent 三意图+蓝橙分离+免责+零写断言；mcp OAuth 双 scope、6 工具发现、受控写 confirm_token 强制拦截 |

**推荐的全量测试执行序**（先离线门禁、后在线联测）：

```bash
python scripts/hub.py all                # ① 一键离线：clean→seed→verify→test→test-redline
INVOICE_HUB_DISABLE_AUTH=1 python scripts/hub.py run &   # ② 三服务在线（见 §2.5，此处示意单起 backend）
python scripts/hub.py run-agent &
python scripts/hub.py run-mcp &
python scripts/hub.py smoke              # ③ 十步冒烟 10/10
python scripts/hub.py intake:demo-drop && python scripts/hub.py intake:poll-mailbox && python scripts/hub.py intake:poll-dox   # ④ 通道桩走查
python scripts/hub.py demo-replay        # ⑤ 八大 Demo 场景回放对照
```

> **注**：`make test` 系列均跑在 `backend/.venv` 解释器上（`hub.py` 自动解析）；Windows 手工执行 pytest 若遇中文乱码，先 `set PYTHONIOENCODING=utf-8`。

更多故障排查、通道桩目录约定、组件切换（PostgreSQL / MinIO / Redis）详见 [docs/RUNBOOK.md](docs/RUNBOOK.md)。

## 历史资产纪律

`../ariba-mock/`、`../invoice-platform/` 为前一版本工程——**禁止拷贝其代码、禁止引用其 contracts 路径**；仅场景断言方法论可参考。本仓 `contracts/` 为唯一契约事实源。

## 会话入口

后续编码会话请先加载 `CLAUDE.md`（主上下文 P00），再执行阶段提示词（`../细化功能清单/vibe-coding-prompts/`）。
