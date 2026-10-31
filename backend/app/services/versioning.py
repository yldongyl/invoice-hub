# -*- coding: utf-8 -*-
"""版本化资产基座（WP1.8 · FN-0-12）。

通用双态资产（draft/published）+ 发布框架：
  - 发布 = 版本递增 v{YYYY-MM-DD}.{序号} + 前值→后值 diff + 旧版本保留 + 回滚接口；
  - 变更写审计链 POLICY_PUBLISHED 类事件（平台级，链域按归属；本阶段 config=PLATFORM）；
  - 红线项（low_confidence_force_human）关闭尝试直接拒绝（E_CONFIG_REDLINE_BYPASS，
    不可被配置绕过 · P00 §5/FN-0-06/5-05）；
  - 路由策略/映射表实体在 M4 复用本框架（asset_type 区分，本阶段落地 config 接入）。

注意：业务写（发布/回滚）必须经受控命令框架（governed_commands action=publish/rollback）；
本模块为执行内核，不面向 API 裸调。
"""

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.domain import models as m
from app.services import audit_chain, config_center
from app.services.errors import (E_CONFIG_REDLINE_BYPASS, E_STATE_PRECONDITION,
                                 E_VERSION_NOT_FOUND, CommandError)

REDLINE_KEYS = {"low_confidence_force_human"}   # 红线关联键（关闭=违例）
ASSET_CONFIG = "config"


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def latest_published(session, asset_type: str, key: str, scope: str = "default") -> m.AssetRevision | None:
    return session.scalar(
        select(m.AssetRevision)
        .where(m.AssetRevision.asset_type == asset_type, m.AssetRevision.key == key,
               m.AssetRevision.state == "published")
        .order_by(m.AssetRevision.id.desc()))


def next_version(session, asset_type: str, key: str) -> str:
    day = f"v{_today()}."
    mx = session.scalar(
        select(func.max(m.AssetRevision.version)).where(
            m.AssetRevision.asset_type == asset_type, m.AssetRevision.key == key,
            m.AssetRevision.version.like(f"{day}%")))
    n = 1
    if mx and mx.startswith(day):
        try:
            n = int(mx[len(day):]) + 1
        except ValueError:
            n = 1
    return f"{day}{n}"


def compute_diff(old: dict | None, new: dict) -> dict:
    """前值→后值 diff（顶层键粒度；FN-9-09 二次确认素材）。"""
    old = old or {}
    d = {}
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            d[k] = {"from": old.get(k), "to": new.get(k)}
    return d


def _assert_no_redline_bypass(key: str, payload: dict):
    if key in REDLINE_KEYS:
        v = payload.get("value")
        if v is not True:
            raise CommandError(E_CONFIG_REDLINE_BYPASS,
                               f"配置红线违例：{key} 不得被关闭（错误自动放行率 ≤0.05% 红线不可被配置绕过，"
                               f"P00 §5 / FN-0-06/5-05）", http=403)


def save_draft(session, key: str, payload: dict, actor: str, *, asset_type: str = ASSET_CONFIG):
    """草稿态保存（重置草稿不产生审计——FN-9-09；发布前 diff 基线取最新发布版）。"""
    _assert_no_redline_bypass(key, payload)
    draft = session.scalar(select(m.AssetRevision).where(
        m.AssetRevision.asset_type == asset_type, m.AssetRevision.key == key,
        m.AssetRevision.state == "draft"))
    if draft is None:
        draft = m.AssetRevision(asset_type=asset_type, key=key, version="draft", state="draft")
        session.add(draft)
    draft.payload = payload
    draft.updated_by = actor
    draft.updated_at = audit_chain.now_iso()
    session.commit()
    return draft


def get_draft(session, key: str, *, asset_type: str = ASSET_CONFIG):
    return session.scalar(select(m.AssetRevision).where(
        m.AssetRevision.asset_type == asset_type, m.AssetRevision.key == key,
        m.AssetRevision.state == "draft"))


def list_revisions(session, key: str, *, asset_type: str = ASSET_CONFIG):
    return list(session.scalars(select(m.AssetRevision).where(
        m.AssetRevision.asset_type == asset_type, m.AssetRevision.key == key,
        m.AssetRevision.state == "published").order_by(m.AssetRevision.id.desc())))


def publish(session, key: str, actor: str, *, payload: dict | None = None,
            opinion: str | None = None, asset_type: str = ASSET_CONFIG, scope: str = "default",
            rollback_of: str | None = None, commit: bool = True) -> dict:
    """发布：draft（或显式 payload）→ 新版本，diff 留痕，旧版保留，审计入链 POLICY_PUBLISHED。"""
    base = latest_published(session, asset_type, key)
    if payload is None:
        draft = get_draft(session, key, asset_type=asset_type)
        if draft is None:
            raise CommandError(E_STATE_PRECONDITION,
                               f"{key}：无草稿且未提供发布载荷——先 save_draft 或显式 payload", http=409)
        payload = dict(draft.payload)
    _assert_no_redline_bypass(key, payload)

    version = next_version(session, asset_type, key)
    diff = compute_diff(base.payload if base else None, payload)
    row = m.AssetRevision(asset_type=asset_type, key=key, version=version, state="published",
                          payload=payload, diff_json=diff,
                          prev_version=base.version if base else None,
                          updated_by=actor, updated_at=audit_chain.now_iso(),
                          opinion=opinion)
    session.add(row)
    # 草稿消费即清
    d = get_draft(session, key, asset_type=asset_type)
    if d is not None:
        session.delete(d)

    # 生效配置同步（copy-and-reassign；红线读取校验兜底）
    item = session.scalar(select(m.ConfigItem).where(
        m.ConfigItem.scope == scope, m.ConfigItem.key == key))
    if item is not None:
        item.value_raw = payload
        item.state = "published"
        item.version = version

    # 路由策略资产同步（FN-2-12 / M4 复用本框架）
    if asset_type == "routing_policy" or key == "routing_policy":
        if isinstance(payload, dict):
            payload["version"] = version
            payload["state"] = "published"
        rp = session.scalar(select(m.RoutingPolicy).where(m.RoutingPolicy.state == "published"))
        if rp is not None:
            rp.version = version
            rp.policy_raw = payload
        else:
            session.add(m.RoutingPolicy(version=version, state="published", policy_raw=payload))

    if commit:
        session.commit()
        config_center.assert_no_redline_bypass(session, scope)

    note = (f"配置发布 {key}：{base.version if base else '（无基线）'} → {version}"
            f" · diff={diff} · 操作人 {actor}"
            + (f" · 处置意见：{opinion}" if opinion else "")
            + (f" · 回滚至 {rollback_of}" if rollback_of else ""))
    ab = audit_chain.append_block(
        session, ts=audit_chain.now_iso(), trace=audit_chain.new_trace_id(), actor="human",
        act="POLICY_PUBLISHED", cs=None,
        from_state=(base.version if base else "无基线"), to_state=f"{version} · {key}",
        note=note, op=actor, category="policy")
    return {"asset_type": asset_type, "key": key, "version": version, "diff": diff,
            "prev_version": base.version if base else None, "rollback_of": rollback_of,
            "blk": ab.blk, "trace": ab.trace}


def rollback(session, key: str, to_version: str, actor: str, *, opinion: str | None = None,
             asset_type: str = ASSET_CONFIG) -> dict:
    """回滚接口：以目标历史版本的载荷发布新版本（旧版全部保留，变更链完整）。"""
    target = session.scalar(select(m.AssetRevision).where(
        m.AssetRevision.asset_type == asset_type, m.AssetRevision.key == key,
        m.AssetRevision.version == to_version, m.AssetRevision.state == "published"))
    if target is None:
        raise CommandError(E_VERSION_NOT_FOUND,
                           f"回滚目标版本 {to_version!r} 不存在（{key}）", http=404)
    return publish(session, key, actor, payload=dict(target.payload), opinion=opinion,
                   asset_type=asset_type, rollback_of=to_version)
