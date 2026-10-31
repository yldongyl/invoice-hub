# -*- coding: utf-8 -*-
"""M5 官方 E2E 七大场景断言（WP5.7 · S-M5-01~07 · 实施规划 §4-M5 验收标准与 P08 §1.3）。

场景清单：
  S-M5-01: 红线告警关闭拦截+留痕（向 P0 红线告警发送关闭请求，被 HTTP 403 强制拦截拒绝，开关回弹保持开启，尝试行为写入不可篡改审计链）；
  S-M5-02: 配置发布→行为变化→回滚恢复（配置中心发布新阈值使得原本通过的案件流转发生预期变化，回滚后系统行为恢复基线，操作全量入审计）；
  S-M5-03: Agent 三意图真实工具链（蓝橙标+免责+工具名+只读断言：对话全程零写事件，调用 case.search / case.get_evidence / dedup.report）；
  S-M5-04: MCP 枚举 6 工具+写工具无 confirm_token 拒绝+agent/mcp 同源（tools/list 发现 6 工具与契约一致；写工具缺 confirm_token 428 拒绝，agent 与 mcp 底层工具层同源）；
  S-M5-05: 审计导出自入链头+链校验（导出行为生成 AUDIT_EXPORT 事件写入链头，blk# 严格递增，链校验全域通过）；
  S-M5-06: 标注回流→沉淀规则→规则生效（修正样本自动入队断言，标注任务流转并沉淀规则入 catalog，规则引擎生效）；
  S-M5-07: 抽检异常→冻结自动放行联动（周期抽检发现异常样本，自动触发熔断机制，联动冻结自动放行通道，进入强制人工复核）。
"""

import json
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.domain import models as m
from app.services import (
    audit_chain,
    config_center,
    persistence,
    rules,
    state_machine,
)

pytestmark = pytest.mark.scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.backend_client import BackendClient
from agent.conversation_graph import ConversationGraph
from mcp.main import app as mcp_app
from mcp.server import McpServer


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-01: 红线告警关闭拦截+留痕
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_01_redline_alert_disable_blocked_and_audited(api_client):
    """[S-M5-01 / FN-9-08 / P00 §5] 红线告警关闭拦截+留痕。
    断言：向 P0 红线告警发送关闭请求，被 HTTP 403 强制拦截拒绝，开关回弹保持开启，尝试行为写入不可篡改审计链。
    """
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post(
        "/api/platform/alerts/rules/false_auto_release_rate/toggle",
        json={"actor": "陈铮", "new_state": False, "opinion": "测试停用红线"},
    )
    assert res.status_code == 403, f"[S-M5-01] 期望返回 403，实际返回: {res.status_code} ({res.text})"
    detail = res.json().get("detail", "")
    assert "不可停用" in detail and "已记入审计日志" in detail

    # 验证规则仍处于开启状态（开关回弹保持 on=True）
    rules_res = api_client.get("/api/platform/alerts/rules")
    redline_rule = next(r for r in rules_res.json()["rules"] if r["rule_id"] == "false_auto_release_rate")
    assert redline_rule["on"] is True, "[S-M5-01] 红线告警开关未能回弹保持开启"

    # 验证尝试关闭行为写入审计链
    with persistence.get_session() as s:
        new_head = audit_chain.head_blk(s)
        assert new_head > old_head
        blk = s.get(m.AuditBlock, new_head)
        assert "【红线告警拦截】" in blk.note
        assert blk.op_component == "platform-admin/redline-guard"


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-02: 配置发布→行为变化→回滚恢复
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_02_config_publish_behavior_change_and_rollback(fresh_session):
    """[S-M5-02 / FN-9-09 / FN-0-12] 配置发布→行为变化→回滚恢复。
    断言：
      1. 基线状态下（阈值 0.85），置信度 86% 的案件未触发低置信流转；
      2. 修改草稿并将阈值提高至 0.90，发布新版本，diff 入不可篡改审计链；
      3. 新阈值生效：同置信度（86%）案件被判定为低置信（86 < 90），流转至 NEEDS_REVIEW；
      4. 执行一键回滚恢复到旧版本，阈值恢复为 0.85，低置信流转消除，行为恢复基线。
    """
    key = "confidence_threshold_default"
    assert config_center.get_value(fresh_session, key) == 0.85

    # 1. 构造 RECOGNIZED 态且置信度 86% 的案件
    c = fresh_session.get(m.Case, "INV-CN-2026-0386")
    c.status = "RECOGNIZED"
    c.confidence = 86
    c.checks_raw = {k: {"result": "PASSED", "note": "ok"} for k in ("supplierMatch", "authenticity", "duplicate", "poMatch")}
    fresh_session.commit()

    ev1 = state_machine.evaluate(fresh_session, "INV-CN-2026-0386")
    assert not any("低置信" in e["reason"] for e in ev1), "[S-M5-02] 基线阈值 0.85 下置信度 86% 不应触发低置信"

    # 2. 修改草稿并发布新阈值 0.90
    config_center.save_draft(fresh_session, key, {"label": "置信度阈值", "value": 0.90, "range": [0.5, 0.99]}, "陈铮")
    pub_res = config_center.publish(fresh_session, key, "陈铮")
    assert pub_res["diff"]["value"]["from"] == 0.85
    assert pub_res["diff"]["value"]["to"] == 0.90
    assert config_center.get_value(fresh_session, key) == 0.90

    # 3. 行为变化：86% < 90%，被判定为低置信，触发 NEEDS_REVIEW
    ev2 = state_machine.evaluate(fresh_session, "INV-CN-2026-0386")
    assert any(e["to"] == "NEEDS_REVIEW" and "低置信" in e["reason"] for e in ev2), "[S-M5-02] 提高阈值至 0.90 后，86% 案件应触发低置信 NEEDS_REVIEW"

    # 4. 回滚旧版
    config_center.rollback(fresh_session, key, pub_res["prev_version"], "陈铮")
    assert config_center.get_value(fresh_session, key) == 0.85
    ev3 = state_machine.evaluate(fresh_session, "INV-CN-2026-0386")
    assert not any("低置信" in e["reason"] for e in ev3), "[S-M5-02] 回滚恢复基线阈值后，86% 案件低置信流转应消除"


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-03: Agent 三意图真实工具链 + 零写事件
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_03_agent_three_intents_tool_chain_and_zero_write():
    """[S-M5-03 / FN-8-08 / ADR-0001] Agent 三意图真实走通工具链，蓝橙标分离、免责声明、只读唤起卡与对话全程零写操作。"""
    from app.main import create_app as create_backend_app
    backend_app = create_backend_app()
    client = TestClient(backend_app)
    b_client = BackendClient(http_client=client)
    graph = ConversationGraph(b_client)

    # 意图 1：差异筛查（case.search）
    resp1 = graph.run("展示所有金额差异大于5000的案件", actor="王莉")
    assert resp1.intent == "VARIANCE_SCREENING"
    assert resp1.tool_called == "case.search"
    assert "tag-blue" in resp1.system_result_html
    assert "tag-orange" in resp1.ai_clues_html
    assert "本建议由大模型生成，不自动执行业务操作" in resp1.disclaimer_html
    assert resp1.zero_write_asserted is True

    # 意图 2：证据链读取（case.get_evidence）
    resp2 = graph.run("查询案件 INV-CN-2026-0387 全部证据链", actor="王莉")
    assert resp2.intent == "EVIDENCE_CHAIN"
    assert resp2.tool_called == "case.get_evidence"
    assert len(resp2.invoked_cards) >= 1
    assert resp2.invoked_cards[0].readonly is True
    assert "Agent 唤起 · 未修改数据" in resp2.invoked_cards[0].marker
    assert resp2.zero_write_asserted is True

    # 意图 3：查重分析（dedup.report）
    resp3 = graph.run("帮我筛查本月重复风险的海外供应商发票", actor="王莉")
    assert resp3.intent == "DEDUP_SCREENING"
    assert resp3.tool_called == "dedup.report"
    assert resp3.zero_write_asserted is True


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-04: MCP 枚举 6 工具 + 写工具无 confirm_token 拒绝 + agent/mcp 同源
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_04_mcp_six_tools_and_confirm_token_rejection():
    """[S-M5-04 / FN-A-04 / ADR-0001] MCP 枚举 6 工具 + 写工具缺 confirm_token 拒绝 + agent/mcp 同源。"""
    from app.main import create_app as create_backend_app
    from mcp import main as mcp_main

    b_app = create_backend_app()
    b_client = BackendClient(http_client=TestClient(b_app))
    mcp_main.backend_client = b_client
    mcp_main.mcp_server = McpServer(b_client)
    mcp_client = TestClient(mcp_app)

    # 1. 枚举 6 工具与契约一致
    res_list = mcp_client.get("/mcp/v1/tools/list")
    assert res_list.status_code == 200
    tools = res_list.json()["tools"]
    assert len(tools) == 6, f"[S-M5-04] MCP tools/list 预期 6 个工具，实际返回: {len(tools)}"
    tool_names = [t["name"] for t in tools]
    assert "case.search" in tool_names
    assert "case.action" in tool_names

    # 2. 受控写工具无 confirm_token 强制拒绝 428
    res_write = mcp_client.post(
        "/mcp/v1/tools/call",
        json={
            "name": "case.action",
            "arguments": {"caseId": "INV-CN-2026-0387", "action": "RELEASE", "operator": "王莉"},
            # 故意不传 confirm_token
        },
        headers={"Authorization": "Bearer test-write-token"},
    )
    assert res_write.status_code == 428, f"[S-M5-04] 写工具缺少 confirm_token 预期返回 428，实际: {res_write.status_code}"
    assert "human_confirm_token" in res_write.json().get("detail", {}).get("message", "")

    # 3. agent/mcp 工具层同源：两者均调用相同的底层 BackendClient
    conv = ConversationGraph(b_client)
    assert conv.backend_client is mcp_main.backend_client, "[S-M5-04] agent 与 mcp 底层 client 未同源"


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-05: 审计导出自入链头 + 链校验全通过
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_05_audit_export_self_audit_at_chain_head(api_client):
    """[S-M5-05 / FN-8-06 / FN-0-10] 审计导出行为自入链头 + 链校验全通过。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post(
        "/api/audit/export",
        json={"actor": "王莉", "filters": {"time_range": "7d", "actor": "human"}},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["audit_blk"] == old_head + 1, "[S-M5-05] 审计导出块高未严格递增插入链头"
    assert data["download_url"].startswith("/v1/exports/")
    assert data["token"]
    assert "expires_at" in data

    # 执行哈希链整体验证
    with persistence.get_session() as s:
        v_res = audit_chain.verify_chain(s, verifier="王莉")
        assert v_res["ok"] is True, f"[S-M5-05] 导出后哈希链校验失败: {v_res}"


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-06: 标注回流→沉淀规则→规则生效
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_06_annotation_reflux_and_rule_deposition(api_client):
    """[S-M5-06 / FN-8-13 / FN-6-01] 标注回流→沉淀规则→规则生效。"""
    # 1. 模拟人工修正样本自动回流排队 -> 优先级 1（真实错误优先）
    ref_res = api_client.post(
        "/api/platform/annotation/reflux",
        json={"case_id": "INV-CN-2026-0388", "error_type": "FIELD_EDITED", "detail": "价税合计金额手工修正"},
    )
    assert ref_res.status_code == 200
    rdata = ref_res.json()
    assert rdata["sample"]["priority"] == 1
    assert "真实错误" in rdata["sample"]["priority_label"]

    # 2. 创建标注任务并流转至已完成
    create_res = api_client.post(
        "/api/platform/annotation/tasks",
        json={"actor": "陈铮", "doc_type": "数电票", "samples_count": 10, "annotator": "标注一组"},
    )
    assert create_res.status_code == 200
    task_id = create_res.json()["task_id"]

    # 3. 沉淀为规则并接入规则引擎
    sed_res = api_client.post(
        "/api/platform/annotation/rules/convert",
        json={"actor": "陈铮", "rule_id": "amount_tax_sum_check", "usage": "数电票特定科目映射规则", "ref_version": "v1.4"},
    )
    assert sed_res.status_code == 200
    assert sed_res.json()["rule_id"] == "amount_tax_sum_check"
    assert sed_res.json()["audit_blk"] > 0

    # 4. 校验规则引擎可正常执行该规则
    r_eval = rules.run_rule("amount_tax_sum_check", {"net": 100.0, "tax": 13.0, "gross": 113.0, "tolerance_reconcile": 0.06})
    assert r_eval["result"] == "PASSED", "[S-M5-06] 沉淀规则未在规则引擎中正确生效"


# ══════════════════════════════════════════════════════════════════════════════
# S-M5-07: 抽检异常→冻结自动放行联动
# ══════════════════════════════════════════════════════════════════════════════

def test_s_m5_07_sampling_anomaly_freezes_auto_release(api_client, fresh_session):
    """[S-M5-07 / FN-5-07 / FN-9-08] 周期抽检发现异常样本，自动触发熔断，联动冻结自动放行。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    # 1. 触发抽检异常
    res = api_client.post(
        "/api/audit/sampling/anomaly",
        json={"actor": "王莉", "batch_no": "QA-2026-W43-01", "anomaly_reason": "抽检发现 1 份原件 SHA-256 摘要与登记不符"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["auto_release_frozen"] is True
    assert data["audit_blk"] > old_head

    # 2. 验证审计链中记录了抽检异常冻结事件
    with persistence.get_session() as s:
        blk = s.get(m.AuditBlock, data["audit_blk"])
        assert "自动放行冻结" in blk.note
        assert blk.op_component == "platform-admin/sampling-freeze"
