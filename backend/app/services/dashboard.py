# -*- coding: utf-8 -*-
"""仪表盘聚合服务（M2 WP2.1 · FN-8-11/FN-5-09 读侧、FN-0-14 深链存在性）。

聚合口径（用户裁决 2026-10-26；contracts/CHANGELOG.md ⑦）：
  - 历史累计基线值（总处理量/Touchless/错误自动放行率展示值/待复核展示值/环形占比/7 日趋势）
    以库内 kpi_snapshots 表为权威源（演示基线，M0 冻结 seed 即数据源，非硬编码透传）；
  - 可核算项一律库内 SQL 真算：红线达标布尔（rate ≤ limit 数值解析）、donut 占比合计=100 校验、
    live NEEDS_REVIEW/BLOCKED 计数、top_cases 逐案交叉核算、告警 case_ref 存在性、
    AI 建议标注必含人工确认文案校验、适配 glyph 从 registry adapter_status code 文本派生；
  - 豁免纪律（G-M0-001）：top_cases 快照↔cases 表机读字段差异仅当命中库内
    known_page_discrepancies 登记条目时豁免，未登记差异抛 E_AGGREGATION_MISMATCH（500）；
  - 本模块禁止读取 seeds/*.json 文件（数据源=DB），亦禁止硬编码 KPI 字面量；
  - 交叉核算字段口径=机读字段（status/amount/supplier/conf/provider/风险存在性）；
    页面展示文案（risk.t、region 串）为 dashboard 口径，不断言与枚举/meta 等值（M0 冻结基线，
    见 seeds/kpi.json source 注记）。
"""

import json
import re

from sqlalchemy import func, select

from app.domain import models as m
from app.domain.registry import CONTRACTS_DIR, get_registry
from app.services.errors import (CommandError, E_AGGREGATION_MISMATCH, E_CASE_NOT_FOUND,
                                 E_DEEPLINK_TAB_INVALID, E_TENANT_MISMATCH)
from app.services.tenant import TenantContext

# 三类风险趋势序列名（清单 §4.3 UI-DSH-04 / FN-5-09：查重拦截/验真异常/字段冲突——
# 展示词汇校验用，词汇以契约 dashboard-response.schema.json trend series.name enum 为准，不另造）
_TREND_NAMES = ("查重拦截", "验真异常", "字段冲突")

# 深链 tab 词汇（FN-0-14 ?tab={log|sla|arch}）——唯一来源=contracts/case-read.schema.json
# 内联 enum（契约即事实源，运行期读取；不入 enum-registry：页面级定位参数非案件域枚举）
_tab_vocab: list[str] | None = None


def deeplink_tabs() -> list[str]:
    global _tab_vocab
    if _tab_vocab is None:
        schema = json.loads((CONTRACTS_DIR / "case-read.schema.json").read_text(encoding="utf-8"))
        _tab_vocab = list(
            schema["$defs"]["existsResponse"]["properties"]["deeplink"]["properties"]["tabs"]["items"]["enum"])
    return list(_tab_vocab)


def _pct_num(s: str) -> float:
    """「0.02%」/「0.05%」→ 0.02/0.05（红线对照数值解析——真算而非字符串比较）。"""
    return float(str(s).strip().rstrip("%"))


def _exemption_note(disc_items: list[str], case_id: str) -> str | None:
    """登记条目摘录：命中 known_page_discrepancies 中含该案号的条目文本（首条），否则 None。"""
    for d in disc_items:
        if case_id in d:
            return d
    return None


def _live_counts(session, ctx: TenantContext) -> tuple[int, int]:
    def _one(status: str) -> int:
        return session.scalar(
            select(func.count()).select_from(m.Case)
            .where(m.Case.instance == ctx.instance, m.Case.status == status)) or 0
    return _one("NEEDS_REVIEW"), _one("BLOCKED")


def build_alert_items(session, ctx: TenantContext) -> list[dict]:
    """告警视图（FN-5-09 读侧：seed 六条基线入 alerts 表 → 响应；dashboard 与 /v1/alerts 同源，
    单一 builder 禁两处漂移）。AI 建议/案件引用校验为真实断言（违例=数据完整性缺陷 500）。"""
    disc_items = _disc_items(session)
    case_ids = set(session.scalars(
        select(m.Case.case_id).where(m.Case.instance == ctx.instance)))
    items: list[dict] = []
    for a in session.scalars(select(m.Alert).where(m.Alert.instance == ctx.instance)
                             .order_by(m.Alert.id)):
        raw = a.alert_raw
        if raw["level"] not in ("danger", "warning"):  # 展示级词汇（FN-5-09；分发级 P0-P2 另轨）
            raise CommandError(E_AGGREGATION_MISMATCH,
                               f"alerts[{a.id}] level {raw['level']!r} 越出 FN-5-09 展示词汇", http=500)
        ai_marked = "AI 建议" in raw["evidence"]
        if ai_marked and ("人工确认" not in raw["evidence"]):
            # FN-5-09/P00 §5：告警中的 AI 建议必须标注人工确认约束，缺一即违例
            raise CommandError(E_AGGREGATION_MISMATCH,
                               f"alerts[{a.id}] 含 AI 建议但缺「人工确认」约束标注", http=500)
        if a.case_ref and a.case_ref not in case_ids and not _exemption_note(disc_items, a.case_ref):
            raise CommandError(E_AGGREGATION_MISMATCH,
                               f"alerts[{a.id}] 引用 {a.case_ref} 不在实例案件集且未登记豁免", http=500)
        items.append({"level": raw["level"], "title": raw["title"], "meta": raw["meta"],
                      "evidence": raw["evidence"], "case_ref": a.case_ref,
                      "ai_advice_marked": ai_marked})
    return items


def _disc_items(session) -> list[str]:
    meta = session.get(m.SeedMeta, "known_page_discrepancies")
    return list(meta.payload.get("items", [])) if meta else []


def _reconcile_top_cases(session, ctx: TenantContext, snap_rows: list[dict],
                         disc_items: list[str]) -> tuple[list[dict], list[str]]:
    """Top5 逐案交叉核算（机读字段：status/amount/supplier/conf/provider/风险存在性）。
    差异命中登记条目 → 豁免（note 摘录）；未登记 → E_AGGREGATION_MISMATCH。返回 (行, 命中豁免摘录)。"""
    out: list[dict] = []
    applied: list[str] = []
    for tc in snap_rows:
        cid = tc["caseId"]
        c = session.get(m.Case, cid)
        row = {"caseId": cid, "region": tc["region"], "supplier": tc["supplier"],
               "amount": tc["amount"], "status": tc["status"], "conf": tc["conf"],
               "risk": tc.get("risk"), "provider": tc["provider"]}
        if c is None or c.instance != ctx.instance:
            note = _exemption_note(disc_items, cid)
            if not note:
                raise CommandError(E_AGGREGATION_MISMATCH,
                                   f"top_cases {cid} 不在 cases 主数据集且未登记扩展（G-M0-001 纪律）", http=500)
            row.update({"in_master_dataset": False, "live_status": None, "exempted": True,
                        "note": note[:120]})
            applied.append(note)
            out.append(row)
            continue
        diffs: list[str] = []
        if c.status != tc["status"]:
            diffs.append(f"status 快照={tc['status']} 库内={c.status}")
        if c.amount_display != tc["amount"]:
            diffs.append(f"amount 快照={tc['amount']} 库内={c.amount_display}")
        if c.supplier != tc["supplier"]:
            diffs.append(f"supplier 不一致 快照={tc['supplier']} 库内={c.supplier}")
        if c.confidence != tc["conf"]:
            diffs.append(f"conf 快照={tc['conf']} 库内={c.confidence}")
        if c.provider != tc["provider"]:
            diffs.append(f"provider 快照={tc['provider']} 库内={c.provider}")
        if (tc.get("risk") is None) != (c.risk_label is None):
            diffs.append(f"风险存在性 快照={tc.get('risk') is not None} 库内={c.risk_label is not None}")
        if diffs:
            note = _exemption_note(disc_items, cid)
            if not note:
                raise CommandError(E_AGGREGATION_MISMATCH,
                                   f"top_cases {cid} 机读字段未登记差异: {diffs}", http=500)
            applied.append(note)
            row.update({"in_master_dataset": True, "live_status": c.status, "exempted": True,
                        "note": f"{note[:80]} · 差异: {'; '.join(diffs)}"})
        else:
            row.update({"in_master_dataset": True, "live_status": c.status, "exempted": False,
                        "note": None})
        out.append(row)
    return out, applied


def get_dashboard(session, ctx: TenantContext) -> dict:
    """GET /v1/dashboard?instance= 聚合（KPI 四卡/环形/趋势/Top5/告警×3/适配状态条一次返回）。"""
    snap_row = session.get(m.KpiSnapshot, ctx.instance)
    if snap_row is None:  # 实例无 KPI 快照基线=装载缺失（数据完整性缺陷，不静默造值）
        raise CommandError(E_AGGREGATION_MISMATCH,
                           f"kpi_snapshots 缺实例 {ctx.instance} 基线（make seed 未装载？）", http=500)
    snap = snap_row.snapshot_raw
    kpi = snap["kpi"]

    # ── 红线对照真算（FN-5-05：rate ≤ 上限 0.05%；禁配置绕过语义由消费侧+引擎侧共同保证）──
    rate = _pct_num(kpi["false_auto_rate"])
    limit = _pct_num(kpi["false_auto_limit"])
    within = rate <= limit

    # ── 实时计数真算（演示口径注记：pending 展示值为历史全量基线，live_* 为 cases 表现值）──
    live_nr, live_bl = _live_counts(session, ctx)

    # ── 环形占比合计=100 校验（真算，不等=数据违例）──
    donut = snap["donut"]
    donut_sum = sum(d["value"] for d in donut)
    if donut_sum != 100:
        raise CommandError(E_AGGREGATION_MISMATCH,
                           f"{ctx.instance} donut 占比合计 {donut_sum}≠100", http=500)

    # ── 7 日趋势：词表/长度校验（展示序列名=契约 enum，禁漂移）──
    trend = snap["trend_7d"]
    names = tuple(s["name"] for s in trend["series"])
    if sorted(names) != sorted(_TREND_NAMES):
        raise CommandError(E_AGGREGATION_MISMATCH, f"{ctx.instance} trend 序列名越出词汇 {names}", http=500)

    disc_items = _disc_items(session)
    top_cases, applied = _reconcile_top_cases(session, ctx, snap["top_cases"], disc_items)

    # ── 适配状态条：adapters 表 + glyph 从 registry code 文本派生（不硬编码字形）──
    reg = get_registry()
    reg_codes = reg.code_set("adapter_status")
    adapter_items = []
    for a in session.scalars(select(m.Adapter).order_by(m.Adapter.load_seq)):
        if a.status_code not in reg_codes:  # 运行期防御（装载已校验）
            raise CommandError(E_AGGREGATION_MISMATCH, f"adapters[{a.name}] status_code 越表", http=500)
        glyph_m = re.search(r"[✓◐○]", a.status_code)
        if not glyph_m:
            raise CommandError(E_AGGREGATION_MISMATCH, f"adapter_status code 文本无字形 {a.status_code!r}", http=500)
        adapter_items.append({"name": a.name, "display": a.display,
                              "status_code": a.status_code, "glyph": glyph_m.group(0)})

    return {
        "instance": ctx.instance,
        "instance_label": snap["label"],
        "donut_scope": snap["donut_scope"],
        "kpi": {
            "total": kpi["total"], "total_sub": kpi["total_sub"],
            "touchless": kpi["touchless"], "touchless_sub": kpi["touchless_sub"],
            "false_auto": {"rate": kpi["false_auto_rate"], "limit": kpi["false_auto_limit"],
                           "within_redline": within,
                           "no_relax_note": "不允许以放松校验换取自动化率（FN-5-05 红线，禁配置绕过）"},
            "pending": {"display": kpi["pending_review"], "risk_display": kpi["pending_risk"],
                        "live_needs_review": live_nr, "live_blocked": live_bl},
        },
        "donut": donut,
        "trend_7d": trend,
        "top_cases": top_cases,
        "alerts": build_alert_items(session, ctx),
        "adapter_status": {"items": adapter_items},
        "reconciliation": {
            "mode": "snapshot+live",
            "sources": ["kpi_snapshots", "cases", "alerts", "adapters", "seed_meta(known_page_discrepancies)"],
            "donut_sum_100": True,
            "exemptions_applied": applied,
            "mismatches_unregistered": [],  # 恒空——未登记差异已在核算中抛错（禁静默）
        },
    }


def get_switcher(session, ctx: TenantContext) -> dict:
    """GET /v1/cases?view=switcher：三演示 full 案件（号+票种+状态，FN-8-03/FN-0-14）。
    排序稳定源=load_seq（seeds/cases.json 原序）；type_short 由 meta.type 首段派生（页面 option 口径）。"""
    items = []
    for c in session.scalars(select(m.Case).where(m.Case.instance == ctx.instance,
                                                  m.Case.detail_level == "full").order_by(m.Case.load_seq)):
        t = c.meta_raw["type"]
        short = re.split(r"（|\(", t, maxsplit=1)[0].strip()
        items.append({"caseId": c.case_id, "instance": c.instance, "type": t,
                      "type_short": short,
                      "invoice_type_machine": c.meta_raw.get("invoice_type_machine"),
                      "status": c.status})
    return {"items": items, "total": len(items)}


def resolve_deeplink(session, ctx: TenantContext, case_id: str,
                     tab: str | None) -> dict:
    """GET /v1/cases/{caseId}/exists：深链存在性校验（FN-0-14）。
    不存在/越权→CASE_NOT_FOUND(404)/E_TENANT_MISMATCH(403)，与详情面同口径；
    ?tab= 非法→E_DEEPLINK_TAB_INVALID(400)（词汇唯一来源=contracts/case-read.schema 内联 enum）。"""
    c = session.get(m.Case, case_id)
    if c is None:
        raise CommandError(E_CASE_NOT_FOUND, f"案件 {case_id} 不存在", http=404)
    if c.instance != ctx.instance:
        raise CommandError(E_TENANT_MISMATCH,
                           f"案件 {case_id} 不属实例 {ctx.instance}（四隔离，FN-0-11）", http=403)
    tabs = deeplink_tabs()
    tab_valid = None if tab is None else (tab in tabs)
    if tab is not None and tab not in tabs:
        raise CommandError(E_DEEPLINK_TAB_INVALID,
                           f"tab {tab!r} 非法（FN-0-14 词汇 {tabs}）", http=400)
    return {"caseId": c.case_id, "exists": True, "instance": c.instance,
            "type": c.meta_raw["type"], "status": c.status,
            "deeplink": {"tabs": tabs, "tab_requested": tab, "tab_valid": tab_valid}}
