# -*- coding: utf-8 -*-
"""税务总局授权查验通道桩（WP3.3 · FN-5-02）。

演示口径（P00 §6）：模拟通道，无真实外呼；模式=配置中心 auth_verify_channel_mode
（pass/timeout/off），运行期参数可注入覆盖（测试/走查）。纪律：
  - 超时 → authenticity=NOT_VERIFIED + **单独排定自动重试**（state_machine.mark_verify_timeout
    既有钩子：AUTH_QUERY_TIMEOUT 事件+断点续跑任务，**不重跑识别**）；
  - 同票结果缓存（VerifyCache，键=业务键同源）避免重复计费——缓存命中不产生通道调用
    （调用计数断言载体）；每次真实外呼登记 EgressLog(purpose=verify)（数据最小外发：只发票号+税号+金额）；
  - 验真必须走授权渠道，**模型不得自行宣称发票真实**（FN-0-09）——本模块零 LLM。
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.domain import models as m
from app.services import config_center, object_store, state_machine
from app.services.audit_chain import append_block, now_iso
from app.services.issuer import new_trace_id

_CALLS: list[dict] = []          # 演示通道调用台账（断言用；缓存命中不追加）


def reset_calls():
    _CALLS.clear()


def calls() -> list[dict]:
    return list(_CALLS)


def biz_key_of(session, case: m.Case) -> str:
    """查验缓存/通道业务键：CN=票号|价税合计|销方税号；OS=票号|价税合计|供应商（CON-05 同源口径）。"""
    no = _field(session, case, "header.invoice_no") or ""
    gross = (case.facts_raw or {}).get("invoiceAmount")
    if case.instance == "CN":
        tax = _field(session, case, "seller.tax_id") or ""
        return f"CN|{no}|{gross}|{tax}"
    return f"OS|{no}|{gross}|{case.supplier_id or case.supplier}"


def _field(session, case, name):
    row = session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id, m.FieldEvidence.field == name))
    return row.evidence_raw.get("value") if row else None


def _demo_channel(biz: str, mode: str) -> tuple[str, str]:
    """模拟通道响应（确定性：不联网、不随机）。"""
    _CALLS.append({"biz_key": biz, "mode": mode, "t": now_iso()})
    if mode == "timeout":
        return "NOT_VERIFIED", "税务总局授权查验超时（演示桩通道）· 已排定自动重试（断点续跑，不重跑识别）"
    if mode == "off":
        return "NOT_VERIFIED", "查验未执行（演示配置 off）"
    return "PASSED", "税务总局授权查验通过（模拟通道 · 演示口径）"


def verify(session, case: m.Case, *, mode: str | None = None) -> tuple[str, str]:
    """查验一次：缓存优先；miss→通道调用（外发登记）；timeout→排定重试。

    返回 (result, note)。红线（FAILED）不经本通道判定——SM2 验签归 sm2_service。
    """
    cfg = mode or config_center.get_value(session, "auth_verify_channel_mode") or "pass"
    biz = biz_key_of(session, case)
    cached = session.get(m.VerifyCache, biz)
    if cached is not None:                       # 缓存命中=零通道调用（断言点）
        return cached.result, f"同票查验缓存命中（避免重复计费，FN-5-02）· {cached.detail}"
    result, note = _demo_channel(biz, cfg)
    session.add(m.EgressLog(ts=now_iso(), batch_id=None, file_seq=None, case_id=case.case_id,
                            provider_id="tax-bureau-simulated-channel", purpose="verify",
                            payload_digest=object_store.sha256_of(biz.encode()),
                            bytes_out=len(biz),
                            note="授权查验模拟通道外发登记（数据最小化：仅票号+税号+金额；演示口径不外呼）"))
    if result == "PASSED":   # 只缓存终局结果；NOT_VERIFIED 不入缓存（否则重试语义被架空）
        session.add(m.VerifyCache(biz_key=biz, case_id=case.case_id, result=result, detail=note,
                                  ts=now_iso()))
    session.commit()
    return result, note


def close_timeout_case(session, case_id: str, result: tuple[str, str]):
    """查验未回时挂接断点续跑钩子（apply_results 之后调用：只排定查验重试，识别不重跑）。"""
    if result[0] == "NOT_VERIFIED":
        return state_machine.mark_verify_timeout(session, case_id)
    return None


def run_due_retries(session, *, now: str | None = None, mode: str = "pass",
                    max_tasks: int = 10) -> dict:
    """查验重试任务消费器（演示口径登记式队列的单次执行）。

    只重发**查验请求**：不触发 SM2、不触发识别（回归断言：sm2 回执计数与 recognize 外发计数不变）。
    成功→authenticity 改判 PASSED（经唯一业务写入口 apply_results）+ 缓存 + 队列闭环。
    """
    now = now or now_iso()
    due = session.scalars(select(m.VerifyRetryTask).where(
        m.VerifyRetryTask.state == "queued",
        m.VerifyRetryTask.step == "verify_auth").limit(max_tasks)).all()
    done = []
    for task in due:
        case = session.get(m.Case, task.case_id)
        if case is None or case.status == state_machine.STATUS.BLOCKED:
            continue
        biz = biz_key_of(session, case)
        calls_before = len(_CALLS)
        result, note = _demo_channel(biz, mode)
        if len(_CALLS) == calls_before + 1:                     # 真实重发了一次查验（非识别）
            session.add(m.EgressLog(ts=now_iso(), case_id=case.case_id,
                                    provider_id="tax-bureau-simulated-channel", purpose="verify",
                                    payload_digest=object_store.sha256_of(biz.encode()),
                                    bytes_out=len(biz), note="查验重试外发（断点续跑闭环）"))
            session.add(m.VerifyCache(biz_key=biz, case_id=case.case_id, result=result,
                                      detail=note, ts=now_iso()))
        checks = {k: dict(v) for k, v in (case.checks_raw or {}).items()}
        checks["authenticity"] = {"result": result, "note": note}
        orchestrator_results = {k: checks[k] for k in checks}
        from app.services import orchestrator
        orchestrator.apply_results(session, case, orchestrator_results, transition=False,
                                   commit=False)
        task.state = "done"
        task.attempts += 1
        v = state_machine.component_version(session, "bw-cloud-verify")
        state_machine.append_case_event(
            session, case, a="provider", act="AUTH_QUERY_TIMEOUT",
            d=f"查验重试 → {result}（断点续跑闭环）",
            x="重试任务仅重发查验请求 · SM2/识别步骤不重跑（FN-1-07/FN-0-02 钩子）",
            v=v, commit=False)
        append_block(session, ts=now_iso(), trace=case.trace_id or new_trace_id(),
                     actor="provider", act="AUTH_QUERY_TIMEOUT", cs=case.case_id,
                     from_state=f"queued attempt={task.attempts}", to_state=result,
                     note="查验重试执行（识别不重跑 · 演示口径消费者）", op=v, category="verify",
                     commit=False)
        session.commit()
        done.append({"case_id": case.case_id, "task_id": task.id, "result": result})
    return {"processed": len(done), "tasks": done}
