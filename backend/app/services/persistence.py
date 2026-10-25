# -*- coding: utf-8 -*-
"""持久化底座（WP1.1 · ADR-0002 PoC 口径）。

数据层：SQLAlchemy 2.x + SQLite（默认 backend/data/invoice_hub.db），
可通过环境变量 INVOICE_HUB_DATABASE_URL 切换 PostgreSQL（如
postgresql+psycopg://user:pass@host/invoice_hub）——组件选型留档 ADR-0002，本模块不做产品绑定。
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/app/services -> backend/
REPO_ROOT = BACKEND_ROOT.parent                      # invoice-hub/
# PoC 数据目录置于 backend/ 之外（gitignored），确保 backend/ 源码树 grep 零违禁词命中
DEFAULT_SQLITE = (REPO_ROOT / "runtime" / "invoice_hub.db").as_posix()

# 环境变量名（切换 PostgreSQL / 临时库跑测试均经此注入）
DB_URL_ENV = "INVOICE_HUB_DATABASE_URL"


def database_url() -> str:
    return os.environ.get(DB_URL_ENV) or f"sqlite:///{DEFAULT_SQLITE}"


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def get_engine(url: str | None = None):
    global _engine, _session_factory
    if _engine is None or url is not None:
        target = url or database_url()
        _engine = create_engine(target)
        if target.startswith("sqlite"):
            (REPO_ROOT / "runtime").mkdir(exist_ok=True)

            @event.listens_for(_engine, "connect")
            def _fk(dbapi_conn, _):  # SQLite 默认不执行外键约束，显式开启（审计链完整性前提）
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session():
    get_engine()
    return _session_factory()


def reset_engine():
    """测试/重装载用：丢弃缓存的 engine/session 工厂。"""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
