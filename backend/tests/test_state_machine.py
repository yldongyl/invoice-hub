# -*- coding: utf-8 -*-
"""WP1.3 状态机测试（P02 §4 验收① 状态机六条流转逐条断言 + 认领不扩态 + 断点续跑钩子）。

用 fresh_session 独立库（避免污染共享 seed 深比对）。
"""

import pytest

from app.domain import models as m
from app.domain.registry import get_registry
from app.services import state_machine as sm
from app.services.errors import (E_CLAIM_LOCKED, E_ILLEGAL_TRANSITION, E_STATE_PRECONDITION,
                                 CommandError)
from sqlalchemy import select


def _get(fresh_session, cid):
    return fresh_session.get(m.Case, cid)


# ── 验收①：FN-0-02 六条流转规则逐条 ──────────────────────────────────────────

def test_rule1_recognized_to_needs_review(fresh_session):
    """RECOGNIZED→NEEDS_REVIEW：poMatch=AMOUNT_VARIANCE ∧ authenticity=NOT_VERIFIED。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    fresh_session.execute(
        m.Case.__table__.update().where(m.Case.case_id == "INV-CN-2026-0386")
        .values(status="RECOGNIZED"))
    fresh_session.commit()
    # 构造触发条件：改 checks_raw
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.checks_raw = {"supplierMatch": {"result": "PASSED", "note": "x"},
                    "authenticity": {"result": "NOT_VERIFIED", "note": "超时"},
                    "duplicate": {"result": "PASSED", "note": "x"},
                    "poMatch": {"result": "AMOUNT_VARIANCE", "note": "差异"}}
    fresh_session.commit()
    ev = sm.evaluate(fresh_session, "INV-CN-2026-0386")
    assert any(e["to"] == "NEEDS_REVIEW" for e in ev), ev
    res = sm.transition(fresh_session, "INV-CN-2026-0386", "NEEDS_REVIEW", subject="system")
    assert res["to"] == "NEEDS_REVIEW"
    assert _get(fresh_session, "INV-CN-2026-0386").status == "NEEDS_REVIEW"
    # 附带动作：STATUS_CHANGE 双写时间线 + 审计块（含组件版本）
    tl = [t.event_raw for t in fresh_session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == "INV-CN-2026-0386"))]
    assert tl[-1]["act"] == "STATUS_CHANGE" and "case-machine" in tl[-1]["v"]


def test_rule1_low_confidence_variant(fresh_session):
    """低置信（<阈值 0.85）也触发 NEEDS_REVIEW（同一边，另一触发条件）。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "RECOGNIZED"
    c.confidence = 70
    c.checks_raw = {k: {"result": "PASSED", "note": "x"}
                    for k in ("supplierMatch", "authenticity", "duplicate", "poMatch")}
    fresh_session.commit()
    ev = sm.evaluate(fresh_session, "INV-CN-2026-0386")
    assert any(e["to"] == "NEEDS_REVIEW" and "低置信" in e["reason"] for e in ev)


def test_rule2_recognized_to_blocked_redline(fresh_session):
    """RECOGNIZED→BLOCKED：验真 FAILED 红线；附带动作=建档挂起 doc_hold_pending。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "RECOGNIZED"
    c.checks_raw = {"supplierMatch": {"result": "PASSED", "note": "x"},
                    "authenticity": {"result": "FAILED", "note": "SM2 失败"},
                    "duplicate": {"result": "PASSED", "note": "x"},
                    "poMatch": {"result": "PASSED", "note": "x"}}
    fresh_session.commit()
    assert sm.redline_hit(_get(fresh_session, "INV-CN-2026-0386")) is True
    res = sm.transition(fresh_session, "INV-CN-2026-0386", "BLOCKED", subject="system")
    assert res["to"] == "BLOCKED"
    c = _get(fresh_session, "INV-CN-2026-0386")
    assert c.meta_raw["doc_hold_pending"] is True      # CON-02：建档挂起子标志，非第七态
    assert c.doc_hold_pending is True


def test_rule2_dedup_hit_variant(fresh_session):
    """RECOGNIZED→BLOCKED：查重命中触发（dedup_hit=True）。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "RECOGNIZED"
    c.checks_raw = {k: {"result": "PASSED", "note": "x"}
                    for k in ("supplierMatch", "authenticity", "duplicate", "poMatch")}
    fresh_session.commit()
    ev = sm.evaluate(fresh_session, "INV-CN-2026-0386", dedup_hit=True)
    assert any(e["to"] == "BLOCKED" for e in ev)


def test_rule3_needs_review_to_investigating(fresh_session):
    """NEEDS_REVIEW→INVESTIGATING：金额差异 > 调查容差（±S$50 / ±0.06 分设，CON-12）。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "NEEDS_REVIEW"
    c.facts_raw = {**c.facts_raw, "variance": 60.0}   # >50（PO 容差，海外口径演示）
    fresh_session.commit()
    ev = sm.evaluate(fresh_session, "INV-CN-2026-0386")
    assert any(e["to"] == "INVESTIGATING" for e in ev)
    res = sm.transition(fresh_session, "INV-CN-2026-0386", "INVESTIGATING", subject="system")
    assert res["to"] == "INVESTIGATING"


def test_rule4_to_resolved_auto_path(fresh_session):
    """NEEDS_REVIEW→RESOLVED：自动路径全 Checks PASSED（人工放行见 test_governed_commands）。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "NEEDS_REVIEW"
    c.checks_raw = {k: {"result": "PASSED", "note": "x"}
                    for k in ("supplierMatch", "authenticity", "duplicate", "poMatch")}
    c.confidence = 99
    fresh_session.commit()
    ev = sm.evaluate(fresh_session, "INV-CN-2026-0386")
    assert any(e["to"] == "RESOLVED" and "自动路径" in e["reason"] for e in ev)
    sm.transition(fresh_session, "INV-CN-2026-0386", "RESOLVED", subject="system")
    assert _get(fresh_session, "INV-CN-2026-0386").status == "RESOLVED"
    assert _get(fresh_session, "INV-CN-2026-0386").meta_raw["doc_hold_pending"] is False


def test_rule5_investigating_to_blocked_return(fresh_session):
    """INVESTIGATING→BLOCKED：人工退回（受控 Action，见命令层；状态机提供边合法性）。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "INVESTIGATING"
    fresh_session.commit()
    res = sm.transition(fresh_session, "INV-CN-2026-0386", "BLOCKED", subject="human",
                        op="王莉 · 复核员", extra="退回供应商")
    assert res["to"] == "BLOCKED"


def test_rule6_blocked_needs_dual_sign_not_direct(fresh_session):
    """BLOCKED 无直接→RESOLVED 边；解除须经 unblock（双人会签，命令层拦截）。"""
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "BLOCKED"
    fresh_session.commit()
    with pytest.raises(CommandError) as ei:
        sm.transition(fresh_session, "INV-CN-2026-0386", "RESOLVED", subject="system")
    assert ei.value.code == E_ILLEGAL_TRANSITION


# ── 认领子态不扩状态机（CON-11） ──────────────────────────────────────────────

def test_claim_substate_does_not_change_status(fresh_session):
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "NEEDS_REVIEW"
    fresh_session.commit()
    before = c.status
    res = sm.claim(fresh_session, "INV-CN-2026-0386", "王莉", org="亚太采购共享中心")
    assert _get(fresh_session, "INV-CN-2026-0386").status == before  # 不扩状态机
    assert res["claimed_by"].startswith("王莉")
    tl = [t.event_raw for t in fresh_session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == "INV-CN-2026-0386"))]
    assert tl[-1]["act"] == "REVIEW_OPENED" and tl[-1]["a"] == "human"


def test_claim_lock_blocks_others_until_timeout(fresh_session):
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "NEEDS_REVIEW"
    fresh_session.commit()
    sm.claim(fresh_session, "INV-CN-2026-0386", "王莉")
    with pytest.raises(CommandError) as ei:
        sm.claim(fresh_session, "INV-CN-2026-0386", "刘工")   # 锁未超时，他人被拒
    assert ei.value.code == E_CLAIM_LOCKED


def test_claim_invalid_state_rejected(fresh_session):
    c = _get(fresh_session, "INV-CN-2026-0386")
    c.status = "RECOGNIZED"     # 非复核队列态
    fresh_session.commit()
    with pytest.raises(CommandError) as ei:
        sm.claim(fresh_session, "INV-CN-2026-0386", "王莉")
    assert ei.value.code == E_STATE_PRECONDITION


# ── 断点续跑钩子：查验超时→NOT_VERIFIED→重试任务，不重跑识别 ──────────────────

def test_verify_timeout_hook_no_recognize_rerun(fresh_session):
    c = _get(fresh_session, "INV-CN-2026-0386")
    fresh_session.commit()
    before_tl = len(list(fresh_session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == "INV-CN-2026-0386"))))
    res = sm.mark_verify_timeout(fresh_session, "INV-CN-2026-0386")
    assert res["result"] == "NOT_VERIFIED"
    assert res["status"] == c.status  # 状态不变
    task = fresh_session.get(m.VerifyRetryTask, res["retry_task_id"])
    assert task.step == "verify_auth"  # 只重试查验步骤
    assert task.state == "queued"
    tl = [t.event_raw for t in fresh_session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == "INV-CN-2026-0386"))]
    assert tl[-1]["act"] == "AUTH_QUERY_TIMEOUT"
    assert len(tl) == before_tl + 1   # 仅新增 1 条超时事件，未重跑识别（无 XML_PARSED/OCR 追加）


def test_illegal_edge_rejected(fresh_session):
    with pytest.raises(CommandError) as ei:
        sm.transition(fresh_session, "INV-CN-2026-0387", "VERIFYING", subject="system")  # 无此边
    assert ei.value.code == E_ILLEGAL_TRANSITION


def test_edges_are_registry_defined_no_redefinition():
    """流转边一律来自 enum-registry.state_transition 六值（触发条件不代码内重写）。"""
    edges, unblock_label = sm.load_edges()
    reg = get_registry()
    items = reg.category_items("state_transition")
    assert len(edges) == 6 and unblock_label is not None   # 6 条普通边（NEEDS_REVIEW/INVESTIGATING 复合左侧拆 2）+ 1 条解除规则
    for item in items:
        left, right = item["code"].split("→")
        for f in left.split("/"):
            to = right.strip()
            if to == "解除":
                continue
            assert edges[(f, to)] == item["label"]        # 触发条件文案逐字引用注册表
