# -*- coding: utf-8 -*-
"""WP1.5 受控写命令框架测试（P02 §4 验收③：五要素逐项缺失拒绝（5 用例）、
批量放行含 BLOCKED 跳过明细正确、edit_field 后原值可追溯；含双人会签拒绝用例）。"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain as ac
from app.services import governed_commands as gc
from app.services import state_machine as sm
from app.services.errors import (E_AUDIT_WRITE_FAILED, E_CONFIRM_INVALID, E_COUNTERSIGN_REQUIRED,
                                 E_EDIT_PARAM_REQUIRED, E_EXPORT_PARAM, E_FIELD_NOT_FOUND,
                                 E_OPINION_REQUIRED, E_PERM_DENIED, E_RISK_NOT_SHOWN,
                                 E_SELF_CONFIRM_REQUIRED, CommandError)


def _status(session, cid):
    return session.get(m.Case, cid).status


def _challenge(session, actor, action, case_id=None, case_ids=None):
    return gc.issue_risk_challenge(session, actor, action, gc.scope_ref(action, case_id, case_ids))["token"]


def _tl_acts(session, cid):
    return [t.event_raw["act"] for t in session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == cid).order_by(m.TimelineEvent.seq))]


# ── 五要素逐项缺失 → 拒绝（5 个用例，P02 §4 验收③） ───────────────────────────

def test_element1_permission_missing_rejected(fresh_session):
    """①权限：运营角色无「受控 Action 放行/退回」权限位 → 拒绝（FN-9-02 矩阵）。"""
    tok = _challenge(fresh_session, "刘工", "release", "INV-CN-2026-0387")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="刘工", action="release", case_id="INV-CN-2026-0387",
                   token=tok, self_confirmed=True)
    assert ei.value.code == E_PERM_DENIED
    assert _status(fresh_session, "INV-CN-2026-0387") == "NEEDS_REVIEW"


def test_element1_ai_actor_rejected(fresh_session):
    """①权限：AI/Agent 不持有 RBAC 角色——LLM 主体发起业务写直接被拒（FN-0-09）。"""
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="qwen-finance-v2", action="release",
                   case_id="INV-CN-2026-0387", token="x", self_confirmed=True)
    assert ei.value.code == E_PERM_DENIED


def test_element2_risk_not_shown_rejected(fresh_session):
    """②风险提示：未携带确认凭据（未经风险展示）→ 拒绝。"""
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="release", case_id="INV-CN-2026-0387",
                   token=None, self_confirmed=True)
    assert ei.value.code == E_RISK_NOT_SHOWN


def test_element3_self_checkbox_missing_rejected(fresh_session):
    """③二次确认+本人勾选：凭据有效但未勾选「由本人执行」→ 拒绝。"""
    tok = _challenge(fresh_session, "王莉", "release", "INV-CN-2026-0387")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="release", case_id="INV-CN-2026-0387",
                   token=tok, self_confirmed=False)
    assert ei.value.code == E_SELF_CONFIRM_REQUIRED
    assert _status(fresh_session, "INV-CN-2026-0387") == "NEEDS_REVIEW"


def test_element3_token_replay_rejected(fresh_session):
    """③凭据一次性：同一确认凭据重复使用 → 拒绝（操作绑定身份+时间戳的一次性证明）。"""
    tok = _challenge(fresh_session, "王莉", "claim", "INV-CN-2026-0387")
    gc.execute(fresh_session, actor="王莉", action="claim", case_id="INV-CN-2026-0387",
               token=tok, self_confirmed=True)
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="claim", case_id="INV-CN-2026-0387",
                   token=tok, self_confirmed=True)
    assert ei.value.code == E_CONFIRM_INVALID


def test_element4_opinion_missing_on_return_rejected(fresh_session):
    """④处置意见：退回类必填备注 → 缺失拒绝（FN-0-08）。"""
    tok = _challenge(fresh_session, "王莉", "return", "INV-SG-2026-0125")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="return", case_id="INV-SG-2026-0125",
                   token=tok, self_confirmed=True, opinion="   ")
    assert ei.value.code == E_OPINION_REQUIRED


def test_element5_audit_failure_rolls_back(fresh_session, monkeypatch):
    """⑤审计留痕：审计双写失败 → 整笔回滚，案件状态与时间线均不变。"""
    tok = _challenge(fresh_session, "王莉", "release", "INV-CN-2026-0384")
    tl_before = _tl_acts(fresh_session, "INV-CN-2026-0384")

    def boom(*a, **k):
        raise RuntimeError("模拟审计存储故障")

    monkeypatch.setattr(gc, "append_block", boom)
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="release", case_id="INV-CN-2026-0384",
                   token=tok, self_confirmed=True)
    assert ei.value.code == E_AUDIT_WRITE_FAILED
    assert _status(fresh_session, "INV-CN-2026-0384") == "NEEDS_REVIEW"
    assert _tl_acts(fresh_session, "INV-CN-2026-0384") == tl_before


# ── 正常执行：双写 + 流转 + 处置意见默认值 ────────────────────────────────────

def test_release_happy_path(fresh_session):
    tok = _challenge(fresh_session, "王莉", "release", "INV-CN-2026-0387")
    out = gc.execute(fresh_session, actor="王莉", action="release", case_id="INV-CN-2026-0387",
                     token=tok, self_confirmed=True, opinion="采纳口径差异解释")
    assert out["from"] == "NEEDS_REVIEW" and out["to"] == "RESOLVED"
    assert _status(fresh_session, "INV-CN-2026-0387") == "RESOLVED"
    acts = _tl_acts(fresh_session, "INV-CN-2026-0387")
    assert acts[-2:] == ["ACTION_RELEASE", "STATUS_CHANGE"]
    # 审计链：ACTION_RELEASE + STATUS_CHANGE 两块入链且链完整
    res = ac.verify_chain(fresh_session)
    assert res["ok"] is True
    # trace 沿用案件原 trace（贯穿）
    assert out["trace"] == "tr-8f3a21c9"


def test_release_without_opinion_falls_back_default(fresh_session):
    """④处置意见未填 → 落库「（未填写处置意见）」（FN-0-08）。"""
    tok = _challenge(fresh_session, "王莉", "release", "INV-CN-2026-0384")
    gc.execute(fresh_session, actor="王莉", action="release", case_id="INV-CN-2026-0384",
               token=tok, self_confirmed=True)
    evs = list(fresh_session.scalars(select(m.TimelineEvent)
             .where(m.TimelineEvent.case_id == "INV-CN-2026-0384")
             .order_by(m.TimelineEvent.seq.desc())))
    rel = next(e for e in evs if e.event_raw["act"] == "ACTION_RELEASE")
    assert "（未填写处置意见）" in rel.event_raw["x"]


def test_hold_transitions_and_holds_doc(fresh_session):
    tok = _challenge(fresh_session, "王莉", "hold", "INV-CN-2026-0384")
    gc.execute(fresh_session, actor="王莉", action="hold", case_id="INV-CN-2026-0384",
               token=tok, self_confirmed=True)
    c = fresh_session.get(m.Case, "INV-CN-2026-0384")
    assert c.status == "INVESTIGATING" and c.doc_hold_pending is True


def test_return_requires_investigating_and_blocks(fresh_session):
    tok = _challenge(fresh_session, "王莉", "return", "INV-SG-2026-0125")
    out = gc.execute(fresh_session, actor="王莉", action="return", case_id="INV-SG-2026-0125",
                     token=tok, self_confirmed=True, opinion="运费 PO 外费用不认，退回重开")
    assert _status(fresh_session, "INV-SG-2026-0125") == "BLOCKED"
    c = fresh_session.get(m.Case, "INV-SG-2026-0125")
    assert c.doc_hold_pending is True
    assert c.meta_raw["document_created_receipt"] is None   # 退回不推送建档
    ab = fresh_session.get(m.AuditBlock, out["blk"])
    assert "退回" in ab.note


# ── 双人会签（P02 §4 验收①：BLOCKED 解除缺会签人被拒） ────────────────────────

def test_unblock_missing_cosigner_rejected(fresh_session):
    tok = _challenge(fresh_session, "王莉", "unblock", "INV-CN-2026-0379")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="unblock", case_id="INV-CN-2026-0379",
                   token=tok, self_confirmed=True)
    assert ei.value.code == E_COUNTERSIGN_REQUIRED


def test_unblock_cosigner_must_be_admin(fresh_session):
    tok = _challenge(fresh_session, "王莉", "unblock", "INV-CN-2026-0379")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="unblock", case_id="INV-CN-2026-0379",
                   token=tok, self_confirmed=True, co_signer="刘工", co_signer_self=True)
    assert ei.value.code == E_COUNTERSIGN_REQUIRED


def test_unblock_cosigner_self_missing_rejected(fresh_session):
    tok = _challenge(fresh_session, "王莉", "unblock", "INV-CN-2026-0379")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="unblock", case_id="INV-CN-2026-0379",
                   token=tok, self_confirmed=True, co_signer="陈铮", co_signer_self=False)
    assert ei.value.code == E_COUNTERSIGN_REQUIRED


def test_unblock_dual_sign_success(fresh_session):
    tok = _challenge(fresh_session, "王莉", "unblock", "INV-CN-2026-0379")
    out = gc.execute(fresh_session, actor="王莉", action="unblock", case_id="INV-CN-2026-0379",
                     token=tok, self_confirmed=True, co_signer="陈铮", co_signer_self=True,
                     opinion="证书链复核为演示数据，解除拦截")
    assert _status(fresh_session, "INV-CN-2026-0379") == "NEEDS_REVIEW"   # 解除后重新流转
    c = fresh_session.get(m.Case, "INV-CN-2026-0379")
    assert c.doc_hold_pending is False
    assert "王莉" in c.meta_raw["claimed_by"] and "陈铮" in c.meta_raw["claimed_by"]
    ab = fresh_session.get(m.AuditBlock, out["blk"])
    assert "双人会签" in ab.note or "会签" in ab.note


# ── edit_field（验收③：修正后原值可追溯） ────────────────────────────────────

def test_edit_field_requires_value_and_reason(fresh_session):
    tok = _challenge(fresh_session, "王莉", "edit_field", "INV-CN-2026-0387")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="edit_field", case_id="INV-CN-2026-0387",
                   token=tok, self_confirmed=True, field="total.gross_amount",
                   new_value=113500.0, reason="")
    assert ei.value.code == E_EDIT_PARAM_REQUIRED


def test_edit_field_unknown_field_rejected(fresh_session):
    tok = _challenge(fresh_session, "王莉", "edit_field", "INV-CN-2026-0387")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="王莉", action="edit_field", case_id="INV-CN-2026-0387",
                   token=tok, self_confirmed=True, field="total.not_a_field",
                   new_value=1, reason="测试")
    assert ei.value.code == E_FIELD_NOT_FOUND


def test_edit_field_traceability_and_rules(fresh_session, case_validator):
    """FN-8-05：值更新、source→manual、confidence→1.0、raw_text 记「原值→新值（原因）」、
    原 page/bbox 保留；FIELD_EDITED 事件入时间线；修正后案件输出仍过契约校验。"""
    row = fresh_session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == "INV-CN-2026-0387",
        m.FieldEvidence.field == "total.gross_amount"))
    old_value = row.evidence_raw["value"]
    old_page, old_bbox = row.evidence_raw["evidence"]["page"], row.evidence_raw["evidence"]["bbox"]
    old_model = row.evidence_raw["evidence"]["model_version"]

    tok = _challenge(fresh_session, "王莉", "edit_field", "INV-CN-2026-0387")
    gc.execute(fresh_session, actor="王莉", action="edit_field", case_id="INV-CN-2026-0387",
               token=tok, self_confirmed=True, field="total.gross_amount",
               new_value=113500.0, reason="票面模糊，以复核测量为准")

    fresh_session.expunge_all()
    row = fresh_session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == "INV-CN-2026-0387",
        m.FieldEvidence.field == "total.gross_amount"))
    e = row.evidence_raw
    assert e["value"] == 113500.0
    assert e["source"] == "manual" and row.source == "manual"
    assert e["confidence"] == 1.0 and row.confidence == 1.0
    assert e["evidence"]["raw_text"] == f"{old_value} → 113500.0（票面模糊，以复核测量为准）"
    assert e["evidence"]["page"] == old_page and e["evidence"]["bbox"] == old_bbox
    assert e["evidence"]["model_version"] == old_model          # Provider 版本保留
    assert e["evidence"]["provider"].startswith("人工修正 · 王莉")
    # FIELD_EDITED 事件
    assert _tl_acts(fresh_session, "INV-CN-2026-0387")[-1] == "FIELD_EDITED"
    ab = list(fresh_session.scalars(select(m.AuditBlock)
           .where(m.AuditBlock.act == "FIELD_EDITED", m.AuditBlock.case_id == "INV-CN-2026-0387")
           .order_by(m.AuditBlock.blk.desc())))[0]
    assert str(old_value) in ab.from_state                      # 原值可从审计链追溯
    # 契约回归：修正后的聚合仍过 invoice-case.schema
    from app.services import case_repository as repo
    errs = list(case_validator.iter_errors(repo.aggregate_case(fresh_session, "INV-CN-2026-0387")))
    assert not errs


# ── 批量（验收③：批量放行含 BLOCKED → 跳过明细正确） ─────────────────────────

def test_batch_release_skips_blocked_with_details(fresh_session):
    ids = ["INV-CN-2026-0387", "INV-CN-2026-0385", "INV-SG-2026-0124"]
    tok = _challenge(fresh_session, "王莉", "batch_release", case_ids=ids)
    out = gc.execute(fresh_session, actor="王莉", action="batch_release", case_ids=ids,
                     token=tok, self_confirmed=True, opinion="口径确认批量放行")
    assert [r["caseId"] for r in out["released"]] == ["INV-CN-2026-0387"]
    skipped = {s["caseId"]: s["reason"] for s in out["skipped"]}
    assert "BLOCKED 不可批量放行" in skipped["INV-CN-2026-0385"]
    assert "VERIFYING" in skipped["INV-SG-2026-0124"]
    assert _status(fresh_session, "INV-CN-2026-0385") == "BLOCKED"   # 未被放行
    assert _status(fresh_session, "INV-CN-2026-0387") == "RESOLVED"


def test_batch_claim(fresh_session):
    ids = ["INV-CN-2026-0381", "INV-CN-2026-0384"]
    tok = _challenge(fresh_session, "王莉", "batch_claim", case_ids=ids)
    out = gc.execute(fresh_session, actor="王莉", action="batch_claim", case_ids=ids,
                     token=tok, self_confirmed=True)
    assert len(out["claimed"]) == 2
    for cid in ids:
        assert fresh_session.get(m.Case, cid).meta_raw["claimed_by"].startswith("王莉")
        assert fresh_session.get(m.Case, cid).status == "NEEDS_REVIEW"   # 认领不扩状态机


# ── 导出自审计（验收③附加：导出行为入链） ────────────────────────────────────

def test_export_requires_condition_and_rowcount(fresh_session):
    tok = _challenge(fresh_session, "张审计", "export")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="张审计", action="export", token=tok,
                   self_confirmed=True, filters=None, rows=None)
    assert ei.value.code == E_EXPORT_PARAM


def test_export_appends_self_audit(fresh_session):
    tok = _challenge(fresh_session, "张审计", "export")
    before = ac.head_blk(fresh_session)
    out = gc.execute(fresh_session, actor="张审计", action="export", token=tok,
                     self_confirmed=True, filters={"近7日": True, "全部主体": True}, rows=1284)
    assert out["blk"] == before + 1
    b = fresh_session.get(m.AuditBlock, out["blk"])
    assert b.act == "AUDIT_EXPORT" and b.chain_scope == ac.PLATFORM_SCOPE
    assert "1284" in b.note and "张审计" in b.op_component and "24" in b.note
    assert ac.verify_chain(fresh_session)["ok"] is True


def test_export_denied_for_ops(fresh_session):
    tok = _challenge(fresh_session, "刘工", "export")
    with pytest.raises(CommandError) as ei:
        gc.execute(fresh_session, actor="刘工", action="export", token=tok,
                   self_confirmed=True, filters={}, rows=1)
    assert ei.value.code == E_PERM_DENIED


def test_unknown_action_rejected(fresh_session):
    with pytest.raises(CommandError):
        gc.execute(fresh_session, actor="王莉", action="deploy", case_id="INV-CN-2026-0387",
                   token="x", self_confirmed=True)
