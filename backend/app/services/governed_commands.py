# -*- coding: utf-8 -*-
"""受控写命令框架（WP1.5 · FN-0-08 全站唯一业务写入口）。

五要素强制全序（缺一即拒，返回明确错误码）：
  ① 权限校验：actor → 角色 → users_roles 权限位（矩阵桩；RBAC 服务 M5 实装；AI/LLM 不持有角色）；
  ② 风险提示：服务端签发 risk-challenge（文案+一次性凭据），执行必须携带有效凭据；
  ③ 二次确认+本人执行勾选：凭据校验（绑定 actor/action/目标、TTL、一次性）+ self_confirmed 勾选；
  ④ 处置意见：拒绝/退回类必填；未填落库「（未填写处置意见）」；edit_field 的新值+原因必填（FN-8-05）；
  ⑤ 审计留痕：审计哈希链 + 案件时间线双写；双写失败→整笔回滚（E_AUDIT_WRITE_FAILED）。
批量命令逐案校验：BLOCKED 跳过并返回跳过明细（FN-0-08 红线：BLOCKED 不可批量放行）。
演示口径（P00 §6）：confirm 凭据为本地签发的演示桩（非真实 MFA/会话）；退回邮件通知、放行后
建档推送为桩注记（M3/M4 接线），代码注释标明。
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.domain import models as m
from app.domain.registry import get_registry
from app.services import audit_chain, config_center, state_machine
from app.services.state_machine import STATUS
from app.services.audit_chain import append_block, new_trace_id, now_iso
from app.services.errors import (E_AUDIT_WRITE_FAILED, E_CONFIRM_INVALID,
                                 E_COUNTERSIGN_REQUIRED, E_EDIT_PARAM_REQUIRED, E_EXPORT_PARAM,
                                 E_FIELD_NOT_FOUND, E_OPINION_REQUIRED, E_PERM_DENIED,
                                 E_RISK_NOT_SHOWN, E_SELF_CONFIRM_REQUIRED,
                                 E_STATE_PRECONDITION, E_TENANT_MISMATCH, CommandError)
from app.services.tenant import TenantContext

# 权限位名称词汇 = seeds/users_roles.json permissions（运行期对照数据校验，防漂移）
PERM_VIEW = "案件查看"
PERM_ACTION = "受控 Action 放行/退回"
PERM_EDIT = "字段修正"
PERM_EXPORT = "审计导出"
PERM_PUBLISH = "策略发布"      # WP1.8 发布/回滚（FN-9-02 权限位⑤，管理员持有）
PERM_INTAKE = "受理提交"       # M3 WP3.2 权限位⑧（FN-1-08 受控写要素①；CHANGELOG ⑧ 裁决）

UNOPINIONED = "（未填写处置意见）"
OPINION_REQUIRED_ACTIONS = {"return"}          # FN-0-08：拒绝/退回类必填备注
RELEASE_STATES = {STATUS.NEEDS_REVIEW, STATUS.INVESTIGATING}   # FN-0-02 放行前提
RETURN_STATE = STATUS.INVESTIGATING   # FN-0-02 退回供应商触发边所在态
# 无目标案件的框架级动作（scope 由业务对象摘要绑定）
NON_CASE_ACTIONS = {"export", "publish", "rollback", "intake"}

ACTION_PERMS = {
    "release": PERM_ACTION, "hold": PERM_ACTION, "return": PERM_ACTION, "unblock": PERM_ACTION,
    "batch_release": PERM_ACTION,
    "edit_field": PERM_EDIT,
    "claim": PERM_VIEW, "batch_claim": PERM_VIEW,
    "export": PERM_EXPORT,
    "publish": PERM_PUBLISH, "rollback": PERM_PUBLISH,
    "intake": PERM_INTAKE,                 # 受理提交（FN-1-08：门户上传=业务写，走五要素全序）
}

RISK_TEXT = {
    "release": "放行后案件进入 RESOLVED 并推送 SAP Ariba cXML 建档流程（warn 级：建档后回退须走冲减流程，不可静默撤销）。",
    "hold": "挂起后进入 INVESTIGATING，系统只读收集 PO/GRN/合同证据，建档保持挂起。",
    "return": "【danger】退回供应商将生成邮件退回通知（演示桩通道）、状态置 BLOCKED、不推送建档；理由必填。",
    "edit_field": "人工修正后字段来源置 manual、置信度 1.0；原识别值、坐标与 Provider 版本永久保留可追溯（FN-8-05）。",
    "claim": "认领将案件锁定至你本人并启动 SLA 处理计时（认领锁超时后可被他人接管）。",
    "unblock": "【danger】解除 BLOCKED 红线案件须复核员+管理员双人会签；解除后按调查结论重新流转，全程留痕。",
    "batch_release": "批量放行逐案校验状态；BLOCKED 案件将被跳过（红线：BLOCKED 不可批量放行）。",
    "batch_claim": "批量认领逐案校验；已被他人锁定（未超时）或状态不符的案件将被跳过。",
    "export": "导出行为本身写入审计链（操作人/时间/检索条件/行数），下载链接 24 小时后失效（演示口径）。",
    "publish": "【warn】配置发布即时生效：前值→后值 diff 已留痕、旧版本保留可回滚、POLICY_PUBLISHED 入审计链（FN-0-12/FN-9-09）；红线项关闭将被拒绝。",
    "rollback": "【warn】回滚=以目标历史版本载荷发布新版本（不删历史）；变更链完整可追。",
    "intake": "受理提交后文件进入五步流水线（信封解析→非发票过滤→载体分流→SHA-256 摘要登记→路由派生案件），"
              "逐文件清单与原件摘要将写入不可篡改审计日志；非发票文档将被拒绝入池并退回通知留痕（FN-1-08）。",
}


def intake_scope_digest(files_meta: list[dict], po_ref: str | None = None) -> str:
    """受理提交确认凭据 scope：绑定逐文件清单（name:size）+目标实例上下文之外由调用方拼 instance。
    风险提示签发与执行时按实际字节重算比对——清单被换=凭据失效（要素③错绑拒绝）。"""
    canon = "|".join(f"{f['name']}:{f['size']}" for f in sorted(files_meta, key=lambda x: x["name"]))
    if po_ref:
        canon += f"|po:{po_ref}"
    return "intake:" + hashlib.sha256(canon.encode()).hexdigest()[:12]


def _now():
    return datetime.now(timezone.utc).astimezone()


def scope_ref(action: str, case_id: str | None = None, case_ids: list[str] | None = None,
              config_key: str | None = None) -> str:
    """确认凭据绑定目标：单案=caseId；批量=目标集摘要；导出=audit-export；发布/回滚=config:{key}。"""
    if action.startswith("batch_"):
        return "batch:" + hashlib.sha256("|".join(sorted(case_ids or [])).encode()).hexdigest()[:12]
    if action == "export":
        return "audit-export"
    if action in ("publish", "rollback"):
        return f"config:{config_key}" if config_key else "config:unknown"
    return case_id or "unknown"


def issue_risk_challenge(session, actor: str, action: str, scope_ref: str,
                         ttl_seconds: int = 600) -> dict:
    """要素②：服务端风险提示 + 要素③凭据签发（一次性、绑定 actor/action/目标）。"""
    if action not in ACTION_PERMS:
        raise CommandError("UNKNOWN_ACTION", f"未注册命令 {action!r}（FN-0-08 框架外写路径=缺陷）")
    _require_user(session, actor)
    token = secrets.token_hex(24)
    now_dt = _now()
    expires = now_dt + timedelta(seconds=ttl_seconds)
    session.add(m.ConfirmToken(token=token, actor=actor, action=action, scope_ref=scope_ref,
                               issued_at=now_dt.isoformat(timespec="seconds"),
                               expires_at=expires.isoformat(timespec="seconds")))
    session.commit()
    return {"action": action, "target": scope_ref, "risk_text": RISK_TEXT[action],
            "token": token, "expires_at": expires.isoformat(timespec="seconds"),
            "self_confirm_label": "我已核对证据，确认由本人执行（AI / Agent / LLM 建议不自动执行）"}


def _consume_token(session, token: str | None, actor: str, action: str, scope_ref: str):
    if not token:
        raise CommandError(E_RISK_NOT_SHOWN, "缺少二次确认凭据：须先请求风险提示（要素②③）", http=428)
    row = session.get(m.ConfirmToken, token)
    if row is None:
        raise CommandError(E_CONFIRM_INVALID, "确认凭据无效（不存在）", http=428)
    if row.consumed_at:
        raise CommandError(E_CONFIRM_INVALID, "确认凭据已使用（一次性）", http=428)
    if row.expires_at <= now_iso():
        raise CommandError(E_CONFIRM_INVALID, "确认凭据已过期，请重新确认风险", http=428)
    if (row.actor, row.action, row.scope_ref) != (actor, action, scope_ref):
        raise CommandError(E_CONFIRM_INVALID, "确认凭据与本操作的执行人/动作/目标不匹配", http=428)
    row.consumed_at = now_iso()


def _require_user(session, actor: str) -> m.UserAccount:
    user = session.get(m.UserAccount, actor)
    if user is None:
        raise CommandError(E_PERM_DENIED,
                           f"主体 {actor!r} 无平台身份——AI/Agent/LLM 不持有 RBAC 角色（FN-0-09），业务写操作仅真人可发起",
                           http=403)
    if user.status != "启用":
        raise CommandError(E_PERM_DENIED, f"用户 {actor} 状态={user.status}，已停用", http=403)
    return user


def _resolve_role_name(session, user: m.UserAccount) -> str:
    """UserAccount.role 为展示串（如「复核员 · 财务经理」），RoleDef.name 为矩阵名——取最长包含匹配。"""
    names = [r.name for r in session.scalars(select(m.RoleDef)) if r.name in (user.role or "")]
    if not names:
        raise CommandError(E_PERM_DENIED, f"无法解析用户角色：{user.role!r}", http=403)
    return max(names, key=len)


def require_permission(session, actor: str, action: str) -> tuple[m.UserAccount, str]:
    """要素①：权限位校验（矩阵暂用 users_roles.json，M5 实装 RBAC 服务）。"""
    user = _require_user(session, actor)
    perm = ACTION_PERMS[action]
    meta = session.get(m.SeedMeta, "permissions")
    perms = (meta.payload.get("permissions") if meta else None) or []
    if perm not in perms:
        raise CommandError(E_PERM_DENIED, f"权限位 {perm!r} 不在 users_roles 权限矩阵", http=403)
    role_name = _resolve_role_name(session, user)
    role = session.get(m.RoleDef, role_name)
    grants = role.grants or []
    if perms.index(perm) >= len(grants) or grants[perms.index(perm)] != 1:
        raise CommandError(E_PERM_DENIED,
                           f"角色 {role_name} 不具备权限位「{perm}」（FN-9-02 矩阵 / FN-0-08 要素①）", http=403)
    return user, role_name


def _op(user: m.UserAccount) -> str:
    return f"{user.name} · {user.role}"


# ───────────────────────── 单案执行内核（五要素齐备后调用） ─────────────────────────

def _action_event(session, case, *, act, d, x, user, role):
    v = state_machine.component_version(session, "review-ui")
    state_machine.append_case_event(session, case, a="human", act=act, d=d, x=x, v=v, commit=False)
    append_block(session, ts=now_iso(), trace=case.trace_id or new_trace_id(), actor="human",
                 act=act, cs=case.case_id, from_state=case.status,
                 to_state=_ACT_TO[act], note=x, op=_op(user), category="action", commit=False)


_ACT_TO = {"ACTION_RELEASE": "放行（RELEASE）", "ACTION_HOLD": "挂起（HOLD）",
           "ACTION_RETURN": "退回供应商（RETURN）", "FIELD_EDITED": "已修正",
           "REVIEW_OPENED": "已认领", "AUDIT_EXPORT": "已导出", "STATUS_CHANGE": "已流转"}


def _do_release(session, case, user, role, opinion):
    if case.status == STATUS.BLOCKED:
        raise CommandError(E_STATE_PRECONDITION,
                           "BLOCKED 不可放行——解除拦截须单独走双人会签（FN-0-08/FN-8-06）", http=409)
    if case.status not in RELEASE_STATES:
        raise CommandError(E_STATE_PRECONDITION,
                           f"当前态 {case.status} 不可放行（放行前提：NEEDS_REVIEW/INVESTIGATING）", http=409)
    x = f"处置意见：{opinion or UNOPINIONED} · 受控写五要素齐备 · 采纳口径解释（如有）不自动执行 AI 建议"
    _action_event(session, case, act="ACTION_RELEASE", d="受控 Action：放行（受控确认）", x=x,
                  user=user, role=role)
    res = state_machine.transition(session, case.case_id, "RESOLVED", subject="human",
                                   op=_op(user), extra="触发目标系统建档（FN-7，Ariba stub M4 接线；演示口径不实际外呼）",
                                   commit=False)
    return {"released": True, **res, "opinion": opinion or UNOPINIONED}


def _do_hold(session, case, user, role, opinion):
    if case.status != "NEEDS_REVIEW":
        raise CommandError(E_STATE_PRECONDITION, "挂起适用于 NEEDS_REVIEW 案件", http=409)
    x = f"处置意见：{opinion or UNOPINIONED} · 进入主动调查（只读取证），建档保持挂起"
    _action_event(session, case, act="ACTION_HOLD", d="受控 Action：挂起", x=x, user=user, role=role)
    res = state_machine.transition(session, case.case_id, "INVESTIGATING", subject="human",
                                   op=_op(user), extra="证据收集只读（investigator M5 接线 · 演示口径排程）",
                                   commit=False)
    return {"held": True, **res}


def _do_return(session, case, user, role, opinion):
    if not opinion:
        raise CommandError(E_OPINION_REQUIRED, "退回供应商必须填写处置意见/理由（FN-0-08 要素④）", http=422)
    if case.status != RETURN_STATE:
        raise CommandError(E_STATE_PRECONDITION,
                           f"退回供应商触发边为 INVESTIGATING→BLOCKED（当前 {case.status}）", http=409)
    x = f"处置意见：{opinion} · 生成退回通知（邮件 · 演示桩通道，TODO(M3/FN-1-04)）· 不推送建档"
    _action_event(session, case, act="ACTION_RETURN", d="受控 Action：退回供应商", x=x, user=user, role=role)
    res = state_machine.transition(session, case.case_id, "BLOCKED", subject="human", op=_op(user),
                                   extra=f"退回供应商：{opinion}", commit=False)
    return {"returned": True, **res}


def _do_edit_field(session, case, user, role, *, field, new_value, reason, opinion):
    if new_value is None or not (reason or "").strip():
        raise CommandError(E_EDIT_PARAM_REQUIRED, "人工修正须同时提供新值与修改原因（FN-8-05）", http=422)
    rows = session.scalars(select(m.FieldEvidence).where(m.FieldEvidence.case_id == case.case_id,
                                                         m.FieldEvidence.field == field)).all()
    if not rows:
        raise CommandError(E_FIELD_NOT_FOUND, f"字段 {field} 不在案件证据链（可修正字段=已识别字段）", http=422)
    reg = get_registry()
    reg.validate("field_source", "manual", where="edit_field")
    results = []
    for row in rows:
        entry = dict(row.evidence_raw)
        old_value = entry.get("value")
        ev = dict(entry.get("evidence") or {})
        old_provider = ev.get("provider")
        ev["raw_text"] = f"{old_value} → {new_value}（{reason}）"  # 原值→新值（原因），原 page/bbox 保留
        ev["provider"] = f"人工修正 · {user.name}"
        entry["value"] = new_value
        entry["source"] = "manual"
        entry["confidence"] = 1.0
        entry["evidence"] = ev
        row.evidence_raw = entry
        row.source = "manual"
        row.confidence = 1.0
        results.append({"field": field, "from": old_value, "to": new_value,
                        "provider_retained": old_provider})
    x = (f"修改原因：{reason} · 来源标记「人工」· 原识别值、坐标与 Provider 版本保留可追溯"
         + (f" · 处置意见：{opinion}" if opinion else ""))
    state_machine.append_case_event(
        session, case, a="human", act="FIELD_EDITED",
        d=f"人工修正字段 {field}：{results[0]['from']} → {results[0]['to']}",
        x=x, v=state_machine.component_version(session, "review-ui"), commit=False)
    append_block(session, ts=now_iso(), trace=case.trace_id or new_trace_id(), actor="human",
                 act="FIELD_EDITED", cs=case.case_id,
                 from_state=f"{field} {results[0]['from']}（{results[0]['provider_retained']}）",
                 to_state=f"{results[0]['to']}（manual · 置信度 1.0）",
                 note=x, op=_op(user), category="field", commit=False)
    return {"edited": True, "caseId": case.case_id, "results": results}


def _do_claim(session, case, user, role, opinion):
    res = state_machine.claim(session, case.case_id, user.name, role=role, org=user.org,
                              commit=False)
    return {"claimed": True, **res}


def _do_unblock(session, case, user, role, *, co_signer, co_signer_self, opinion):
    """双人会签：发起人须复核权限，会签人须管理员权限位且为启用真人、不得同人、须本人确认。"""
    if not co_signer:
        raise CommandError(E_COUNTERSIGN_REQUIRED,
                           "解除 BLOCKED 拦截须复核员+管理员双人会签——缺会签人（FN-0-02/FN-8-06）", http=409)
    if co_signer == user.name:
        raise CommandError(E_COUNTERSIGN_REQUIRED, "会签人不得与发起人为同一人", http=409)
    admin = _require_user(session, co_signer)
    admin_role = _resolve_role_name(session, admin)
    if admin_role != "管理员":
        raise CommandError(E_COUNTERSIGN_REQUIRED,
                           f"会签人 {co_signer} 非管理员角色（矩阵要求：复核员 + 管理员，FN-8-06）", http=403)
    if not co_signer_self:
        raise CommandError(E_COUNTERSIGN_REQUIRED,
                           f"会签人 {co_signer} 未完成本人执行勾选（要素③同样适用于会签人）", http=422)
    if case.status != STATUS.BLOCKED:
        raise CommandError(E_STATE_PRECONDITION, "仅 BLOCKED 案件走解除会签", http=409)
    x = f"双人会签：复核员 {user.name} + 管理员 {co_signer} · 处置意见：{opinion or UNOPINIONED} · 解除后按调查结论重新流转"
    state_machine.append_case_event(session, case, a="human", act="REVIEW_OPENED",
                                    d="解除拦截（双人会签）", x=x,
                                    v=state_machine.component_version(session, "review-ui"), commit=False)
    res = state_machine.lift(session, case.case_id, reviewer=user.name, admin=co_signer, commit=False)
    # 会签补记入链（复核员 op 由 transition 写 STATUS_CHANGE；此处补管理员签署块）
    append_block(session, ts=now_iso(), trace=case.trace_id or new_trace_id(), actor="human",
                 act="STATUS_CHANGE", cs=case.case_id, from_state="BLOCKED",
                 to_state=f"{res['to']}（会签补记）",
                 note=f"会签人签署：{co_signer} · 本人执行已勾选", op=_op(admin), category="status",
                 commit=False)
    return {"unblocked": True, **res, "signers": [user.name, co_signer]}


def _do_batch(session, case_ids, user, role, *, release: bool, opinion):
    released, claimed, skipped = [], [], []
    for cid in case_ids:
        case = state_machine.get_case(session, cid)
        if release:
            if case.status == STATUS.BLOCKED:
                skipped.append({"caseId": cid, "reason": "BLOCKED 不可批量放行（红线）——解除须单独双人会签"})
                continue
            if case.status not in RELEASE_STATES:
                skipped.append({"caseId": cid, "reason": f"当前态 {case.status} 不在放行前提（NEEDS_REVIEW/INVESTIGATING）"})
                continue
            try:
                r = _do_release(session, case, user, role, opinion)
                released.append({"caseId": cid, "blk": r["blk"]})
            except CommandError as e:
                skipped.append({"caseId": cid, "reason": e.message})
        else:
            if case.status not in state_machine.claim_statuses():
                skipped.append({"caseId": cid, "reason": f"当前态 {case.status} 不在复核队列态，不可认领"})
                continue
            try:
                res = state_machine.claim(session, cid, user.name, role=role, commit=False)
                claimed.append({"caseId": cid, "lock_expire_at": res["lock_expire_at"]})
            except CommandError as e:
                skipped.append({"caseId": cid, "reason": e.message})
    return {"released": released, "claimed": claimed, "skipped": skipped,
            "processed": len(released) + len(claimed), "skipped_count": len(skipped)}


def _do_export(session, user, role, *, filters, rows):
    if filters is None or rows is None:
        raise CommandError(E_EXPORT_PARAM, "导出须携带检索条件与行数（审计留痕要素，FN-8-07）", http=422)
    trace = new_trace_id()
    fr = f"检索条件：{_fmt_filters(filters)}"
    to = f"导出 {rows} 行 CSV"
    fnote = (f"文件 audit-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv · "
             f"操作人 {_op(user)} · 时间 {now_iso()} · 行数 {rows} · 下载链接 24 小时后失效（演示口径）")
    ab = append_block(session, ts=now_iso(), trace=trace, actor="human", act="AUDIT_EXPORT",
                      cs=None, from_state=fr, to_state=to, note=fnote, op=_op(user),
                      category="export")
    return {"file": fnote.split(" · ")[0].replace("文件 ", ""), "rows": rows,
            "blk": ab.blk, "trace": trace, "expires": "24h（演示口径）"}


def _asset_type_for(key: str) -> str:
    """受控发布资产域路由（M3：channel:* → 渠道配置；intake_rules → 受理规则版本资产）。"""
    from app.services import versioning
    if key.startswith("channel:"):
        return "channel_config"
    if key == "intake_rules":
        return "intake_rules"
    return versioning.ASSET_CONFIG


def _do_publish(session, user, role, key, payload, opinion):
    """配置发布内核：转 versioning（diff/版本递增/旧版保留/POLICY_PUBLISHED 入链）。"""
    from app.services import versioning
    return {"published": True, **versioning.publish(session, key, user.name,
                                                    payload=payload, opinion=opinion,
                                                    asset_type=_asset_type_for(key))}


def _do_intake(session, user, role, *, instance: str, files: list[dict], po_ref: str | None,
               opinion: str | None, scope: str) -> dict:
    """受理提交内核（FN-1-08 五要素齐备后执行；FN-1-03/05 门户上传→流水线）。

    命令级审计块先行（逐文件 SHA-256 清单+操作人+处置意见入链，要素⑤），批次内每文件的
    流水线事件另行入链；步骤边界提交为 FN-1-07 检查点语义（不保持单事务原子性，已注释）。
    """
    from app.services import intake_pipeline, object_store
    trace = new_trace_id()
    manifest = " · ".join(f"{f['name']}[{object_store.sha256_of(f['content'])[:8]}…]" for f in files)
    ab = append_block(session, ts=now_iso(), trace=trace, actor="human", act="CHANNEL_RECEIVED",
                      cs=None, from_state="门户上传·受控受理提交",
                      to_state=f"批次受理中（{len(files)} 件）",
                      note=f"受控受理提交（五要素齐备）· 实例 {instance} · 处置意见：{opinion or UNOPINIONED} · "
                           f"逐文件 SHA-256：{manifest} · 确认凭据 scope {scope}",
                      op=_op(user), category="intake")
    payload, ver = intake_pipeline.current_intake_rules(session)
    batch = intake_pipeline.create_batch(session, channel="门户上传", instance=instance, trace=trace)
    results, dups = [], []
    for f in files:
        sha = object_store.sha256_of(f["content"])
        dup = intake_pipeline.find_business_dup(session, sha, None)
        if dup is not None:
            dups.append({"file": f["name"], "existing_case": dup.case_id,
                         "existing_batch": dup.batch_id,
                         "reason": "摘要幂等：同文件此前已受理，不重复受理（CON-05）"})
            continue
        frow = intake_pipeline.add_file(session, batch, name=f["name"], content=f["content"],
                                        mime=f.get("mime"), po_ref=po_ref, target_doc_ref=None)
        out = intake_pipeline.run_file(session, batch, frow, rules_payload=payload)
        out["sha256_display"] = f"{sha[:4]}…{sha[-4:]}"
        results.append(out)
    if not results:
        row = session.get(m.Batch, batch.batch_id)
        if row is not None and row.files == 0:
            session.delete(row)
            session.commit()
        raise CommandError("E_INTAKE_DUP",
                           "全部命中摘要幂等：本次提交无新文件可受理（FN-1-05④/CON-05）",
                           http=409, details={"duplicates": dups, "trace_id": trace})
    batch = intake_pipeline.recompute_batch(session, batch.batch_id)
    return {"batch_id": batch.batch_id, "status": batch.status, "files": results,
            "duplicates": dups, "opinion": opinion or UNOPINIONED, "trace": trace,
            "blk": ab.blk, "intake_rules_version": ver}


def _do_rollback(session, user, role, key, to_version, opinion):
    from app.services import versioning
    if not to_version:
        raise CommandError(E_STATE_PRECONDITION, "rollback 须指定 to_version", http=422)
    return {"rolled_back": True, **versioning.rollback(session, key, to_version, user.name,
                                                       opinion=opinion,
                                                       asset_type=_asset_type_for(key))}


def _fmt_filters(f):
    if isinstance(f, dict):
        return " · ".join(f"{k}={v}" for k, v in f.items())
    return str(f)


# ───────────────────────── 统一入口 ─────────────────────────

def execute(session, *, actor: str, action: str, instance: str | None = None,
            case_id: str | None = None,
            case_ids: list[str] | None = None, token: str | None = None,
            self_confirmed: bool = False, opinion: str | None = None,
            co_signer: str | None = None, co_signer_self: bool = False,
            field: str | None = None, new_value=None, reason: str | None = None,
            filters=None, rows: int | None = None,
            config_key: str | None = None, to_version: str | None = None,
            config_payload: dict | None = None,
            intake_files: list[dict] | None = None, po_ref: str | None = None,
            scope_override: str | None = None) -> dict:
    """受控写唯一入口：五要素全序校验 → 执行 → 审计+时间线双写 → 状态流转。

    租户上下文（WP1.7）：instance 必携带（缺失 E_TENANT_MISSING→400）；
    与目标数据归属实例不符 → E_TENANT_MISMATCH→403（四隔离①数据越权拒绝）；
    批量目标跨实例整批拒绝；发布/回滚为平台级资产写，ctx 在场校验 + 审计落 PLATFORM 链。
    """
    if action not in ACTION_PERMS:
        raise CommandError("UNKNOWN_ACTION", f"未注册命令 {action!r}", http=400)
    ctx = TenantContext.of(instance)          # 缺失即 E_TENANT_MISSING（FN-0-11/WP1.7）
    batch = action in ("batch_claim", "batch_release")
    scope = scope_override or scope_ref(action, case_id, case_ids, config_key)
    if not batch and action not in NON_CASE_ACTIONS and not case_id:
        raise CommandError(E_STATE_PRECONDITION, "单案命令须指定 caseId", http=422)
    if action == "intake" and not intake_files:
        raise CommandError(E_STATE_PRECONDITION, "受理提交缺少文件清单（intake_files）", http=422)
    if batch:
        for cid in case_ids or []:
            ctx.assert_matches_case_id(cid)   # 跨实例批量 → E_TENANT_MISMATCH
    elif action not in NON_CASE_ACTIONS:
        ctx.assert_matches_case_id(case_id)

    # ① 权限
    user, role = require_permission(session, actor, action)
    # ②③ 风险提示凭据 + 本人勾选
    _consume_token(session, token, actor, action, scope)
    if not self_confirmed:
        raise CommandError(E_SELF_CONFIRM_REQUIRED,
                           "缺「确认由本人执行」勾选——AI / Agent / LLM 建议不自动执行（FN-0-08 要素③）", http=422)
    # ④ 处置意见
    if action in OPINION_REQUIRED_ACTIONS and not (opinion or "").strip():
        raise CommandError(E_OPINION_REQUIRED, f"动作 {action} 处置意见必填（FN-0-08 要素④）", http=422)
    if action in ("publish", "rollback") and not config_key:
        raise CommandError(E_STATE_PRECONDITION, "publish/rollback 须指定 config_key", http=422)

    try:
        if batch:
            result = _do_batch(session, case_ids, user, role,
                               release=(action == "batch_release"), opinion=opinion)
        elif action == "export":
            result = _do_export(session, user, role, filters=filters, rows=rows)
        elif action == "publish":
            result = _do_publish(session, user, role, config_key, config_payload, opinion)
        elif action == "rollback":
            result = _do_rollback(session, user, role, config_key, to_version, opinion)
        elif action == "intake":
            result = _do_intake(session, user, role, instance=ctx.instance, files=intake_files,
                                po_ref=po_ref, opinion=opinion, scope=scope)
        else:
            case = state_machine.get_case(session, case_id)
            if action == "release":
                result = _do_release(session, case, user, role, opinion)
            elif action == "hold":
                result = _do_hold(session, case, user, role, opinion)
            elif action == "return":
                result = _do_return(session, case, user, role, opinion)
            elif action == "edit_field":
                result = _do_edit_field(session, case, user, role, field=field,
                                        new_value=new_value, reason=reason, opinion=opinion)
            elif action == "claim":
                result = _do_claim(session, case, user, role, opinion)
            elif action == "unblock":
                result = _do_unblock(session, case, user, role, co_signer=co_signer,
                                     co_signer_self=co_signer_self, opinion=opinion)
            else:
                raise CommandError("UNKNOWN_ACTION", action)
        session.commit()  # ⑤ 双写与业务写同事务提交（原子）
    except CommandError:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        raise CommandError(E_AUDIT_WRITE_FAILED, f"写入/审计失败，整笔回滚：{e}", http=500) from e
    if not batch and case_id:
        result.setdefault("caseId", case_id)
        st = session.get(m.Case, case_id)
        if st:
            result.setdefault("status", st.status)
    return result
