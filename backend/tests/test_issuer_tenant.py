# -*- coding: utf-8 -*-
"""WP1.7 发号器（分实例域递增）与租户上下文（四隔离/强制注入）测试。"""

import re

import pytest

from app.domain.registry import get_registry
from app.services import issuer
from app.services.errors import E_TENANT_MISSING, CommandError
from app.services.tenant import TenantContext


def _pat(code):
    return re.compile(get_registry().id_pattern(code))


# ── 发号器：分域递增 + 播种自 seed 现值 ──────────────────────────────────────

def test_case_no_per_instance_domain_increment(fresh_session):
    """CN 段自种子现值 0387 续起；OS 段自 0125 续起（分实例域，CON-04）。"""
    n1 = issuer.next_case_no(fresh_session, "CN", 2026)
    n2 = issuer.next_case_no(fresh_session, "CN", 2026)
    assert n1 == "INV-CN-2026-0388" and n2 == "INV-CN-2026-0389"
    s1 = issuer.next_case_no(fresh_session, "OS", 2026)
    assert s1 == "INV-SG-2026-0126"
    assert _pat("案件号").match(n1) and _pat("案件号").match(s1)


def test_case_no_invalid_instance_rejected(fresh_session):
    with pytest.raises(CommandError):
        issuer.next_case_no(fresh_session, "EU", 2026)


def test_batch_no_per_day_per_instance(fresh_session):
    """批次按 实例:日 分域；种子 20261020 现值 009 → 续起 010。"""
    b = issuer.next_batch_no(fresh_session, "CN", "20261020")
    assert b == "BT-20261020-010"
    b2 = issuer.next_batch_no(fresh_session, "OS", "20261020")
    assert b2 == "BT-20261020-010"           # 另一实例同日独立计数（演示口径，日最大值播种）
    fresh_day = issuer.next_batch_no(fresh_session, "CN", "20261026")
    assert fresh_day == "BT-20261026-001"    # 新日重置
    assert _pat("批次号").match(b)


def test_gm_rcpt_and_qa_anno(fresh_session):
    assert issuer.next_gm_rcpt(fresh_session) == "gm-rcpt-1043"   # 种子现值 1042（0379 回执）续起
    assert issuer.next_qa_batch(fresh_session, 2026, 42) == "QA-2026-W42-01"
    assert issuer.next_anno_task(fresh_session, 2026) == "ANNO-2026-0001"
    assert _pat("验签回执").match("gm-rcpt-1043")
    assert _pat("抽检批次").match("QA-2026-W42-01")
    assert _pat("标注任务").match("ANNO-2026-0001")


def test_trace_pattern_and_single_source(fresh_session):
    """trace 生成收口 issuer（audit_chain/state_machine/governed 共用）；pattern 自注册表。"""
    from app.services import audit_chain
    t1 = audit_chain.new_trace_id(); t2 = issuer.new_trace_id()
    assert _pat("trace ID").match(t1) and _pat("trace ID").match(t2)
    assert t1 != t2


def test_counters_seeded_idempotent(session_factory, tmp_path):
    """重放装载后计数器回到种子现值（幂等）。"""
    from sqlalchemy import select, create_engine
    from sqlalchemy.orm import sessionmaker
    from app.domain import models as mm
    from app.services.seed_loader import load_all
    eng = create_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    mm.Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    load_all(s)
    d1 = {r.domain: r.seq for r in s.scalars(select(mm.IdCounter))}
    issuer.next_case_no(s, "CN", 2026)
    mm.Base.metadata.drop_all(eng); mm.Base.metadata.create_all(eng)
    s2 = sessionmaker(bind=eng)(); load_all(s2)
    d2 = {r.domain: r.seq for r in s2.scalars(select(mm.IdCounter))}
    assert d1 == d2 and d1["case:CN"] == 387 and d1["case:SG"] == 125 and d1["gm_rcpt"] == 1042
    s.close(); s2.close(); eng.dispose()


# ── 租户上下文：强制注入 + 四隔离 ─────────────────────────────────────────────

def test_tenant_required_everywhere(fresh_session):
    """缺失/非法 instance → E_TENANT_MISSING。"""
    with pytest.raises(CommandError) as ei:
        TenantContext.of(None)
    assert ei.value.code == E_TENANT_MISSING
    with pytest.raises(CommandError):
        TenantContext.of("EU")
    from app.services import case_repository as repo
    with pytest.raises(CommandError):
        repo.aggregate_case(fresh_session, TenantContext.of("CN"), "INV-SG-2026-0125")  # mismatch 另测
    with pytest.raises(CommandError) as ei2:
        repo.aggregate_case(fresh_session, TenantContext.of(None), "INV-CN-2026-0387")
    assert ei2.value.code == E_TENANT_MISSING


def test_tenant_region_and_id_fields():
    cn = TenantContext.of("CN")
    os_ = TenantContext.of("OS")
    assert "境内" in cn.region and "新加坡" in os_.region
    assert cn.tenant_id == "TENANT-CN-LANWU-001"
    assert re.match(get_registry().id_pattern("租户 ID"), os_.tenant_id)
    assert os_.scope().startswith("tenant:")


def test_config_scope_isolation_path(fresh_session):
    """四隔离②配置：tenant scope 读取回落 default；显式覆盖行仅对本 tenant 生效。"""
    from app.domain import models as mm
    from app.services import config_center as cc
    assert cc.get_value(fresh_session, "confidence_threshold_default",
                        scope=TenantContext.of("OS").scope()) == 0.85
    fresh_session.add(mm.ConfigItem(scope=TenantContext.of("CN").scope(),
                                    key="confidence_threshold_default",
                                    value_raw={"value": 0.88}, state="published"))
    fresh_session.commit()
    assert cc.get_value(fresh_session, "confidence_threshold_default",
                        scope=TenantContext.of("CN").scope()) == 0.88
    assert cc.get_value(fresh_session, "confidence_threshold_default",
                        scope=TenantContext.of("OS").scope()) == 0.85


def test_provider_key_region_declaration(fresh_session):
    """四隔离③Provider：providers 种子 regions 声明（CN 境内/海外分离，M4 路由消费）。"""
    from app.domain import models as mm
    bwy = fresh_session.get(mm.Provider, "bwyun-cn")
    assert "CN" in (bwy.provider_raw.get("regions") or [])
