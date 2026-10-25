# invoice-hub backend · M1 工作入口（WP1.1）
# Windows 无 make 时可直接运行等价命令：python -m app.services.seed_loader / python -m pytest

PY ?= python

.PHONY: seed test cov healthz

## 全量种子装载（幂等：清空重载，重复执行结果一致）
seed:
	$(PY) -m app.services.seed_loader

## 全部测试（单元 + 契约）
test:
	$(PY) -m pytest -q

cov:
	$(PY) -m pytest -q --cov=app/domain --cov=app/services --cov-report=term-missing

## 本地起服务（healthz 冒烟）
healthz:
	$(PY) -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000)"
