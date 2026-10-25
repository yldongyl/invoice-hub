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
    from referencing import Registry, Resource
    names = ["invoice-schema.json", "invoice-case.schema.json", "events.schema.json",
             "provider-spi.schema.json", "routing-config.schema.json",
             "adapter-contract.schema.json"]
    loaded = []
    for n in names:
        s = _absolutize_refs(json.loads((CONTRACTS_DIR / n).read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(s)
        loaded.append((_to_file_uri(n), s))
    registry = Registry().with_resources([(u, Resource.from_contents(s)) for u, s in loaded])
    case_schema = dict(loaded)[_to_file_uri("invoice-case.schema.json")]
    return Draft202012Validator(case_schema, registry=registry)


@pytest.fixture(scope="session")
def events_validator():
    from jsonschema import Draft202012Validator
    s = json.loads((CONTRACTS_DIR / "events.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(s)
    return Draft202012Validator(s)


def schema_errors(validator, obj):
    return sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
