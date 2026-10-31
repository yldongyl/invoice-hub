# -*- coding: utf-8 -*-
"""Provider 实体管理与连通测试/SLA/成本统计测试（WP4.1 · FN-2-02~07）。

验证要点：
  1. list_providers 包含 6 个 Provider 的完整信息（SLA 判定、成本、合规备注、KMS 凭证掩码）；
  2. 客户自有 OCR P95 8.2s > 8s 触发 warn 状态（FN-2-05）；
  3. 人工兜底 lock=True 禁止停用，抛 E_PROVIDER_LOCKED 且明确提示（FN-2-03）；
  4. 常规 Provider 停用成功，审计链中追加 PROVIDER_DISABLED 事件（FN-2-02）；
  5. 连通性测试模拟握手时延，通过 SPI 契约与归一化校验，入不可篡改审计日志（FN-2-04）；
  6. SLA 监控与多币种成本统计服务正常返回。
"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import provider_service
from app.services.errors import CommandError


def test_list_providers_and_sla_warning(fresh_session):
    """断言 list_providers 输出正确，客户自有 OCR 正确标记 warn 状态。"""
    providers = provider_service.list_providers(fresh_session)
    assert len(providers) == 6
    p_map = {p["provider_id"]: p for p in providers}

    # 1. 客户自有 OCR SLA 超阈值告警态
    cust = p_map["customer-ocr"]
    assert cust["sla"]["lv"] == "warn"
    assert cust["sla"]["p95_ms"] == 8200
    assert cust["sla"]["warn_threshold_ms"] == 8000

    # 2. 百望云 SLA 正常
    bw = p_map["bwyun-cn"]
    assert bw["sla"]["lv"] == "ok"
    assert bw["sla"]["availability_pct"] == 99.95

    # 3. 人工兜底 lock 属性
    man = p_map["human-fallback"]
    assert man["lock"] is True

    # 4. 凭证 KMS 掩码断言（界面不回显明文）
    for p in providers:
        creds = p["credentials"]
        assert "api_secret" in creds
        assert "***" in creds["api_secret"]


def test_human_fallback_lock_prevent_disable(fresh_session):
    """断言人工兜底不可停用，被拦截并提示（FN-2-03）。"""
    with pytest.raises(CommandError) as exc_info:
        provider_service.toggle_provider(fresh_session, "human-fallback", enabled=False)

    err = exc_info.value
    assert err.code == "E_PROVIDER_LOCKED"
    assert "「人工兜底」是所有降级链路的最终兜底，不可停用" in err.message
    assert err.http == 400

    # 数据库中状态保持 enabled=True
    p = fresh_session.get(m.Provider, "human-fallback")
    assert p.enabled is True


def test_toggle_provider_audit_logging(fresh_session):
    """断言停用 Provider 时产生 PROVIDER_DISABLED 审计留痕（FN-2-02）。"""
    # 停用百望云
    res = provider_service.toggle_provider(
        fresh_session, "bwyun-cn", enabled=False, actor="human", opinion="维护中"
    )
    assert res["enabled"] is False

    # 验证审计日志中存在 PROVIDER_DISABLED
    blocks = fresh_session.scalars(
        select(m.AuditBlock).where(m.AuditBlock.act == "PROVIDER_DISABLED")
    ).all()
    assert len(blocks) >= 1
    latest = blocks[-1]
    assert latest.act == "PROVIDER_DISABLED"
    assert latest.actor == "human"
    assert "百望云" in latest.note
    assert "自动跳过并降级" in latest.note

    # 重新启用
    res_on = provider_service.toggle_provider(
        fresh_session, "bwyun-cn", enabled=True, actor="human"
    )
    assert res_on["enabled"] is True


def test_provider_connection_test(fresh_session):
    """断言 Provider 连通性测试（FN-2-04）。"""
    # 1. 测试百望云连通
    res = provider_service.test_connection(fresh_session, "bwyun-cn", actor="human")
    assert res["ok"] is True
    assert res["latency_ms"] > 0
    assert res["normalized_valid"] is True
    assert res["capabilities_valid"] is True
    assert "连通测试通过" in res["message"]

    # 2. 测试人工兜底连通
    res_man = provider_service.test_connection(fresh_session, "human-fallback", actor="human")
    assert res_man["ok"] is True
    assert res_man["latency_display"] == "—"

    # 3. 验证传入具体操作员姓名（如“陈铮”）时，审计主体合规映射为 human 并正确留痕（修复 UI-M4-F01）
    res_cz = provider_service.test_connection(fresh_session, "nuonuo-cn", actor="陈铮")
    assert res_cz["ok"] is True
    assert "连通测试通过" in res_cz["message"]

    latest_block = fresh_session.scalars(
        select(m.AuditBlock).order_by(m.AuditBlock.blk.desc())
    ).first()
    assert latest_block is not None
    assert latest_block.actor == "human"
    assert "陈铮" in latest_block.op_component


def test_sla_and_cost_monitoring(fresh_session):
    """断言 SLA 监控指标与多币种成本统计服务（FN-2-05/06）。"""
    sla = provider_service.get_sla_stats(fresh_session)
    assert sla["total_providers"] == 6
    assert sla["warn_count"] >= 1  # customer-ocr

    costs = provider_service.get_cost_stats(fresh_session)
    assert "CNY" in costs["currencies"]
    assert "SGD" in costs["currencies"]
    items = {item["provider_id"]: item for item in costs["items"]}
    assert "bwyun-cn" in items
    assert "overseas-einv-sg" in items
