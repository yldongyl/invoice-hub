# -*- coding: utf-8 -*-
"""Provider 实体管理与连通/SLA/成本服务（WP4.1 · FN-2-02~07 · FN-2-13）。

职责：
  - Provider 注册与生命周期管理（启用/停用、lock 锁定保护、KMS 凭证掩码）；
  - 停用 Provider 自动产生 PROVIDER_DISABLED 审计留痕，路由链顺次降级跳过；
  - 人工兜底 lock=True 停用请求被拒绝并提示（FN-2-03）；
  - 连通测试：握手时延 + SPI 契约与结果归一化校验 + 留痕入不可篡改审计；
  - SLA 监控与超阈值告警（FN-2-05：客户自有 OCR P95 8.2s > 8s warn 态）；
  - 成本统计（FN-2-06：多币种、单张价、GPU 分摊与内部结算）。
"""

from datetime import datetime, timezone
import re
from typing import Any, Optional

from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain
from app.services.audit_chain import new_trace_id, now_iso
from app.services.errors import CommandError
from app.services.providers import get_provider, list_spi_providers
from app.services.providers.base import (
    validate_capabilities,
    validate_recognize_result,
    validate_verify_result,
)

_SENSITIVE = re.compile(r"(secret|credential|cert|appkey|token|password|key)", re.I)


def _mask_credentials(raw: dict) -> dict:
    """KMS 托管凭证掩码，不回显明文（FN-2-02/07）。"""
    out = {}
    for k, v in raw.items():
        if _SENSITIVE.search(k):
            out[k] = "***（KMS 托管 · 演示桩不回显）***"
        elif isinstance(v, dict):
            out[k] = _mask_credentials(v)
        else:
            out[k] = v
    return out


def list_providers(session) -> list[dict[str, Any]]:
    """获取所有 Provider 列表，包含启用状态、SLA、成本与合规配置。"""
    rows = list(session.scalars(select(m.Provider)))
    out = []
    for r in rows:
        praw = dict(r.provider_raw or {})
        # 从 SPI 实例获取实时 capabilities
        spi = get_provider(r.provider_id)
        caps = spi.capabilities() if spi else {}

        # SLA 判定超阈值状态（如客户自有 OCR 8200ms > 8000ms warn 阈值）
        sla_info = praw.get("sla") or {}
        p95_ms = sla_info.get("p95_ms") or (caps.get("sla", {}).get("p95_latency_ms") if caps else 0)
        warn_th = sla_info.get("warn_threshold_ms") or 8000
        sla_lv = "warn" if (p95_ms and p95_ms > warn_th) else sla_info.get("lv", "ok")

        cost_info = praw.get("unit_cost")
        out.append({
            "provider_id": r.provider_id,
            "ui_id": praw.get("ui_id", r.provider_id),
            "display_name": r.display_name,
            "provider_label": praw.get("provider_label", caps.get("provider_label", "商业厂商")),
            "type": praw.get("type", "OCR 识别"),
            "deploy_mode": praw.get("deploy_mode", caps.get("deploy_mode", "API（SaaS）")),
            "enabled": bool(r.enabled),
            "lock": bool(r.lock),
            "sla": {
                "lv": sla_lv,
                "text": sla_info.get("text", f"{caps.get('sla', {}).get('availability_pct', 99.9)}% · P95 {p95_ms/1000:.1f}s"),
                "availability_pct": sla_info.get("availability_pct", caps.get("sla", {}).get("availability_pct")),
                "p95_ms": p95_ms,
                "warn_threshold_ms": warn_th,
            },
            "cost_display": praw.get("cost_display", "¥0"),
            "unit_cost": cost_info,
            "compliance_note": praw.get("compliance_note", caps.get("compliance_note")),
            "contract_ref": praw.get("contract_ref"),
            "services": praw.get("services", caps.get("services", ["recognize"])),
            "regions": praw.get("regions", caps.get("regions", ["CN"])),
            "formats": praw.get("formats", caps.get("formats", ["pdf_scan", "image"])),
            "credentials": _mask_credentials({"kms_key_arn": f"arn:kms:demo:provider/{r.provider_id}", "api_secret": "sk-live-masked-987"}),
        })
    return out


def get_provider_detail(session, provider_id: str) -> dict[str, Any]:
    """获取单个 Provider 详情。"""
    r = session.get(m.Provider, provider_id)
    if r is None:
        raise CommandError("E_PROVIDER_NOT_FOUND", f"Provider {provider_id!r} 不存在", http=404)
    all_p = list_providers(session)
    for p in all_p:
        if p["provider_id"] == provider_id:
            return p
    raise CommandError("E_PROVIDER_NOT_FOUND", f"Provider {provider_id!r} 不存在", http=404)


def toggle_provider(session, provider_id: str, enabled: bool, actor: str = "human", opinion: str | None = None) -> dict[str, Any]:
    """启用或停用 Provider（FN-2-02/03）。

    - 人工兜底 lock=True 锁定禁止停用，拒绝并报错提示；
    - 停用 Provider 产生 PROVIDER_DISABLED 审计日志，路由策略将自动跳过并降级。
    """
    r = session.get(m.Provider, provider_id)
    if r is None:
        raise CommandError("E_PROVIDER_NOT_FOUND", f"Provider {provider_id!r} 不存在", http=404)

    if r.lock and not enabled:
        raise CommandError(
            "E_PROVIDER_LOCKED",
            "「人工兜底」是所有降级链路的最终兜底，不可停用",
            http=400,
            details={"provider_id": provider_id, "lock": True},
        )

    prev_enabled = r.enabled
    r.enabled = enabled
    session.commit()

    audit_actor = actor if actor in ("system", "provider", "human", "ai") else "human"
    op_user = actor if actor not in ("system", "provider", "human", "ai") else "陈铮"
    trace = new_trace_id()
    if not enabled and prev_enabled:
        # 停用事件：必须记入审计链与时间线事件 PROVIDER_DISABLED
        note = (
            f"⚠ 已停用「{r.display_name}」· 引用该 Provider 的路由策略将自动跳过并降级至链上下一个"
            f"{f' · 原因：{opinion}' if opinion else ''}"
        )
        audit_chain.append_block(
            session,
            ts=now_iso(),
            trace=trace,
            actor=audit_actor,
            act="PROVIDER_DISABLED",
            cs=None,
            from_state="enabled",
            to_state="disabled",
            note=note,
            op=f"provider_service v1.0 · {op_user}",
            category="provider",
            commit=True,
        )

    return {
        "provider_id": r.provider_id,
        "display_name": r.display_name,
        "enabled": r.enabled,
        "lock": r.lock,
        "message": f"已启用「{r.display_name}」· 变更记入审计日志" if enabled else f"⚠ 已停用「{r.display_name}」· 引用该 Provider 的路由策略将自动跳过并降级至链上下一个（留痕于审计日志）",
    }


def test_connection(session, provider_id: str, actor: str = "human") -> dict[str, Any]:
    """Provider 连通测试（FN-2-04）。

    测试步骤：
      1. 检查 Provider 是否已注册；
      2. 校验 Provider capabilities 是否合乎 provider-spi.schema.json；
      3. 模拟握手测试连通时延；
      4. 执行样张识别测试，校验输出是否通过 ProviderResult 归一化校验；
      5. 若支持 verify，测试 verify 归一化输出；
      6. 结果与留痕记入不可篡改审计日志。
    """
    r = session.get(m.Provider, provider_id)
    if r is None:
        raise CommandError("E_PROVIDER_NOT_FOUND", f"Provider {provider_id!r} 不存在", http=404)

    spi = get_provider(provider_id)
    if spi is None:
        raise CommandError("E_SPI_NOT_IMPLEMENTED", f"Provider {provider_id} 尚未实装 SPI 契约", http=501)

    # 1. 契约 capabilities 校验
    caps = spi.capabilities()
    cap_errors = validate_capabilities(caps)
    if cap_errors:
        raise CommandError(
            "E_SPI_CAPABILITIES_INVALID",
            f"Provider {provider_id} 能力声明不符契约: {'; '.join(cap_errors)}",
            http=500,
            details={"errors": cap_errors},
        )

    # 2. 模拟时延与样张测试
    latency_ms = 0.0 if r.lock else round(float(caps.get("sla", {}).get("p95_latency_ms", 2000.0) * 0.1), 1)
    sample_payload = {
        "file_ref": f"mock://samples/{provider_id}_sample.pdf",
        "mime_type": "application/pdf",
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "instance": "CN" if "CN" in caps.get("regions", []) else "OS",
        "doc_type_hint": caps.get("invoice_types", ["通用"])[0],
        "request_id": f"req-test-{provider_id}",
    }

    rec_res = spi.recognize(sample_payload)
    rec_errors = validate_recognize_result(rec_res)
    if rec_errors:
        raise CommandError(
            "E_SPI_RESULT_INVALID",
            f"Provider {provider_id} 识别归一化输出不符契约: {'; '.join(rec_errors)}",
            http=500,
            details={"errors": rec_errors},
        )

    ver_ok = True
    if "verify" in caps.get("services", []):
        ver_payload = {
            "caseId": "INV-CN-2026-0001",
            "fields": {"invoice_no": "24312000000012345678", "gross": 1000.0},
            "channel": "tax_auth",
        }
        ver_res = spi.verify(ver_payload)
        if ver_res:
            ver_errors = validate_verify_result(ver_res)
            if ver_errors:
                raise CommandError(
                    "E_SPI_VERIFY_INVALID",
                    f"Provider {provider_id} 查验输出不符契约: {'; '.join(ver_errors)}",
                    http=500,
                    details={"errors": ver_errors},
                )

    audit_actor = actor if actor in ("system", "provider", "human", "ai") else "human"
    op_user = actor if actor not in ("system", "provider", "human", "ai") else "陈铮"
    trace = new_trace_id()
    lat_disp = "—" if r.lock else f"{latency_ms} ms"
    note = f"✓「{r.display_name}」连通测试通过 · 握手 {lat_disp} · 结果归一化格式校验 OK · 已记入审计日志"

    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor=audit_actor,
        act="CARRIER_ROUTED",
        cs=None,
        from_state="offline",
        to_state="online",
        note=note,
        op=f"provider_service v1.0 · {op_user}",
        category="provider",
        commit=True,
    )

    return {
        "ok": True,
        "provider_id": provider_id,
        "display_name": r.display_name,
        "latency_display": lat_disp,
        "latency_ms": latency_ms,
        "normalized_valid": True,
        "capabilities_valid": True,
        "message": note,
    }


def get_sla_stats(session) -> dict[str, Any]:
    """SLA 统计服务（FN-2-05）。"""
    providers = list_providers(session)
    warn_count = sum(1 for p in providers if p["sla"]["lv"] == "warn")
    return {
        "total_providers": len(providers),
        "active_providers": sum(1 for p in providers if p["enabled"]),
        "warn_count": warn_count,
        "providers": [
            {
                "provider_id": p["provider_id"],
                "display_name": p["display_name"],
                "sla": p["sla"],
            }
            for p in providers
        ],
    }


def get_cost_stats(session) -> dict[str, Any]:
    """成本统计服务（FN-2-06 · 多币种/单张价/GPU 分摊/内部结算）。"""
    providers = list_providers(session)
    return {
        "currencies": ["CNY", "SGD"],
        "items": [
            {
                "provider_id": p["provider_id"],
                "display_name": p["display_name"],
                "cost_display": p["cost_display"],
                "unit_cost": p["unit_cost"],
            }
            for p in providers
        ],
    }
