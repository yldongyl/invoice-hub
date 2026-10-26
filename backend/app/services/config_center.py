# -*- coding: utf-8 -*-
"""配置中心（WP1.1 租户级覆盖模型 + WP1.8 草稿/已发布双态实装）。

CON-01 决议：置信度全局默认阈值 0.85 由本承载（唯一默认值，规格 v0.3 的 0.75 为历史标注）。
红线关联（P00 §5 / FN-0-06/09/5-05）：low_confidence_force_human 不可被配置绕过关闭——
读取与发布双侧校验；发布/回滚/diff/审计由 versioning 基座承载（FN-0-12），业务写一律
经 governed_commands（publish/rollback 动作，五要素齐备后调用本层→versioning）。
"""

from sqlalchemy import select

from app.domain import models as m

DEFAULT_SCOPE = "default"


def get_effective(session, key: str, scope: str = DEFAULT_SCOPE):
    """租户覆盖读取：先取 tenant scope，缺省回落 default（四隔离②配置的隔离路径 · WP1.7）。"""
    row = session.scalar(select(m.ConfigItem).where(
        m.ConfigItem.scope == scope, m.ConfigItem.key == key))
    if row is None and scope != DEFAULT_SCOPE:
        row = session.scalar(select(m.ConfigItem).where(
            m.ConfigItem.scope == DEFAULT_SCOPE, m.ConfigItem.key == key))
    return row


def get_value(session, key: str, scope: str = DEFAULT_SCOPE):
    row = get_effective(session, key, scope)
    if row is None:
        return None
    v = row.value_raw
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def confidence_threshold_default(session) -> float:
    """CON-01：0.85 唯一全局默认。"""
    return get_value(session, "confidence_threshold_default")


def assert_no_redline_bypass(session, scope: str = DEFAULT_SCOPE):
    """红线校验：低置信强制人工不得被关闭（不可被配置绕过 · P00 §5）。"""
    v = get_value(session, "low_confidence_force_human", scope)
    if v is not True:
        raise ValueError("红线违例：low_confidence_force_human 不得关闭（FN-0-06/5-05）")


# ─── WP1.8：草稿/发布/回滚（委托版本化基座；懒导入避免循环依赖） ───

def save_draft(session, key: str, payload: dict, actor: str, scope: str = DEFAULT_SCOPE):
    from app.services import versioning
    return versioning.save_draft(session, key, payload, actor)


def publish(session, key: str, actor: str, *, scope: str = DEFAULT_SCOPE,
            payload: dict | None = None, opinion: str | None = None):
    from app.services import versioning
    return versioning.publish(session, key, actor, payload=payload, opinion=opinion, scope=scope)


def rollback(session, key: str, to_version: str, actor: str, *,
             opinion: str | None = None, scope: str = DEFAULT_SCOPE):
    from app.services import versioning
    return versioning.rollback(session, key, to_version, actor, opinion=opinion)


def diff(session, key: str, draft_payload: dict) -> dict:
    """发布前 diff 预览（前值→后值，FN-9-09 二次确认素材；不落库）。"""
    from app.services import versioning
    base = versioning.latest_published(session, versioning.ASSET_CONFIG, key)
    return versioning.compute_diff(base.payload if base else None, draft_payload)
