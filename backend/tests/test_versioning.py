# -*- coding: utf-8 -*-
"""WP1.8 版本化资产基座测试（草稿/已发布双态、发布=版本递增+diff+旧版保留+回滚、
POLICY_PUBLISHED 入审计链、红线不可被配置绕过、经受控命令五要素发布）。"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain as ac
from app.services import governed_commands as gc
from app.services import versioning
from app.services.errors import (E_CONFIG_REDLINE_BYPASS, E_PERM_DENIED,
                                 E_STATE_PRECONDITION, E_VERSION_NOT_FOUND, CommandError)

KEY = "confidence_threshold_default"


def _payload(session, value):
    base = versioning.latest_published(session, versioning.ASSET_CONFIG, KEY)
    return {**base.payload, "value": value}


def _revisions(session, key=KEY):
    return list(session.scalars(select(m.AssetRevision).where(
        m.AssetRevision.key == key, m.AssetRevision.state == "published")
        .order_by(m.AssetRevision.id)))


def test_seed_baseline_revision_exists(fresh_session):
    """装载基线：config.json 各键有 published 基线修订（首 diff 起点）。"""
    base = versioning.latest_published(fresh_session, versioning.ASSET_CONFIG, KEY)
    assert base is not None and base.version == "v2026-10-21.2"


def test_draft_publish_diff_rollback(fresh_session):
    versioning.save_draft(fresh_session, KEY, _payload(fresh_session, 0.9), "陈铮")
    d = versioning.get_draft(fresh_session, KEY)
    assert d.state == "draft" and d.payload["value"] == 0.9

    res = versioning.publish(fresh_session, KEY, "陈铮")
    today = versioning._today()
    assert res["version"].startswith(f"v{today}.")
    assert res["prev_version"] == "v2026-10-21.2"
    assert res["diff"] == {"value": {"from": 0.85, "to": 0.9}}
    # 生效同步 + 旧版本保留
    item = fresh_session.scalar(select(m.ConfigItem).where(m.ConfigItem.key == KEY))
    assert item.value_raw["value"] == 0.9 and item.version == res["version"]
    revs = _revisions(fresh_session)
    assert [r.version for r in revs] == ["v2026-10-21.2", res["version"]]

    # 同日再发布 → 序号递增
    versioning.save_draft(fresh_session, KEY, _payload(fresh_session, 0.88), "陈铮")
    res2 = versioning.publish(fresh_session, KEY, "陈铮")
    assert res2["version"].endswith(".2")

    # 回滚到基线：新版本（不删历史）
    rb = versioning.rollback(fresh_session, KEY, "v2026-10-21.2", "陈铮")
    assert rb["rollback_of"] == "v2026-10-21.2"
    assert rb["version"].endswith(".3")
    item = fresh_session.scalar(select(m.ConfigItem).where(m.ConfigItem.key == KEY))
    assert item.value_raw["value"] == 0.85
    assert len(_revisions(fresh_session)) == 4      # 基线+2 发布+1 回滚，全部保留


def test_publish_appends_policy_published_to_chain(fresh_session):
    before = ac.head_blk(fresh_session)
    versioning.save_draft(fresh_session, KEY, _payload(fresh_session, 0.9), "陈铮")
    res = versioning.publish(fresh_session, KEY, "陈铮")
    ab = fresh_session.get(m.AuditBlock, res["blk"])
    assert ab.blk == before + 1 and ab.act == "POLICY_PUBLISHED"
    assert ab.chain_scope == ac.PLATFORM_SCOPE
    assert "diff" in ab.note and "陈铮" in ab.op_component
    assert ab.trace == res["trace"]
    assert ac.verify_chain(fresh_session)["ok"] is True


def test_redline_key_denied(fresh_session):
    before = ac.head_blk(fresh_session)
    with pytest.raises(CommandError) as ei:
        versioning.publish(fresh_session, "low_confidence_force_human", "陈铮",
                           payload={"label": "低置信强制人工", "value": False})
    assert ei.value.code == E_CONFIG_REDLINE_BYPASS
    # 链未被污染：无任何新增块（种子基线中的历史 POLICY_PUBLISHED 不计）
    assert ac.head_blk(fresh_session) == before


def test_publish_requires_draft_or_payload(fresh_session):
    with pytest.raises(CommandError) as ei:
        versioning.publish(fresh_session, "new_customer_first_month_review", "陈铮")
    assert ei.value.code == E_STATE_PRECONDITION


def test_rollback_unknown_version(fresh_session):
    with pytest.raises(CommandError) as ei:
        versioning.rollback(fresh_session, KEY, "v1999-01-01.9", "陈铮")
    assert ei.value.code == E_VERSION_NOT_FOUND


# ── 经受控命令框架发布（五要素 + 权限位「策略发布」） ─────────────────────────

def test_command_publish_five_elements(fresh_session):
    scope = gc.scope_ref("publish", config_key=KEY)
    tok = gc.issue_risk_challenge(fresh_session, "陈铮", "publish", scope)["token"]
    out = gc.execute(fresh_session, actor="陈铮", action="publish", instance="CN",
                     token=tok, self_confirmed=True, config_key=KEY,
                     config_payload=_payload(fresh_session, 0.9), opinion="校准提升")
    assert out["published"] is True and out["diff"]["value"]["to"] == 0.9
    assert out["version"].startswith("v")
    item = fresh_session.scalar(select(m.ConfigItem).where(m.ConfigItem.key == KEY))
    assert item.value_raw["value"] == 0.9


def test_command_publish_denied_for_reviewer(fresh_session):
    """复核员无「策略发布」权限位 → 要素①拒绝。"""
    scope = gc.scope_ref("publish", config_key=KEY)
    tok = gc.issue_risk_challenge(fresh_session, "王莉", "publish", scope)["token"]
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="publish", instance="CN",
                   token=tok, self_confirmed=True, config_key=KEY,
                   config_payload=_payload(fresh_session, 0.9))
    assert ei.value.code == E_PERM_DENIED


def test_command_rollback(fresh_session):
    base = versioning.latest_published(fresh_session, versioning.ASSET_CONFIG, KEY)
    scope = gc.scope_ref("rollback", config_key=KEY)
    tok = gc.issue_risk_challenge(fresh_session, "陈铮", "rollback", scope)["token"]
    out = gc.execute(fresh_session, actor="陈铮", action="rollback", instance="CN",
                     token=tok, self_confirmed=True, config_key=KEY,
                     to_version=base.version, opinion="恢复基线")
    assert out["rolled_back"] is True
    assert fresh_session.scalar(
        select(m.ConfigItem).where(m.ConfigItem.key == KEY)).value_raw["value"] == 0.85
