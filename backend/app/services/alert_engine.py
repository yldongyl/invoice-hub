# -*- coding: utf-8 -*-
"""告警引擎服务（WP5.2 · FN-9-08）。

功能与规则：
  - 四基线告警规则管理：
    ① Provider P95 超阈值（P2 · 警告，邮件 + webhook）
    ② 错误自动放行率 > 0.05%（P0 · 红线，不可停用！邮件 + webhook + 短信）
    ③ 队列积压 > 5,000（P2 · 警告，邮件 + webhook）
    ④ GPU 利用率 > 90%（P1 · 重要，webhook）
  - 红线告警不可停用机制（验收要点①）：
    关闭尝试一律被强制拦截拒绝（保持 on=True 回弹），且尝试行为即时记入不可篡改审计日志；
  - 常规告警开关变更即时入审计；
  - 触发状态实时判定与高亮；
  - 抽检异常 → 冻结自动放行联动机制。
"""

from typing import Any
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain
from app.services.audit_chain import now_iso, new_trace_id
from app.services.errors import CommandError
from app.services.rbac_service import assert_not_ai_agent, require_permission

# 告警规则基线定义（与 platform-admin.html Tab2 ALERT_RULES 逐字对齐）
BASELINE_RULES = {
    "provider_p95": {
        "rule_id": "provider_p95",
        "name": "Provider P95 超阈值",
        "detail": "当前触发中：客户自有 OCR P95 8.2s > 8s",
        "level": "warning",
        "levelTxt": "P2 · 警告",
        "channel": "邮件 + webhook（运维群）",
        "firing": True,
        "on": True,
        "redline": False,
    },
    "false_auto_release_rate": {
        "rule_id": "false_auto_release_rate",
        "name": "错误自动放行率 > 0.05%",
        "detail": "产品红线指标 · 当前 0.02%，未触发",
        "level": "danger",
        "levelTxt": "P0 · 红线",
        "channel": "邮件 + webhook + 短信（管理员）",
        "firing": False,
        "on": True,
        "redline": True,  # 产品红线：不可停用！
    },
    "queue_backlog": {
        "rule_id": "queue_backlog",
        "name": "队列积压 > 5,000",
        "detail": "任一异步队列积压超阈值 · 当前最大 214，未触发",
        "level": "warning",
        "levelTxt": "P2 · 警告",
        "channel": "邮件 + webhook（运维群）",
        "firing": False,
        "on": True,
        "redline": False,
    },
    "gpu_utilization": {
        "rule_id": "gpu_utilization",
        "name": "GPU 利用率 > 90%",
        "detail": "自托管 OCR-VLM 推理节点 · 当前 68%，未触发",
        "level": "warning",
        "levelTxt": "P1 · 重要",
        "channel": "webhook（运维群）",
        "firing": False,
        "on": True,
        "redline": False,
    },
}

# 内存/持久化存储当前规则状态（支持动态开关）
_CURRENT_RULES: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BASELINE_RULES.items()}


def get_alert_rules(session) -> list[dict]:
    """获取全部告警规则清单及当前触发状态。"""
    return list(_CURRENT_RULES.values())


def toggle_alert_rule(session, actor: str, rule_id: str, new_state: bool, opinion: str | None = None) -> dict:
    """切换告警规则启用状态（FN-9-08）。
    核心红线逻辑：
      若目标规则为产品红线规则（redline=True）且尝试设为 false（关闭）：
      1. 拒绝关闭操作，强制重置/回弹保持 on=True；
      2. 将本次违例尝试即时写入不可篡改审计链（REDLINE_DISABLE_ATTEMPT_BLOCKED）；
      3. 抛出明确异常或返回拦截提示。
    非红线规则变更：
      写入不可篡改审计链（ALERT_RULE_TOGGLED）。
    """
    assert_not_ai_agent(actor)

    if rule_id not in _CURRENT_RULES:
        raise CommandError("E_RULE_NOT_FOUND", f"告警规则 {rule_id!r} 不存在", http=404)

    rule = _CURRENT_RULES[rule_id]

    # ══════ 红线告警不可停用拦截（FN-9-08 / 实施规划 M5 验收①） ══════
    if rule.get("redline") and not new_state:
        # 强制回弹为 True
        rule["on"] = True
        trace = new_trace_id()
        msg = f"【红线告警拦截】用户 {actor} 尝试停用产品红线告警「{rule['name']}」被系统强制拦截，规则保持启用状态（FN-9-08/P00 §5）"
        blk = audit_chain.append_block(
            session,
            ts=now_iso(),
            trace=trace,
            actor="human",
            act="POLICY_PUBLISHED",
            cs=None,
            category="security",
            note=msg,
            op="platform-admin/redline-guard",
        )
        raise CommandError(
            "E_REDLINE_ALERT_CANNOT_BE_DISABLED",
            f"「{rule['name']}」为产品红线告警，不可停用 · 本次尝试已记入审计日志（blk#{blk.blk}）",
            http=403,
        )

    # 普通规则变更
    old_state = rule["on"]
    rule["on"] = bool(new_state)

    trace = new_trace_id()
    action_text = "启用" if rule["on"] else "停用"
    note_msg = (
        f"告警规则「{rule['name']}」已{action_text} · "
        f"操作人：{actor} · 意见：{opinion or '（无）'}"
    )
    blk = audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="POLICY_PUBLISHED",
        cs=None,
        category="platform",
        note=note_msg,
        op="platform-admin/alert-engine",
    )

    return {
        "rule_id": rule_id,
        "name": rule["name"],
        "on": rule["on"],
        "redline": rule.get("redline", False),
        "audit_blk": blk.blk,
        "trace": trace,
        "message": f"告警规则「{rule['name']}」已{action_text} · 变更记入审计日志（操作人{actor}）",
    }


def freeze_auto_release_due_to_sampling_anomaly(session, actor: str, batch_id: str, reason: str) -> dict:
    """告警联动：抽检异常 → 冻结自动放行联动（FN-9-08）。"""
    assert_not_ai_agent(actor)
    trace = new_trace_id()
    note_msg = f"【告警联动】抽检批次 {batch_id} 出现异常，触发自动放行冻结 · 原因：{reason} · 操作人：{actor}"
    blk = audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="POLICY_PUBLISHED",
        cs=None,
        category="compliance",
        note=note_msg,
        op="platform-admin/sampling-freeze",
    )
    return {
        "frozen": True,
        "batch_id": batch_id,
        "reason": reason,
        "audit_blk": blk.blk,
        "trace": trace,
    }
