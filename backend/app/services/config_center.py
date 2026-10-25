# -*- coding: utf-8 -*-
"""配置中心（WP1.1 · seeds/config.json → 租户级覆盖模型，草稿/已发布双态接口位）。

CON-01 决议：置信度全局默认阈值 0.85 由本承载（唯一默认值，规格 v0.3 的 0.75 为历史标注）。
红线关联（P00 §5 / FN-0-06/09/5-05）：low_confidence_force_human 不可被配置绕过关闭——
本层读取时强制校验；发布/回滚/diff 的版本化框架属 WP1.8（FN-0-12），此处仅状态位与接口位。
"""

from sqlalchemy import select

from app.domain import models as m

DEFAULT_SCOPE = "default"


def get_effective(session, key: str, scope: str = DEFAULT_SCOPE):
    """租户覆盖读取：先取 tenant scope，缺省回落 default（四隔离配置维度的最小实现 · WP1.7 收口）。"""
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


def save_draft(session, key: str, value, scope: str = DEFAULT_SCOPE):
    """草稿态接口位（WP1.8 版本化框架实装：发布=版本递增+diff+回滚+审计）。TODO(WP1.8)"""
    raise NotImplementedError("草稿保存属 WP1.8 版本化资产基座（FN-0-12）")


def publish(session, key: str, scope: str = DEFAULT_SCOPE):
    """发布接口位。TODO(WP1.8)"""
    raise NotImplementedError("发布/diff/审计属 WP1.8 版本化资产基座（FN-0-12）")
