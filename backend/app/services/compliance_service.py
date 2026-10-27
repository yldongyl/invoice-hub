# -*- coding: utf-8 -*-
"""合规编排（WP3.3 总装 · FN-5-01~05 + FN-4-02/03 接入受理链路）。

顺序（每步确定性判断，checks 写入唯一入口=orchestrator.apply_results；状态流转唯一入口=状态机）：
  ① SM2 验签（CN 且有 XML 原件；回执归档）→ authenticity 底稿；
  ② 授权查验（CN，通道桩+缓存；timeout→NOT_VERIFIED→排定重试钩子）；
  ③ 海外名录（OS；webhook 回执 source=webhook）→ authenticity 判定依据；
  ④ 全局查重（两键池比对+DEDUP 事件+命中告警+不入池）→ duplicate；
  ⑤ 勾稽实跑（amount_tax_sum_check / line_amount_sum_check，容差 CON-12）——超容差=冲突信号；
  ⑥ 多源融合（提供 ocr_values 时）——冲突=降级+conflict 信号；
  → apply_results（红线自动 BLOCKED）→ 超时排定重试 → auto_flow（FN-0-02 自动边：低置信/冲突
    → NEEDS_REVIEW）。红线回归：全 PASSED 才可能自动 RESOLVED；<阈值仅到 NEEDS_REVIEW，
    低置信强制人工不可绕过（config low_confidence_force_human）。
"""

from app.domain import models as m
from app.services import (dedup_service, fusion_service, orchestrator, rules, sm2_service,
                          state_machine, tax_directory, verify_channel)
from app.services.audit_chain import now_iso
from app.services.errors import CommandError

_NOT_APPLIC = "不适用（无 XML 原件/载体不可验签）· 授权查验判定（FN-5-01）"
LEVEL_REDLINE = "P0 · 红线"      # enum-registry.alert_level code（引用不造词）


def _redline_alert(session, case: m.Case, kind: str, detail: str):
    """高风险通知生成（FN-5-01）：展示级 danger 入 raw.level（FN-5-09 读侧契约），
    分发级 P0·红线 存 raw.sev；分发渠道属 M5（CON-14）；红线告警不可停用（FN-5-05/P00 §5）。"""
    from app.domain.registry import get_registry
    get_registry().validate("alert_level", LEVEL_REDLINE, where="redline alert sev")
    title = f"验真红线拦截（{kind}）：{case.case_id}"
    session.add(m.Alert(
        instance=case.instance, level="danger", title=title, case_ref=case.case_id,
        alert_raw={"level": "danger", "sev": LEVEL_REDLINE, "title": title,
                   "meta": f"{case.case_id} · {case.supplier} · 验真红线（运行期合规链）",
                   "evidence": f"<b>{kind}</b>：{detail}。失败回执 gm-rcpt-* 已随案归档"
                               "（可用于对供应商追责与司法取证，FN-5-01）。"
                               "<br>来源：sm2-verify（算法真实 · 演示证书链，规则引擎判定非模型推断）。"
                               "<br><b>处置</b>：案件已置为 BLOCKED、建档挂起；解除拦截需双人会签留痕。",
                   "source": "sm2-verify/gm-verify", "t": now_iso()}))
    session.commit()


def run_compliance(session, case_id: str, *, file_text: str | None = None,
                   ocr_values: dict | None = None, verify_mode: str | None = None) -> dict:
    from app.services import config_center
    case = state_machine.get_case(session, case_id)
    ctx = orchestrator.build_context(session, case)
    mode_used = verify_mode or config_center.get_value(session, "auth_verify_channel_mode") or "pass"
    out: dict = {"caseId": case_id, "sm2": None, "verify": None, "dedup": None,
                 "taxid": None, "reconcile": None, "fusion": None}
    conflict = False
    timeout_pending = False

    # ① SM2 验签（CN）
    auth_result = auth_note = None
    if case.instance == "CN":
        sm2 = sm2_service.run_sm2(session, case, file_text)
        out["sm2"] = sm2
        if sm2 is not None and not sm2["ok"]:
            auth_result, auth_note = "FAILED", f"SM2 验签 FAILED → 红线（回执 {sm2['receipt_no']} 归档）"
        elif sm2 is not None and sm2["ok"]:
            # ② 授权查验（验签通过后仍需授权渠道——FN-0-09 验真必须走授权渠道）
            vr, vn = verify_channel.verify(session, case, mode=mode_used)
            out["verify"] = {"result": vr, "note": vn}
            timeout_pending = vr == "NOT_VERIFIED" and mode_used == "timeout"
            auth_result, auth_note = vr, f"SM2 PASS（回执 {sm2['receipt_no']}）+ 授权查验：{vn}"
        else:
            vr, vn = verify_channel.verify(session, case, mode=mode_used)
            out["verify"] = {"result": vr, "note": f"{_NOT_APPLIC} · {vn}"}
            timeout_pending = vr == "NOT_VERIFIED" and mode_used == "timeout"
            auth_result, auth_note = vr, out["verify"]["note"]
    else:
        # ③ OS：名录校验为 authenticity 判定依据（FN-5-03）
        tax = tax_directory.check(session, case)
        out["taxid"] = tax
        auth_result, auth_note = tax["authenticity_result"], tax["note"]

    # ④ 全局查重（池=同实例非 BLOCKED；本案件自身排除）
    pool_hit = dedup_service.check(session, case, exclude_case_id=case_id)
    dedup_service.register_events(session, case, pool_hit,
                                  po_ref=(case.meta_raw or {}).get("po"))
    out["dedup"] = pool_hit
    dup_result = "FAILED" if pool_hit["hit"] else "PASSED"
    dup_note = (f"{'业务键硬命中' if pool_hit['hard'] else '相似度命中'} {pool_hit['matched_case']}"
                f"（sim={pool_hit['sim']} ≥ 阈值 {pool_hit['threshold']}）· 不入发票池"
                if pool_hit["hit"] else
                f"池内无命中（阈值 {pool_hit['threshold']}，{pool_hit['elapsed_ms']}ms < P95 目标）")

    # ⑤ 勾稽实跑（金额类字段重算；超容差=冲突信号，FN-4-03）
    recon = None
    try:
        if ctx.get("net") is not None and ctx.get("tax") is not None:
            recon = rules.run_rule("amount_tax_sum_check", ctx)
        elif ctx.get("lines"):
            recon = rules.run_rule("line_amount_sum_check", ctx)
    except Exception as e:  # 缺输入不中止（FN-0-07 独立性）
        recon = {"rule_id": "amount_tax_sum_check", "result": "NOT_VERIFIED", "note": str(e)}
    out["reconcile"] = recon
    if recon and recon["result"] == "FAILED":
        conflict = True

    # ⑥ 多源融合（OCR stub 值可用时）
    if ocr_values:
        fused = fusion_service.merge(session, case, ocr_values)
        out["fusion"] = fused
        if fused["conflicts"]:
            conflict = True

    po_r, po_n = "NOT_VERIFIED", "PO 金额档案未接入（non-PO 或 M4 匹配域 FN-6-01）· PO 匹配未验证"
    if ctx.get("po_amount"):
        try:
            t = rules.run_rule("tolerance_check", {**ctx, "kind": "po",
                                                   "diff": abs(float(ctx.get("variance") or 0))})
            po_r, po_n = t["result"], t["note"]
        except Exception as e:
            po_n = f"容差规则未产出（{e}）"
    results = {
        "supplierMatch": {"result": "NOT_VERIFIED",
                          "note": "供应商主数据档案未接入（FN-6-05 匹配就绪化归 M4）· 受理层不判"},
        "authenticity": {"result": auth_result, "note": auth_note},
        "duplicate": {"result": dup_result, "note": dup_note},
        "poMatch": {"result": po_r, "note": po_n},
    }
    applied = orchestrator.apply_results(session, case, results, transition=True)
    # 验签红线：生成高风险告警（FN-5-01/5-05；分发渠道 M5——红线告警不可停用）
    if results["authenticity"]["result"] == "FAILED":
        _redline_alert(session, case, "SM2 验签失败", auth_note)
    # 查验超时→断点续跑钩子（在 checks 落库后排定：只重试查验，不重跑识别——S-M3-CMP-*）
    if timeout_pending:
        out["retry_task"] = verify_channel.close_timeout_case(
            session, case_id, ("NOT_VERIFIED", ""))
    flow = state_machine.auto_flow(session, case_id, conflict=conflict,
                                   dedup_hit=pool_hit["hit"])
    fresh = session.get(m.Case, case_id)
    out.update({"status": fresh.status, "checks": fresh.checks_raw,
                "transitions": [t["to"] for t in flow]})
    return out
