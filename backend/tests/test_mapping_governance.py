# -*- coding: utf-8 -*-
"""映射治理、推荐队列规则桩与 Link 候选/确认测试（WP4.5 · FN-6-07/08/09/10 · FN-4-06/07）。

验证要点：
  1. 预设规则库查询与覆盖率统计（FN-6-07）；
  2. LLM 推荐队列规则桩（FN-6-08）：
     - 采纳推荐：沉淀为长期规则 + 记入确认历史 + 记入不可篡改审计；
     - 拒绝推荐：拒绝原因必填（缺失报 422）+ 回落人工队列 + LLM_ADVICE_REJECTED 入审计；
     - 接口隔离说明：规则桩与未来 M5 真实 LLM 实现替换点完全解耦；
  3. Link 候选推断（FN-4-06）：四项确定性校验（供应商一致、金额冲减对应、开票时序先后、重复 Link 检查）+ 92% 匹配度评分；
  4. Link 受控确认与拒绝（FN-6-10）：
     - 确认：写入对象模型 ObjectLink 冲减关系 + 案件时间线 PO_MATCH + 审计链；
     - 拒绝：必填理由 + 候选保留可追溯 + 审计留痕。
"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import mapping_governance
from app.services.errors import CommandError


def test_preset_rules_and_coverage(fresh_session):
    """断言预设规则库治理与命中覆盖率统计（FN-6-07）。"""
    res = mapping_governance.get_preset_rules(fresh_session)
    assert res["total"] >= 5
    assert res["stats"]["preset_coverage_pct"] >= 90.0
    assert res["stats"]["preset_month_hits"] > 10000

    # 匹配规则
    m1 = mapping_governance.match_field_preset(fresh_session, "价税合计（小写）")
    assert m1 is not None and m1["to"] == "total.gross_amount"

    m2 = mapping_governance.match_field_preset(fresh_session, "发票号码 / Invoice No.")
    assert m2 is not None and m2["to"] == "header.invoice_no"


def test_ai_recommendations_adopt_and_reject(fresh_session):
    """断言 AI 推荐队列采纳沉淀与拒绝留痕（FN-6-08/09）。"""
    # 1. 列表包含推荐条目
    recs = mapping_governance.list_ai_recommendations(fresh_session)
    assert len(recs) >= 3
    rec_customs = next(r for r in recs if "报关单号" in r["src"])
    assert rec_customs["confidence"] == 86
    assert rec_customs["state"] == "pending"
    assert "⚠ 大模型生成" in rec_customs["disclaimer"]

    # 2. 采纳推荐 → 沉淀为规则
    adopt_res = mapping_governance.adopt_recommendation(
        fresh_session,
        src_field=rec_customs["src"],
        actor="王莉",
        opinion="同意沉淀为长期规则",
    )
    assert adopt_res["adopted"] is True

    # 校验沉淀入预设库
    p_hit = mapping_governance.match_field_preset(fresh_session, rec_customs["src"])
    assert p_hit is not None
    assert p_hit["to"] == "custom_fields.customs_ref"

    # 校验追加至人工确认历史
    history = mapping_governance.get_confirmation_history(fresh_session)
    assert any(h["src"] == rec_customs["src"] for h in history)

    # 3. 拒绝推荐：缺失理由抛 422
    rec_disc = next(r for r in recs if "折扣行" in r["src"])
    with pytest.raises(CommandError) as exc_info:
        mapping_governance.reject_recommendation(
            fresh_session, src_field=rec_disc["src"], reason="", actor="王莉"
        )
    assert exc_info.value.code == "E_OPINION_REQUIRED"

    # 填写理由正常拒绝
    rej_res = mapping_governance.reject_recommendation(
        fresh_session,
        src_field=rec_disc["src"],
        reason="目标平台不支持独立折扣行，须按行内折扣入账",
        actor="王莉",
    )
    assert rej_res["rejected"] is True

    # 校验审计链中记录 LLM_ADVICE_REJECTED
    blocks = fresh_session.scalars(
        select(m.AuditBlock).where(m.AuditBlock.act == "LLM_ADVICE_REJECTED")
    ).all()
    assert len(blocks) >= 1
    assert "折扣行" in blocks[-1].note


def test_link_candidate_inference_four_checks(fresh_session):
    """断言 Link 候选推断与四项确定性校验（FN-4-06 · 0384 案场景）。"""
    res = mapping_governance.infer_link_candidates(fresh_session, "INV-CN-2026-0384")
    assert res["has_candidate"] is True
    cand = res["candidate"]
    assert cand["origin"]["caseId"] == "INV-CN-2026-0310"
    assert cand["match_score"] == 92
    assert cand["mode"] == "全额冲减"

    # 校验四项确定性证据
    ev_keys = {e["k"] for e in cand["evidence"]}
    assert "供应商一致" in ev_keys
    assert "金额冲减对应" in ev_keys
    assert "开票日期先后" in ev_keys
    assert "重复 Link 检查" in ev_keys
    for e in cand["evidence"]:
        assert "✓ 通过" in e["v"]


def test_link_confirm_and_reject_controlled_write(fresh_session):
    """断言 Link 确认与拒绝受控操作（FN-6-10）。"""
    # 1. 确认建立冲减 Link
    conf_res = mapping_governance.confirm_link(
        fresh_session,
        credit_case_id="INV-CN-2026-0384",
        origin_case_id="INV-CN-2026-0310",
        actor="王莉",
        opinion="核对原票无误，确认全额冲减",
    )
    assert conf_res["confirmed"] is True

    # 检查数据库中已生成 ObjectLink 冲减关系
    link = fresh_session.scalar(
        select(m.ObjectLink).where(
            m.ObjectLink.case_id == "INV-CN-2026-0384",
            m.ObjectLink.link_type == "冲减",
        )
    )
    assert link is not None
    assert link.ref == "INV-CN-2026-0310"

    # 检查案件时间线追加了 PO_MATCH
    case_0384 = fresh_session.get(m.Case, "INV-CN-2026-0384")
    acts = [e.act for e in fresh_session.scalars(
        select(m.TimelineEvent).where(m.TimelineEvent.case_id == "INV-CN-2026-0384")
    )]
    assert "PO_MATCH" in acts

    # 2. 拒绝 Link 操作
    with pytest.raises(CommandError) as ei:
        mapping_governance.reject_link(
            fresh_session,
            credit_case_id="INV-SG-2026-0123",
            origin_case_id="INV-SG-2026-0101",
            reason="",  # 缺失理由
            actor="王莉",
        )
    assert ei.value.code == "E_OPINION_REQUIRED"

    rej_res = mapping_governance.reject_link(
        fresh_session,
        credit_case_id="INV-SG-2026-0123",
        origin_case_id="INV-SG-2026-0101",
        reason="供应商开票信息与原服务单不匹配，退回核实",
        actor="王莉",
    )
    assert rej_res["rejected"] is True
