# -*- coding: utf-8 -*-
"""M5 审计报表、归档合规与标注沉淀全量测试套件（WP5.3–WP5.4 · FN-5-06~11, FN-8-12~14）。

覆盖内容：
  - FN-5-08 审计日志四维检索过滤 + 统计条聚合 + 链重验 + CSV 导出自审计入链头（blk# 递增断言）+ 24h 限时凭证；
  - FN-8-12 SLA 六链路 P95 + 可用性/吞吐 + §9.2 质量指标表 + 红线 12 周序列；
  - FN-8-14 AI 异常归因建议卡处置（采纳/拒绝留痕）；
  - FN-5-06 归档保留策略实体（10/7/2 年）+ 生命周期清理任务 + 区域驻留；
  - FN-5-10/11 双实例独立成链校验 + 数据最小外发与合规说明导出；
  - FN-5-07 周期抽检任务管理（QA-YYYY-Wnn-NN）+ SHA-256 比对 + 记录入链 + 异常联动冻结自动放行；
  - FN-8-13 错误样本自动回流（真实错误优先）+ ANNO 发号 + 任务四态流转 + 规则转化接入引擎 + 标注不出域开关拦截留痕。
"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import (
    annotation_service,
    archival_service,
    audit_chain,
    audit_service,
    persistence,
    sampling_service,
    sla_reporting_service,
)
from app.services.errors import CommandError


# ───────────────────────── 1. 审计检索与导出 (FN-5-08) ─────────────────────────

def test_search_audit_logs_four_dimensions(api_client):
    """验证审计日志四维检索（时间窗/主体/动作/关键词）与分页。"""
    res = api_client.get("/api/audit/logs?time_range=7d&actor=human&page=1&page_size=20")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert "stats" in data
    assert "pagination" in data
    # 验证主体过滤生效
    for log in data["logs"]:
        assert log["actor"] == "human"


def test_search_audit_stats_aggregation(api_client):
    """验证统计条实时聚合（命中数/Action数/修改数/拦截数/完整性）。"""
    res = api_client.get("/api/audit/logs?time_range=30d")
    assert res.status_code == 200
    stats = res.json()["stats"]
    assert "stat_count" in stats
    assert "stat_action" in stats
    assert "stat_field" in stats
    assert "stat_block" in stats
    assert stats["chain_integrity"] == "100%"


def test_verify_chain_and_record(api_client):
    """重新校验哈希链并登记至 VerifyRun。"""
    res = api_client.post("/api/audit/verify-chain", json={"verifier": "王莉"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["verifier"] == "王莉"
    assert "100%" in data["message"]

    # 验证 DB 记录
    with persistence.get_session() as s:
        vrun = s.scalars(select(m.VerifyRun).order_by(m.VerifyRun.id.desc())).first()
        assert vrun is not None
        assert vrun.verifier == "王莉"
        assert vrun.ok is True


def test_export_audit_csv_self_audit_at_chain_head(api_client):
    """验收标准⑤：CSV 导出自审计入链头（blk# 严格递增断言）+ 24h 限时凭据。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/audit/export", json={
        "actor": "王莉",
        "filters": {"time_range": "7d", "actor": "human"},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["audit_blk"] == old_head + 1  # 链头 blk# 严格递增断言
    assert data["download_url"].startswith("/v1/exports/")
    assert data["token"]
    assert "expires_at" in data

    # 验证自审计事件在链中
    with persistence.get_session() as s:
        blk = s.get(m.AuditBlock, data["audit_blk"])
        assert blk is not None
        assert blk.act == "AUDIT_EXPORT"
        assert "审计日志导出" in blk.note
        assert blk.actor == "human"


# ───────────────────────── 2. SLA 与质量报表 (FN-8-12, FN-8-14) ─────────────────────────

def test_sla_six_links_and_quality_report(api_client):
    """验证 SLA 分链路 P95 六卡、质量指标与 12 周红线趋势序列。"""
    res = api_client.get("/api/audit/sla-quality")
    assert res.status_code == 200
    data = res.json()

    # 1. SLA 六链路
    links = data["sla_links"]["cards"]
    assert len(links) == 6
    link_ids = [l["id"] for l in links]
    assert "xml_ofd_direct" in link_ids
    assert "pdf_text_extraction" in link_ids
    assert "ocr_provider" in link_ids
    assert "sync_form_recognition" in link_ids
    assert "global_dedup" in link_ids
    assert "archival_hash_chain" in link_ids
    assert all(l["status"] == "达标" for l in links)

    # 2. 可用性与吞吐
    avail = data["availability_and_throughput"]["availability"]
    assert avail["current"] >= 99.5
    throughput = data["availability_and_throughput"]["throughput"]
    assert throughput["current"] == 62

    # 3. 质量指标表
    q_table = data["quality_metrics"]["table"]
    assert len(q_table) == 5
    assert all(q["passed"] for q in q_table)

    # 4. 产品红线指标与 12 周序列
    redline = data["redline_indicator"]
    assert redline["current"] <= redline["limit"]  # 0.02% <= 0.05%
    twelve_weeks = redline["twelve_weeks_trend"]
    assert len(twelve_weeks) == 12
    # 趋近 0 趋势
    assert twelve_weeks[-1]["rate"] <= twelve_weeks[0]["rate"]


def test_handle_attribution_advice(api_client):
    """测试处置 AI 异常归因建议（采纳转发布/拒绝留痕）。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/audit/attribution", json={
        "actor": "陈铮",
        "action": "adopt",
        "opinion": "采纳重复票前移建议",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "adopted"
    assert data["audit_blk"] > old_head


# ───────────────────────── 3. 归档与保留策略 (FN-5-06, 10, 11) ─────────────────────────

def test_archival_policies_and_dual_instance_chains(api_client):
    """验证归档保留策略实体（10/7/2年）与双实例独立成链。"""
    res = api_client.get("/api/audit/archival")
    assert res.status_code == 200
    data = res.json()
    assert data["stats"]["total_archived"] == 128462
    assert data["stats"]["structured_ratio_pct"] == 71.6

    policies = data["policies"]
    assert len(policies) == 6
    # 验证 10/7/2 年梯度
    p_map = {p["type_id"]: p["retention_years"] for p in policies}
    assert p_map["xml_original"] == 10
    assert p_map["ofd_original"] == 10
    assert p_map["pdf_presentation"] == 7
    assert p_map["image_scan"] == 7
    assert p_map["intermediate_results"] == 2
    assert p_map["audit_log_evidence"] == 10

    # 验证双实例独立成链
    chains_res = api_client.get("/api/audit/archival/verify-dual-chains")
    assert chains_res.status_code == 200
    cdata = chains_res.json()
    assert cdata["verified"] is True
    assert cdata["chains"]["CN"]["intact"] is True
    assert cdata["chains"]["OS"]["intact"] is True


def test_archival_lifecycle_cleanup_and_export(api_client):
    """生命周期清理任务与合规说明导出。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    # 1. 清理满 2 年中间结果
    clean_res = api_client.post("/api/audit/archival/cleanup", json={"actor": "陈铮"})
    assert clean_res.status_code == 200
    assert clean_res.json()["cleaned_count"] > 0
    assert clean_res.json()["audit_blk"] > old_head

    # 2. 导出合规说明
    exp_res = api_client.post("/api/audit/archival/export-compliance", json={"actor": "王莉"})
    assert exp_res.status_code == 200
    assert exp_res.json()["exported"] is True
    assert exp_res.json()["audit_blk"] > clean_res.json()["audit_blk"]


# ───────────────────────── 4. 周期抽检任务与异常联动 (FN-5-07) ─────────────────────────

def test_sampling_records_and_run(api_client):
    """周期抽检任务管理（QA-YYYY-Wnn-NN 发号 + 记录入链）。"""
    # 1. 列表
    res = api_client.get("/api/audit/sampling")
    assert res.status_code == 200
    records = res.json()["records"]
    assert len(records) >= 3
    assert any(r["batch_no"].startswith("QA-") for r in records)

    # 2. 执行新一轮抽检
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    run_res = api_client.post("/api/audit/sampling/run", json={
        "actor": "王莉",
        "target_scope": "CN_XML",
        "sample_size": 500,
    })
    assert run_res.status_code == 200
    rdata = run_res.json()
    assert rdata["batch_no"].startswith("QA-")
    assert rdata["passed"] is True
    assert rdata["audit_blk"] > old_head


def test_sampling_anomaly_freezes_auto_release(api_client):
    """抽检异常联动：高风险告警并联动冻结自动放行。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/audit/sampling/anomaly", json={
        "actor": "王莉",
        "batch_no": "QA-2026-W43-01",
        "anomaly_reason": "抽检发现 1 份原件 SHA-256 摘要与登记不符",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["auto_release_frozen"] is True
    assert data["audit_blk"] > old_head


# ───────────────────────── 5. 标注与数据沉淀 (FN-8-13) ─────────────────────────

def test_annotation_dashboard_and_reflux(api_client):
    """标注面板统计与错误样本自动回流（真实错误优先）。"""
    # 1. 面板指标
    res = api_client.get("/api/platform/annotation")
    assert res.status_code == 200
    data = res.json()
    assert data["stats"]["monthly_samples"] == 1284
    assert data["stats"]["inter_rater_agreement_pct"] == 97.2
    assert data["stats"]["sedimented_rules_count"] == 46
    assert data["data_stay_in_domain"] is True

    # 2. 回流人工修正真实错误样本 -> 优先级 1（置于队首）
    ref_res = api_client.post("/api/platform/annotation/reflux", json={
        "case_id": "INV-CN-2026-0388",
        "error_type": "FIELD_EDITED",
        "detail": "价税合计金额手工修正",
    })
    assert ref_res.status_code == 200
    rdata = ref_res.json()
    assert rdata["sample"]["priority"] == 1
    assert "真实错误" in rdata["sample"]["priority_label"]


def test_annotation_task_lifecycle_four_states(api_client):
    """标注任务管理与四态流转（排队中/标注中/三审仲裁/已完成已沉淀）。"""
    # 1. 创建任务
    create_res = api_client.post("/api/platform/annotation/tasks", json={
        "actor": "陈铮",
        "doc_type": "海外 Credit Note",
        "samples_count": 50,
        "annotator": "标注二组",
    })
    assert create_res.status_code == 200
    task_id = create_res.json()["task_id"]
    assert task_id.startswith("ANNO-")
    assert create_res.json()["task"]["status"] == "排队中"

    # 2. 流转至「标注中」
    s1 = api_client.post(f"/api/platform/annotation/tasks/{task_id}/status", json={
        "actor": "陈铮",
        "new_status": "标注中",
        "progress_pct": 30,
    })
    assert s1.status_code == 200
    assert s1.json()["new_status"] == "标注中"

    # 3. 流转至「三审仲裁」
    s2 = api_client.post(f"/api/platform/annotation/tasks/{task_id}/status", json={
        "actor": "陈铮",
        "new_status": "三审仲裁",
        "progress_pct": 80,
    })
    assert s2.status_code == 200
    assert s2.json()["new_status"] == "三审仲裁"

    # 4. 流转至「已完成已沉淀」
    s3 = api_client.post(f"/api/platform/annotation/tasks/{task_id}/status", json={
        "actor": "陈铮",
        "new_status": "已完成已沉淀",
    })
    assert s3.status_code == 200
    assert s3.json()["new_status"] == "已完成已沉淀"
    assert s3.json()["progress_pct"] == 100


def test_convert_annotation_to_rule(api_client):
    """沉淀规则转化：人工修正 → 规则引擎条款（版本化 + 写入 rule_catalog + 审计）。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    rule_id = "anno_vat_tail_reconcile_v1"
    res = api_client.post("/api/platform/annotation/rules/convert", json={
        "actor": "陈铮",
        "rule_id": rule_id,
        "usage": "针对特定扫描版专票的尾差自动宽容条款",
        "ref_version": "v1.1",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["rule_id"] == rule_id
    assert data["audit_blk"] > old_head

    # 验证规则已接入 rule_catalog
    with persistence.get_session() as s:
        entry = s.get(m.RuleCatalogEntry, rule_id)
        assert entry is not None
        assert entry.ref_version == "v1.1"


def test_data_stay_in_domain_toggle_blocked(api_client):
    """合规硬约束：「标注数据不出客户控制域」开关关闭被系统强制拦截，开关回弹且留痕。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/platform/annotation/data-stay/toggle", json={
        "actor": "陈铮",
        "new_state": False,  # 尝试关闭开关
    })
    # 期望 403 拦截
    assert res.status_code == 403
    assert "合规硬约束" in res.json()["detail"]
    assert "禁止关闭" in res.json()["detail"]

    # 验证审计留痕
    with persistence.get_session() as s:
        new_head = audit_chain.head_blk(s)
        assert new_head > old_head
        blk = s.get(m.AuditBlock, new_head)
        assert "【合规硬约束拦截】" in blk.note
        assert blk.op_component == "platform-admin/data-compliance-guard"

    # 验证开关保持开启（回弹）
    overview = api_client.get("/api/platform/annotation").json()
    assert overview["data_stay_in_domain"] is True
