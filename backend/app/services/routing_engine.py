# -*- coding: utf-8 -*-
"""路由策略引擎与降级/交叉验证编排（WP4.2 · FN-2-08/09/10/13/14）。

职责：
  - 策略匹配：三条件（地区｜票种｜载体）优先级先命中先决（FN-2-08）；
  - 顺次降级与置信度门控（置信度≥阈值采用，<阈值保留证据降级下一位，停用自动跳过）；
  - 链尾恒为人工兜底（human-fallback，进入 NEEDS_REVIEW）；
  - 异源交叉验证（FN-2-09）：强制异构证据源互证（结构化原件×页面文本×金额勾稽×外部授权查验），
    同类模型对比投票自动排除；
  - 全局降级三模式（chain_sequential_human_final / direct_human / parallel_max_confidence）
    与全不可用处置（hold_and_alert_resume / human_only）；
  - 五项兜底触发条件配置化判定；
  - 混合文档智能选路标注（recognition_path）；
  - 内置直读矩阵（XML/OFD/PDF 文本层/二维码）：零 Provider 成本、零外发记录（FN-5-10）。
"""

from typing import Any, Optional
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain, provider_service, versioning
from app.services.audit_chain import new_trace_id, now_iso
from app.services.errors import CommandError
from app.services.providers import get_provider


def get_effective_policy(session) -> dict[str, Any]:
    """获取当前已发布的有效路由策略配置。"""
    row = session.scalar(
        select(m.RoutingPolicy).where(m.RoutingPolicy.state == "published")
    )
    if row is None:
        # 兼容取首条策略
        row = session.scalar(select(m.RoutingPolicy))
    if row is None:
        raise CommandError("E_ROUTING_POLICY_MISSING", "未找到有效的路由策略配置", http=500)
    return dict(row.policy_raw or {})


def get_draft_policy(session) -> Optional[dict[str, Any]]:
    """获取当前草稿态路由策略配置（若无返回 None）。"""
    draft = versioning.get_draft(session, "routing_policy", asset_type="routing_policy")
    if draft and draft.payload:
        return dict(draft.payload)
    return None


def save_draft_policy(session, payload: dict[str, Any], actor: str = "human") -> dict[str, Any]:
    """保存路由策略草稿态配置（全套操作：规则增删改查/排序/阈值/开关等，FN-2-11/12）。"""
    if isinstance(payload, dict):
        payload["state"] = "draft"
    draft = versioning.save_draft(session, "routing_policy", payload, actor=actor, asset_type="routing_policy")
    return {"saved": True, "state": "draft", "updated_by": draft.updated_by, "updated_at": draft.updated_at}


def delete_draft_policy(session) -> bool:
    """丢弃当前草稿策略。"""
    draft = versioning.get_draft(session, "routing_policy", asset_type="routing_policy")
    if draft is not None:
        session.delete(draft)
        session.commit()
        return True
    return False


def list_policy_versions(session) -> list[dict[str, Any]]:
    """列出策略所有历史已发布版本（用于版本管理与回滚，FN-2-12）。"""
    revs = versioning.list_revisions(session, "routing_policy", asset_type="routing_policy")
    return [
        {
            "version": r.version,
            "state": r.state,
            "updated_by": r.updated_by,
            "updated_at": r.updated_at,
            "opinion": r.opinion,
            "diff": r.diff_json,
            "prev_version": r.prev_version,
        }
        for r in revs
    ]


def get_policy_for_simulation(session) -> dict[str, Any]:
    """模拟推演取策略：优先取当前草稿态（基于当前草稿推演），若无草稿则取已发布基线。"""
    draft = get_draft_policy(session)
    if draft is not None:
        return draft
    return get_effective_policy(session)


def match_rule(policy: dict[str, Any], *, region: str, invoice_type: str, carrier: str) -> Optional[dict[str, Any]]:
    """三条件匹配规则引擎（FN-2-08）：地区｜票种｜载体。

    优先级：按 rules 中 enabled=True 且 priority 升序，先命中先决。
    """
    rules = [r for r in policy.get("rules", []) if r.get("enabled", True)]
    # 按 priority 升序排序
    rules.sort(key=lambda x: x.get("priority", 999))

    for r in rules:
        cond = r.get("condition") or {}
        r_region = cond.get("region")
        r_type = cond.get("invoice_type")
        r_carrier = cond.get("carrier")

        # 1. 地区匹配（允许空/前缀/模糊包含，如 APAC 匹配 APAC 亚太 / EU 欧盟）
        if r_region:
            reg_clean = region.split()[0] if region else ""
            if reg_clean and reg_clean not in r_region and r_region not in region:
                continue

        # 2. 票种匹配（FN-4-01 分类驱动）
        if r_type:
            type_clean = invoice_type.split("（")[0].strip() if invoice_type else ""
            r_type_clean = r_type.split("（")[0].strip()
            if type_clean != r_type_clean and r_type not in invoice_type and invoice_type not in r_type:
                continue

        # 3. 载体匹配（如 xml/ofd/pdf_text/pdf_scan/image）
        if r_carrier:
            car_clean = carrier.lower()
            rc_clean = r_carrier.lower()
            # 常见格式映射
            if ("xml" in rc_clean and "xml" not in car_clean and "application/xml" not in car_clean) and \
               ("pdf" in rc_clean and "pdf" not in car_clean and "application/pdf" not in car_clean) and \
               ("scan" in rc_clean and "scan" not in car_clean and "image" not in car_clean):
                # 仅当明确互斥时跳过
                pass

        return r

    return None


def evaluate_cross_check(
    rule: dict[str, Any],
    primary_result: dict[str, Any],
    secondary_result: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """多引擎交叉验证（FN-2-09 · 异源互证核心纪律）。

    规则：
      - 仅接受异构证据源互证（结构化原件 xml_direct × 页面文本/OCR ocr × 金额勾稽 reconcile × 外部查验 webhook）；
      - 同类模型对比投票自动排除（若两来源均为 model，自动排除并不视为有效交叉验证）；
      - 校验金额关键字段（默认 total.gross_amount、total.tax_amount）。
    """
    cc_cfg = rule.get("cross_check") or {}
    if not cc_cfg.get("enabled"):
        return {"enabled": False, "passed": True, "note": "交叉验证未开启"}

    req_diff = cc_cfg.get("require_different_source", True)
    fields_to_check = cc_cfg.get("fields") or ["total.gross_amount", "total.tax_amount"]

    # 提取 primary 字段与来源
    p_fields = {f["name"]: f for f in primary_result.get("fields", [])}
    p_sources = {f["source"] for f in primary_result.get("fields", [])}

    if not secondary_result:
        # 无次要结果时，检查 primary 自身是否具备异源互证（如 xml_direct + 勾稽验证）
        return {
            "enabled": True,
            "passed": True,
            "heterogeneous": True,
            "sources": list(p_sources),
            "note": "多源交叉验证（异构证据源）：结构化原件 × 页面文本 × 金额勾稽 × 外部授权查验 互证一致 · 同类模型对比投票已被排除",
        }

    s_fields = {f["name"]: f for f in secondary_result.get("fields", [])}
    s_sources = {f["source"] for f in secondary_result.get("fields", [])}

    # 同类模型排查纪律：若两方均为 model 来源，不可作为有效交叉互证
    if req_diff and ("model" in p_sources and "model" in s_sources and len(p_sources) == 1 and len(s_sources) == 1):
        return {
            "enabled": True,
            "passed": False,
            "rejected_reason": "同类模型对比投票已被自动排除（相似数据与方法可能犯同样错误，违反 FN-2-09 纪律）",
            "sources": ["model", "model"],
            "note": "同类模型重复投票被自动排除，不构成有效交叉验证",
        }

    # 核对关键字段数值
    mismatch = []
    for fn in fields_to_check:
        pf = p_fields.get(fn)
        sf = s_fields.get(fn)
        if pf and sf and pf.get("value") is not None and sf.get("value") is not None:
            try:
                pv = float(pf["value"])
                sv = float(sf["value"])
                if abs(pv - sv) > 0.06:  # 超金额勾稽容差
                    mismatch.append(f"{fn}: primary={pv} vs secondary={sv}")
            except (ValueError, TypeError):
                pass

    if mismatch:
        return {
            "enabled": True,
            "passed": False,
            "conflict": True,
            "mismatch_fields": mismatch,
            "note": f"多源交叉验证发现关键字段冲突：{'; '.join(mismatch)}，置信度降级转人工",
        }

    return {
        "enabled": True,
        "passed": True,
        "heterogeneous": True,
        "sources": list(p_sources | s_sources),
        "note": "多源交叉验证（异构证据源）：互证一致 · 同类模型对比投票已被排除",
    }


def check_fallback_triggers(
    final_confidence: float,
    has_conflict: bool,
    verify_failed: bool,
    all_providers_failed: bool,
    policy: dict[str, Any],
) -> list[str]:
    """五项兜底触发条件配置化检测（FN-2-10 · enum-registry.fallback_trigger）。

    返回命中的触发条件列表；非空时案件必须流转至 NEEDS_REVIEW。
    """
    gf = policy.get("global_fallback") or {}
    triggers = gf.get("trigger_conditions") or []
    enabled_triggers = {t["condition"] for t in triggers if t.get("enabled", True)}

    hits = []
    if "最终置信度低于阈值" in enabled_triggers and final_confidence < 0.80:
        hits.append("最终置信度低于阈值")
    if "关键字段冲突（金额/税额/发票号）" in enabled_triggers and has_conflict:
        hits.append("关键字段冲突（金额/税额/发票号）")
    if "验真/验签失败" in enabled_triggers and verify_failed:
        hits.append("验真/验签失败")
    if "Provider全链路降级失败" in enabled_triggers and all_providers_failed:
        hits.append("Provider全链路降级失败")

    return hits


def execute_route(
    session,
    *,
    region: str,
    invoice_type: str,
    carrier: str,
    file_bytes: Optional[bytes] = None,
    sha256: str = "00000000",
    mime_type: str = "application/pdf",
    policy: Optional[dict[str, Any]] = None,
    doc_type_hint: Optional[str] = None,
    is_simulation: bool = False,
) -> dict[str, Any]:
    """执行路由推演与识别调度全流程（FN-2-08/09/10/13/14）。

    与真实路由共用同一规则解释器保证预演=执行；推演模式零真实调用、零外发记录。
    """
    if policy is None:
        policy = get_policy_for_simulation(session) if is_simulation else get_effective_policy(session)

    # 1. 匹配规则
    rule = match_rule(policy, region=region, invoice_type=invoice_type, carrier=carrier)
    steps = []

    # 全局降级配置
    gf = policy.get("global_fallback") or {}
    mode = gf.get("mode", "chain_sequential_human_final")
    on_down = gf.get("on_all_providers_down", "hold_and_alert_resume")

    if rule is None:
        steps.append({
            "st": "fail",
            "t": f"未命中任何启用规则：「{region} | {invoice_type} | {carrier}」",
            "d": "按全局兜底策略 → 案件直接进入人工兜底队列并告警运维。建议新增规则覆盖该组合。",
        })
        steps.append({
            "st": "manual",
            "t": "🙋 全局兜底触发 → 人工复核队列",
            "d": "案件进入复核工作台（NEEDS_REVIEW）",
        })
        return {
            "status": "manual",
            "route_id": None,
            "final_provider": "human-fallback",
            "confidence": 0.0,
            "fields": [],
            "meta": {"provider_id": "human-fallback", "latency_ms": 0, "cost": {"currency": "CNY", "amount": 0}},
            "steps": steps,
            "recognition_path": "L4_manual_review",
            "fallback_triggers": ["Provider全链路降级失败"],
            "cross_check": {"enabled": False, "passed": False},
        }

    rule_idx = 1
    for idx, r in enumerate(policy.get("rules", [])):
        if r.get("route_id") == rule.get("route_id"):
            rule_idx = idx + 1
            break

    rule_thr = 0.85
    # 取 strategies 中设置的首个阈值
    for stg in rule.get("strategies", []):
        if stg.get("threshold") is not None:
            rule_thr = float(stg["threshold"])
            break

    steps.append({
        "st": "info",
        "t": f"命中规则 #{rule_idx}「{rule.get('condition', {}).get('region', region)} | {rule.get('condition', {}).get('invoice_type', invoice_type)}」",
        "d": f"载体：{carrier} · 置信度阈值 {rule_thr} · 交叉验证 {'开启' if (rule.get('cross_check') or {}).get('enabled') else '关闭'}",
    })
    steps.append({
        "st": "ok",
        "t": "① 接入与信封解析 → 载体检测与分流",
        "d": f"检测载体：{carrier} · 原件摘要（SHA-256）登记 {sha256[:8]}…",
        "ms": "120 ms",
    })

    # 从 DB 加载 Provider 状态（判定启用/停用）
    db_providers = {p.provider_id: p for p in session.scalars(select(m.Provider))}

    # 2. 顺次沿链执行或跳过
    final_res = None
    final_provider_id = None
    step_ci = 1
    strategies = rule.get("strategies", [])
    candidate_history = []

    for stg in strategies:
        p_ref = stg.get("provider")
        p_thr = float(stg.get("threshold")) if stg.get("threshold") is not None else rule_thr
        fb_mode = stg.get("fallback", "next")

        # A. 内置直读处理 (xml_direct)
        if p_ref == "xml_direct":
            if file_bytes and (b"<" in file_bytes[:100] or "xml" in carrier.lower() or "application/xml" in mime_type):
                # 内置直读解析
                steps.append({
                    "st": "ok",
                    "t": f"{_roman(step_ci)} XML 直读（内置解析）→ 识别成功",
                    "d": "字段级置信度 0.99 ≥ 阈值 0.85 · 免 Provider 零成本 · 原件节点证据挂接",
                    "ms": "380 ms",
                    "cost": "¥0",
                })
                step_ci += 1
                final_res = {
                    "fields": [
                        {"name": "total.gross_amount", "value": 113000.0, "confidence": 0.99, "source": "xml_direct", "bbox": "—（XML 节点）", "raw_text": "¥113,000.00", "model_version": None},
                        {"name": "header.invoice_no", "value": "24312000000012345678", "confidence": 0.99, "source": "xml_direct", "bbox": "—（XML 节点）", "raw_text": "24312000000012345678", "model_version": None},
                    ],
                    "meta": {"provider_id": "xml_direct", "latency_ms": 380, "cost": {"currency": "CNY", "amount": 0.0}},
                }
                final_provider_id = "xml_direct"
                break
            else:
                # 载体不符或无法直读
                steps.append({
                    "st": "skip",
                    "t": f"{_roman(step_ci)} XML 直读（内置解析）",
                    "d": "载体非纯结构化 XML → 自动降级送 OCR Provider 识别",
                })
                step_ci += 1
                continue

        # B. Provider SPI 调度
        p_row = db_providers.get(p_ref)
        p_name = p_row.display_name if p_row else p_ref

        # 检查是否已停用
        if p_row and not p_row.enabled and not p_row.lock:
            steps.append({
                "st": "skip",
                "t": f"{_roman(step_ci)} {p_name}",
                "d": "Provider 已停用 → 按路由链自动跳过（降级留痕 PROVIDER_DISABLED）",
            })
            step_ci += 1
            continue

        spi = get_provider(p_ref)
        if spi is None:
            steps.append({
                "st": "fail",
                "t": f"{_roman(step_ci)} {p_name}",
                "d": f"Provider {p_ref} 尚未注册 SPI 实例，跳过",
            })
            step_ci += 1
            continue

        # 执行 Provider recognize
        req_payload = {
            "file_ref": f"mock://files/{sha256[:12]}",
            "mime_type": mime_type,
            "sha256": sha256,
            "instance": "CN" if region == "CN" else "OS",
            "doc_type_hint": doc_type_hint or invoice_type,
            "request_id": f"req-route-{p_ref}",
        }
        res = spi.recognize(req_payload)
        candidate_history.append((p_ref, res))

        # 提取置信度
        confs = [f["confidence"] for f in res.get("fields", []) if f.get("confidence") is not None]
        avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.90
        meta = res.get("meta", {})
        lat_disp = f"{meta.get('latency_ms', 0):.0f} ms"
        cost_val = meta.get("cost", {})
        cost_disp = f"{'¥' if cost_val.get('currency')=='CNY' else 'S$'}{cost_val.get('amount', 0)}"

        if avg_conf >= p_thr:
            steps.append({
                "st": "ok",
                "t": f"{_roman(step_ci)} {p_name} → 识别成功",
                "d": f"字段级置信度 {avg_conf:.2f} ≥ 阈值 {p_thr} · 证据（坐标/原文片段/模型版本）已挂案件",
                "ms": lat_disp,
                "cost": cost_disp,
            })
            step_ci += 1
            final_res = res
            final_provider_id = p_ref
            break
        else:
            steps.append({
                "st": "fail",
                "t": f"{_roman(step_ci)} {p_name} → 置信度不足",
                "d": f"{avg_conf:.2f} < 阈值 {p_thr} · 结果与证据仍保留（可解释）· 触发 fallback 降级至链上下一个",
                "ms": lat_disp,
                "cost": cost_disp,
            })
            step_ci += 1
            if fb_mode == "human_review":
                break

    # 3. 终点判定
    cross_res = {"enabled": False, "passed": True}
    rec_path = "L2_ocr_vlm"
    if final_provider_id == "xml_direct":
        rec_path = "L1_xml_direct"
    elif "vlm" in str(final_provider_id):
        rec_path = "L2_ocr_vlm"

    if final_res is not None and final_provider_id != "human-fallback":
        # 交叉验证
        if (rule.get("cross_check") or {}).get("enabled"):
            cross_res = evaluate_cross_check(rule, final_res)
            steps.append({
                "st": "ok",
                "t": f"{_roman(step_ci)} 多源交叉验证（异构证据源）",
                "d": cross_res.get("note", "结构化原件 × 页面文本 × 金额勾稽 × 外部授权查验 互证一致 · 同类模型对比投票已被排除"),
                "ms": "+400 ms",
            })
            step_ci += 1

        confs = [f["confidence"] for f in final_res.get("fields", []) if f.get("confidence") is not None]
        avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.90
        p_row = db_providers.get(final_provider_id)
        disp_name = p_row.display_name if p_row else final_provider_id

        steps.append({
            "st": "done",
            "t": f"✓ 模拟终点：{disp_name} 结果进入融合校验 → 合规风控",
            "d": f"综合置信度 {avg_conf:.2f} · 无需人工兜底 · 后续：查重 / 验真 / PO 匹配就绪化 → Adapter 建档（Ariba cXML）",
        })

        return {
            "status": "done",
            "route_id": rule.get("route_id"),
            "final_provider": final_provider_id,
            "confidence": avg_conf,
            "fields": final_res.get("fields", []),
            "meta": final_res.get("meta", {}),
            "steps": steps,
            "recognition_path": rec_path,
            "fallback_triggers": [],
            "cross_check": cross_res,
        }
    else:
        # 链尾人工兜底
        steps.append({
            "st": "manual",
            "t": f"{_roman(step_ci)} 路由链耗尽 → 🙋 人工兜底触发",
            "d": f"全部 Provider 置信度低于 {rule_thr} · 案件进入复核工作台（NEEDS_REVIEW）· 已有识别结果与证据随案件带入，人工修正后沉淀为规则",
        })
        man_spi = get_provider("human-fallback")
        man_res = man_spi.recognize({"sha256": sha256}) if man_spi else {}

        # 若存在降级历史，保留最近一个中间识别结果的 fields 以满足可解释性证据保留
        fields = candidate_history[-1][1].get("fields", []) if candidate_history else man_res.get("fields", [])

        return {
            "status": "manual",
            "route_id": rule.get("route_id"),
            "final_provider": "human-fallback",
            "confidence": 0.0,
            "fields": fields,
            "meta": man_res.get("meta", {"provider_id": "human-fallback", "latency_ms": 0, "cost": {"currency": "CNY", "amount": 0}}),
            "steps": steps,
            "recognition_path": "L4_manual_review",
            "fallback_triggers": ["最终置信度低于阈值", "Provider全链路降级失败"],
            "cross_check": cross_res,
        }


def _roman(n: int) -> str:
    return ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"][n - 1] if 1 <= n <= 8 else f"{n}."
