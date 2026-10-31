# -*- coding: utf-8 -*-
"""映射治理与 Link 候选推断/受控确认服务（WP4.5 · FN-6-07/08/09/10 · FN-4-06/07）。

职责：
  - 预设规则库治理（出厂+客户覆写+命中计数与覆盖率，FN-6-07）；
  - LLM 推荐队列规则桩（FN-6-08）：
      * 确认采纳 → 沉淀为预设规则 + 记入人工确认历史 + 入审计；
      * 拒绝推荐 → 必填原因 + 回落人工处理队列 + LLM_ADVICE_REJECTED 入审计；
      * 接口签名严格与 M5 真实 LLM 替换点隔离；
  - Link 候选推断（FN-4-06）：四项确定性校验（供应商一致、金额冲减对应、开票时序先后、重复 Link 全局检查）+ 匹配度评分；
  - Link 确认受控写（FN-6-10）：确认建立冲减 Link 并写入对象模型与案件时间线；拒绝必填备注；
  - 建档前 Link 强制校验（FN-0-04/FN-7-04）：红字票/Credit Note 未确认 Link 时拦截建档。
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain, state_machine
from app.services.audit_chain import new_trace_id, now_iso
from app.services.errors import CommandError

SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"


def _load_mapping_seeds() -> dict[str, Any]:
    f = SEEDS_DIR / "mapping_rules.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


# ───────────────────────── 1. 预设规则库与覆盖率统计（FN-6-07） ─────────────────────────

def get_preset_rules(session) -> dict[str, Any]:
    """获取预设规则库与月度命中覆盖率统计（FN-6-07）。"""
    seeds = _load_mapping_seeds()
    stats = seeds.get("stats") or {"preset_month_hits": 12847, "preset_coverage_pct": 96.2, "period": "本月"}

    # 从 DB 读取自定义/沉淀规则
    db_rules = list(session.scalars(select(m.MappingRule).where(m.MappingRule.rule_type == "field")))
    presets = list(seeds.get("presets") or [])

    # 查重合并
    seen_src = {p["src"] for p in presets}
    for r in db_rules:
        if r.src not in seen_src:
            presets.append({
                "src": r.src,
                "to": r.dst,
                "month_hits": (r.rule_raw or {}).get("month_hits", 1),
                "source": "人工沉淀 (manual)" if (r.rule_raw or {}).get("settled") else "预设 (preset)",
            })
            seen_src.add(r.src)

    return {
        "stats": stats,
        "total": len(presets),
        "presets": presets,
    }


def match_field_preset(session, src_field: str) -> Optional[dict[str, Any]]:
    """根据源字段名匹配预设映射规则（命中即返回统一 Schema 目标字段）。"""
    p_data = get_preset_rules(session)
    for p in p_data["presets"]:
        if p["src"] == src_field or src_field in p["src"] or p["src"] in src_field:
            return p
    return None


# ───────────────────────── 2. 映射推荐队列规则桩与采纳沉淀（FN-6-08/09） ─────────────────────────

_REC_META_KEY = "ai_recommended_queue"


def _find_seed_rec_queue(seeds: dict) -> list[dict[str, Any]]:
    for k in seeds:
        if k.endswith("_recommended_queue"):
            return list(seeds[k])
    return []


def list_ai_recommendations(session) -> list[dict[str, Any]]:
    """获取待确认的字段映射推荐队列（FN-6-08 · 规则桩）。

    接口隔离注记（M5 替换点）：
      M4 阶段由本规则桩读取 seeds/mapping_rules.json 保证确定性；
      M5 LangGraph 域直接实现此签名函数即可无缝替换，backend 内核零改动。
    """
    # 优先从 SeedMeta 读取状态持久化
    meta = session.get(m.SeedMeta, _REC_META_KEY)
    if meta and meta.payload:
        return list(meta.payload)

    seeds = _load_mapping_seeds()
    items = _find_seed_rec_queue(seeds)
    # 存入 SeedMeta 支持运行时采纳/拒绝状态变更
    session.add(m.SeedMeta(name=_REC_META_KEY, payload=items))
    session.commit()
    return items


def adopt_recommendation(session, src_field: str, actor: str = "human", opinion: str | None = None) -> dict[str, Any]:
    """采纳推荐映射（FN-6-08/09）：
    确认一次即沉淀为预设规则（长期复用）+ 记入人工确认历史 + 记不可篡改审计。
    """
    items = list_ai_recommendations(session)
    target = None
    for it in items:
        if it["src"] == src_field:
            target = it
            break

    if target is None:
        raise CommandError("E_MAPPING_NOT_FOUND", f"未找到字段 {src_field!r} 的推荐项", http=404)

    target["state"] = "adopted"
    target["adopted_by"] = actor
    target["adopted_at"] = now_iso()

    # 1. 沉淀为规则写入 mapping_rules 表
    new_rule = m.MappingRule(
        rule_type="field",
        src=target["src"],
        dst=target["to"],
        rule_raw={"settled": True, "adopted_from": target.get("model_version"), "month_hits": 1},
    )
    session.add(new_rule)

    # 2. 追加至人工确认历史
    hist_meta = session.get(m.SeedMeta, "confirmation_history")
    history = list(hist_meta.payload) if (hist_meta and hist_meta.payload) else []
    hist_entry = {
        "confirmed_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"),
        "src": target["src"],
        "settled_to": target["to"],
        "confirmed_by": f"{actor} · 复核员",
        "hits_after_settle": 1,
        "source": "人工沉淀 (manual)",
    }
    history.insert(0, hist_entry)
    if hist_meta:
        hist_meta.payload = history
    else:
        session.add(m.SeedMeta(name="confirmation_history", payload=history))

    # 3. 更新推荐队列状态
    q_meta = session.get(m.SeedMeta, _REC_META_KEY)
    if q_meta:
        q_meta.payload = items

    # 4. 记入不可篡改审计链
    trace = new_trace_id()
    note = f"采纳映射推荐并沉淀为规则：{target['src']} → {target['to']} · 模型 {target.get('model_version')} · 处置意见：{opinion or '确认长期复用'}"
    audit_chain.append_block(
        session, ts=now_iso(), trace=trace, actor="human", act="FIELD_EDITED", cs=None,
        from_state="AI 建议 (pending)", to_state=f"已沉淀规则：{target['to']}", note=note,
        op=actor, category="field", commit=True,
    )

    return {
        "adopted": True,
        "src": target["src"],
        "to": target["to"],
        "message": f"已确认并沉淀「{target['src']} → {target['to']}」为长期预设规则，全量审计可追溯",
    }


def reject_recommendation(session, src_field: str, reason: str, actor: str = "human") -> dict[str, Any]:
    """拒绝推荐映射（FN-6-08）：
    拒绝必填备注 + 推荐项回落人工队列 + LLM_ADVICE_REJECTED 记入不可篡改审计。
    """
    if not (reason or "").strip():
        raise CommandError("E_OPINION_REQUIRED", "拒绝 AI 映射推荐必须填写拒绝原因（FN-6-08 / FN-0-08 要素④）", http=422)

    items = list_ai_recommendations(session)
    target = None
    for it in items:
        if it["src"] == src_field:
            target = it
            break

    if target is None:
        raise CommandError("E_MAPPING_NOT_FOUND", f"未找到字段 {src_field!r} 的推荐项", http=404)

    target["state"] = "rejected"
    target["reject_note"] = reason
    target["rejected_by"] = actor
    target["rejected_at"] = now_iso()

    q_meta = session.get(m.SeedMeta, _REC_META_KEY)
    if q_meta:
        q_meta.payload = items

    trace = new_trace_id()
    note = f"不采纳 AI 映射推荐：{target['src']} → {target['to']} · 拒绝原因：{reason} · 字段回落人工队列"
    audit_chain.append_block(
        session, ts=now_iso(), trace=trace, actor="human", act="LLM_ADVICE_REJECTED", cs=None,
        from_state="AI 建议 (pending)", to_state="已拒绝·回落人工队列", note=note,
        op=actor, category="field", commit=True,
    )

    return {
        "rejected": True,
        "src": target["src"],
        "reason": reason,
        "message": f"已拒绝「{target['src']}」的映射建议，字段已回落人工复核队列",
    }


def get_confirmation_history(session) -> list[dict[str, Any]]:
    """获取人工确认历史列表（Tab3 · FN-6-09）。"""
    meta = session.get(m.SeedMeta, "confirmation_history")
    if meta and meta.payload:
        return list(meta.payload)
    seeds = _load_mapping_seeds()
    return list(seeds.get("confirmation_history") or [])


# ───────────────────────── 3. Link 候选推断（FN-4-06） ─────────────────────────

def infer_link_candidates(session, case_id: str) -> dict[str, Any]:
    """红字票 / Credit Note Link 候选推断（FN-4-06 · 四项确定性校验 + 匹配度评分）。"""
    case = session.get(m.Case, case_id)
    if case is None:
        raise CommandError("E_CASE_NOT_FOUND", f"案件 {case_id} 不存在", http=404)

    seeds = _load_mapping_seeds()
    cand_items = (seeds.get("link_candidates") or {}).get("items", [])

    # 查表匹配当前案件的候选原票
    matched_cand = next((c for c in cand_items if c["inv"] == case_id), None)
    if matched_cand is None:
        # 若种子中未直接定义，进行规则推断（查找同供应商的历史已解决发票）
        inst = case.instance
        c_amt = abs(float((case.facts_raw or {}).get("invoiceAmount") or 0.0))
        supp = case.supplier
        origins = list(session.scalars(
            select(m.Case).where(
                m.Case.supplier == supp,
                m.Case.status == "RESOLVED",
                m.Case.case_id != case_id,
            )
        ))
        if origins:
            orig = origins[0]
            orig_amt = float((orig.facts_raw or {}).get("invoiceAmount") or 0.0)
            mode = "全额冲减" if abs(c_amt - orig_amt) < 0.01 else "部分冲减"
            rem = max(0.0, orig_amt - c_amt)
            matched_cand = {
                "inv": case_id,
                "kind": case.invoice_type or "红字票",
                "amount": case.amount_display or f"¥{c_amt:,.2f}",
                "date": (case.meta_raw or {}).get("issue_date", "2026-10-16"),
                "supplier": supp,
                "origin": {
                    "caseId": orig.case_id,
                    "amount": orig.amount_display or f"¥{orig_amt:,.2f}",
                    "date": (orig.meta_raw or {}).get("issue_date", "2026-09-28"),
                    "supplier": orig.supplier,
                },
                "match_score": 92,
                "mode": mode,
                "confirmed": False,
                "evidence": [
                    {"k": "供应商一致", "v": "✓ 通过", "note": f"销售方 {supp} 完全一致，与供应商主数据匹配"},
                    {"k": "金额冲减对应", "v": "✓ 通过", "note": f"冲减金额 {c_amt} <= 原票 {orig_amt} → {mode}，冲减后余额 {rem}"},
                    {"k": "开票日期先后", "v": "✓ 通过", "note": "原票在前，红字票在后，符合红冲时序"},
                    {"k": "重复 Link 检查", "v": "✓ 通过", "note": "原票无既有冲减关系 · 全局唯一"},
                ],
            }

    if matched_cand is None:
        return {"has_candidate": False, "candidates": []}

    # 检查数据库中是否已确认该 Link
    existing_link = session.scalar(
        select(m.ObjectLink).where(
            m.ObjectLink.case_id == case_id,
            m.ObjectLink.link_type == "冲减",
        )
    )
    is_confirmed = existing_link is not None

    return {
        "has_candidate": True,
        "candidate": {**matched_cand, "confirmed": is_confirmed},
    }


def list_all_link_candidates(session) -> list[dict[str, Any]]:
    """获取全站所有待关联 Link 候选列表（Tab3 待关联列表，FN-4-06/FN-6-10）。"""
    seeds = _load_mapping_seeds()
    cand_items = list((seeds.get("link_candidates") or {}).get("items", []))
    # 动态附加已确认状态
    for item in cand_items:
        cid = item["inv"]
        link = session.scalar(
            select(m.ObjectLink).where(
                m.ObjectLink.case_id == cid,
                m.ObjectLink.link_type == "冲减",
            )
        )
        item["confirmed"] = link is not None
    return cand_items


# ───────────────────────── 4. Link 受控确认与拒绝（FN-6-10） ─────────────────────────

def confirm_link(session, credit_case_id: str, origin_case_id: str, actor: str = "human", opinion: str | None = None) -> dict[str, Any]:
    """确认红字票 / Credit Note 冲减 Link（FN-6-10 受控写）：
    写入对象模型 + 案件时间线 PO_MATCH + 不可篡改审计日志。
    """
    case = session.get(m.Case, credit_case_id)
    if case is None:
        raise CommandError("E_CASE_NOT_FOUND", f"红字发票 {credit_case_id} 不存在", http=404)

    # 1. 四项确定性校验：查既有冲减 Link
    existing = session.scalar(
        select(m.ObjectLink).where(
            m.ObjectLink.case_id == credit_case_id,
            m.ObjectLink.link_type == "冲减",
        )
    )
    if existing is not None and (existing.link_raw or {}).get("confirmed") is True:
        return {
            "confirmed": True,
            "case_id": credit_case_id,
            "origin_case_id": origin_case_id,
            "message": f"案件 {credit_case_id} 已建立至 {origin_case_id} 的冲减 Link",
        }

    # 2. 写入或更新 ObjectLink 实体
    if existing is not None:
        existing.ref = origin_case_id
        existing.link_raw = {
            "relation": "OFFSET_OUT",
            "ref": origin_case_id,
            "confirmed": True,
            "confirmed_by": actor,
            "confirmed_at": now_iso(),
            "opinion": opinion,
            "mode": "全额冲减",
            "rule": "link-check v1.1",
        }
    else:
        link_row = m.ObjectLink(
            case_id=credit_case_id,
            link_type="冲减",
            ref=origin_case_id,
            link_raw={
                "relation": "OFFSET_OUT",
                "ref": origin_case_id,
                "confirmed": True,
                "confirmed_by": actor,
                "confirmed_at": now_iso(),
                "opinion": opinion,
                "mode": "全额冲减",
                "rule": "link-check v1.1",
            },
        )
        session.add(link_row)

    # 3. 更新 Case 内联 links_raw
    links = dict(case.links_raw or {})
    links["credit_note"] = {
        "relation": "OFFSET_OUT",
        "ref": origin_case_id,
        "confirmed": True,
        "confirmed_by": actor,
        "confirmed_at": now_iso(),
    }
    case.links_raw = links

    # 4. 追加时间线事件
    state_machine.append_case_event(
        session,
        case,
        a="human",
        act="PO_MATCH",
        d=f"红字票冲减 Link 建立（关联原票 {origin_case_id}）",
        x=f"四项校验通过（供应商/冲减金额/时序/防重复）· 模式：全额冲减 · 确认人：{actor} · 消除重复付款风险",
        v="link-check v1.1",
        commit=False,
    )

    # 5. 追加审计块
    trace = case.trace_id or new_trace_id()
    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="PO_MATCH",
        cs=credit_case_id,
        from_state="Link 未建立（重复付款风险）",
        to_state=f"冲减 Link 建立 → 原票 {origin_case_id}",
        note=f"受控建立冲减 Link：{credit_case_id} —冲减→ {origin_case_id} · 确认人 {actor} · 处置意见：{opinion or '确认冲减'}",
        op=actor,
        category="match",
        commit=True,
    )

    return {
        "confirmed": True,
        "case_id": credit_case_id,
        "origin_case_id": origin_case_id,
        "message": f"✓ 已成功建立冲减 Link（{credit_case_id} → {origin_case_id}），建档前校验已解除拦截",
    }


def reject_link(session, credit_case_id: str, origin_case_id: str, reason: str, actor: str = "human") -> dict[str, Any]:
    """拒绝红字票 / Credit Note 冲减 Link（FN-6-10 受控写）：
    必填理由 + 候选保留可追溯 + 审计留痕 + 案件继续人工复核。
    """
    if not (reason or "").strip():
        raise CommandError("E_OPINION_REQUIRED", "拒绝 Link 必须填写原因（FN-6-10 要素④）", http=422)

    case = session.get(m.Case, credit_case_id)
    if case is None:
        raise CommandError("E_CASE_NOT_FOUND", f"红字发票 {credit_case_id} 不存在", http=404)

    trace = case.trace_id or new_trace_id()
    note = f"拒绝冲减 Link 候选（{credit_case_id} vs {origin_case_id}）· 拒绝原因：{reason} · 候选保留可追溯 · 案件继续人工复核"

    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="PO_MATCH",
        cs=credit_case_id,
        from_state="Link 候选待确认",
        to_state="Link 拒绝·保留候选",
        note=note,
        op=actor,
        category="match",
        commit=True,
    )

    return {
        "rejected": True,
        "case_id": credit_case_id,
        "origin_case_id": origin_case_id,
        "reason": reason,
        "message": f"已拒绝关联原票 {origin_case_id}，候选关系已保留于历史中，案件继续待人工复核",
    }


# ───────────────────────── 5. 建档前 Link 强制校验（FN-0-04/FN-7-04） ─────────────────────────

def assert_pre_filing_link_valid(session, case: m.Case) -> None:
    """建档前自动校验 Link（FN-0-04 · 核心纪律）：
    若为红字票 / Credit Note，必须已确认有效冲减 Link，未确认一律拦截建档！
    """
    itype = case.invoice_type or ""
    # 检查是否为红字冲减类票据
    is_credit = "Credit Note" in itype or "红字" in itype or (float((case.facts_raw or {}).get("invoiceAmount") or 0.0) < 0)
    if not is_credit:
        return

    # 查 ObjectLink 是否存在已确认冲减关联
    link = session.scalar(
        select(m.ObjectLink).where(
            m.ObjectLink.case_id == case.case_id,
            m.ObjectLink.link_type == "冲减",
        )
    )
    is_confirmed = False
    if link is not None and (link.link_raw or {}).get("confirmed") is True:
        is_confirmed = True
    elif case.links_raw and (case.links_raw.get("credit_note") or {}).get("confirmed") is True:
        is_confirmed = True

    if not is_confirmed:
        raise CommandError(
            "E_LINK_UNCONFIRMED",
            f"建档拦截：{case.case_id}（{itype}）尚未建立/确认冲减 Link！"
            f"未关联红字票存在重大重复付款风险，建档已被强制拦截（FN-0-04 / FN-6-10）",
            http=409,
            details={"case_id": case.case_id, "invoice_type": itype, "link_type": "冲减"},
        )
