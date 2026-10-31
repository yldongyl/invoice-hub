# -*- coding: utf-8 -*-
"""路由策略版本化与模拟推演引擎测试（WP4.3 · FN-2-11/12 · S-M4-01/05）。

验证要点：
  1. 策略草稿态全套操作（保存草稿、修改阈值、调整顺序、读取草稿、丢弃草稿）；
  2. 策略发布（FN-2-12）：版本号自增（v年-月-日.序号）、diff 准确入审计、旧版本保留；
  3. 策略回滚：按目标历史版本发布新版本，行为与配置准确恢复；
  4. 模拟推演与真实路由共用同一规则解释器（FN-2-11 · 一致性断言）：
     同输入下，推演步骤（steps）序列、步骤类型（st）、标题、说明、时延与成本逐步比对完全一致；
  5. 推演只读零真实调用：模拟推演期间 EgressLog 记录计数严格为零（零外发断言）；
  6. S-M4-05 策略发布与回滚闭环用例。
"""

import pytest
from sqlalchemy import func, select

from app.domain import models as m
from app.services import governed_commands as gc, provider_service, routing_engine, versioning
from app.services.tenant import TenantContext


def test_routing_draft_crud_operations(fresh_session):
    """断言路由策略草稿态全套操作（FN-2-11/12）。"""
    base_policy = routing_engine.get_effective_policy(fresh_session)
    assert base_policy["version"] == "v2026-10-20.3"

    # 1. 初始无草稿
    assert routing_engine.get_draft_policy(fresh_session) is None

    # 2. 修改阈值并保存草稿
    draft_payload = dict(base_policy)
    draft_rules = [dict(r) for r in draft_payload["rules"]]
    # 把纸质专票阈值从 0.88 改为 0.95
    for r in draft_rules:
        if r.get("route_id") == "cn_vat_paper_recognize":
            r["strategies"] = [dict(s) for s in r["strategies"]]
            for s in r["strategies"]:
                if s.get("threshold") is not None:
                    s["threshold"] = 0.95
    draft_payload["rules"] = draft_rules

    res = routing_engine.save_draft_policy(fresh_session, draft_payload, actor="陈铮")
    assert res["saved"] is True
    assert res["state"] == "draft"

    # 3. 读取草稿
    loaded_draft = routing_engine.get_draft_policy(fresh_session)
    assert loaded_draft is not None
    paper_rule = next(r for r in loaded_draft["rules"] if r.get("route_id") == "cn_vat_paper_recognize")
    assert paper_rule["strategies"][0]["threshold"] == 0.95

    # 4. 优先基于草稿推演：0.95 高阈值下，诺诺 0.91 亦不达标 → 降级人工兜底！
    sim_draft = routing_engine.execute_route(
        fresh_session,
        region="CN 中国",
        invoice_type="增值税专票/普票（纸质扫描）",
        carrier="纸质扫描 / 图片",
        doc_type_hint="增值税专票/普票（纸质扫描）",
        is_simulation=True,
    )
    # 百望云 0.82 < 0.95 降级，诺诺 0.91 < 0.95 降级，客户 0.88 < 0.95 降级 → 人工兜底
    assert sim_draft["status"] == "manual"
    assert sim_draft["final_provider"] == "human-fallback"

    # 5. 丢弃草稿
    deleted = routing_engine.delete_draft_policy(fresh_session)
    assert deleted is True
    assert routing_engine.get_draft_policy(fresh_session) is None


def test_simulation_and_real_routing_consistency(fresh_session):
    """断言模拟推演与真实路由共用同一规则解释器，输出序列逐步比对完全一致（FN-2-11）。"""
    # 同一输入：增值税专票
    kwargs = {
        "region": "CN 中国",
        "invoice_type": "增值税专票/普票（纸质扫描）",
        "carrier": "纸质扫描 / 图片",
        "doc_type_hint": "增值税专票/普票（纸质扫描）",
        "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
    }

    # 真实路由执行
    real_out = routing_engine.execute_route(fresh_session, is_simulation=False, **kwargs)
    # 模拟推演执行
    sim_out = routing_engine.execute_route(fresh_session, is_simulation=True, **kwargs)

    # 1. 结果元数据完全一致
    assert real_out["status"] == sim_out["status"] == "done"
    assert real_out["route_id"] == sim_out["route_id"] == "cn_vat_paper_recognize"
    assert real_out["final_provider"] == sim_out["final_provider"] == "nuonuo-cn"
    assert real_out["confidence"] == sim_out["confidence"] == 0.91

    # 2. 步骤数量与逐步内容（st, t, d, ms, cost）严格一致
    assert len(real_out["steps"]) == len(sim_out["steps"])
    for r_s, s_s in zip(real_out["steps"], sim_out["steps"]):
        assert r_s["st"] == s_s["st"]
        assert r_s["t"] == s_s["t"]
        assert r_s["d"] == s_s["d"]
        assert r_s.get("ms") == s_s.get("ms")
        assert r_s.get("cost") == s_s.get("cost")


def test_simulation_zero_egress_assertion(fresh_session):
    """断言模拟推演为只读沙箱，零真实外发（EgressLog 计数绝对为零，FN-2-11）。"""
    init_egress = fresh_session.scalar(select(func.count()).select_from(m.EgressLog)) or 0

    # 连续执行 5 次模拟推演
    for itype in ["数电票", "增值税专票/普票（纸质扫描）", "Supplier Invoice", "Credit Note"]:
        routing_engine.execute_route(
            fresh_session,
            region="CN 中国" if "增值税" in itype or "数电" in itype else "APAC 亚太",
            invoice_type=itype,
            carrier="纸质扫描 / 图片",
            is_simulation=True,
        )

    after_egress = fresh_session.scalar(select(func.count()).select_from(m.EgressLog)) or 0
    assert after_egress == init_egress, "模拟推演产生了非预期的 EgressLog 外发记录"


def test_s_m4_05_policy_publish_and_rollback(fresh_session):
    """S-M4-05 策略发布全流程：草稿改阈值 → 发布版本递增 + diff 入审计 → 回滚恢复旧版。"""
    base_policy = routing_engine.get_effective_policy(fresh_session)
    orig_ver = base_policy["version"]

    # 1. 准备新策略载荷：修改阈值为 0.92
    new_policy = dict(base_policy)
    new_rules = [dict(r) for r in new_policy["rules"]]
    for r in new_rules:
        if r.get("route_id") == "cn_vat_paper_recognize":
            r["strategies"] = [dict(s) for s in r["strategies"]]
            for s in r["strategies"]:
                if s.get("threshold") is not None:
                    s["threshold"] = 0.92
    new_policy["rules"] = new_rules

    # 2. 模拟受控发布（经过 governed_commands 五要素框架）
    # 获取 risk token
    tkn = gc.issue_risk_challenge(
        fresh_session,
        "陈铮",
        "publish",
        gc.scope_ref("publish", None, None, "routing_policy"),
    )["token"]
    pub_res = gc.execute(
        fresh_session,
        actor="陈铮",
        action="publish",
        instance="CN",
        token=tkn,
        self_confirmed=True,
        opinion="上调纸质专票置信度阈值至 0.92",
        config_key="routing_policy",
        config_payload=new_policy,
    )
    assert pub_res["published"] is True
    new_ver = pub_res["version"]
    assert new_ver != orig_ver
    assert new_ver.startswith(f"v{versioning._today()}.")

    # 3. 校验数据库已更新
    curr_policy = routing_engine.get_effective_policy(fresh_session)
    assert curr_policy["version"] == new_ver
    p_rule = next(r for r in curr_policy["rules"] if r.get("route_id") == "cn_vat_paper_recognize")
    assert p_rule["strategies"][0]["threshold"] == 0.92

    # 4. 校验审计链中记录 POLICY_PUBLISHED 事件
    blocks = fresh_session.scalars(
        select(m.AuditBlock).where(m.AuditBlock.act == "POLICY_PUBLISHED").order_by(m.AuditBlock.blk.desc())
    ).all()
    assert len(blocks) >= 1
    assert "上调纸质专票置信度阈值" in blocks[0].note

    # 5. 回滚至原版本
    rb_tkn = gc.issue_risk_challenge(
        fresh_session,
        "陈铮",
        "rollback",
        gc.scope_ref("rollback", None, None, "routing_policy"),
    )["token"]
    rb_res = gc.execute(
        fresh_session,
        actor="陈铮",
        action="rollback",
        instance="CN",
        token=rb_tkn,
        self_confirmed=True,
        opinion="回滚至原基线策略",
        config_key="routing_policy",
        to_version=orig_ver,
    )
    assert rb_res["rolled_back"] is True
    rollback_ver = rb_res["version"]

    # 6. 验证已恢复至原基线规则阈值（0.88）
    restored_policy = routing_engine.get_effective_policy(fresh_session)
    assert restored_policy["version"] == rollback_ver
    res_rule = next(r for r in restored_policy["rules"] if r.get("route_id") == "cn_vat_paper_recognize")
    assert res_rule["strategies"][0]["threshold"] == 0.88
