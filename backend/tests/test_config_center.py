# -*- coding: utf-8 -*-
"""配置中心测试（WP1.1 · seeds/config.json 租户级覆盖模型 + 草稿/已发布双态接口位）。"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import config_center as cc


def test_config_items_loaded(session):
    n = len(list(session.scalars(select(m.ConfigItem).where(m.ConfigItem.scope == "default"))))
    assert n == 8  # 6 配置项 + __sla_targets + __asset_versions
    assert all(r.state == "published" for r in session.scalars(select(m.ConfigItem)))


def test_confidence_threshold_default_085(session):
    """CON-01 决议：0.85 唯一全局默认（规格 v0.3 的 0.75 为历史标注，不承载）。"""
    assert cc.confidence_threshold_default(session) == 0.85


def test_tolerances_split(session):
    assert cc.get_value(session, "amount_reconcile_tolerance") == "±0.06"
    assert cc.get_value(session, "po_match_tolerance") == "±S$50"  # TODO(CON-12) 两套容差分设


def test_tenant_override_falls_back_to_default(session):
    """无租户覆盖行 → get_effective 回落 default 行（租户级覆盖模型语义）。"""
    row = cc.get_effective(session, "confidence_threshold_default", scope="tenant:TENANT-CN-LANWU-001")
    assert row is not None and row.scope == "default"
    assert cc.get_value(session, "confidence_threshold_default",
                        scope="tenant:TENANT-CN-LANWU-001") == 0.85


def test_tenant_override_wins(session):
    """租户覆盖优先（四隔离配置维度最小实现；完整收口 WP1.7）。"""
    session.add(m.ConfigItem(scope="tenant:TENANT-CN-LANWU-001", key="confidence_threshold_default",
                             label="覆盖", value_raw={"value": 0.9}, state="published", version="draft-test"))
    session.commit()
    assert cc.get_value(session, "confidence_threshold_default",
                        scope="tenant:TENANT-CN-LANWU-001") == 0.9
    assert cc.get_value(session, "confidence_threshold_default") == 0.85
    # 清理，保持 seed 幂等基线
    session.query(m.ConfigItem).filter_by(scope="tenant:TENANT-CN-LANWU-001").delete()
    session.commit()


def test_redline_no_bypass(session):
    """红线：低置信强制人工不得关闭（P00 §5 / FN-0-06/5-05）。"""
    assert cc.get_value(session, "low_confidence_force_human") is True
    cc.assert_no_redline_bypass(session)
    row = session.scalar(select(m.ConfigItem).where(m.ConfigItem.key == "low_confidence_force_human"))
    original = dict(row.value_raw)
    try:
        row.value_raw = {"value": False}
        session.commit()
        with pytest.raises(ValueError):
            cc.assert_no_redline_bypass(session)
    finally:
        row.value_raw = original
        session.commit()


def test_draft_publish_are_interface_stubs(session):
    """草稿/发布双态接口位属 WP1.8（FN-0-12），本阶段显式拒绝实现（不得静默）。"""
    with pytest.raises(NotImplementedError):
        cc.save_draft(session, "confidence_threshold_default", 0.9)
    with pytest.raises(NotImplementedError):
        cc.publish(session, "confidence_threshold_default")
