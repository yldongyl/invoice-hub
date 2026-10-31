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

### 2. 标准启动流程（五步全栈）

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

# ⑤（可选）启动扩展服务
python scripts/hub.py run-agent   # 端口 8001：LangGraph Agent 域（多意图对话与主动调查）
python scripts/hub.py run-mcp     # 端口 8002：MCP Server 网关（6 项标准工具）
```

> **提示**：若系统环境已配置 `make`，上述命令亦可直接使用 `make seed`、`make run`、`make smoke` 等等价执行。

### 3. 三种运行形态

| 形态 | 启动方式 | 特性说明 |
|---|---|---|
| **A. 全栈接线态（推荐）** | `python scripts/hub.py run`，访问 `http://localhost:8000/` | 12 个页面全部走真实 `/v1`、`/api` RESTful API，消费后端数据与状态机流转。 |
| **B. 核心 API 态** | 仅启动 `python scripts/hub.py run` | 供系统集成调用、自动化测试或 MCP/Agent 消费，健康探针为 `/healthz`。 |
| **C. 离线演示态（回退）** | **不启动后端**，直接浏览器打开 `web/*.html` 或 `python -m http.server 8001 -d web` | 前端探测到后端不可达时触发 `demo-mode.js` 回退，页面右上角常驻橙色角标，以同源内嵌数据支持完整演示交互。 |

### 4. 常用管理与验证命令

| 操作 | 命令（CLI 入口） | 等价 Makefile | 说明 |
|---|---|---|---|
| 种子装载 | `python scripts/hub.py seed` | `make seed` | 数据库表级幂等重建与初始种子装载 |
| 服务启动 | `python scripts/hub.py run` | `make run` | 启动 backend 确定性核心（端口 8000） |
| 启动 Agent | `python scripts/hub.py run-agent` | `make run-agent` | 启动 LangGraph Agent 服务（端口 8001） |
| 启动 MCP | `python scripts/hub.py run-mcp` | `make run-mcp` | 启动 MCP Server 网关（端口 8002） |
| 冒烟检查 | `python scripts/hub.py smoke` | `make smoke` | 运行中实例十步端到端冒烟断言 |
| 单元与契约测试 | `python scripts/hub.py test` | `make test` | 运行全部 pytest 测试套件 |
| E2E 场景测试 | `python scripts/hub.py test-e2e` | `make test-e2e` | 场景断言测试（`pytest -m scenario`） |
| 红线回归集 | `python scripts/hub.py test-redline` | `make test-redline` | 关键红线断言回归集（`pytest -m redline`） |
| 离线静态校验 | `python scripts/hub.py verify` | `make verify` | 顺序执行枚举、契约 Schema、UI 种子静态核验 |
| 数据重置 | `python scripts/hub.py clean` | `make clean` | 清除 `runtime/invoice_hub.db` SQLite 数据库 |
| 全量离线流水线 | `python scripts/hub.py all` | `make all` | clean → seed → verify → test 全量离线流水线 |

更多故障排查、通道桩（邮箱/DOX）手动拉取触发、组件切换（PostgreSQL / MinIO / Redis）详见 [docs/RUNBOOK.md](docs/RUNBOOK.md)。

## 历史资产纪律

`../ariba-mock/`、`../invoice-platform/` 为前一版本工程——**禁止拷贝其代码、禁止引用其 contracts 路径**；仅场景断言方法论可参考。本仓 `contracts/` 为唯一契约事实源。

## 会话入口

后续编码会话请先加载 `CLAUDE.md`（主上下文 P00），再执行阶段提示词（`../细化功能清单/vibe-coding-prompts/`）。
