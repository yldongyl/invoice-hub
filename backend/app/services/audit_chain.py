# -*- coding: utf-8 -*-
"""审计哈希链服务（WP1.4 · FN-0-10）。

链式 SHA-256（prev→this）、append-only（WORM：ORM 层拦截 update/delete）、
按链域独立成链（CN / OS / PLATFORM——无案件归属的平台事件单列成链，演示口径）、
链头管理（blk# 全局递增分配，跨链域共享序号，与 audit_events.json blk 口径一致）、
完整性校验（逐条前向比对，任一字段被篡改→定位首个断点 blk#，校验人/时间登记 VerifyRun）、
trace 贯穿（tr-{8hex} 生成器：编号发号器正式实装属 WP1.7，此处以 secrets 随机 hex 生成并做 pattern 校验，
标注 TODO(WP1.7)）。

canonical 记录载荷（FN-0-10）：
  {blk, ts, trace_id, actor, act, cs, from, to, note, op, prev_hash}
  hash = SHA-256( canonical_json ) 的 hexdigest（64hex）。
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone

from sqlalchemy import event, select

from app.domain import models as m
from app.domain.registry import get_registry
from app.services.persistence import Base

GENESIS_HASH = "0" * 64
PLATFORM_SCOPE = "PLATFORM"


class ChainTampered(Exception):
    def __init__(self, blk: int, scope: str, reason: str):
        self.blk = blk
        self.scope = scope
        self.reason = reason
        super().__init__(f"链校验失败 @ blk#{blk}（链域 {scope}）: {reason}")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_trace_id() -> str:
    """tr-{8位hex}（enum-registry.id_format）。TODO(WP1.7): 正式发号器实装后替换。"""
    tid = f"tr-{secrets.token_hex(4)}"
    assert trace_ok(tid), f"trace 生成不符 pattern: {tid}"
    return tid


def trace_ok(tid: str) -> bool:
    import re
    return bool(re.match(get_registry().id_pattern("trace ID"), tid))


def _seg_to_scope(seg: str) -> str:
    """案件号实例段 → 链域：CN 段=CN 实例；SG 段=OS 实例（CON-04 决议）。"""
    return {"CN": "CN", "SG": "OS"}.get(seg, PLATFORM_SCOPE)


def scope_of(case_id: str | None) -> str:
    if case_id and case_id.startswith("INV-"):
        return _seg_to_scope(case_id[4:6])
    return PLATFORM_SCOPE


def record_payload(blk, ts, trace, actor, act, cs, from_state, to_state, note, op, prev_hash):
    return {
        "blk": blk, "ts": ts, "trace_id": trace, "actor": actor, "act": act,
        "cs": cs, "from": from_state, "to": to_state, "note": note, "op": op,
        "prev_hash": prev_hash,
    }


def compute_hash(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _chain_blocks(session, scope: str):
    return list(session.scalars(
        select(m.AuditBlock).where(m.AuditBlock.chain_scope == scope).order_by(m.AuditBlock.blk)))


def build_chain(session) -> dict:
    """建链/重建：按链域逐块计算 prev_hash 与本块 hash（装载与恢复用；幂等——重算结果一致）。

    注：本函数会更新块内链列（链元数据非业务内容，WORM 语义保护业务字段不被改写；
    测试篡改会改 note/from 等业务字段导致 hash 前向不一致，仍可检出并定位）。
    """
    summary = {}
    for scope in (scope for scope in {b.chain_scope for b in session.scalars(select(m.AuditBlock))} if scope):
        prev = GENESIS_HASH
        for b in _chain_blocks(session, scope):
            b.prev_hash = prev
            payload = record_payload(b.blk, b.ts, b.trace, b.actor, b.act, b.case_id,
                                     b.from_state, b.to_state, b.note, b.op_component, prev)
            b.chain_hash = compute_hash(payload)
            prev = b.chain_hash
        summary[scope] = {"count": len(_chain_blocks(session, scope)), "head_blk": prev}
    session.commit()
    return summary


def head_blk(session) -> int:
    blk = session.scalar(select(_max_blk()))
    return blk or 0


def _max_blk():
    from sqlalchemy import func
    return func.max(m.AuditBlock.blk)


def append_block(session, *, ts, trace, actor, act, cs=None, from_state=None, to_state=None,
                 note=None, op=None, category=None, commit=True) -> m.AuditBlock:
    """链头追加新块（唯一合法写入路径；WORM——不 update 不 delete）。

    actor 主体枚举（timeline_actor）、act 事件码（timeline_event）由 registry 校验（调用方命令层已校验，此处防御再验）。
    blk# 全局递增（跨链域共享序号，与 M0 种子链头 blk 口径一致）。
    """
    reg = get_registry()
    reg.validate("timeline_actor", actor, where="audit.actor")
    reg.validate("timeline_event", act, where="audit.act")
    scope = scope_of(cs)
    blk = head_blk(session) + 1
    prev = GENESIS_HASH
    chain = _chain_blocks(session, scope)
    if chain:
        prev = chain[-1].chain_hash or GENESIS_HASH
    inst = session.get(m.Case, cs).instance if cs and session.get(m.Case, cs) else None
    b = m.AuditBlock(blk=blk, ts=ts, trace=trace, actor=actor, act=act, category=category,
                     case_id=cs, from_state=from_state, to_state=to_state, note=note,
                     op_component=op, hash_display=f"{compute_hash(record_payload(blk, ts, trace, actor, act, cs, from_state, to_state, note, op, prev))[:4]}…",
                     instance=inst,
                     chain_scope=scope, prev_hash=prev)
    b.chain_hash = compute_hash(record_payload(blk, ts, trace, actor, act, cs, from_state,
                                               to_state, note, op, prev))
    session.add(b)
    if commit:
        session.commit()
    return b


def verify_chain(session, verifier: str = "system", scope: str | None = None) -> dict:
    """逐条前向比对，登记校验人/时间/结果（VerifyRun）。

    返回 {ok, bad_blk, scope, detail}；默认校验全部链域（scope=None）。篡改任一块 → 返回首个断点 blk#。
    """
    scopes = [scope] if scope else sorted(
        {b.chain_scope for b in session.scalars(select(m.AuditBlock)) if b.chain_scope})
    for sc in scopes:
        prev = GENESIS_HASH
        for b in _chain_blocks(session, sc):
            expected = compute_hash(record_payload(b.blk, b.ts, b.trace, b.actor, b.act, b.case_id,
                                                   b.from_state, b.to_state, b.note, b.op_component, prev))
            if (b.prev_hash or GENESIS_HASH) != prev:
                _record_run(session, verifier, sc, False, b.blk, "prev_hash 链接断裂")
                return {"ok": False, "bad_blk": b.blk, "scope": sc, "detail": "prev_hash 链接断裂"}
            if (b.chain_hash or "") != expected:
                _record_run(session, verifier, sc, False, b.blk, "本块 hash 与内容不一致（内容被篡改）")
                return {"ok": False, "bad_blk": b.blk, "scope": sc, "detail": "本块 hash 与内容不一致"}
            prev = b.chain_hash
        _record_run(session, verifier, sc, True, None, f"链域 {sc} 全量校验通过")
    ok_all = True
    return {"ok": ok_all, "bad_blk": None, "scope": scope, "detail": "全部链域校验通过"}


def _record_run(session, verifier, scope, ok, bad_blk, detail):
    session.add(m.VerifyRun(ran_at=now_iso(), verifier=verifier, scope=scope, ok=ok,
                            bad_blk=bad_blk, detail=detail))
    session.commit()


# ── WORM：应用层禁止 update/delete 审计块（P02 WP1.4 / FN-0-10） ──────────────
# 业务字段一旦写入不可变更；链列（prev_hash/chain_hash）允许 build_chain 重算（链元数据，
# 非业务内容——业务字段被改会令前向 hash 不一致，篡改仍可检出并定位 blk#）。
_IMMUTABLE_FIELDS = ("blk", "ts", "trace", "actor", "act", "category", "case_id",
                     "from_state", "to_state", "note", "op_component", "hash_display",
                     "instance", "chain_scope")


@event.listens_for(m.AuditBlock, "before_update", propagate=True)
def _guard_update(mapper, connection, target):
    from sqlalchemy import inspect as sa_inspect
    state = sa_inspect(target)
    for attr in _IMMUTABLE_FIELDS:
        if getattr(state.attrs, attr).history.has_changes():
            raise RuntimeError(f"WORM：审计块业务字段 {attr} 不可变更（blk#{target.blk}）")


@event.listens_for(m.AuditBlock, "before_delete", propagate=True)
def _guard_delete(mapper, connection, target):
    raise RuntimeError(f"WORM：审计块不可删除（blk#{target.blk}）——append-only 语义")
