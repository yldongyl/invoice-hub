#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""invoice-hub 一键运行入口（P07 1.2 · 与 Makefile 命令等价，Windows 无 make 时的主入口）。

用法：python scripts/hub.py <command> [args]
  seed            全量种子装载（幂等：重建表后重写，重复执行结果一致）
  run [--port 8000] [--reload]  backend（FastAPI，同源静态托管 web/；端口约定 8000）
  run-agent       agent 域启动占位（LangGraph 服务端口 8001，M5 实装——不阻塞 backend）
  run-mcp         MCP Server 启动占位（streamable-http 端口 8002，M5 实装）
  run-workers     workers 占位（受理流水线/重试/归档随 backend 进程内钩子，独立进程属 M3+）
  test            全部测试（单元+契约）
  test-e2e        E2E 场景断言占位（tests/scenarios/ 最小场景集 M3 建立）
  verify:enums    enum-registry ↔ Excel Sheet08 逐字校验
  verify:contracts 契约结构/种子交叉校验
  verify:ui       seeds ↔ ui-design 页面交叉校验（G-M0-001）
  verify          以上三项依次执行
  smoke [--base URL] 对运行中实例的冒烟检查（tools/smoke.py，需先 run）
  clean           数据重置：删除 runtime/invoice_hub.db（随后 make seed 恢复初始演示态）
  all             clean→seed→verify→test（离线全量校验，不含需起服务的 smoke）

零外部服务强依赖（P07 1.1）：默认 SQLite + 本地目录 + 进程内队列即可全栈启动；
PostgreSQL/MinIO/Redis 切换方法见 docs/RUNBOOK.md。
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]        # invoice-hub/
BACKEND = ROOT / "backend"
RUNTIME_DB = ROOT / "runtime" / "invoice_hub.db"

# Windows 控制台 UTF-8 兜底（与 seed_loader/tools 同口径）：env 供子进程继承，本进程 stdout 亦强制
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _run(argv, cwd=BACKEND):
    """等价命令直跑（不做 shell 插值）；返回退出码。"""
    print(f"$ (cd {Path(cwd).name if cwd == BACKEND else cwd}) {' '.join(argv)}", flush=True)
    return subprocess.call(argv, cwd=str(cwd))


def cmd_seed(a):
    return _run([sys.executable, "-m", "app.services.seed_loader"])


def cmd_run(a):
    argv = [sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", a.host, "--port", str(a.port)]
    if a.reload:
        argv.append("--reload")
    return _run(argv)


def cmd_run_agent(a):
    print("agent/ = LangGraph 域（ADR-0001）：M5 实装。当前无可启动目标（占位），不阻塞 backend。")
    print("端口约定：8001（agent 服务，仅消费 backend API）。")
    return 0


def cmd_run_mcp(a):
    print("mcp/ = MCP Server 六工具（FN-A-04）：M5 实装。当前无可启动目标（占位），不阻塞 backend。")
    print("端口约定：8002（streamable-http）。")
    return 0


def cmd_run_workers(a):
    print("workers/：受理流水线属 M3（FN-1-05）；断点续跑队列为进程内演示口径"
          "（app/workers/retry.py，随 backend 挂载）。独立 worker 进程形态 M3+ 评估。")
    return 0


def cmd_test(a):
    return _run([sys.executable, "-m", "pytest", "-q"])


def cmd_test_e2e(a):
    print("E2E 场景断言集 = tests/scenarios/（P07 引用实施规划 §7）：最小场景集随 M3 建立，"
          "当前为 README 占位。本里程碑以 test_api_dashboard / test_api_web 的端到端冒烟"
          "（tools/smoke.py）作为运行基线验证。")
    return 0


def cmd_verify_enums(a):
    return _run([sys.executable, str(ROOT / "tools" / "check_enums.py")], cwd=ROOT)


def cmd_verify_contracts(a):
    return _run([sys.executable, str(ROOT / "tools" / "validate_contracts.py")], cwd=ROOT)


def cmd_verify_ui(a):
    return _run([sys.executable, str(ROOT / "tools" / "check_seeds_vs_ui.py")], cwd=ROOT)


def cmd_smoke(a):
    return _run([sys.executable, str(ROOT / "tools" / "smoke.py"), "--base", a.base], cwd=ROOT)


def cmd_clean(a):
    removed = []
    try:
        if RUNTIME_DB.exists():
            RUNTIME_DB.unlink()
            removed.append(str(RUNTIME_DB))
        for extra in (ROOT / "runtime").glob("invoice_hub.db-*"):   # WAL/journal 残留
            extra.unlink()
            removed.append(str(extra))
    except PermissionError as e:
        print(f"clean 受阻（文件被占用）：{e}\n"
              "请先停止 backend 进程（RUNBOOK §8）；若仅想恢复演示态，可直接重跑 seed——"
              "make seed 本身即表级重建，无需删文件。")
        return 1
    print("clean 完成，删除：" + ("、".join(removed) if removed else "（无数据文件，已是干净态）"))
    print("恢复初始演示态：python scripts/hub.py seed")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed")
    p = sub.add_parser("run"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8000); p.add_argument("--reload", action="store_true")
    sub.add_parser("run-agent"); sub.add_parser("run-mcp"); sub.add_parser("run-workers")
    sub.add_parser("test"); sub.add_parser("test-e2e")
    sub.add_parser("verify:enums"); sub.add_parser("verify:contracts"); sub.add_parser("verify:ui")
    sub.add_parser("verify")
    p = sub.add_parser("smoke"); p.add_argument("--base", default="http://127.0.0.1:8000")
    sub.add_parser("clean")
    sub.add_parser("all")
    a = ap.parse_args()

    if a.cmd == "verify":
        for name in ("verify:enums", "verify:contracts", "verify:ui"):
            rc = main_one(name, a)
            if rc:
                return rc
        return 0
    if a.cmd == "all":
        for name in ("clean", "seed", "verify", "test"):
            rc = main_one(name, a)
            if rc:
                print(f"✗ {name} 失败（exit {rc}）"); return rc
        print("✓ all：clean→seed→verify→test 全过（冒烟请起服务后 python scripts/hub.py smoke）")
        return 0
    return main_one(a.cmd, a)


def main_one(name, a):
    return {
        "seed": cmd_seed, "run": cmd_run, "run-agent": cmd_run_agent, "run-mcp": cmd_run_mcp,
        "run-workers": cmd_run_workers, "test": cmd_test, "test-e2e": cmd_test_e2e,
        "verify:enums": cmd_verify_enums, "verify:contracts": cmd_verify_contracts,
        "verify:ui": cmd_verify_ui, "smoke": cmd_smoke, "clean": cmd_clean,
    }[name](a)


if __name__ == "__main__":
    sys.exit(main())
