# -*- coding: utf-8 -*-
"""全局查重服务（WP3.3 · FN-5-04 + CON-05 决议两键口径）。

  - 业务键（键计算复用规则引擎 dedup_business_key，本服务只做池比对）：
      CN = 发票代码（null→空串）+ 发票号码 + 价税合计（销售方税号辅助）；
      OS = Invoice No. + Amount + 供应商；
  - 相似度阈值可配（config `dedup_similarity_threshold`，默认 1.0=仅硬命中）；
    模糊命中条件=金额全等 且 票号逐位匹配率 sim≥阈值（同长）——**100% 完全一致=硬命中**；
  - 命中 → duplicate=FAILED → 红线 BLOCKED（apply_results 唯一通道）+ DEDUP_BLOCKED 事件 +
    告警生成（Alert 行，alert_level=P0·红线；分发渠道 M5）+ **不入发票池**（池匹配排除 BLOCKED，
    结构性保证重复件不再参与后续比对）；
  - 池按租户隔离（四隔离④：仅同实例案件入池）；与受理摘要幂等台账（intake_ledger）分离
    ——同文件重复提交=409 不重复受理；不同文件同票面=本服务 DEDUP_BLOCKED（规格 §5.4）；
  - 性能目标 P95 < 200ms（sla_targets.dedup_p95_ms，用例计时断言）。
"""

import time

from sqlalchemy import select

from app.domain import models as m
from app.services import config_center, rules, state_machine
from app.services.audit_chain import append_block, now_iso
from app.services.errors import CommandError

LEVEL_REDLINE = "P0 · 红线"          # enum-registry.alert_level code（引用不造词）


def _field(session, case, name):
    row = session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id, m.FieldEvidence.field == name))
    return row.evidence_raw.get("value") if row else None


def biz_key(session, case: m.Case) -> dict:
    """规则引擎产出的业务键字符串 + 分量（sim 计算用）。"""
    no = str(_field(session, case, "header.invoice_no") or "")
    code = _field(session, case, "header.invoice_code")
    gross = (case.facts_raw or {}).get("invoiceAmount")
    r = rules.run_rule("dedup_business_key", {
        "instance": case.instance, "invoice_code": code, "invoice_no": no,
        "gross": gross, "tax_id": _field(session, case, "seller.tax_id"),
        "supplier_id": case.supplier_id or case.supplier})
    return {"key": r["note"].split("：")[-1].split("（")[0], "invoice_no": no,
            "gross": gross, "rule": r}


def pool_keys(session, instance: str) -> list[dict]:
    """当前实例发票池（四隔离④）：BLOCKED 案件不入池（命中件排除，结构性「不入发票池」）。"""
    rows = session.scalars(select(m.Case).where(
        m.Case.instance == instance,
        m.Case.status != state_machine.STATUS.BLOCKED)).all()
    pool = []
    for c in rows:
        try:
            bk = biz_key(session, c)
        except Exception:
            continue
        if bk["invoice_no"] and bk["gross"] is not None:
            pool.append({"case_id": c.case_id, **bk})
    return pool


def digit_similarity(a: str, b: str) -> float:
    """票号逐位匹配率（同长）；异长取公共前缀占比——确定性数值口径，无模型。"""
    if not a or not b:
        return 0.0
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x == y) / len(a)
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return common / max(len(a), len(b))


def check(session, case: m.Case, *, threshold: float | None = None,
          exclude_case_id: str | None = None) -> dict:
    """池比对：返回 {hit, sim, matched_case, hard, threshold, elapsed_ms}。
    命中硬条件=业务键全等；模糊=金额全等且 sim≥阈值（票号不同）。"""
    t0 = time.perf_counter()
    thr = threshold if threshold is not None else float(
        config_center.get_value(session, "dedup_similarity_threshold") or 1.0)
    bk = biz_key(session, case)
    best = {"hit": False, "sim": 0.0, "matched_case": None, "hard": False}
    for cand in pool_keys(session, case.instance):
        if exclude_case_id and cand["case_id"] == exclude_case_id:
            continue
        if bk["key"] == cand["key"]:                       # 硬命中：业务键全等（sim=1.0）
            best = {"hit": True, "sim": 1.0, "hard": True, "matched_case": cand["case_id"]}
            break
        sim = digit_similarity(bk["invoice_no"], cand["invoice_no"])
        amount_eq = (bk["gross"] is not None and cand["gross"] is not None
                     and abs(float(bk["gross"]) - float(cand["gross"])) < 1e-9)
        if amount_eq and sim >= thr and bk["invoice_no"] != cand["invoice_no"] \
                and sim > best["sim"]:                     # 模糊命中：金额全等+票号相似≥阈值
            best = {"hit": True, "sim": round(sim, 4), "hard": False,
                    "matched_case": cand["case_id"]}
    best.update({"threshold": thr, "key": bk["key"], "invoice_no": bk["invoice_no"],
                 "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)})
    return best


def register_events(session, case: m.Case, res: dict, *, po_ref: str | None = None) -> dict:
    """查重事件入时间线+审计链：DEDUP_CHECK（含池结果）；PO 维度另发 DEDUP_PO_CHECK；
    命中另发 DEDUP_BLOCKED + 生成红线告警（FN-5-04/5-09；分发渠道 M5）。"""
    v = state_machine.component_version(session, "dedup-rule")
    trace = case.trace_id
    d = (f"全局查重 · 业务键 {'全等硬命中' if res['hard'] else '相似度命中' if res['hit'] else '无命中'}"
         f"（sim={res['sim']}，阈值={res['threshold']}，耗时 {res['elapsed_ms']}ms）")
    x = f"池=当前实例发票案件（租户隔离，四隔离④）· BLOCKED 件不入池 · 与摘要幂等台账分离" \
        + (f" · 命中 {res['matched_case']}" if res["hit"] else "")
    state_machine.append_case_event(session, case, a="system", act="DEDUP_CHECK", d=d, x=x,
                                    v=v, commit=False)
    append_block(session, ts=now_iso(), trace=trace, actor="system", act="DEDUP_CHECK",
                 cs=case.case_id, from_state="受理派生", to_state="查重命中" if res["hit"] else "查重通过",
                 note=x, op=v, category="dedup", commit=False)
    if po_ref:
        state_machine.append_case_event(session, case, a="system", act="DEDUP_PO_CHECK",
                                        d="PO 维度查重执行", x=f"PO {po_ref} 同额/同号交叉比对（FN-5-04 附）",
                                        v=v, commit=False)
    if res["hit"]:
        state_machine.append_case_event(
            session, case, a="system", act="DEDUP_BLOCKED", d="重复票拦截（付款/建档前）",
            x=f"命中 {res['matched_case']} · 本件不入发票池 · 解除拦截需复核员权限双人会签并留痕（FN-5-04）",
            v=v, commit=False)
        _generate_alert(session, case, res)
    session.commit()
    return {"case_id": case.case_id, "hit": res["hit"]}


def _generate_alert(session, case: m.Case, res: dict):
    """红线告警生成（FN-5-04/5-09）：**展示级词汇 danger/warning 入 raw.level（FN-5-09 读侧契约，
    M2 builder 强制）；分发级 P0·红线 存 raw.sev（enum-registry.alert_level 引用）**；
    分发渠道（消息中心/邮件）属 M5（CON-14）；红线告警不可停用（FN-5-05）。"""
    from app.domain.registry import get_registry
    get_registry().validate("alert_level", LEVEL_REDLINE, where="dedup alert sev")
    title = f"重复票红线拦截：{case.case_id}"
    raw = {"level": "danger", "sev": LEVEL_REDLINE, "title": title,
           "meta": f"{case.case_id} · {case.supplier} · "
                   f"命中 {res['matched_case']}（sim {res['sim']}，运行期查重）",
           "evidence": f"<b>规则查重命中</b>：业务键比对命中 {res['matched_case']}"
                       f"（相似度 {res['sim']} ≥ 阈值 {res['threshold']}，规则引擎判定非模型推断）。"
                       "<br><b>处置</b>：案件已置为 BLOCKED，不入发票池、未推送建档；"
                       "解除拦截需复核员+管理员双人会签并留痕。",
           "source": "dedup-rule（规则引擎确定性判定）", "t": now_iso()}
    session.add(m.Alert(instance=case.instance, level="danger", title=title,
                        case_ref=case.case_id, alert_raw=raw))
    session.commit()
