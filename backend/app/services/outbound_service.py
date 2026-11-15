# -*- coding: utf-8 -*-
"""出站台账与受控重推服务（FN-7-05 / FN-7-06 · 20261102 S4）。

职责：
  - 出站批次列表与详情（GET /v1/outbound/batches、GET /v1/outbound/batches/{id}）；
  - KPI 五卡聚合（待出站、推送中、建档成功、失败待人工、平均回写时延）；
  - 4 类 Ariba 标准单据枚举呈现：Invoice(PO/Contract/Non-PO/Credit Memo)；
  - 状态语义对齐：对账与付款分离，终态语义为「建档成功/对账完成（生成支付凭证传会计系统）」；
  - 失败记录管理与退避调度（30s / 2min / 10min 退避序列）；
  - 受控重推（五要素闭环：权限校验、风险提示凭据、二次确认、处置意见、不可篡改审计留痕）。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import json

from sqlalchemy import select

from app.domain import models as m
from app.services import adapter_service, audit_chain, governed_commands as gc, state_machine
from app.services.audit_chain import new_trace_id, now_iso
from app.services.errors import CommandError


# 退避序列（30s / 2min / 10min，FN-7-05）
BACKOFF_SEQUENCE = [30, 120, 600]

ALLOWED_RETRY_ROLES = {"管理员", "运营", "admin", "ops"}


def compute_next_retry_time(retry_count: int) -> str:
    """根据退避序列计算下次允许重试时间（ISO 字符串）。"""
    idx = min(max(0, retry_count), len(BACKOFF_SEQUENCE) - 1)
    seconds = BACKOFF_SEQUENCE[idx]
    next_dt = datetime.now(timezone.utc).astimezone() + timedelta(seconds=seconds)
    return next_dt.isoformat(timespec="seconds")


def list_outbound_batches(
    session,
    adapter: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """获取出站批次列表与 KPI 五卡聚合（FN-7-06）。"""
    stmt = select(m.OutboundBatch).order_by(m.OutboundBatch.created_ts.desc())
    if adapter:
        stmt = stmt.where(
            (m.OutboundBatch.adapter == adapter) | (m.OutboundBatch.adapter_id == adapter)
        )
    if status:
        stmt = stmt.where(m.OutboundBatch.status == status)

    batches = list(session.scalars(stmt))

    # 查询全量批次以计算全局 KPI 五卡
    all_batches = list(session.scalars(select(m.OutboundBatch)))
    all_records = list(session.scalars(select(m.OutboundFilingRecord)))

    # KPI 统计
    kpi_wait = sum(b.docs for b in all_batches if b.status == "待出站")
    kpi_pushing = sum(b.docs for b in all_batches if b.status == "推送中")
    kpi_ok = sum(b.ok for b in all_batches)
    kpi_bad = sum(b.fail for b in all_batches) + len([b for b in all_batches if b.status == "待人工处理"])

    # 本月建档总量（FN-7-01 / 出站台账聚合）：基准 5,836（各 live 适配器本月建档量汇总 1,284 + 642 + 3,910）+ 库内非沙箱建档成功增量
    base_month_total = 5836
    additional_filings = len([
        r for r in all_records
        if not r.is_sandbox and r.filing_status and ("成功" in r.filing_status or "完成" in r.filing_status)
    ])
    month_filing_count = base_month_total + additional_filings
    month_filing_display = f"{month_filing_count:,}"

    # 时延聚合：计算有效 latency_ms 的平均值，无真实数据时输出 null（前端展示「演示口径」）
    latencies = [r.latency_ms for r in all_records if r.latency_ms is not None and r.latency_ms > 0]
    if latencies:
        avg_ms = sum(latencies) / len(latencies)
        avg_latency_display = f"{(avg_ms / 1000.0):.1f}s"
        avg_latency_raw = round(avg_ms, 1)
        is_demo_metric = False
    else:
        avg_latency_display = None
        avg_latency_raw = None
        is_demo_metric = True

    # 批次明细组装
    batch_list = []
    for b in batches:
        recs = list(
            session.scalars(
                select(m.OutboundFilingRecord)
                .where(m.OutboundFilingRecord.batch_id == b.batch_id)
                .order_by(m.OutboundFilingRecord.id.asc())
            )
        )
        detail_items = []
        for r in recs:
            detail_items.append({
                "id": r.id,
                "caseId": r.case_id,
                "docType": r.doc_type,
                "receipt": r.receipt_no or "—",
                "payload": r.payload_summary,
                "payload_body": r.payload_body,
                "attach": r.attachment_status,
                "writeback": r.writeback_status,
                "filing_status": r.filing_status,
                "error_reason": r.error_reason,
                "note": r.note or "",
                "is_sandbox": r.is_sandbox,
                "retry_count": r.retry_count,
                "max_retries": r.max_retries,
                "next_retry_at": r.next_retry_at,
                "latency_ms": r.latency_ms,
            })

        batch_list.append({
            "id": b.batch_id,
            "adapter": b.adapter,
            "adapter_id": b.adapter_id,
            "docs": b.docs,
            "status": b.status,
            "ok": b.ok,
            "fail": b.fail,
            "retry": b.retry,
            "t": b.time_display,
            "created_ts": b.created_ts,
            "updated_ts": b.updated_ts,
            "detail": detail_items,
        })

    return {
        "total": len(batch_list),
        "batches": batch_list,
        "kpi": {
            "wait": kpi_wait,
            "pushing": kpi_pushing,
            "ok": kpi_ok,
            "bad": kpi_bad,
            "month_filing_count": month_filing_count,
            "month_filing_display": month_filing_display,
            "avg_latency": avg_latency_raw,
            "avg_latency_display": avg_latency_display,
            "is_demo_latency": is_demo_metric,
            "metric_note": "时延指标源自目标系统回执时间戳差值 · 无真实数据时为 null（演示口径）",
        },
    }


def get_outbound_batch_detail(session, batch_id: str) -> dict[str, Any]:
    """获取单个出站批次详情（FN-7-06）。"""
    batch = session.get(m.OutboundBatch, batch_id)
    if not batch:
        raise CommandError("E_BATCH_NOT_FOUND", f"出站批次 {batch_id} 不存在", http=404)

    recs = list(
        session.scalars(
            select(m.OutboundFilingRecord)
            .where(m.OutboundFilingRecord.batch_id == batch_id)
            .order_by(m.OutboundFilingRecord.id.asc())
        )
    )

    detail_items = []
    for r in recs:
        detail_items.append({
            "id": r.id,
            "caseId": r.case_id,
            "docType": r.doc_type,
            "receipt": r.receipt_no or "—",
            "payload": r.payload_summary,
            "payload_body": r.payload_body,
            "attach": r.attachment_status,
            "writeback": r.writeback_status,
            "filing_status": r.filing_status,
            "error_reason": r.error_reason,
            "note": r.note or "",
            "is_sandbox": r.is_sandbox,
            "retry_count": r.retry_count,
            "max_retries": r.max_retries,
            "next_retry_at": r.next_retry_at,
            "latency_ms": r.latency_ms,
            "steps": r.steps_raw or [],
            "created_ts": r.created_ts,
            "updated_ts": r.updated_ts,
        })

    return {
        "id": batch.batch_id,
        "adapter": batch.adapter,
        "adapter_id": batch.adapter_id,
        "docs": batch.docs,
        "status": batch.status,
        "ok": batch.ok,
        "fail": batch.fail,
        "retry": batch.retry,
        "t": batch.time_display,
        "created_ts": batch.created_ts,
        "updated_ts": batch.updated_ts,
        "detail": detail_items,
    }


def _verify_repush_permission(session, actor: str) -> m.UserAccount:
    """受控重推权限校验（要素①）：仅 ops/admin 角色，复核员禁止重推。"""
    user = session.get(m.UserAccount, actor)
    if not user or user.status != "启用":
        raise CommandError("E_PERM_DENIED", f"用户 {actor} 不存在或未启用", http=403)

    user_role = (user.role or "").lower()
    is_allowed = any(r in user_role for r in ["管理员", "运营", "admin", "ops"])
    if not is_allowed:
        raise CommandError(
            "E_PERM_DENIED",
            f"复核员不直接重推出站（职责分离：当前操作人 {actor} 属于复核员角色，受控重推仅限平台运营组与实施管理员）",
            http=403,
        )
    return user


def issue_repush_challenge(session, actor: str, record_id: int) -> dict[str, Any]:
    """受控重推风险提示与凭据签发（五要素②）：

    前置拦截：
      - 仅 ops/admin 角色；
      - 仅失败/待人工处理记录可重推；
      - 退避未到期拦截。
    """
    _verify_repush_permission(session, actor)

    rec = session.get(m.OutboundFilingRecord, record_id)
    if not rec:
        raise CommandError("E_RECORD_NOT_FOUND", f"出站记录 #{record_id} 不存在", http=404)

    # 状态拦截：仅失败/待人工处理记录可重推
    if rec.filing_status == "建档成功/对账完成（生成支付凭证传会计系统）" and not rec.error_reason:
        raise CommandError("E_STATE_PRECONDITION", f"单据 {rec.case_id} 此前已成功建档并生成回执，无需重推", http=409)

    # 退避冷静期拦截（FN-7-05）
    if rec.next_retry_at:
        now_str = now_iso()
        if now_str < rec.next_retry_at:
            raise CommandError(
                "E_BACKOFF_ACTIVE",
                f"记录仍在退避冷静期内（下次可重试时间：{rec.next_retry_at}），当前禁止重推！",
                http=409,
                details={"next_retry_at": rec.next_retry_at, "retry_count": rec.retry_count},
            )

    scope = f"repush:{rec.adapter_id}:{rec.case_id}:{record_id}"
    risk_text = (
        f"【受控重推风险警示】即将向目标平台 {rec.adapter_id} 重新发起出站建档请求（案件号：{rec.case_id} · 单据类型：{rec.doc_type}）。"
        f"将重新执行五步链路并生成/归档回执，操作全过程将双写时间线与不可篡改审计链（TODO(H24) 外呼桩保持）。"
    )

    ch = gc.issue_risk_challenge(session, actor, "manual_verify", scope, ttl_seconds=300)
    ch["action"] = "outbound_repush"
    ch["risk_text"] = risk_text
    ch["adapter_id"] = rec.adapter_id
    ch["case_id"] = rec.case_id
    ch["record_id"] = record_id
    return ch


def execute_repush(
    session,
    *,
    record_id: int,
    actor: str,
    token: str,
    self_confirmed: bool = False,
    opinion: Optional[str] = None,
) -> dict[str, Any]:
    """执行受控重推（五要素闭环）：

    ① 权限校验（ops/admin）；
    ② 风险挑战校验；
    ③ 二次确认校验（self_confirmed）；
    ④ 处置意见；
    ⑤ 重新走 execute_filing + 状态流转 + 审计留痕。
    """
    user = _verify_repush_permission(session, actor)

    rec = session.get(m.OutboundFilingRecord, record_id)
    if not rec:
        raise CommandError("E_RECORD_NOT_FOUND", f"出站记录 #{record_id} 不存在", http=404)

    # 检查二次确认勾选
    if not self_confirmed:
        raise CommandError("E_SELF_CONFIRM_REQUIRED", "必须勾选二次确认：我已核对证据，确认由本人执行", http=422)

    # 凭据校验与消费
    scope = f"repush:{rec.adapter_id}:{rec.case_id}:{record_id}"
    gc._consume_token(session, token, actor, "manual_verify", scope)

    # 检查退避冷静期
    if rec.next_retry_at:
        now_str = now_iso()
        if now_str < rec.next_retry_at:
            raise CommandError(
                "E_BACKOFF_ACTIVE",
                f"记录仍在退避冷静期内（下次可重试时间：{rec.next_retry_at}），当前禁止重推！",
                http=409,
            )

    # 执行重新建档（按记录来源：沙箱或生产）
    # 注释标注 TODO(H24)：外呼接口按沙箱 stub 网关模拟
    filing_res = adapter_service.execute_filing(
        session,
        adapter_id=rec.adapter_id,
        case_id=rec.case_id,
        actor=actor,
        is_sandbox=rec.is_sandbox,
        opinion=opinion or "受控人工重推",
    )

    # 更新 OutboundFilingRecord 状态
    rec.retry_count += 1
    rec.receipt_no = filing_res["receipt_no"]
    rec.filing_status = "建档成功/对账完成（生成支付凭证传会计系统）"
    rec.writeback_status = "已回写"
    rec.error_reason = None
    rec.next_retry_at = None
    rec.note = f"受控人工重推成功 · 新回执号：{filing_res['receipt_no']} · 操作人：{actor} · 处置意见：{opinion or '确认重推'}"
    rec.updated_ts = now_iso()

    # 更新 OutboundBatch 统计
    batch = session.get(m.OutboundBatch, rec.batch_id)
    if batch:
        batch.ok += 1
        batch.fail = max(0, batch.fail - 1)
        batch.retry = max(0, batch.retry - 1)
        if batch.fail == 0 and batch.retry == 0:
            batch.status = "已完成"
        batch.updated_ts = now_iso()

    # 审计留痕（要素⑤）
    trace = new_trace_id()
    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="STATUS_CHANGE",
        cs=rec.case_id,
        from_state="失败待人工",
        to_state="建档成功/对账完成（生成支付凭证传会计系统）",
        note=f"受控重推完成 · 目标 Adapter：{rec.adapter_id} · 回执号：{filing_res['receipt_no']} · 处置意见：{opinion or '确认重推'}",
        op=f"{user.name} · {user.role}",
        category="action",
        commit=True,
    )

    return {
        "success": True,
        "record_id": record_id,
        "case_id": rec.case_id,
        "adapter_id": rec.adapter_id,
        "receipt_no": filing_res["receipt_no"],
        "filing_status": rec.filing_status,
        "retry_count": rec.retry_count,
        "message": f"✓ 案件 {rec.case_id} 受控重推成功 · 目标系统回执号: {filing_res['receipt_no']}",
    }
