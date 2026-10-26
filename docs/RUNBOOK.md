# invoice-hub · RUNBOOK（运行手册 · P07 建立，2026-10-26）

全球采购平台票据智能与合规中台 —— 干净环境一键启动全栈并冒烟验证的操作基准。
**当前里程碑状态：M2 读路径垂直切片**（backend 确定性核心 + web 三页接线完成；agent/mcp/workers 为占位，M3-M5 实装）。

---

## 1. 前置条件与安装

| 项 | 要求 |
|---|---|
| Python | **≥3.11**（`pyproject.toml requires-python`；本仓在 3.14.3 实测） |
| pip 流 | `cd backend && pip install -r requirements-dev.txt`（运行+测试+校验全量） |
| uv 流（推荐，精确重现） | 安装 uv 后：`cd backend && uv sync --extra dev`（按 `uv.lock` 锁定 44 包，自动建 `.venv/`；后续命令用 `uv run python scripts/...` 或激活 venv） |
| 零外部服务强依赖 | 默认 **SQLite**（`runtime/invoice_hub.db`）+ **本地目录**对象存储位 + **进程内**队列；无需安装 PostgreSQL/MinIO/Redis |

**Windows / macOS·Linux 差异**：
- Windows Git-Bash 通常无 `make` → 用等价入口 `python scripts/hub.py <command>`（Makefile 只是薄委托）；
- Windows 控制台默认 cp1252：仓库内所有 CLI 入口（seed_loader/tools/smoke）已强制 stdout UTF-8；手工跑 `python -m pytest` 乱码可 `set PYTHONIOENCODING=utf-8`；
- 路径含空格（本仓 `Virtual Project Part2`）已实测无碍；uv/pip 安装建议同样在空格路径下验证过。

**组件切换（可配置，ADR-0002 PoC 口径）**：

| 组件 | 默认 | 切换方法 |
|---|---|---|
| 数据库 | SQLite `runtime/invoice_hub.db` | 环境变量 `INVOICE_HUB_DATABASE_URL=postgresql+psycopg://user:pwd@host:5432/invoice_hub`（需 `pip install psycopg[binary]`），重跑 seed |
| 对象存储 | 本地目录桩（M3 受理登记落 `runtime/`） | MinIO：M3 接线时经 S3 兼容 endpoint 配置（桩位注记随 M3 落地） |
| 队列 | 进程内（`app/workers/retry.py` 演示口径） | Redis：M3 断点续跑投产时替换消费者实现 |

## 2. 首次启动流程（干净 clone）

```text
① 安装依赖          cd backend && uv sync --extra dev        （或 pip install -r requirements-dev.txt）
② 种子装载          python scripts/hub.py seed                （幂等，可重跑；控制台乱码见 §1 差异）
③ 启动全栈          python scripts/hub.py run                 （backend 8000，同源托管 web/）
④ 打开            http://localhost:8000/                     （根路径→总览仪表盘；或 /web/login.html 走登录演示桩）
⑤ 冒烟验证          python scripts/hub.py smoke               （另开终端；十步逐项 PASS/FAIL，见 §6）
```

浏览器控制台检查接线态：`document.body.dataset.ihubMode === 'live'`（无演示角标）。

## 3. 三种运行形态

| 形态 | 起法 | 表现 |
|---|---|---|
| **A 全栈（接线态）** | `run` 后浏览器开 `http://localhost:8000/web/…` | dashboard/case-detail 走 `/v1` API（demo-mode 探测 ok→live）；dashboard-overview/case-detail/login 已接线；其余 9 页=M3-M5 批次 |
| **B 仅核心** | `run` 后用 API 端点/接口集成（MCP/agent 缺席） | `curl http://127.0.0.1:8000/healthz`；`/v1/dashboard?instance=cn` 等全量可用；agent/mcp 占位不阻塞 |
| **C 独立演示（demo-mode）** | 不起 backend：双击 `web/*.html`（file://）或 `python -m http.server 8001 -d web` | 顶部橙角标「演示模式（未连接后台）」，页面回落内嵌 mock 常量（与 seed 同源），完整演示可用；case-detail Action 提交为 M3 提示（本就无写后端） |

形态 C 的 http.server 变体注意：`/healthz` 404 同样触发回落（探测失败即演示态），行为与 file:// 一致。

## 4. 端口与进程表

| 进程 | 命令 | 端口 | 状态 |
|---|---|---|---|
| backend（含 web 静态托管） | `make run` / `python scripts/hub.py run` | **8000** | ✅ M2 可用 |
| agent（LangGraph） | `make run-agent` | 8001 | 占位（M5 实装；仅消费 backend API） |
| mcp（MCP streamable-http） | `make run-mcp` | 8002 | 占位（M5 实装；6 工具见 contracts/mcp-tools.json） |
| workers | `make run-workers` | — | 随 backend 进程内钩子（受理流水线 M3） |

## 5. 常用命令表（Makefile ↔ scripts/hub.py 等价）

| 命令 | 作用 |
|---|---|
| `make seed` / `hub.py seed` | 全量种子装载（幂等重建，13 类资产） |
| `make run` / `hub.py run [--port 8000] [--reload]` | 启动 backend |
| `make test` / `hub.py test` | 全部测试（单元+契约，171 项目标态） |
| `make test-e2e` / `hub.py test-e2e` | E2E 场景断言（M3 建立，当前占位说明） |
| `make verify-enums / verify-contracts / verify-ui / verify` | 三校验脚本（枚举↔Sheet08 / 契约结构↔种子 / 种子↔页面） |
| `make smoke` / `hub.py smoke [--base URL]` | 冒烟十步（需先 run） |
| `make clean` / `hub.py clean` | 删除 runtime/invoice_hub.db |
| `make all` / `hub.py all` | clean→seed→verify→test（离线全量） |

**重复 seed 幂等**：`hub.py seed` 两次连续执行，库内行态与聚合输出逐字节一致（回归测试 `test_rebuild_twice_identical` 常驻保证）。

## 6. 冒烟检查（make smoke 十步）

`01 healthz → 02 seed 装载断言（11 案）→ 03 dashboard 双实例 → 04 三案聚合过 Schema（jsonschema 缺失自动降级结构断言并注明）→ 05 证据七要素 → 06 时间线事件码 ∈ registry → 07 审计链三域完整性 → 08 无凭据受控写被拒（五要素守门实证）→ 09 web 静态可达 → 10 demo-mode 回退在位`。
全 PASS 退出码 0；任一 FAIL 打印错误信息与本手册 §8 指引。

## 7. 桩做边界清单（演示口径 · P00 §6 / 实施规划 §6）

| 域 | 桩做方式 | 代码/演示位置 |
|---|---|---|
| 商业 Provider（百望云/诺诺/海外 e-invoicing 等） | SPI stub（按 provider-spi.schema 返回归一化结果+模拟时延成本） | `seeds/providers.json` 6 实例；真实化=商务合同+凭证（M4 实装路由编排） |
| SM2 验签 | **算法真实、证书链模拟**；回执 gm-rcpt-* 按契约生成 | 时间线 SM2_VERIFY 事件/案件 sm2 卡（0387 通过、0379 失败→BLOCKED） |
| 税局授权查验 | 模拟通道（含超时→NOT_VERIFIED→断点续跑重试） | authenticity note「渠道超时·已排定重试」+ AUTH_QUERY_TIMEOUT；workers/retry 演示队列 |
| SAP DOX / 邮箱 Job | DOX 桥接桩；邮箱本地信箱模拟 15 分钟 Job | 0125 channel「邮箱→定时 Job→SAP DOX」注记（H30 余项） |
| Ariba 建档 | 沙箱网关 stub（五步链路真实执行、回执模拟） | TODO(M3/FN-1-04) 退回邮件桩注记；Adapter 五步属 M4 |
| SSO / MFA / KMS | 演示桩 | login.html 页面声明「设计期预留」；confirm 凭据=服务端本地签发（governed_commands 注记）；RBAC 矩阵 M5 实装 |
| 身份/真人核验 | 操作人以 actor 参数声明 | 演示口径（M5 替换） |
| LLM / GPU 推理 | agent 域 M5 接真实 LLM（qwen-finance-v2 为演示口径名）；backend 零依赖 | ADR-0001；AI 卡数据为 seed 预置非实时生成 |
| 监控 | 自监控指标（组件名不绑定） | `/healthz` 为当前唯一探针 |
| 数据驻留 | `TODO(H39)` 推断标注 | tenant.py region 文案；login 租户注记 |

> 桩必须在代码注释与本文档同口径标注「演示口径」——评审红线。

## 8. 故障排查

| 症状 | 排查 |
|---|---|
| 端口 8000 占用（`[Errno 10048]`/`address already in use`） | `python scripts/hub.py run --port 8001`（smoke 加 `--base http://127.0.0.1:8001`）；或找出占用进程后释放 |
| `ModuleNotFoundError: No module named 'app'` | uvicorn 必须在 **backend/** 目录起（`hub.py run` 已处理；手工 `cd backend` 后运行） |
| seed 失败 `EnumViolation` | 种子被改动引入造词/越枚举值——对照 `contracts/enum-registry.json` 还原或按 FN-A-07 走兼容登记后重跑 |
| seed 失败 `种子链自检失败 @ blk#N` | `seeds/audit_events.json` 被篡改（链装载即校验）；git 还原 seeds 后 `hub.py clean && hub.py seed` |
| smoke 07 链校验 FAIL（运行期写入后） | M2 受控写会追加链块，属正常增长；若 `bad_blk` 为 seed 区间块号 → 数据被旁路修改，clean+seed 重置 |
| dashboard/case-detail 数据为空 | 未 seed（`hub.py seed`）；或 env `INVOICE_HUB_DATABASE_URL` 指向空库 |
| 页面顶部演示角标在 backend 已起时仍出现 | `/healthz` 返回非 ok（DB 不可达=degraded）或反向代理剥离了路径；F12 Network 看 healthz 状态 |
| Windows 控制台乱码/UnicodeEncodeError | 已修（入口 reconfigure UTF-8）；若手工调库仍现：`set PYTHONIOENCODING=utf-8` |
| `make clean` 报文件被占用（WinError 32） | backend 进程未退出/句柄未释放；先停服务再 clean。**注**：`make seed` 本身即表级重建，恢复演示态不依赖 clean |
| 依赖纪律 grep 误报（`fullmatch` 含 llm 子串） | 扫描边界=自研源码：`grep -rn "langgraph\|openai\|llm" backend/ --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__`（venv 属安装产物非源码面；单测 `test_dependency_discipline` 同口径排除） |

## 9. 数据重置

```text
python scripts/hub.py clean   # 删 runtime/invoice_hub.db（含 journal/WAL 残留）
python scripts/hub.py seed    # 重建：13 类资产 + 链计算 + 计数器播种，恢复初始演示态
```
重置后所有状态回到 seed 基线（0379 BLOCKED/0387 NEEDS_REVIEW 等演示六态分布），与 M0 冻结口径一致。

## 10. TODO(H/CON) 汇总（与代码实态一致 · 2026-10-26 扫描）

扫描命令（收工检查单同款）：
```text
grep -rnoE "TODO\((H[0-9]+|CON-[0-9]+|WP[0-9.]+|M[0-9][^)]*)\)" backend/app web/js --include=*.py --include=*.js
```
运行代码现存 2 处：`TODO(M3/FN-1-04)`（退回邮件通知桩注记，governed_commands）· `TODO(H39)`（数据驻留推断，tenant 文案）。
其余未决项登记于 `contracts/CHANGELOG.md`「TODO 未决项登记」表（H24/H25/H29/H38/H39、CON-06/09/12/13/14——归属 M3/M4/M5 对应工作包落地时消费）；里程碑边界注记（如 summary 投影、KPI live 口径）见 `docs/gate-reports/M1/M2-self-check.md` 遗留节。

---

*维护约定：任一里程碑后重跑 P07（刷新本手册 §1-§4/§7/§10 与冒烟清单）；本文件与 Makefile/hub.py 行为不一致时，以代码为准并回写本手册。*
