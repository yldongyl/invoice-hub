# -*- coding: utf-8 -*-
"""四校验编排器（WP1.6 · FN-0-07）。

纪律：
  - 四校验相互独立执行：单项规则异常/缺输入不中止其余项（缺输入如实 NOT_VERIFIED，
    内部异常降级为 NOT_VERIFIED + 注记）；
  - BLOCKED 不中止其余校验：红线（authenticity FAILED / duplicate 命中）触发状态机
    →BLOCKED（CON-02 建档挂起），但四项结果全部产出——解除拦截时结论可参考；
  - checks 结果只由规则引擎写入（依赖纪律⑥）：CheckResult 表与 case.checks_raw 的
    唯一业务写入口即本模块（apply_results）；命令层 edit_field 不触碰 checks。
  - 输入上下文 = 调用方（M3 受理管线 / 服务层）供给的确定性字段快照；本模块不读 LLM。
"""

from sqlalchemy import select

from app.domain import models as m
from app.domain.registry import get_registry
from app.services import config_center, rules, state_machine


def check_items() -> list[str]:
    return list(get_registry().category("check_item"))


def _tolerances(session) -> tuple[float, float]:
    """两套容差分开取用（CON-12），值来自 config 中心（规则内不写字面值）。"""
    rec = config_center.get_effective(session, "amount_reconcile_tolerance")
    po = config_center.get_effective(session, "po_match_tolerance")
    return (float((rec.value_raw or {}).get("amount", 0.06)),
            float((po.value_raw or {}).get("amount", 50)))


def build_context(session, case: m.Case, *, extra: dict | None = None) -> dict:
    """从案件契约快照派生规则上下文（值取自 evidence/facts/meta；缺项由调用方 extra 注入）。"""
    ev = {}
    for row in session.scalars(select(m.FieldEvidence).where(m.FieldEvidence.case_id == case.case_id)):
        ev[row.field] = row.evidence_raw.get("value")
    facts = case.facts_raw or {}
    ctx = {
        "instance": case.instance,
        "invoice_no": ev.get("header.invoice_no"),
        "invoice_code": ev.get("header.invoice_code"),
        "issue_date": ev.get("header.issue_date"),
        "net": ev.get("total.net_amount"),
        "tax": ev.get("total.tax_amount"),
        "gross": facts.get("invoiceAmount"),
        "freight": ev.get("total.freight"),
        "currency": facts.get("currency"),
        "tax_id": ev.get("seller.tax_id"),
        "lines": [{"amount": r[-1]} for r in (case.items_raw or {}).get("rows") or []],
        "po_amount": facts.get("poAmount"),
        "variance": facts.get("variance"),
        "supplier_id": case.supplier_id,
        "sm2_ok": (case.meta_raw or {}).get("sm2", {}).get("ok") if (case.meta_raw or {}).get("sm2") else None,
    }
    rec_tol, po_tol = _tolerances(session)
    ctx["tolerance_reconcile"] = rec_tol
    ctx["tolerance_po"] = po_tol
    ctx.update(extra or {})
    return ctx


def _run_guarded(rule_id: str, ctx: dict) -> dict:
    try:
        return rules.run_rule(rule_id, ctx)
    except Exception as e:  # 缺输入/内部异常 → 如实 NOT_VERIFIED，不中止其余项
        return {"rule_id": rule_id, "result": "NOT_VERIFIED", "note": f"规则未产出确定结论（{e}）"}


def _combine(results: list[dict]) -> tuple[str, str]:
    """severity：FAILED > AMOUNT_VARIANCE > NOT_VERIFIED > PASSED；note 分号合并。"""
    sev = ["PASSED", "NOT_VERIFIED", "AMOUNT_VARIANCE", "FAILED"]
    worst = max(results, key=lambda r: sev.index(r["result"]))["result"] if results else "NOT_VERIFIED"
    note = "；".join(f"[{r['rule_id']}] {r['note']}" for r in results) or "无规则输入"
    return worst, note


def run_all(session, ctx: dict) -> dict:
    """四校验编排：独立执行，返回 {item: {result, note}}（FN-0-07）。"""
    out = {}

    # supplierMatch：主数据匹配 + 税号校验位
    rs = [_run_guarded("supplier_master_match", ctx)]
    if ctx.get("tax_id"):
        rs.append(_run_guarded("tax_id_checksum", ctx))
    _r, _n = _combine(rs)
    out["supplierMatch"] = {"result": _r, "note": _n, "rules": rs}

    # authenticity：CN=SM2 验签+授权查验；OS=Tax ID 名录校验（FN-0-07）
    if ctx.get("instance") == "CN":
        if ctx.get("sm2_ok") is True:
            ar = {"rule_id": "sm2_verify", "result": rules.PASSED, "note": "SM2 验签 PASS（回执归档）"}
        elif ctx.get("sm2_ok") is False:
            ar = _run_guarded("redline_policy", {**ctx, "authenticity_result": rules.FAILED})
        else:
            ar = {"rule_id": "auth_query", "result": "NOT_VERIFIED",
                  "note": "授权查验未回/超时（断点续跑排定重试，不阻塞其余校验）"}
    else:
        hit = ctx.get("taxid_directory_hit")
        ar = ({"rule_id": "tax_id_directory", "result": "PASSED", "note": "Tax ID 名录校验命中"}
              if hit is True else
              {"rule_id": "tax_id_directory", "result": "NOT_VERIFIED", "note": "名录未命中/未接入（M3 桩）"})
    out["authenticity"] = ar | {"rules": [ar]}

    # duplicate：业务键计算 + 池比对（池服务本体 M3；pool_keys 显式注入才判 PASSED/FAILED）
    key = _run_guarded("dedup_business_key", ctx)
    pool = ctx.get("pool_keys")
    if pool is None:
        dr = {"rule_id": "dedup_business_key", "result": rules.NOT_VERIFIED,
              "note": key["note"] + " · 查重池服务 M3 接线，未比对"}
    else:
        biz = key["note"].split("：")[-1]
        hit = biz in set(pool)
        dr = {"rule_id": "dedup_business_key", "result": rules.FAILED if hit else rules.PASSED,
              "note": key["note"] + ("· 池内命中 → 重复票拦截" if hit else "· 池内无命中")}
    out["duplicate"] = dr | {"rules": [key, dr]}

    # poMatch：PO 匹配容差（CON-12 po 套）
    if not ctx.get("po_amount"):
        pr = {"rule_id": "tolerance_check", "result": rules.NOT_VERIFIED,
              "note": "无 PO 金额输入（non-PO 票或未关联），PO 匹配未验证"}
    else:
        t = _run_guarded("tolerance_check", {**ctx, "kind": "po",
                                            "diff": abs(float(ctx.get("variance") or 0))})
        pr = {"rule_id": "tolerance_check", "result": t["result"], "note": t["note"]}
    out["poMatch"] = pr | {"rules": [pr]}

    for item in check_items():
        if item not in out:
            out[item] = {"result": rules.NOT_VERIFIED, "note": "编排器无该项输入", "rules": []}
    return out


def redline_of(results: dict) -> dict | None:
    """红线判定（FN-0-07/5-05）：authenticity FAILED 或 duplicate FAILED → BLOCKED。"""
    for item in ("authenticity", "duplicate"):
        if results.get(item, {}).get("result") == rules.FAILED:
            return {"item": item, "to_status": state_machine.STATUS.BLOCKED,
                    "note": f"{item} {rules.FAILED} 命中红线 → BLOCKED（建档挂起）；其余 Checks 结论保留供解除参考"}
    return None


def apply_results(session, case: m.Case, results: dict, *, transition: bool = True,
                  commit: bool = True):
    """写入 CheckResult 投影 + case.checks_raw 快照（copy-and-reassign），红线触发流转。"""
    order = check_items()
    checks = dict(case.checks_raw or {})
    for i, item in enumerate(order):
        r = results.get(item, {"result": rules.NOT_VERIFIED, "note": "未产出"})
        checks[item] = {"result": r["result"], "note": r["note"]}
        row = session.scalar(select(m.CheckResult).where(m.CheckResult.case_id == case.case_id,
                                                         m.CheckResult.item == item))
        if row is None:
            session.add(m.CheckResult(case_id=case.case_id, seq=i, item=item,
                                      result=r["result"], note=r["note"]))
        else:
            row.result, row.note = r["result"], r["note"]
    case.checks_raw = checks          # 重赋新对象（JSON 脏追踪）
    rl = redline_of(results)
    t = None
    if rl and transition and case.status == state_machine.STATUS.RECOGNIZED:
        t = state_machine.transition(session, case.case_id, rl["to_status"], subject="system",
                                     extra=f"{rl['item']} FAILED（redline_policy）", commit=False)
    if commit:
        session.commit()
    return {"caseId": case.case_id, "checks": checks, "redline": rl, "transition": t}
