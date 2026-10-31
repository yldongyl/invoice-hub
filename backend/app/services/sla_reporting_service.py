# -*- coding: utf-8 -*-
"""SLA 与质量报表聚合及异常归因分析服务（WP5.3 · FN-8-12 / FN-8-14）。

功能与规则：
  - 性能 SLA 分链路 P95 六卡（直读、PDF、OCR、表单、查重、归档）；
  - 服务可用性（99.62% 目标 99.5%）与单实例吞吐（62 张/分钟）；
  - §9.2 识别质量指标表（字段精确匹配率三档、整票正确率、Touchless Rate）；
  - 产品红线指标大卡与近 12 周趋势序列（错误自动放行率 0.02% ≤ 0.05%）；
  - 单张成本（¥0.31）与异常解决时长（42 分钟）；
  - AI 异常归因分析建议卡（采纳转人工发布，不自动执行，FN-8-14）。
"""

from typing import Any
from app.domain import models as m
from app.services import audit_chain
from app.services.audit_chain import now_iso, new_trace_id
from app.services.rbac_service import assert_not_ai_agent, require_permission

# 分链路 P95 基线
SLA_LINKS = [
    {
        "id": "xml_ofd_direct",
        "name": "XML / OFD 结构化直读",
        "p95_display": "380",
        "unit": "ms · P95",
        "target": "目标 < 500ms",
        "ratio_pct": 76,
        "status": "达标",
        "note": "数电票原件直读 · 免 Provider 调用",
    },
    {
        "id": "pdf_text_extraction",
        "name": "PDF 文本层抽取",
        "p95_display": "0.8",
        "unit": "s · P95",
        "target": "目标 < 1s",
        "ratio_pct": 80,
        "status": "达标",
        "note": "海外 Supplier Invoice 原生文本层可用时优先",
    },
    {
        "id": "ocr_provider",
        "name": "OCR Provider 识别",
        "p95_display": "6.2",
        "unit": "s · P95",
        "target": "建议 5–10s 区间",
        "ratio_pct": 62,
        "status": "达标",
        "note": "扫描版专票 / 低质图像 · 可插拔 Provider",
    },
    {
        "id": "sync_form_recognition",
        "name": "同步表单识别（交互式）",
        "p95_display": "2.4",
        "unit": "s · P95",
        "target": "目标 < 3s",
        "ratio_pct": 80,
        "status": "达标",
        "note": "工作台单张上传即时反馈 · 人在环路",
    },
    {
        "id": "global_dedup",
        "name": "全局查重",
        "p95_display": "140",
        "unit": "ms · P95",
        "target": "目标 < 200ms",
        "ratio_pct": 70,
        "status": "达标",
        "note": "发票号 + 价税合计 + 销售方税号 组合键",
    },
    {
        "id": "archival_hash_chain",
        "name": "归档（原件 + 证据链）",
        "p95_display": "0.7",
        "unit": "s · P95",
        "target": "目标 < 1s",
        "ratio_pct": 70,
        "status": "达标",
        "note": "对象存储写入 + SHA-256 摘要登记",
    },
]

# §9.2 质量指标项
QUALITY_METRICS = [
    {
        "name": "字段级精确匹配率",
        "sub_name": "清晰标准件 · 关键字段",
        "detail": "供应商名称 / 税号 / 发票号 / 开票日期 / 金额等关键字段逐字段比对",
        "current": "99.2%",
        "target": "≥ 99%",
        "passed": True,
    },
    {
        "name": "字段级精确匹配率",
        "sub_name": "金额 / 税额 / 发票号",
        "detail": "高风险字段单独统计：错一位即计为错误，不容忍近似",
        "current": "99.6%",
        "target": "≥ 99.5%",
        "passed": True,
    },
    {
        "name": "字段级精确匹配率",
        "sub_name": "复杂件",
        "detail": "扫描件 / 低质图像 / 多语种 / 版式非常规票面",
        "current": "95.8%",
        "target": "≥ 95%",
        "passed": True,
    },
    {
        "name": "整票完全正确率",
        "sub_name": "全票维度",
        "detail": "全字段无一错误的案件占比（案件级口径）",
        "current": "98.1%",
        "target": "≥ 98%",
        "passed": True,
    },
    {
        "name": "Touchless Rate",
        "sub_name": "自动完成率（STP Accuracy）",
        "detail": "口径：正确的自动完成率——无人工介入且结论正确的案件占比，非放宽校验标准刷数",
        "current": "86.2%",
        "target": "试点参考 ≥ 80%",
        "passed": True,
    },
]

# 近 12 周错误自动放行率序列（趋近于 0）
REDLINE_12_WEEKS = [
    {"week": "W31", "rate": 0.048, "limit": 0.050},
    {"week": "W32", "rate": 0.045, "limit": 0.050},
    {"week": "W33", "rate": 0.041, "limit": 0.050},
    {"week": "W34", "rate": 0.038, "limit": 0.050},
    {"week": "W35", "rate": 0.034, "limit": 0.050},
    {"week": "W36", "rate": 0.030, "limit": 0.050},
    {"week": "W37", "rate": 0.027, "limit": 0.050},
    {"week": "W38", "rate": 0.025, "limit": 0.050},
    {"week": "W39", "rate": 0.023, "limit": 0.050},
    {"week": "W40", "rate": 0.022, "limit": 0.050},
    {"week": "W41", "rate": 0.021, "limit": 0.050},
    {"week": "W42", "rate": 0.020, "limit": 0.050},
]

# AI 归因建议卡内存态
_ATTRIBUTION_ADVICE = {
    "title": "异常归因分析（AI 建议）",
    "model": "qwen-finance-v2 · 2026-10-15",
    "confidence": 0.86,
    "confidence_label": "86%（中）",
    "disclaimer": "AI 生成内容仅供参考 · 结论须人工确认后转策略发布，系统不自动执行",
    "findings": [
        "重复票拦截 2 起（INV-CN-2026-0385、INV-SG-2026-0122）均来自「供应商邮箱直投」渠道，建议在渠道受理层增加提交前查重提示，把拦截从「建档前」前移到「投递前」；",
        "OCR Provider P95 6.2s 的长尾主要由倾斜 > 3° 的扫描版增值税专票贡献，建议在路由策略 v2026-10-20.4 基础上，将自托管 VLM 前置至该类样本；",
        "字段修改集中在「票面 OCR × XML 直读」冲突场景（INV-CN-2026-0381），建议将「结构化原件优先」写入字段级采信规则，减少人工改值。",
    ],
    "status": "pending",  # pending | adopted | rejected
    "disposition": None,
}


def get_sla_and_quality_report(session) -> dict:
    """获取 SLA 性能指标、质量报表与 12 周红线趋势（FN-8-12）。"""
    return {
        "sla_links": {
            "summary": "6 / 6 链路达标",
            "cards": list(SLA_LINKS),
        },
        "availability_and_throughput": {
            "availability": {
                "current": 99.62,
                "target": 99.50,
                "status": "✓ 达标 +0.12pp",
                "max_downtime_minutes": 11,
                "note": "受理接口成功 + 解析链路可完成（含降级链路）计为可用",
            },
            "throughput": {
                "current": 62,
                "unit": "张 / 分钟",
                "target_range": "20–100",
                "status": "✓ 目标 20–100",
                "breakdown": {"xml_direct": 62, "ocr": 27, "human": 11},
                "note": "混合负载口径（直读 62% + OCR 27% + 人工兜底 11%）",
            },
        },
        "quality_metrics": {
            "summary": "5 / 5 达标",
            "table": list(QUALITY_METRICS),
        },
        "redline_indicator": {
            "name": "错误自动放行率",
            "current": 0.02,
            "limit": 0.05,
            "status": "✓ 未突破红线",
            "note": "产品红线：不允许通过放松校验标准提高自动化率。Touchless Rate 与错误自动放行率成对呈现。",
            "twelve_weeks_trend": list(REDLINE_12_WEEKS),
        },
        "cost_and_duration": {
            "cost_per_invoice": "¥0.31 / 张",
            "median_resolution_minutes": 42,
            "blocked_claim_sla_minutes": 30,
        },
        "attribution_advice": dict(_ATTRIBUTION_ADVICE),
    }


def handle_attribution_advice(session, actor: str, action: str, opinion: str | None = None) -> dict:
    """处理 AI 异常归因建议（采纳转人工发布流程 / 拒绝留痕，FN-8-14）。"""
    assert_not_ai_agent(actor)
    require_permission(session, actor, "策略发布")

    if action not in ("adopt", "reject"):
        raise ValueError(f"无效处置动作 {action!r}，须为 adopt 或 reject")

    _ATTRIBUTION_ADVICE["status"] = "adopted" if action == "adopt" else "rejected"
    _ATTRIBUTION_ADVICE["disposition"] = {
        "actor": actor,
        "action": action,
        "opinion": opinion or ("采纳意向转策略发布流程" if action == "adopt" else "不予采纳"),
        "ts": now_iso(),
    }

    trace = new_trace_id()
    act_code = "POLICY_PUBLISHED" if action == "adopt" else "LLM_ADVICE_REJECTED"
    blk = audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act=act_code,
        cs=None,
        category="compliance",
        note=f"AI 异常归因建议处置 · 动作：{action} · 操作人：{actor} · 意见：{opinion or '（无）'}",
        op="audit-reports/attribution",
    )

    return {
        "action": action,
        "status": _ATTRIBUTION_ADVICE["status"],
        "audit_blk": blk.blk,
        "trace": trace,
        "message": "AI 归因建议处置已完成并记入审计链",
    }
