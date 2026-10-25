# -*- coding: utf-8 -*-
"""案件状态机（WP1.3 · FN-0-02 + CON-02/11 决议）。

纪律：
  - 流转边与触发条件文案一律消费 enum-registry.state_transition 六值（代码内不重写规则文案）；
  - 状态转换属确定性判断（依赖纪律⑥）：系统侧 auto_flow 为引擎通道（M3 受理流水线接线），
    人工侧必须经 WP1.5 受控命令框架进入，本服务不对外暴露裸写路径；
  - 每次流转双写：审计链 STATUS_CHANGE 块（平台视角全量）+ 案件时间线 STATUS_CHANGE 事件（案件视角投影），
    事件带触发条件与组件版本号（case-machine，版本取自 ComponentVersion/versions.json，非硬编码）；
  - CON-02：建档挂起 = doc_hold_pending 子标志（非第七态）；CON-11：认领 = claimed_by/claimed_at/
    claim_lock_expire_at 子态字段，不扩状态机；
  - 断点续跑钩子：查验超时→authenticity NOT_VERIFIED→workers/retry 单独排定重试任务，不重跑识别。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.domain import models as m
from app.domain.registry import get_registry
from app.services import audit_chain, config_center
from app.services.audit_chain import append_block, new_trace_id, now_iso
from app.services.errors import (E_CASE_NOT_FOUND, E_CLAIM_LOCKED, E_ILLEGAL_TRANSITION,
                                 E_STATE_PRECONDITION, CommandError)
from app.workers import retry

EDGE_ARROW = "→"
UNBLOCK_SUFFIX = "解除"


def _status_ns():
    """六态代码命名空间——值由 enum-registry.case_status 派生（禁止散落字面量，依赖纪律④）。"""
    ns = type("Status", (), {})
    for _c in get_registry().category("case_status"):
        setattr(ns, _c, _c)
    return ns


STATUS = _status_ns()


def claim_statuses():
    """复核队列态（CON-11 决议：NEEDS_REVIEW 子态；INVESTIGATING 亦属人工队列态）。"""
    return {STATUS.NEEDS_REVIEW, STATUS.INVESTIGATING}


def load_edges():
    """enum-registry.state_transition → {(from, to): 触发条件文案}；返回 (edges, 解除规则文案)。"""
    reg = get_registry()
    edges, unblock_label = {}, None
    for item in reg.category_items("state_transition"):
        left, right = item["code"].split(EDGE_ARROW)
        right = right.strip()
        if right == UNBLOCK_SUFFIX:
            unblock_label = item["label"]
            continue
        allowed = reg.code_set("case_status")
        if right not in allowed:
            raise ValueError(f"state_transition 目标态 {right!r} 不在 case_status 枚举")
        for f in left.split("/"):
            edges[(f, right)] = item["label"]
    return edges, unblock_label


def get_case(session, case_id: str) -> m.Case:
    c = session.get(m.Case, case_id)
    if c is None:
        raise CommandError(E_CASE_NOT_FOUND, f"案件 {case_id} 不存在", http=404)
    return c


def component_version(session, name: str) -> str:
    """组件版本串（附录 B 基线，如 case-machine v2.2）——时间线 v 字段唯一来源，禁止硬编码。"""
    cv = session.get(m.ComponentVersion, name)
    return f"{name} {cv.version}" if cv and cv.version else name


def append_case_event(session, case: m.Case, *, a: str, act: str, d: str, x: str | None, v: str,
                      commit: bool = True) -> dict:
    """案件时间线追加（append-only；双写审计链由调用方保证）。"""
    reg = get_registry()
    reg.validate("timeline_actor", a, where=f"timeline.{act}")
    reg.validate("timeline_event", act, where=f"timeline.{act}")
    seq = max([t.seq for t in session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == case.case_id))] or [-1]) + 1
    ev = {"t": now_iso(), "a": a, "act": act, "d": d, "x": x, "v": v}
    session.add(m.TimelineEvent(case_id=case.case_id, seq=seq, t=ev["t"], actor=a, act=act,
                                event_raw=ev))
    if commit:
        session.commit()
    return ev


def set_meta(case: m.Case, **updates):
    """meta_raw 变更唯一入口：copy-and-reassign（禁止原地变更 loaded dict——
    原地改会让 SQLAlchemy 脏追踪将「被同步改脏的已提交快照」与新值判等而漏写）。"""
    case.meta_raw = {**case.meta_raw, **updates}


def _sync_meta(session, case: m.Case):
    """契约快照与投影列一致性：meta_raw 为真相源，同步投影列。"""
    meta = case.meta_raw
    case.region = meta.get("region")
    case.instance = meta.get("instance")
    case.invoice_type = meta.get("type")
    case.po = meta.get("po")
    case.supplier = meta.get("supplier")
    case.supplier_id = meta.get("supplier_id")
    case.amount_display = meta.get("amount_display")
    case.risk_label = meta.get("risk_label")
    case.confidence = meta.get("confidence")
    case.provider = meta.get("provider")
    case.trace_id = meta.get("trace_id")
    case.claimed_by = meta.get("claimed_by")
    case.claimed_at = meta.get("claimed_at")
    case.doc_hold_pending = bool(meta.get("doc_hold_pending"))


def _apply_effects(session, case: m.Case, frm: str, to: str):
    """FN-0-02 表附带动作（演示口径：涉及外部系统的通知/建档以注记+接口位承载）。"""
    if to in (STATUS.BLOCKED, STATUS.INVESTIGATING):
        set_meta(case, doc_hold_pending=True)     # CON-02：cXML 建档挂起子标志
    elif to == STATUS.RESOLVED:
        set_meta(case, doc_hold_pending=False)
    _sync_meta(session, case)


def transition(session, case_id: str, to: str, *, subject: str = "system", op: str | None = None,
               extra: str | None = None, via_unblock: bool = False, commit: bool = True) -> dict:
    """一次合法流转：校验边→附带动作→审计链+时间线双写→状态落库。

    subject 取 timeline_actor 枚举（system/human）；op 为审计执行主体描述
    （system=组件版本串；human=「姓名 · 角色」，由命令层传入）。
    """
    case = get_case(session, case_id)
    frm = case.status
    edges, unblock_label = load_edges()
    if via_unblock:
        label = unblock_label or "解除拦截（双人会签）"
    else:
        label = edges.get((frm, to))
        if label is None:
            raise CommandError(E_ILLEGAL_TRANSITION,
                               f"{frm}{EDGE_ARROW}{to} 不在 FN-0-02 流转表（enum-registry.state_transition）内",
                               http=409)
    _apply_effects(session, case, frm, to)
    trace = case.trace_id or new_trace_id()
    if not case.trace_id:
        set_meta(case, trace_id=trace)
        _sync_meta(session, case)
    x = f"触发条件：{label}"
    if extra:
        x = f"{x} · {extra}"
    v = component_version(session, "case-machine")
    result = None
    try:
        ab = append_block(session, ts=now_iso(), trace=trace, actor=subject, act="STATUS_CHANGE",
                          cs=case_id, from_state=frm, to_state=to, note=x, op=op or v,
                          category="status", commit=False)
        append_case_event(session, case, a=subject, act="STATUS_CHANGE",
                          d=f"案件状态 {frm} {EDGE_ARROW} {to}", x=x, v=v, commit=False)
    except Exception as e:  # 要素⑤审计失败→整笔回滚（FN-0-08）
        session.rollback()
        from app.services.errors import E_AUDIT_WRITE_FAILED
        raise CommandError(E_AUDIT_WRITE_FAILED, f"审计双写失败，流转已回滚：{e}", http=500) from e
    case.status = to
    session.commit() if commit else session.flush()
    result = {"caseId": case_id, "from": frm, "to": to, "blk": ab.blk, "trace": trace,
              "trigger": label}
    return result


# ───────────────────────── 触发条件评估（确定性；M3 引擎接线复用） ─────────────────────────

def _check_result(case: m.Case, item: str):
    return ((case.checks_raw or {}).get(item) or {}).get("result")


def redline_hit(case: m.Case, *, dedup_hit: bool = False) -> bool:
    """红线（FN-0-06/5-05）：验真失败 或 查重命中——错误自动放行率红线不可被配置绕过。"""
    return _check_result(case, "authenticity") == "FAILED" or dedup_hit \
        or _check_result(case, "duplicate") == "FAILED"


def _thresholds(session):
    thr = config_center.confidence_threshold_default(session) or 0.85
    po = config_center.get_effective(session, "po_match_tolerance")
    tol = (po.value_raw or {}).get("amount", 50) if po else 50
    return float(thr) * 100, float(tol)


def evaluate(session, case_id: str, *, conflict: bool = False, dedup_hit: bool = False) -> list[dict]:
    """按 FN-0-02 触发条件返回当前态可走的自动边（人工边 release/return/unblock 由命令层触发）。"""
    case = get_case(session, case_id)
    thr, tol = _thresholds(session)
    conf = case.confidence if case.confidence is not None else (case.meta_raw.get("confidence") or 100)
    variance = (case.facts_raw or {}).get("variance")
    results = {k: v["result"] for k, v in (case.checks_raw or {}).items()}
    out = []
    st = case.status
    if st == STATUS.RECOGNIZED:
        if redline_hit(case, dedup_hit=dedup_hit):
            out.append({"to": "BLOCKED", "reason": "authenticity FAILED（验签红线）或查重命中"})
        elif results.get("poMatch") == "AMOUNT_VARIANCE" and results.get("authenticity") == "NOT_VERIFIED":
            out.append({"to": "NEEDS_REVIEW",
                        "reason": "poMatch=AMOUNT_VARIANCE ∧ authenticity=NOT_VERIFIED"})
        elif conf < thr:
            out.append({"to": "NEEDS_REVIEW", "reason": f"低置信（{conf} < 阈值 {thr:.0f}）"})
        elif conflict:
            out.append({"to": "NEEDS_REVIEW", "reason": "关键字段冲突"})
        # 注：FN-0-02 表无 RECOGNIZED→RESOLVED 边（自动路径放行仅存在于 NEEDS_REVIEW/INVESTIGATING→RESOLVED）
    elif st in (STATUS.NEEDS_REVIEW, STATUS.INVESTIGATING):
        if variance is not None and abs(variance) > tol and st == STATUS.NEEDS_REVIEW:
            out.append({"to": "INVESTIGATING", "reason": f"金额差异 {variance} > 调查容差 ±{tol}"})
        elif set(results.values()) == {"PASSED"} and len(results) == 4:
            out.append({"to": "RESOLVED", "reason": "自动路径全部 Checks 通过（FN-0-02 表 4 号边）"})
    elif st == STATUS.BLOCKED:
        out.append({"to": None, "reason": "解除拦截须双人会签（复核员+管理员），经受控命令 unblock"})
    return out


def auto_flow(session, case_id: str, *, conflict: bool = False, dedup_hit: bool = False) -> list[dict]:
    """系统侧自动流转链（受理管线 M3 接线用；本阶段用于六条规则的可测性）。"""
    path = []
    for _ in range(6):  # 有限防环
        cands = [c for c in evaluate(session, case_id, conflict=conflict, dedup_hit=dedup_hit)
                 if c["to"]]
        if not cands:
            break
        pick = cands[0]
        path.append(transition(session, case_id, pick["to"], subject="system", extra=pick["reason"]))
    return path


# ───────────────────────── 认领子态（CON-11 · 不扩状态机） ─────────────────────────

def claim(session, case_id: str, actor_name: str, *, role: str = "复核员",
          org: str | None = None, commit: bool = True) -> dict:
    case = get_case(session, case_id)
    if case.status not in claim_statuses():
        raise CommandError(E_STATE_PRECONDITION,
                           f"认领适用于复核队列态 {sorted(claim_statuses())}，当前 {case.status}（认领不扩状态机）",
                           http=409)
    now_dt = datetime.now(timezone.utc).astimezone()
    lock_min = (config_center.get_effective(session, "__sla_targets").value_raw.get(
        "claim_high_risk_minutes", 30)
        if config_center.get_effective(session, "__sla_targets") else 30)
    holder = case.meta_raw.get("claimed_by")
    if holder:
        exp = case.meta_raw.get("claim_lock_expire_at")
        expired = True
        if exp:
            try:
                expired = datetime.fromisoformat(exp) < now_dt
            except ValueError:
                expired = True
        if not expired and holder.split("（")[0] != actor_name:
            raise CommandError(E_CLAIM_LOCKED, f"案件已被 {holder} 认领且锁未超时（{exp}）", http=409)
    disp = f"{actor_name}（{org}）" if org else actor_name
    set_meta(case, claimed_by=disp,
             claimed_at=now_dt.isoformat(timespec="seconds"),
             claim_lock_expire_at=(now_dt + timedelta(minutes=lock_min)).isoformat(timespec="seconds"))
    _sync_meta(session, case)
    v = component_version(session, "review-ui")
    append_case_event(session, case, a="human", act="REVIEW_OPENED",
                      d="人工认领并开始复核",
                      x=f"复核员：{disp} · 认领动作绑定用户身份与时间戳（认领锁 {lock_min} 分钟）",
                      v=v, commit=False)
    append_block(session, ts=now_iso(), trace=case.trace_id or new_trace_id(), actor="human",
                 act="REVIEW_OPENED", cs=case_id, from_state="未认领", to_state=f"{disp} 认领（复核中）",
                 note=f"认领锁 {lock_min} 分钟 · 认领子态不扩状态机（CON-11）",
                 op=f"{actor_name} · {role}", category="action", commit=False)
    if commit:
        session.commit()
    return {"caseId": case_id, "status": case.status, "claimed_by": disp,
            "lock_expire_at": case.meta_raw["claim_lock_expire_at"]}


# ───────────────────────── BLOCKED 解除（双人会签，命令层校验后调本函数） ─────────────────────────

def lift(session, case_id: str, *, reviewer: str, admin: str, target: str | None = None,
         commit: bool = True) -> dict:
    """解除拦截后按调查结论重新流转（演示口径：默认回落复核队列由人工再处置）。"""
    case = get_case(session, case_id)
    if case.status != STATUS.BLOCKED:
        raise CommandError(E_STATE_PRECONDITION, "仅 BLOCKED 案件需走解除拦截会签流程", http=409)
    set_meta(case, claimed_by=f"{reviewer} · 管理员会签人：{admin}",
             doc_hold_pending=False)            # 解除拦截=建档挂起解除（CON-02）
    _sync_meta(session, case)
    target = target or STATUS.NEEDS_REVIEW      # 解除后默认回落复核队列再处置
    res = transition(session, case_id, target, subject="human",
                     op=f"{reviewer} + {admin}（双人会签）", via_unblock=True,
                     extra=f"会签：复核员 {reviewer} + 管理员 {admin} · 全程留痕",
                     commit=False)
    if commit:
        session.commit()
    return res


# ───────────────────────── 断点续跑钩子：查验超时 ─────────────────────────

def mark_verify_timeout(session, case_id: str, commit: bool = True) -> dict:
    """授权查验超时→authenticity=NOT_VERIFIED→单独排定重试任务（不重跑识别）。"""
    case = get_case(session, case_id)
    checks = {k: dict(v) for k, v in (case.checks_raw or {}).items()}
    checks["authenticity"] = {"result": "NOT_VERIFIED", "note": "授权查验渠道超时 · 已排定自动重试（断点续跑）"}
    case.checks_raw = checks                      # 重赋新对象（JSON 脏追踪）
    row = session.scalar(select(m.CheckResult).where(m.CheckResult.case_id == case_id,
                                                     m.CheckResult.item == "authenticity"))
    if row:
        row.result = "NOT_VERIFIED"
        row.note = checks["authenticity"]["note"]
    v = component_version(session, "bw-cloud-verify")
    trace = case.trace_id or new_trace_id()
    append_case_event(session, case, a="provider", act="AUTH_QUERY_TIMEOUT",
                      d="税务总局授权查验 → 超时 NOT_VERIFIED",
                      x="查验请求已发出，渠道响应超时 · 案件不阻塞其余校验，查验步骤单独排定重试（断点续跑，不重跑识别）",
                      v=v, commit=False)
    append_block(session, ts=now_iso(), trace=trace, actor="provider", act="AUTH_QUERY_TIMEOUT",
                 cs=case_id, from_state="查验进行中", to_state="NOT_VERIFIED",
                 note="超时→单独排定重试（断点续跑钩子）· 识别步骤不重跑", op=v,
                 category="verify", commit=False)
    task = retry.enqueue_verify_retry(session, case_id, commit=False)
    if commit:
        session.commit()
    return {"caseId": case_id, "check": "authenticity", "result": "NOT_VERIFIED",
            "retry_task_id": task.id, "status": case.status}
