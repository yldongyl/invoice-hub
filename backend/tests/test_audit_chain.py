# -*- coding: utf-8 -*-
"""WP1.4 审计哈希链测试（P02 §4 验收②：seed 15 条装载后链校验通过；
篡改任一记录→校验失败且定位 blk#；导出事件插入链头）。"""

import pytest
from sqlalchemy import select, text

from app.domain import models as m
from app.services import audit_chain as ac
from app.domain.registry import EnumViolation


def _blocks(session):
    return list(session.scalars(select(m.AuditBlock).order_by(m.AuditBlock.blk)))


# ── seed 装载后链校验 ────────────────────────────────────────────────────────

def test_seed_chain_verifies(fresh_session):
    res = ac.verify_chain(fresh_session, verifier="张审计")
    assert res["ok"] is True, res
    assert len(_blocks(fresh_session)) == 15
    for b in _blocks(fresh_session):
        assert b.chain_hash and len(b.chain_hash) == 64
        assert b.chain_scope in ("CN", "OS", "PLATFORM")


def test_seed_chain_domains_independent(fresh_session):
    """双实例独立成链（FN-0-10）：CN 10 块 / OS 2 块 / PLATFORM 3 块（POLICY×2 + EXPORT）。"""
    counts = {}
    for b in _blocks(fresh_session):
        counts[b.chain_scope] = counts.get(b.chain_scope, 0) + 1
    assert counts == {"CN": 10, "OS": 2, "PLATFORM": 3}
    # 每链域首块 prev=GENESIS
    for scope in counts:
        first = min((b for b in _blocks(fresh_session) if b.chain_scope == scope), key=lambda x: x.blk)
        assert first.prev_hash == ac.GENESIS_HASH


def test_genesis_and_linkage(fresh_session):
    """链式前向：每块 prev_hash == 前块 chain_hash。"""
    for scope in ("CN", "OS", "PLATFORM"):
        prev = ac.GENESIS_HASH
        for b in [x for x in _blocks(fresh_session) if x.chain_scope == scope]:
            assert b.prev_hash == prev
            prev = b.chain_hash


# ── 篡改任一记录 → 校验失败且定位 blk# ────────────────────────────────────────

def test_tamper_detected_and_located(fresh_session):
    """改任一记录业务字段（绕过 ORM 直改 DB）→ verify 失败并精确报出 blk#。"""
    target_blk = 10313
    fresh_session.execute(text("UPDATE audit_blocks SET note='伪造：抹掉触发条件' WHERE blk=:b"),
                          {"b": target_blk})
    fresh_session.commit()
    fresh_session.expunge_all()
    res = ac.verify_chain(fresh_session, verifier="张审计")
    assert res["ok"] is False
    assert res["bad_blk"] == target_blk
    # 校验人/时间登记在 VerifyRun
    run = list(fresh_session.scalars(select(m.VerifyRun).order_by(m.VerifyRun.id.desc())))[0]
    assert run.ok is False and run.verifier == "张审计" and run.bad_blk == target_blk


def test_tamper_trace_field_detected(fresh_session):
    fresh_session.execute(text("UPDATE audit_blocks SET trace='tr-deadbeef' WHERE blk=10339"))
    fresh_session.commit()
    fresh_session.expunge_all()
    res = ac.verify_chain(fresh_session)
    assert res["ok"] is False and res["bad_blk"] == 10339


def test_prev_link_tamper_detected(fresh_session):
    fresh_session.execute(text("UPDATE audit_blocks SET prev_hash='" + "f" * 64 + "' WHERE blk=10312"))
    fresh_session.commit()
    fresh_session.expunge_all()
    res = ac.verify_chain(fresh_session)
    assert res["ok"] is False and res["bad_blk"] == 10312


def test_tamper_late_block_locates_first_break_not_chain_end(fresh_session):
    """篡改中间块：定位到被改的那块（前向比对，非末端）。"""
    fresh_session.execute(text("UPDATE audit_blocks SET from_state='RECOGNIZED-FAKE' WHERE blk=10336"))
    fresh_session.commit()
    fresh_session.expunge_all()
    res = ac.verify_chain(fresh_session)
    assert res["bad_blk"] == 10336


# ── 导出事件插入链头 ─────────────────────────────────────────────────────────

def test_export_appends_at_chain_head(fresh_session):
    before_head = ac.head_blk(fresh_session)
    plat_tail = max((x for x in _blocks(fresh_session) if x.chain_scope == ac.PLATFORM_SCOPE),
                    key=lambda x: x.blk)
    expect_prev = plat_tail.chain_hash
    b = ac.append_block(fresh_session, ts=ac.now_iso(), trace=ac.new_trace_id(), actor="human",
                        act="AUDIT_EXPORT", cs=None, from_state="检索条件：近 7 日",
                        to_state="导出 1,284 行 CSV", note="导出行为自审计（演示口径链接 24h 失效）",
                        op="王莉 · 复核员（财务经理）", category="export")
    assert b.blk == before_head + 1          # blk# 递增插入链头
    assert b.chain_scope == ac.PLATFORM_SCOPE
    assert b.prev_hash == expect_prev        # 前向链接自原 PLATFORM 尾块
    assert b.trace and b.trace.startswith("tr-")
    res = ac.verify_chain(fresh_session)
    assert res["ok"] is True                 # 新块前向可验


# ── WORM：应用层禁止 update/delete ───────────────────────────────────────────

def test_worm_orm_update_blocked(fresh_session):
    b = fresh_session.get(m.AuditBlock, 10342)
    b.note = "篡改"
    with pytest.raises(RuntimeError, match="WORM"):
        fresh_session.flush()
    fresh_session.rollback()


def test_worm_orm_delete_blocked(fresh_session):
    b = fresh_session.get(m.AuditBlock, 10343)
    with pytest.raises(RuntimeError, match="WORM"):
        fresh_session.delete(b)
        fresh_session.flush()
    fresh_session.rollback()


def test_append_validates_enums(fresh_session):
    from app.domain.registry import EnumViolation as EV
    with pytest.raises(EV):
        ac.append_block(fresh_session, ts=ac.now_iso(), trace=ac.new_trace_id(),
                        actor="bot", act="STATUS_CHANGE", cs="INV-CN-2026-0387")
    with pytest.raises(EV):
        ac.append_block(fresh_session, ts=ac.now_iso(), trace=ac.new_trace_id(),
                        actor="system", act="NOT_A_CODE", cs="INV-CN-2026-0387")


def test_trace_id_generator_pattern(fresh_session):
    import re
    for _ in range(5):
        assert re.match(r"^tr-[0-9a-f]{8}$", ac.new_trace_id())
