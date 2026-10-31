# -*- coding: utf-8 -*-
"""根目录 tests/ pytest conftest 桥接配置。
加载 backend/tests/conftest 中的全局 fixtures（session, fresh_session, client, api_client, case_validator 等）。
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 导入 backend conftest 中的所有 fixture
from backend.tests.conftest import *  # noqa: F401, F403

import pytest

@pytest.fixture()
def tmp_dirs(tmp_path, monkeypatch):
    from app.services import object_store, sm2_service
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")
    monkeypatch.setattr(sm2_service, "GM_RECEIPT_DIR", tmp_path / "gm-receipts")
    return tmp_path

