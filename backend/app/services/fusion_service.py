# -*- coding: utf-8 -*-
"""多源字段融合最小实现（WP3.3 · FN-4-02 采信与冲突口径）。

演示边界（P04 原文）：XML 直读值 × OCR stub 值 两源比对——
  - 一致（差 ≤ 勾稽容差 CON-12）→ 互证标注「XML 直读 + OCR 互证一致」（OCR_CROSS_CHECK 事件），
    支撑置信度（维持整案档，证据 rule 注记）；
  - 冲突（任一致命字段超容差）→ OCR_CROSS_CHECK_CONFLICT 事件 + **置信度降级**
    （policy.degrade_to，0381 案口径 82）+ 强制人工（由编排层以 conflict=True 走 FN-0-02 边
    → NEEDS_REVIEW）；采信=**结构化原件优先且配置化**（config `fusion_adoption_policy`.priority）；
  - **不得静默取舍**：冲突双方的证据都留在链上（OCR 值另立一条 source=ocr 证据行注记「未采信」）；
  - 融合规则版本化：策略=配置中心受控项（变更走 publish）。
"""

from sqlalchemy import select

from app.domain import models as m
from app.services import config_center, state_machine
from app.services.audit_chain import append_block, now_iso


def _policy(session) -> tuple[dict, float]:
    pol = config_center.get_value(session, "fusion_adoption_policy") or {}
    tol = float((config_center.get_effective(session, "amount_reconcile_tolerance")
                 .value_raw or {}).get("amount", 0.06))
    return pol, tol


def merge(session, case: m.Case, ocr_values: dict) -> dict:
    """对致命字段比对 XML 现值 vs OCR 值；返回 {consistent, conflicts, degraded, policy}。"""
    pol, tol = _policy(session)
    fields = pol.get("conflict_fields") or []
    degrade_to = int(pol.get("degrade_to", 82))
    rows = {r.field: r for r in session.scalars(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id))}
    consistent, conflicts = [], []
    for f in fields:
        base = rows.get(f)
        if base is None or f not in ocr_values:
            continue
        xv, ov = base.evidence_raw.get("value"), ocr_values[f]
        try:
            diff = abs(float(xv) - float(ov)) if isinstance(xv, (int, float)) or str(xv).replace(
                ".", "").replace(",", "").isdigit() else (0.0 if str(xv) == str(ov) else float("inf"))
        except (TypeError, ValueError):
            diff = 0.0 if str(xv) == str(ov) else float("inf")
        if diff <= tol:
            consistent.append({"field": f, "xml": xv, "ocr": ov})
            ev = dict(base.evidence_raw)
            e = dict(ev.get("evidence") or {})
            e["rule"] = (e.get("rule") or "L1_xml_direct") + " · XML 直读 + OCR 互证一致"
            ev["evidence"] = e
            base.evidence_raw = ev
            session.add(m.FieldEvidence(
                case_id=case.case_id, seq=max([r.seq for r in session.scalars(
                    select(m.FieldEvidence).where(m.FieldEvidence.case_id == case.case_id))]
                    or [-1]) + 1,
                field=f, source="ocr", confidence=0.82,
                evidence_raw={"field": f, "label": "OCR 交叉验证值", "value": ov,
                              "source": "ocr", "confidence": 0.82,
                              "evidence": {"page": 1, "bbox": "—（stub 无坐标）",
                                           "raw_text": f"OCR 值 {ov} 与 XML 直读一致（差 ≤ 容差 {tol}）",
                                           "rule": "cross_check ✓", "model_version": "ocr stub（演示）",
                                           "provider": "自托管 OCR-VLM（SPI stub · 演示口径）",
                                           "role": "cross_check"}}))   # 佐证注记行（非合并基准，edit_field 不覆写）
        else:
            conflicts.append({"field": f, "xml": xv, "ocr": ov, "diff": None if diff == float("inf") else diff})
            # 采信对象=policy.priority 首个来源（配置化——默认 xml_direct 结构化原件优先；
            # 改配 ["ocr",...] 即反转采信方向，双方证据仍都留存不静默取舍）
            adopted = (pol.get("priority") or ["xml_direct"])[0]
            session.add(m.FieldEvidence(
                case_id=case.case_id, seq=max([r.seq for r in session.scalars(
                    select(m.FieldEvidence).where(m.FieldEvidence.case_id == case.case_id))]
                    or [-1]) + 1,
                field=f, source="ocr", confidence=0.82,
                evidence_raw={"field": f, "label": "OCR 票面值（冲突未采信）", "value": ov,
                              "source": "ocr", "confidence": 0.82,
                              "evidence": {"page": 1, "bbox": "—（stub 无坐标）",
                                           "raw_text": f"OCR 值 {ov} vs XML 直读 {xv} · 超容差 {tol}",
                                           "rule": f"cross_check ✗（冲突留证 · 采信={adopted}（结构化原件优先，配置化））",
                                           "model_version": "ocr stub（演示）",
                                           "provider": "自托管 OCR-VLM（SPI stub · 演示口径）",
                                           "role": "conflict_non_adopted"}}))   # 冲突未采信留存行（FN-4-02 不静默取舍）
    v = state_machine.component_version(session, "router-policy")
    if consistent:
        d = "OCR 交叉验证（异源互证）→ 一致"
        x = "；".join(f"{c['field']} XML {c['xml']}=OCR {c['ocr']}" for c in consistent) \
            + f" · 差 ≤ 容差 {tol} · 支撑置信度（FN-4-02 互证标注）"
        act = "OCR_CROSS_CHECK"
    elif conflicts:
        # 降级：整案置信度 → policy.degrade_to（0381 案口径）；原值保留于证据链，不得静默取舍
        state_machine.set_meta(case, confidence=degrade_to)
        state_machine._sync_meta(session, case)
        case.confidence = degrade_to
        d = "多源冲突（XML×OCR 关键金额字段不一致）"
        x = "；".join(f"{c['field']} XML {c['xml']} vs OCR {c['ocr']}" for c in conflicts) \
            + f" · 超容差 {tol} · 置信度降级至 {degrade_to}% 强制人工 · 采信=结构化原件优先" \
              "（policy.priority 配置化）· 双方证据留存不静默取舍（FN-4-02）"
        act = "OCR_CROSS_CHECK_CONFLICT"
    else:
        return {"consistent": [], "conflicts": [], "degraded": False, "policy": pol}
    state_machine.append_case_event(session, case, a="provider", act=act, d=d, x=x, v=v,
                                    commit=False)
    append_block(session, ts=now_iso(), trace=case.trace_id, actor="provider", act=act,
                 cs=case.case_id, from_state="两源字段集", to_state=("冲突" if conflicts else "一致"),
                 note=x, op=v, category="fusion", commit=False)
    session.commit()
    return {"consistent": consistent, "conflicts": conflicts, "degraded": bool(conflicts),
            "policy": pol}
