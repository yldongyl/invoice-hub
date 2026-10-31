# -*- coding: utf-8 -*-
"""pytest 基座：临时 SQLite 库 + 全量种子装载（session 级）+ 契约校验工具。

数据层 PoC 口径（ADR-0002）：测试用独立临时 sqlite 文件，经环境变量
INVOICE_HUB_DATABASE_URL 注入，与默认 backend/data 隔离。
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

CONTRACTS_DIR = REPO_ROOT / "contracts"
SEEDS_DIR = REPO_ROOT / "seeds"


# ---------- 临时 DB（session 级，装载一次） ----------

@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    return tmp_path_factory.mktemp("ihub-db") / "test.db"


@pytest.fixture(scope="session")
def engine_url(db_path):
    url = f"sqlite:///{db_path.as_posix()}"
    os.environ["INVOICE_HUB_DATABASE_URL"] = url
    os.environ.setdefault("INVOICE_HUB_DISABLE_AUTH", "1")  # 单元/契约测试默认跳过 HTTP 会话门禁；认证测试直接打 auth 端点
    return url


@pytest.fixture(scope="session")
def session_factory(engine_url):
    from app.services import persistence
    persistence.reset_engine()
    eng = persistence.get_engine(engine_url)
    from app.domain import models as m
    m.Base.metadata.create_all(eng)
    from app.services.seed_loader import load_all
    s = persistence.get_session()
    load_all(s)
    s.close()
    yield persistence
    persistence.reset_engine()


@pytest.fixture
def session(session_factory):
    s = session_factory.get_session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="session")
def seeds_cases():
    return json.loads((SEEDS_DIR / "cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client(engine_url, session_factory):
    # 依赖 session_factory：表已建 + 种子已装载，TestClient 走同一临时库
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    """受控写 API 冒烟专用：独立临时库 + TestClient（函数级隔离，不污染 session 级共享库）。"""
    from fastapi.testclient import TestClient
    from app.services import persistence
    from app.domain import models as m
    from app.services.seed_loader import load_all

    url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
    monkeypatch.setenv("INVOICE_HUB_DATABASE_URL", url)
    monkeypatch.setenv("INVOICE_HUB_DISABLE_AUTH", "1")
    persistence.reset_engine()
    eng = persistence.get_engine()
    m.Base.metadata.create_all(eng)
    s = persistence.get_session()
    load_all(s)
    s.close()
    from app.main import app
    with TestClient(app) as c:
        yield c
    persistence.reset_engine()


@pytest.fixture
def fresh_session(tmp_path):
    """独立临时库 + 全量种子装载（函数级）：状态机/哈希链/受控写等会改数据的测试专用，
    不污染 session 级共享库（保证 seed 深比对与只读契约测试稳定）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.domain import models as m
    from app.services.seed_loader import load_all

    eng = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    m.Base.metadata.create_all(eng)
    maker = sessionmaker(bind=eng, expire_on_commit=False)
    s = maker()
    load_all(s)
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


# ---------- 契约 Schema 校验（镜像 tools/validate_contracts.py 的 referencing 口径） ----------

def _to_file_uri(name: str) -> str:
    p = str(CONTRACTS_DIR / name).replace("\\", "/").lstrip("/")
    return "file:///" + quote(p, safe="/:")


def _absolutize_refs(schema):
    if isinstance(schema, dict):
        return {k: (_to_file_uri(v) if (k == "$ref" and isinstance(v, str)
                                        and re.match(r"[\w.-]+\.json\Z", v))
                    else _absolutize_refs(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_absolutize_refs(x) for x in schema]
    return schema


@pytest.fixture(scope="session")
def case_validator():
    from jsonschema import Draft202012Validator
    return Draft202012Validator(_contract_schema("invoice-case.schema.json"),
                                 registry=_contract_registry())


def _contract_registry():
    from referencing import Registry, Resource
    names = ["invoice-schema.json", "invoice-case.schema.json", "events.schema.json",
             "provider-spi.schema.json", "routing-config.schema.json",
             "adapter-contract.schema.json",
             # M2 读面契约（CHANGELOG ⑦）
             "dashboard-response.schema.json", "alerts-response.schema.json",
             "case-read.schema.json"]
    res = []
    for n in names:
        s = _contract_schema(n)
        res.append((_to_file_uri(n), Resource.from_contents(s)))
    return Registry().with_resources(res)


def _contract_schema(name: str):
    from jsonschema import Draft202012Validator
    s = _absolutize_refs(json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(s)
    return s


@pytest.fixture(scope="session")
def contract_registry():
    return _contract_registry()


def _validator_for(name: str, def_key: str | None = None):
    from jsonschema import Draft202012Validator
    schema = _contract_schema(name)
    if def_key:
        schema = dict(schema)  # $defs 分支：保留 $defs 以便内部 $ref 解析
        schema = {**{k: schema[k] for k in schema if k in ("$defs",)}, **schema["$defs"][def_key]}
    return Draft202012Validator(schema, registry=_contract_registry())


@pytest.fixture(scope="session")
def dashboard_validator():
    return _validator_for("dashboard-response.schema.json")


@pytest.fixture(scope="session")
def alerts_validator():
    return _validator_for("alerts-response.schema.json")


@pytest.fixture(scope="session")
def list_projection_validator():
    return _validator_for("case-read.schema.json")  # top=listResponse


@pytest.fixture(scope="session")
def switcher_validator():
    return _validator_for("case-read.schema.json", "switcherResponse")


@pytest.fixture(scope="session")
def exists_validator():
    return _validator_for("case-read.schema.json", "existsResponse")


@pytest.fixture(scope="session")
def events_validator():
    from jsonschema import Draft202012Validator
    s = json.loads((CONTRACTS_DIR / "events.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(s)
    return Draft202012Validator(s)


def schema_errors(validator, obj):
    return sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
