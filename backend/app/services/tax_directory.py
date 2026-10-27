# -*- coding: utf-8 -*-
"""海外 Tax ID / VAT 名录校验（WP3.3 · FN-5-03）。

  - 格式校验走规则引擎（sg_uen_format_check / tax_id_checksum——确定性）；
  - 名录命中=模拟授权名录 webhook 通道（数据源 seeds/tax_directory.json 入 SeedMeta，
    演示口径无真实外呼）；回执作为字段证据入链，**source=webhook**（field_source 六枚举）；
  - 无统一验签体系地区：以名录命中为 authenticity 判定依据并明示口径（FN-5-03）——
    hit→PASSED / miss→NOT_VERIFIED（不判伪，明示「名录未命中（模拟 webhook）」）；
  - 事件 TAXID_CHECK（组件版本 webhook-sg，versions.json 附录 B）。
"""

from sqlalchemy import select

from app.domain import models as m
from app.services import rules, state_machine
from app.services.audit_chain import append_block, now_iso

_COMPONENT = "webhook-sg"


def directory(session) -> dict:
    meta = session.get(m.SeedMeta, "tax_directory")
    entries = (meta.payload.get("entries") if meta else None) or []
    return {e["tax_id"]: e for e in entries}


def check(session, case: m.Case) -> dict:
    """执行名录校验：返回 {format_rule, hit, tax_id, entity, authenticity_result, note}。"""
    tax = None
    row = session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id, m.FieldEvidence.field == "seller.tax_id"))
    if row is not None:
        tax = row.evidence_raw.get("value")
    fmt = None
    if tax:
        try:
            fmt = rules.run_rule("sg_uen_format_check", {"tax_id": tax})
        except Exception as e:  # 规则缺输入不中止（FN-0-07 独立性）
            fmt = {"rule_id": "sg_uen_format_check", "result": "NOT_VERIFIED", "note": str(e)}
    entry = directory(session).get(tax) if tax else None
    hit = entry is not None
    result = "PASSED" if hit else ("NOT_VERIFIED" if tax else "NOT_VERIFIED")
    note = (f"名录命中：{entry['entity']}（{entry['region']} · GST registered={entry['gst_registered']}）"
            if hit else
            (f"名录未命中 {tax!r}（模拟 webhook 通道 · 演示口径，不判伪）" if tax
             else "票面无 TaxID · 名录校验不适用"))
    # 回执证据（source=webhook）+事件+审计
    v = state_machine.component_version(session, _COMPONENT)
    if tax:
        seq = max([r.seq for r in session.scalars(select(m.FieldEvidence).where(
            m.FieldEvidence.case_id == case.case_id))] or [-1]) + 1
        ev = {"field": "seller.tax_id_directory", "label": "Tax ID 名录校验回执",
              "value": hit, "source": "webhook",
              "confidence": 1.0 if hit else 0.6,
              "evidence": {"page": None, "bbox": "—（webhook 回执）",
                           "raw_text": note,
                           "rule": (fmt["rule_id"] + " " + ("✓" if fmt["result"] == "PASSED" else "✗"))
                                 if fmt else None,
                           "model_version": v, "provider": "模拟授权名录 webhook（演示桩）"}}
        session.add(m.FieldEvidence(case_id=case.case_id, seq=seq, field=ev["field"],
                                    source="webhook", confidence=ev["confidence"], evidence_raw=ev))
        state_machine.append_case_event(
            session, case, a="system", act="TAXID_CHECK",
            d=f"海外 Tax ID 名录校验 → {'命中' if hit else '未命中'}",
            x=f"{note} · 无统一验签体系地区以名录为 authenticity 判定依据（FN-5-03）· source=webhook",
            v=v, commit=False)
        append_block(session, ts=now_iso(), trace=case.trace_id, actor="system", act="TAXID_CHECK",
                     cs=case.case_id, from_state=f"TaxID {tax}", to_state="HIT" if hit else "MISS",
                     note=note, op=v, category="verify", commit=False)
        session.commit()
    return {"format_rule": fmt, "hit": hit, "tax_id": tax,
            "entity": (entry or {}).get("entity"), "authenticity_result": result, "note": note}
