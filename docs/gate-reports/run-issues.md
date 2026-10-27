# 运行与部署缺陷/阻塞记录（P07 §3 · 首次建立 2026-10-26）

> 约定：P07 不新增业务功能，执行中发现缺陷记录于此；本会话仅修「阻塞启动/验收」项（RCA 注明），其余移交对应里程碑。

## 已修复（阻塞类）

| 编号 | 症状 | 根因与修复 | 回归证据 |
|---|---|---|---|
| RI-M2-001 | `make test` 在 venv 环境 1 failed：test_no_model_framework_references 命中 `.venv/Lib/site-packages/**.py` | **P07 引入 .venv 后暴露**：第三方 wheel 源码含携带 CS 违禁词子串的常见标识符（R5「匹配函数名含子串」同源问题）；扫描边界应=自研源码，安装产物非 backend 源码面。修复：`test_dependency_discipline` 排除 `{__pycache__, .venv, venv}`（两处 rglob）；RUNBOOK §8 同步手工 grep `--exclude-dir` 口径 | 双解释器（系统 3.14.3 + venv 3.13.3）`171 passed`；venv 即 requires-python>=3.11 兼容实证 |
| RI-M2-002 | `hub.py clean` 在 cp1252 控制台 print 中文崩溃 UnicodeEncodeError | os.environ.setdefault 仅影响子进程，hub.py 本体 stdout 未 reconfigure。修复：入口 `sys.stdout.reconfigure("utf-8")`（与 seed_loader R4/tools 同口径） | 干净链重跑无崩溃 |
| RI-M2-003 | `hub.py clean` 删 runtime/invoice_hub.db 报 WinError 32（文件被占用），端口已释放仍有外部进程持句柄（PID 20140，疑似 IDE Python 工具链） | Windows 句柄语义；clean 增加 PermissionError 明确提示（先停 backend）+ **兜底路径已文档化**：`make seed` 本身即表级重建，恢复演示态不依赖文件删除（RUNBOOK §8/§9） | seed 幂等链实测过；文件删除待环境重启后复验（不阻塞验收⑤——幂等断言以 seed 链为准，test_rebuild_twice_identical 常驻） |

## 观察项（不修复，移交对应里程碑）

| 编号 | 内容 | 去向 |
|---|---|---|
| RI-M2-004 | M1 门禁 MINOR **M-M1-003**（编排器桩通道 sm2_verify/auth_query/tax_id_directory 未注册 rule_id）延续——P07 纪律「不顺手修业务」 | M3 查重/验真服务本体接线（门禁报告已归属） |
| RI-M2-005 | 本环境无 Playwright：`tools/screenshot-diff/` 跳过（P03 WP2.4 允许）；三页**浏览器级逐区块核验**待下一会话（执行载体=tools/ui-consistency-checklist.md §5，含 live/demo 两态与深链四分支操作脚本） | M2 正式核验会话 |
| RI-M2-006 | 时间线展示双口径（seed 页面口径 MM-DD HH:MM:SS vs 运行期 ISO-8601）：M2 详情面=seed 逐字无冲突；运行期新事件（M3 受控写追加）的呈现格式化归接线期定稿 | M3（checklist §4-2 登记） |
| RI-M2-007 | smoke 04 在「仅核心依赖、无 jsonschema」环境自动降级结构断言并打印注记——精确版本校验需 dev 组（uv.lock/--extra dev 已覆盖该场景；Runbook §1 指引） | 设计口径，非缺陷 |

## 运行基线首验记录（2026-10-26）

- 干净链：`uv sync --extra dev` → `hub.py clean`（RI-M2-003 兜底）→ `hub.py seed`（EXIT 0）→ `hub.py run` → `hub.py smoke` **10/10 PASS** → `hub.py test` **171 passed**。
- 三形态：A 接线态（test_api_web 6 项 + smoke 09/10 实证）；B 仅核心（API 面全量，agent/mcp 占位不阻塞）；C 独立演示（http.server 8001 页面/js 200、/healthz 404 触发回落——角标与 mock 逻辑由测试断言，浏览器目验待 RI-M2-005）。
- ui-design 只读：12 页源文件 mtime 全部 ≤2026-10-22 零改动；web 副本 diff 审查：10 页 ZERO-DIFF、2 页仅接线段（dashboard 40 行/case-detail 118 行，均收敛于数据入口与 M3 门控，未触碰原型数据常量/渲染函数/文案——清单 §R1 自查记录）。

## M3-WP3.1/3.2 会话缺陷记录（2026-10-27 · 均已闭）

| 编号 | 症状 | 根因与修复 | 回归证据 |
|---|---|---|---|
| RI-M3-001 | 门户上传报 `E_NO_FILE`（文件部件全被跳过） | fastapi 0.162 的 `UploadFile` 与 starlette 1.10 表单解析器产出的 `starlette.datastructures.UploadFile` **不同源**，`isinstance` 判 False。修复：api/intake.py 文件部件改鸭子类型（`hasattr read/filename`），不再 import fastapi.UploadFile | test_intake_api 上传/recognize multipart 全绿；213 passed |
| RI-M3-002 | 通道桩样例落 `backend/runtime/`（应=仓库根 `runtime/`） | object_store/channels_ops 的 REPO_ROOT 用 `parents[2]`（=backend），应为 `parents[3]`（与 domain/registry.py 同基准=invoice-hub/）。修复后 backend/runtime 清除重播 | RUNBOOK §5.1 实机走查：两桩批次/案件/KPI 与页面锚点核对一致 |
| RI-M3-003 | 同日晚些 CN/OS 各自首批发号同为 `BT-…-001` → PRIMARY KEY 冲突 | BT 编号规则不含实例段而发号计数分实例域（CON-04 域）——同日双域同序必撞。修复：`_next_batch` 全局唯一检查+域内重发（≤16 次防御） | S-M3-INT-05 两桩连发不撞；seed 计数器播种口径不变 |
| RI-M3-004 | 门户 KPI 运行段成功率=50%（2 受理+2 退回/4 件） | 口径修正：退回（FILTERED）属受理处置成功（FN-1-09「受理登记成功/接入总量」），仅 FAILED 计失败——`success_rate=(accepted+filtered)/total` | intake_kpi 注释+场景 05；页面 merged 回落锚点逻辑不变 |
| RI-M3-005 | `test_dependency_discipline` 误报：测试函数名含违禁词子串 | CS 组大小写敏感镜像 grep 从严，函数名 `…_no_llm` 命中。修复：函数改中性名（断言不变=直读零外发）；「自误报纪律」注记已有、本条补执行案例 | 213 passed 含纪律测 |
| RI-M3-006 | multipart 上传端点 500：`python-multipart` 缺失 | FastAPI 表单解析运行期硬依赖未入 pyproject（M2 无表单面未暴露）。修复：dependencies 增 `python-multipart>=0.0.9`，uv.lock 重锁 45 包；RUNBOOK §1/§8 同步 | 干净 uv sync 链待门禁复验；本会话 venv 实测 ok |
| RI-M3-007 | 走查前 8000 端口响应 404 `/v1/intake/*` | **环境项**：M2 会话遗留 backend 进程（v0.3.0，PID 5408）持续占端，本会话两次 `hub.py run` bind 失败静默退出（日志有 10048 但链式命令未暴露）。处置：taskkill 后重启 v0.4.0 复验 | healthz version=0.4.0-m3-wp3.1-3.2 + smoke 10/10；RUNBOOK §8 已有端口占用条目（建议补「先核对 /healthz version」提示已含） |
