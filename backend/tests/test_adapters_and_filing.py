# -*- coding: utf-8 -*-
"""Adapter 适配层与沙箱建档五步链路测试（WP4.6 · FN-7-01~08/11 · S-M4-03/04）。

验证要点：
  1. 6 个目标系统 Adapter 注册档案（Ariba, Oracle, 自研, Data Lake 为 live，Coupa 为 wip，S4 为 plan）；
  2. 字段映射模板服务（v1.4 版本化，来源三分类：preset, manual, ai）；
  3. 建档前 Link 强制校验（FN-0-04 / S-M4-04 反向用例）：
     - 未确认 Link 的红字票建档被强制拦截（报 409 E_LINK_UNCONFIRMED）；
     - 确认冲减 Link 后建档顺利通过；
  4. BLOCKED 拦截案件建档挂起（报 409 E_STATE_PRECONDITION）；
  5. 建档五步链路（Schema 校验 → 报文组装 → 签名 → 发送 → 回执归档）；
  6. 沙箱测试建档（FN-7-08）：不写回案件状态、生成测试标记回执（如 AID-2026-*）、操作入审计；
  7. Oracle、自研应付、Data Lake 沙箱测试建档及回执格式断言；
  8. 回执与失败重试队列数据结构校验。
"""

import pytest

from app.domain import models as m
from app.services import adapter_service, mapping_governance
from app.services.errors import CommandError


def test_list_adapters_and_plan_panels(fresh_session):
    """断言 6 个 Adapter 档案与计划面板数据（FN-7-01）。"""
    adapters = adapter_service.list_adapters(fresh_session)
    assert len(adapters) == 6
    a_map = {a["id"]: a for a in adapters}

    # live 适配器
    assert a_map["ariba"]["status"] == "live"
    assert a_map["oracle"]["status"] == "live"
    assert a_map["custom"]["status"] == "live"
    assert a_map["datalake"]["status"] == "live"

    # 计划面板适配器
    coupa = a_map["coupa"]
    assert coupa["status"] == "wip"
    assert coupa["plan"]["progress_pct"] == 60
    assert len(coupa["plan"]["items"]) == 4

    s4 = a_map["s4"]
    assert s4["status"] == "plan"
    assert s4["plan"]["eta"] == "2027-Q1"


def test_mapping_templates_v14(fresh_session):
    """断言字段映射模板服务（FN-7-03 · v1.4 版本化）。"""
    tpl_ariba = adapter_service.get_mapping_template("ariba")
    assert tpl_ariba["version"] == "v1.4"
    assert "cXML" in tpl_ariba["target"]
    assert len(tpl_ariba["rows"]) >= 8

    # 包含三类来源治理（预设/人工/AI）
    classes = {r["class"] for r in tpl_ariba["rows"]}
    assert "preset" in classes
    assert "manual" in classes
    assert "ai" in classes

    # Oracle 模板
    tpl_oracle = adapter_service.get_mapping_template("oracle")
    assert tpl_oracle["version"] == "v1.4"


def test_s_m4_04_pre_filing_link_validation_reverse_and_pass(fresh_session):
    """S-M4-04 核心用例：未确认冲减 Link 建档被拦截（反向用例）→ 确认 Link 后建档通过。"""
    # 0384 案为红字票，初始未确认 Link
    # 1. 未确认 Link 直接建档 → 强制拦截！
    with pytest.raises(CommandError) as exc_info:
        adapter_service.execute_filing(
            fresh_session,
            adapter_id="ariba",
            case_id="INV-CN-2026-0384",
            is_sandbox=True,
        )
    err = exc_info.value
    assert err.code == "E_LINK_UNCONFIRMED"
    assert "尚未建立/确认冲减 Link" in err.message
    assert err.http == 409

    # 2. 确认冲减 Link（关联 INV-CN-2026-0310）
    mapping_governance.confirm_link(
        fresh_session,
        credit_case_id="INV-CN-2026-0384",
        origin_case_id="INV-CN-2026-0310",
        actor="王莉",
        opinion="全额冲减原票无误，确认建立 Link",
    )

    # 3. 再次发起沙箱建档 → 校验通过并成功生成回执！
    filing_res = adapter_service.execute_filing(
        fresh_session,
        adapter_id="ariba",
        case_id="INV-CN-2026-0384",
        is_sandbox=True,
    )
    assert filing_res["success"] is True
    assert filing_res["receipt_no"].startswith("AID-2026-")
    assert len(filing_res["steps"]) == 5


def test_filing_five_step_chain_and_sandbox_no_status_mutation(fresh_session):
    """断言建档五步链路执行与沙箱模式不写回案件状态（FN-7-04/08）。"""
    case_0387 = fresh_session.get(m.Case, "INV-CN-2026-0387")
    init_status = case_0387.status
    assert init_status == "NEEDS_REVIEW"

    # 执行 Ariba 沙箱测试建档
    res = adapter_service.execute_filing(
        fresh_session,
        adapter_id="ariba",
        case_id="INV-CN-2026-0387",
        is_sandbox=True,
    )
    assert res["success"] is True
    assert res["is_sandbox"] is True
    assert res["receipt_no"].startswith("AID-2026-")

    # 校验五步全部完成
    step_titles = [s["t"] for s in res["steps"]]
    assert step_titles == ["Schema 校验", "报文组装", "签名", "发送", "回执归档"]
    assert all(s["ok"] for s in res["steps"])

    # 关键断言：沙箱建档不修改案件状态！
    fresh_session.refresh(case_0387)
    assert case_0387.status == init_status == "NEEDS_REVIEW"


def test_oracle_custom_datalake_filing(fresh_session):
    """断言 Oracle / 自研系统 / Data Lake 建档及回执格式（FN-7-04/08）。"""
    # 1. Oracle AP Invoice Import
    res_ora = adapter_service.execute_filing(
        fresh_session, adapter_id="oracle", case_id="INV-CN-2026-0387", is_sandbox=True
    )
    assert res_ora["success"] is True
    assert res_ora["receipt_no"].startswith("302455")

    # 2. 自研应付系统
    res_custom = adapter_service.execute_filing(
        fresh_session, adapter_id="custom", case_id="INV-CN-2026-0387", is_sandbox=True
    )
    assert res_custom["success"] is True
    assert res_custom["receipt_no"].startswith("AP-2026-")

    # 3. Data Lake 快照
    res_dl = adapter_service.execute_filing(
        fresh_session, adapter_id="datalake", case_id="INV-CN-2026-0387", is_sandbox=True
    )
    assert res_dl["success"] is True
    assert res_dl["receipt_no"].startswith("DL-2026-")


def test_blocked_case_filing_prevented(fresh_session):
    """断言 BLOCKED 案件建档被挂起并拦截（红线）。"""
    # 将一个案件临时设为 BLOCKED
    c = fresh_session.get(m.Case, "INV-CN-2026-0379")
    c.status = "BLOCKED"
    fresh_session.commit()

    with pytest.raises(CommandError) as ei:
        adapter_service.execute_filing(
            fresh_session, adapter_id="ariba", case_id="INV-CN-2026-0379", is_sandbox=True
        )
    assert ei.value.code == "E_STATE_PRECONDITION"
    assert "处于 BLOCKED 拦截状态" in ei.value.message


def test_adapter_queue_and_api(api_client):
    """断言 Adapter REST API 端点与重试队列。"""
    # 1. 列表
    r_list = api_client.get("/v1/adapters")
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 6

    # 2. Ariba 队列
    r_q = api_client.get("/v1/adapters/ariba/queue")
    assert r_q.status_code == 200
    assert r_q.json()["total"] >= 2

    # 3. 映射模板
    r_map = api_client.get("/v1/adapters/ariba/mapping")
    assert r_map.status_code == 200
    assert r_map.json()["version"] == "v1.4"

    # 4. 测试建档
    r_file = api_client.post(
        "/v1/adapters/ariba/file",
        json={"case_id": "INV-CN-2026-0387", "is_sandbox": True},
    )
    assert r_file.status_code == 200
    assert r_file.json()["success"] is True
    assert "AID-2026-" in r_file.json()["receipt_no"]


def test_investigating_case_filing_prevented(fresh_session):
    """[FN-7-04 / P08 最小集] 断言 INVESTIGATING 待调查案件建档被挂起并拦截。"""
    c = fresh_session.get(m.Case, "INV-CN-2026-0387")
    c.status = "INVESTIGATING"
    fresh_session.commit()

    with pytest.raises(CommandError) as ei:
        adapter_service.execute_filing(
            fresh_session, adapter_id="ariba", case_id="INV-CN-2026-0387", is_sandbox=False
        )
    assert ei.value.code == "E_STATE_PRECONDITION"
    assert "处于 INVESTIGATING 状态" in ei.value.message


def test_filing_idempotency_no_duplicate_submission(fresh_session):
    """[FN-7-04 / CON-06 / P08 最小集] 幂等重发不重复建档：已建档案件直接返回既有回执。"""
    c = fresh_session.get(m.Case, "INV-CN-2026-0387")
    c.meta_raw = {**(c.meta_raw or {}), "document_created_receipt": "AID-2026-EXISTING-1"}
    fresh_session.commit()

    res = adapter_service.execute_filing(
        fresh_session, adapter_id="ariba", case_id="INV-CN-2026-0387", is_sandbox=False
    )
    assert res["success"] is True
    assert res["receipt_no"] == "AID-2026-EXISTING-1"
    assert "零重复建档" in res["message"]


def test_adapter_retry_backoff_sequence():
    """[FN-7-06 / P08 最小集] 重试队列退避序列（30s/2min/10min 退避，≤3 次防重复建档）。"""
    q = adapter_service.list_adapter_queue("ariba")
    retry_items = [item for item in q if item["status"] == "retry"]
    assert len(retry_items) >= 1
    assert any("30s/2min/10min" in item["action"] for item in retry_items)

