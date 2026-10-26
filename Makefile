# invoice-hub · 一键运行入口（P07 1.2）
# 所有命令委托 scripts/hub.py（Windows 无 make 时直接：python scripts/hub.py <command>，
# 命令与端口/形态说明见 docs/RUNBOOK.md）。

PY ?= python

.PHONY: seed run run-agent run-mcp run-workers test test-e2e verify-enums verify-contracts verify-ui verify smoke clean all

## 种子装载（幂等可重跑，P07 1.2）
seed:
	$(PY) scripts/hub.py seed

## backend（含 web 同源静态托管）· 端口 8000
run:
	$(PY) scripts/hub.py run

## agent（LangGraph）· 端口 8001 占位（M5 实装，不阻塞 backend）
run-agent:
	$(PY) scripts/hub.py run-agent

## MCP Server · 端口 8002 占位（M5 实装）
run-mcp:
	$(PY) scripts/hub.py run-mcp

## workers（随 backend 进程内钩子；独立进程属 M3+）
run-workers:
	$(PY) scripts/hub.py run-workers

## 全部测试（单元+契约，backend/venv 内）
test:
	$(PY) scripts/hub.py test

## E2E 场景断言（M3 建立最小场景集；当前占位说明）
test-e2e:
	$(PY) scripts/hub.py test-e2e

verify-enums:
	$(PY) scripts/hub.py verify:enums

verify-contracts:
	$(PY) scripts/hub.py verify:contracts

verify-ui:
	$(PY) scripts/hub.py verify:ui

verify:
	$(PY) scripts/hub.py verify

## 冒烟检查（需先 make run）
smoke:
	$(PY) scripts/hub.py smoke

## 数据重置（删 runtime/invoice_hub.db；随后 make seed 恢复演示态）
clean:
	$(PY) scripts/hub.py clean

## 离线全量校验：clean→seed→verify→test
all:
	$(PY) scripts/hub.py all
