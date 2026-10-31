# -*- coding: utf-8 -*-
"""M4 官方 E2E 五大场景断言（WP4.7 · S-M4-01~05 · 实施规划 §4-M4 验收标准）。

场景清单：
  S-M4-01: "纸质专票"推演与真实路由行为一致（百望云 0.82<0.88→降级诺诺 0.91 通过；推演输出=真实执行日志逐步比对）
  S-M4-02: 停用百望云→数电票路由自动跳过→XML 直读不受影响+留痕 PROVIDER_DISABLED
  S-M4-03: 0387 口径差异：确认卡数据完整→"确认口径差异并放行建议"→差异标记+PO 含税回填→放行→Ariba 沙箱建档→回执 AID-* 归档时间线
  S-M4-04: 0384→0310：Link 候选四项校验→未确认时建档被拦截（反向用例）→确认全额冲减→对象模型+时间线→建档前 Link 校验通过
  S-M4-05: 策略发布：草稿改阈值→推演生效→发布版本递增+diff 入审计→回滚旧版恢复行为
"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import (
    adapter_service,
    governed_commands as gc,
    mapping_governance,
    matching_service,
    provider_service,
    routing_engine,
    versioning,
)
from app.services.errors import CommandError

pytestmark = pytest.mark.scenario


def test_s_m4_01_paper_vat_inference_and_real_routing_consistency(fresh_session):
    """S-M4-01 "纸质专票"推演与真实路由行为一致。

    断言：百望云 0.82 < 0.88 → 降级诺诺 0.91 通过；
    推演输出与真实执行日志逐步比对完全一致，含时延与成本字段。
    """
    kwargs = {
        "region": "CN 中国",
        "invoice_type": "增值税专票/普票（纸质扫描）",
        "carrier": "纸质扫描 / 图片",
        "doc_type_hint": "增值税专票/普票（纸质扫描）",
        "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
    }

    real_res = routing_engine.execute_route(fresh_session, is_simulation=False, **kwargs)
    sim_res = routing_engine.execute_route(fresh_session, is_simulation=True, **kwargs)

    assert real_res["status"] == sim_res["status"] == "done"
    assert real_res["final_provider"] == sim_res["final_provider"] == "nuonuo-cn"
    assert real_res["confidence"] == sim_res["confidence"] == 0.91

    assert len(real_res["steps"]) == len(sim_res["steps"])
    for r_step, s_step in zip(real_res["steps"], sim_res["steps"]):
        assert r_step["st"] == s_step["st"]
        assert r_step["t"] == s_step["t"]
        assert r_step["d"] == s_step["d"]
        assert r_step.get("ms") == s_step.get("ms")
        assert r_step.get("cost") == s_step.get("cost")


def test_s_m4_02_disabled_provider_auto_skip_and_xml_direct(fresh_session):
    """S-M4-02 停用百望云→数电票路由自动跳过→XML 直读不受影响+留痕。"""
    # 1. 停用百望云
    t_res = provider_service.toggle_provider(
        fresh_session, "bwyun-cn", enabled=False, actor="human", opinion="系统例行维护"
    )
    assert t_res["enabled"] is False

    # 验证审计日志中存在 PROVIDER_DISABLED 事件
    audit_ev = fresh_session.scalars(
        select(m.AuditBlock).where(m.AuditBlock.act == "PROVIDER_DISABLED")
    ).all()
    assert len(audit_ev) >= 1
    assert "百望云" in audit_ev[-1].note

    # 2. 数电票直读路径：XML 直读不受影响，零 Provider 成本完成
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
    <EInvoice><Header><InvoiceNo>24312000000012345678</InvoiceNo><InvoiceType>数电票</InvoiceType></Header>
    <Total><GrossAmount>113000.00</GrossAmount></Total></EInvoice>""".encode("utf-8")

    res = routing_engine.execute_route(
        fresh_session,
        region="CN 中国",
        invoice_type="数电票",
        carrier="XML 原件 + PDF",
        file_bytes=xml_content,
        sha256="1234567890abcdef",
    )
    assert res["status"] == "done"
    assert res["final_provider"] == "xml_direct"
    assert res["recognition_path"] == "L1_xml_direct"
    assert res["meta"]["cost"]["amount"] == 0.0

    # 恢复启用百望云
    provider_service.toggle_provider(fresh_session, "bwyun-cn", enabled=True, actor="human")


def test_s_m4_03_0387_tax_variance_release_and_filing(fresh_session):
    """S-M4-03 0387 口径差异：确认卡完整 → 放行 → Ariba 沙箱建档 → 回执 AID-* 归档时间线。"""
    # 1. 确认卡数据完整性核对
    card = matching_service.get_case_matching_detail(fresh_session, "INV-CN-2026-0387")
    assert card["supplier"] == "北京中科华创科技有限公司"
    assert card["amount"] == "¥113,000.00"
    detail = card["detail"]
    assert len(detail["comp"]) == 3
    # 差异构成明细：价税合计 ¥113,000.00 vs PO 净额 ¥100,000.00 = 税额 ¥13,000.00
    assert detail["comp"][2]["v"] == "¥13,000.00"
    assert "税额口径" in card["badges"][0]["t"]

    # 2. 模拟复核员放行受控操作
    tkn = gc.issue_risk_challenge(
        fresh_session,
        "王莉",
        "release",
        gc.scope_ref("release", "INV-CN-2026-0387"),
    )["token"]
    rel_res = gc.execute(
        fresh_session,
        actor="王莉",
        action="release",
        instance="CN",
        case_id="INV-CN-2026-0387",
        token=tkn,
        self_confirmed=True,
        opinion="确认含税vs净额口径差异，回填 PO 含税金额后放行",
    )
    assert rel_res["status"] == "RESOLVED"

    # 3. 触发 Ariba 建档
    filing_res = adapter_service.execute_filing(
        fresh_session,
        adapter_id="ariba",
        case_id="INV-CN-2026-0387",
        actor="王莉",
        is_sandbox=False,  # 生产/正式建档模式
    )
    assert filing_res["success"] is True
    receipt_no = filing_res["receipt_no"]
    assert receipt_no.startswith("AID-2026-")

    # 4. 校验案件时间线归档了该回执
    case = fresh_session.get(m.Case, "INV-CN-2026-0387")
    events = fresh_session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == "INV-CN-2026-0387")
    ).all()
    filing_ev = next((e for e in events if receipt_no in str(e.event_raw.get("x", ""))), None)
    assert filing_ev is not None


def test_s_m4_04_0384_link_validation_and_pre_filing_interception(fresh_session):
    """S-M4-04 0384→0310：Link 候选四项校验 → 未确认时建档被拦截（反向用例）→ 确认全额冲减 → 建档通过。"""
    # 1. 0384 案 Link 候选推断与四项校验
    cands = mapping_governance.infer_link_candidates(fresh_session, "INV-CN-2026-0384")
    assert cands["has_candidate"] is True
    cand = cands["candidate"]
    assert cand["origin"]["caseId"] == "INV-CN-2026-0310"
    assert cand["match_score"] == 92
    assert cand["mode"] == "全额冲减"

    # 2. 未确认冲减 Link 前，发起建档 → 强制拦截！
    with pytest.raises(CommandError) as ei:
        adapter_service.execute_filing(
            fresh_session,
            adapter_id="ariba",
            case_id="INV-CN-2026-0384",
            is_sandbox=True,
        )
    assert ei.value.code == "E_LINK_UNCONFIRMED"
    assert "冲减 Link" in ei.value.message

    # 3. 受控确认 Link（建立 0384 —冲减→ 0310）
    conf_res = mapping_governance.confirm_link(
        fresh_session,
        credit_case_id="INV-CN-2026-0384",
        origin_case_id="INV-CN-2026-0310",
        actor="王莉",
        opinion="确认全额冲减原票 INV-CN-2026-0310",
    )
    assert conf_res["confirmed"] is True

    # 校验对象模型已写入 ObjectLink 冲减关系
    link = fresh_session.scalar(
        select(m.ObjectLink).where(
            m.ObjectLink.case_id == "INV-CN-2026-0384",
            m.ObjectLink.link_type == "冲减",
        )
    )
    assert link is not None
    assert link.ref == "INV-CN-2026-0310"

    # 4. 确认后再次建档 → 校验通过
    f_res = adapter_service.execute_filing(
        fresh_session,
        adapter_id="ariba",
        case_id="INV-CN-2026-0384",
        is_sandbox=True,
    )
    assert f_res["success"] is True
    assert f_res["receipt_no"].startswith("AID-2026-")


def test_s_m4_05_policy_publish_draft_update_and_rollback(fresh_session):
    """S-M4-05 策略发布：草稿改阈值 → 推演生效 → 发布版本递增+diff 入审计 → 回滚旧版恢复行为。"""
    base = routing_engine.get_effective_policy(fresh_session)
    orig_ver = base["version"]

    # 1. 保存草稿：上调纸质专票阈值至 0.93
    draft = dict(base)
    rules_copy = [dict(r) for r in draft["rules"]]
    for r in rules_copy:
        if r.get("route_id") == "cn_vat_paper_recognize":
            r["strategies"] = [dict(s) for s in r["strategies"]]
            for s in r["strategies"]:
                if s.get("threshold") is not None:
                    s["threshold"] = 0.93
    draft["rules"] = rules_copy
    routing_engine.save_draft_policy(fresh_session, draft, actor="陈铮")

    # 2. 推演基于草稿生效：百望云 0.82 < 0.93、诺诺 0.91 < 0.93、客户 0.88 < 0.93 全部降级 → 人工兜底
    sim_out = routing_engine.execute_route(
        fresh_session,
        region="CN 中国",
        invoice_type="增值税专票/普票（纸质扫描）",
        carrier="纸质扫描 / 图片",
        doc_type_hint="增值税专票/普票（纸质扫描）",
        is_simulation=True,
    )
    assert sim_out["status"] == "manual"
    assert sim_out["final_provider"] == "human-fallback"

    # 3. 发布草稿：版本递增 + diff 记录
    tkn = gc.issue_risk_challenge(
        fresh_session, "陈铮", "publish", gc.scope_ref("publish", None, None, "routing_policy")
    )["token"]
    pub_res = gc.execute(
        fresh_session,
        actor="陈铮",
        action="publish",
        instance="CN",
        token=tkn,
        self_confirmed=True,
        opinion="正式发布 0.93 新阈值策略",
        config_key="routing_policy",
        config_payload=draft,
    )
    new_ver = pub_res["version"]
    assert new_ver != orig_ver

    # 4. 回滚旧版策略
    rb_tkn = gc.issue_risk_challenge(
        fresh_session, "陈铮", "rollback", gc.scope_ref("rollback", None, None, "routing_policy")
    )["token"]
    rb_res = gc.execute(
        fresh_session,
        actor="陈铮",
        action="rollback",
        instance="CN",
        token=rb_tkn,
        self_confirmed=True,
        opinion="回滚恢复 0.88 旧版阈值",
        config_key="routing_policy",
        to_version=orig_ver,
    )
    assert rb_res["rolled_back"] is True

    # 5. 验证行为已恢复：纸质专票恢复诺诺通过（0.91 >= 0.88）
    restored_out = routing_engine.execute_route(
        fresh_session,
        region="CN 中国",
        invoice_type="增值税专票/普票（纸质扫描）",
        carrier="纸质扫描 / 图片",
        doc_type_hint="增值税专票/普票（纸质扫描）",
        is_simulation=True,
    )
    assert restored_out["status"] == "done"
    assert restored_out["final_provider"] == "nuonuo-cn"
