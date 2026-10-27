# -*- coding: utf-8 -*-
"""种子装载测试（WP1.1 · make seed 幂等 + 枚举违例拒载）。"""

import json
import shutil

from sqlalchemy import func, select

from app.domain import models as m
from app.domain.registry import EnumViolation
from app.services.seed_loader import load_all


def test_counts(session):
    assert session.scalar(select(func.count()).select_from(m.Case)) == 11
    assert session.scalar(select(func.count()).select_from(m.FieldEvidence)) == 36
    assert session.scalar(select(func.count()).select_from(m.TimelineEvent)) == 34
    assert session.scalar(select(func.count()).select_from(m.CheckResult)) > 0
    assert session.scalar(select(func.count()).select_from(m.Batch)) == 9
    assert session.scalar(select(func.count()).select_from(m.FileIntake)) == 19
    assert session.scalar(select(func.count()).select_from(m.AuditBlock)) == 15
    assert session.scalar(select(func.count()).select_from(m.RuleCatalogEntry)) == 22
    assert session.scalar(select(func.count()).select_from(m.Provider)) == 6
    assert session.scalar(select(func.count()).select_from(m.ComponentVersion)) == 19
    # M2 新增装载：适配状态条 5 条（seeds/adapters.json）；页面差异登记入 SeedMeta
    assert session.scalar(select(func.count()).select_from(m.Adapter)) == 5
    assert session.get(m.SeedMeta, "known_page_discrepancies") is not None
    # load_seq 播种与 seed 原序一致（0..10，切换器排序稳定源）
    seqs = session.scalars(select(m.Case.load_seq).order_by(m.Case.load_seq)).all()
    assert seqs == list(range(11))


def test_rebuild_twice_identical(session_factory, seeds_cases):
    """rebuild_and_load 连跑两次，聚合结果逐字节一致（make seed 幂等口径）。"""
    from app.services.seed_loader import rebuild_and_load
    from app.services.tenant import TenantContext
    sf = session_factory.get_session  # 复用测试临时库的 session 工厂
    counts1 = rebuild_and_load(session_factory=sf)
    from app.services import case_repository as repo
    s1 = sf()
    snap1 = {c["caseId"]: repo.aggregate_case(s1, TenantContext.of_case_id(c["caseId"]), c["caseId"]) for c in seeds_cases["cases"]}
    s1.close()
    counts2 = rebuild_and_load(session_factory=sf)
    assert counts1 == counts2
    s2 = sf()
    snap2 = {c["caseId"]: repo.aggregate_case(s2, TenantContext.of_case_id(c["caseId"]), c["caseId"]) for c in seeds_cases["cases"]}
    s2.close()
    assert snap1 == snap2
    # 聚合与种子深度一致（两跑均成立）
    for seed in seeds_cases["cases"]:
        assert snap2[seed["caseId"]] == seed


def test_enum_violation_rejects_dirty_seed(session_factory, tmp_path):
    """脏种子（状态造词）拒载——枚举单一来源纪律。"""
    from app.domain.registry import SEEDS_DIR
    sdir = tmp_path / "seeds"
    shutil.copytree(SEEDS_DIR, sdir)
    p = sdir / "cases.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["cases"][0]["status"] = "RECOGNIZED_OK"  # 造词
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    s = session_factory.get_session()
    try:
        import pytest
        with pytest.raises(EnumViolation):
            load_all(s, seeds_dir=sdir)
    finally:
        s.rollback()
        s.close()


def test_source_violation_rejects(session_factory, tmp_path):
    """字段来源造词拒载（field_source 六枚举）。"""
    from app.domain.registry import SEEDS_DIR
    sdir = tmp_path / "seeds"
    shutil.copytree(SEEDS_DIR, sdir)
    p = sdir / "cases.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for c in data["cases"]:
        if c.get("evidence"):
            c["evidence"][0]["source"] = "gpt"
            break
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    s = session_factory.get_session()
    try:
        import pytest
        with pytest.raises(EnumViolation):
            load_all(s, seeds_dir=sdir)
    finally:
        s.rollback()
        s.close()
