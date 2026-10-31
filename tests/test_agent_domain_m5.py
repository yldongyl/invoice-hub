# -*- coding: utf-8 -*-
"""M5 LangGraph Agent 域全量测试套件（WP5.5 · FN-8-08/09, FN-6-08/12, FN-8-14, FN-9-11）。

覆盖内容：
  - FN-8-08 三条 seed 意图真实走通（金额差异>5000 / 0387 证据链 / 海外重复票）+ 蓝橙标分离 + 免责块 + MCP 工具名标注 + 只读卡唤起 + 零写事件断言 + 会话审计；
  - FN-8-09 AI 建议卡生成服务（差异解释全要素结构）；
  - FN-6-12 主动调查编排（INVESTIGATING 态只读取证 → 组装证据链 → LLM 解释）；
  - FN-6-08 LLM 映射推荐真实替换 M4 规则桩（签名不变，<80% 强制人工）；
  - FN-8-14 周期异常归因分析（建议类，不自动执行）；
  - FN-9-11 模型客户端可替换配置化、逐次调用审计与 Prompt 30 天清理任务；
  - 依赖纪律验证：agent/ 零 DB 直连，backend/ 零 LLM import。
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# 引入 agent 根路径与 backend 根路径
INVOICE_HUB_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = INVOICE_HUB_ROOT / "backend"
AGENT_ROOT = INVOICE_HUB_ROOT / "agent"
if str(INVOICE_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(INVOICE_HUB_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agent.backend_client import BackendClient
from agent.conversation_graph import ConversationGraph
from agent.investigation_graph import InvestigationGraph
from agent.mapping_assistant import MappingAssistant
from agent.attribution_agent import AttributionAgent
from agent.model_client import ModelClient
from agent.main import app as agent_app
from app.main import create_app as create_backend_app


@pytest.fixture
def test_backend_client():
    """提供对接 backend API 的测试客户端（模拟端口 8000 内部 HTTP 调用，零 DB 直连）。"""
    backend_app = create_backend_app()
    client = TestClient(backend_app)
    return BackendClient(http_client=client)


@pytest.fixture
def agent_client():
    """提供针对 agent 服务的 TestClient（模拟端口 8001 API）。"""
    return TestClient(agent_app)


# ───────────────────────── 1. 三条 seed 意图对话图真实走通 (FN-8-08) ─────────────────────────

def test_intent_1_variance_screening(test_backend_client):
    """意图 1：金额差异 > 5000 筛查。
    断言：
      1. 走通 MCP 工具 case.search；
      2. 蓝标系统查询结果与橙标 AI 生成线索同屏分离；
      3. 包含免责声明块；
      4. 唤起只读详情卡且带「Agent 唤起 · 未修改数据」标记；
      5. 全程零写操作断言通过；
      6. 对话审计留痕。
    """
    graph = ConversationGraph(test_backend_client)
    res = graph.run("展示所有金额差异大于5000的案件", actor="王莉")

    assert res.intent == "VARIANCE_SCREENING"
    assert res.tool_called == "case.search"
    # 蓝橙分离断言
    assert "tag-blue" in res.system_result_html
    assert "tag-orange" in res.ai_clues_html
    # 免责声明
    assert "本建议由大模型生成，不自动执行业务操作" in res.disclaimer_html
    # 零写事件断言
    assert res.zero_write_asserted is True
    # 唤起只读卡标记
    assert len(res.invoked_cards) >= 1
    for card in res.invoked_cards:
        assert card.readonly is True
        assert card.marker == "Agent 唤起 · 未修改数据"
    # 对话审计留痕
    audits = graph.get_audit_history()
    assert len(audits) >= 1
    assert audits[-1]["intent"] == "VARIANCE_SCREENING"


def test_intent_2_evidence_chain_reading(test_backend_client):
    """意图 2：0387 案件证据链读取。
    断言：走通 MCP: case.get_evidence，蓝橙分离，只读卡唤起，零写事件。
    """
    graph = ConversationGraph(test_backend_client)
    res = graph.run("查询案件 INV-CN-2026-0387 全部证据链", actor="王莉")

    assert res.intent == "EVIDENCE_CHAIN"
    assert res.tool_called == "case.get_evidence"
    assert "INV-CN-2026-0387" in res.system_result_html
    assert "tag-blue" in res.system_result_html
    assert "tag-orange" in res.ai_clues_html
    assert res.zero_write_asserted is True
    assert any(c.case_id == "INV-CN-2026-0387" for c in res.invoked_cards)
    assert res.invoked_cards[0].marker == "Agent 唤起 · 未修改数据"


def test_intent_3_dedup_screening(test_backend_client):
    """意图 3：海外重复票筛查。
    断言：走通 MCP: dedup.report，返回 SCH-SG-77410 重复拦截与 BLOCKED 状态，只读卡唤起。
    """
    graph = ConversationGraph(test_backend_client)
    res = graph.run("帮我筛查本月重复风险的海外供应商发票", actor="王莉")

    assert res.intent == "DEDUP_SCREENING"
    assert res.tool_called == "dedup.report"
    assert "INV-SG-2026-0122" in res.system_result_html
    assert "BLOCKED" in res.system_result_html
    assert res.zero_write_asserted is True
    assert any(c.case_id == "INV-SG-2026-0122" for c in res.invoked_cards)


def test_intent_fallback_boundary_explanation(test_backend_client):
    """未命中意图：返回规范的能力边界说明。"""
    graph = ConversationGraph(test_backend_client)
    res = graph.run("今天天气怎么样？能帮我直接支付发票吗？", actor="王莉")

    assert res.intent == "FALLBACK"
    assert "不执行任何业务写操作" in res.system_result_html
    assert res.zero_write_asserted is True
    assert len(res.invoked_cards) == 0


# ───────────────────────── 2. AI 建议卡生成与主动调查编排 (FN-8-09, FN-6-12) ─────────────────────────

def test_investigation_orchestration_and_suggestion_card(test_backend_client):
    """测试主动调查编排（只读取证）与差异解释建议卡生成。"""
    invest_graph = InvestigationGraph(test_backend_client)
    card = invest_graph.investigate_case("INV-SG-2026-0125")

    assert card.case_id == "INV-SG-2026-0125"
    assert "含税总额 vs PO 净额差异" in card.title
    assert card.confidence >= 0.80
    assert card.model_name == "qwen-finance-v2"
    # 证据引用包含 PO、GRN、GST、合同条款
    citations_text = " ".join(card.evidence_citations)
    assert "PO" in citations_text
    assert "GRN" in citations_text
    assert "GST" in citations_text
    assert "合同条款" in citations_text
    # 治理脚注与免责
    assert "不自动执行" in card.governance_footnote
    assert "确定性判断" in card.disclaimer
    # 保持 pending 待人工受控确认
    assert card.status == "pending"


# ───────────────────────── 3. LLM 映射推荐真实替换与低置信红线 (FN-6-08) ─────────────────────────

def test_llm_mapping_recommendation_and_low_confidence_flag():
    """测试 LLM 字段映射推荐引擎：低置信 <80% 强制人工红线标记。"""
    assistant = MappingAssistant()

    # 1. 正常置信度字段（报关单号 ≥80%）
    rec_normal = assistant.recommend("报关单号", doc_type_hint="数电票")
    assert rec_normal.src == "报关单号"
    assert rec_normal.to == "custom_fields.customs_ref"
    assert rec_normal.confidence >= 0.80
    assert rec_normal.low_confidence_forced_human is False
    assert rec_normal.state == "pending"

    # 2. 低置信度字段（<80% 触发红线标记）
    rec_low = assistant.recommend("低置信未知代码", doc_type_hint="增值税专票")
    assert rec_low.confidence < 0.80
    assert rec_low.low_confidence_forced_human is True
    assert rec_low.state == "needs_human"

    # 3. 完整推荐队列保持数据契约一致
    queue = assistant.get_full_recommendation_queue()
    assert len(queue) >= 3
    assert any(item["low_confidence_forced_human"] is True for item in queue)


# ───────────────────────── 4. 周期异常归因分析 (FN-8-14) ─────────────────────────

def test_attribution_analysis_report():
    """测试基于审计样本的周期异常归因分析。"""
    agent = AttributionAgent()
    report = agent.analyze()

    assert report.confidence == 0.86
    assert len(report.findings) >= 3
    findings_text = " ".join([f["issue"] + f["detail"] for f in report.findings])
    # 覆盖三大长尾问题：邮箱渠道、OCR P95 倾斜专票、XML 冲突
    assert "邮箱" in findings_text
    assert "专票" in findings_text
    assert "XML" in findings_text
    assert len(report.recommendations) >= 3
    assert "不自动执行" in report.execution_policy


# ───────────────────────── 5. 模型客户端配置化与 30 天清理任务 (FN-9-11) ─────────────────────────

def test_model_client_configurable_and_prompt_cleanup():
    """测试可替换模型客户端及 30 天 Prompt 审计清理任务。"""
    client = ModelClient(model_name="custom-vlm-model", model_version="2026-11-01")
    assert client.model_name == "custom-vlm-model"
    assert client.model_version == "2026-11-01"

    # 执行生成
    resp = client.generate("测试 Prompt 调用")
    assert resp.model == "custom-vlm-model"
    assert client.get_audit_log_count() == 1

    # 测试清理（保留天数 30 天，无过期数据）
    cleaned = client.cleanup_expired_prompts(retention_days=30)
    assert cleaned == 0
    assert client.get_audit_log_count() == 1

    # 测试清理（保留天数 -1 天，模拟超期清理）
    cleaned_expired = client.cleanup_expired_prompts(retention_days=-1)
    assert cleaned_expired == 1
    assert client.get_audit_log_count() == 0


# ───────────────────────── 6. Agent HTTP 服务接口测试 (端口 8001 API) ─────────────────────────

def test_agent_api_endpoints(agent_client):
    """测试 Agent 服务 FastAPI 端点（/healthz, /v1/agent/chat 等）。"""
    # 1. 探活
    h_res = agent_client.get("/healthz")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "healthy"

    # 2. 对话端点
    c_res = agent_client.post("/v1/agent/chat", json={
        "query": "展示所有金额差异大于5000的案件",
        "actor": "王莉",
    })
    assert c_res.status_code == 200
    assert c_res.json()["intent"] == "VARIANCE_SCREENING"

    # 3. 映射推荐端点
    m_res = agent_client.get("/v1/agent/mapping/recommendations")
    assert m_res.status_code == 200
    assert len(m_res.json()["items"]) >= 3

    # 4. 归因分析端点
    a_res = agent_client.get("/v1/agent/attribution")
    assert a_res.status_code == 200
    assert a_res.json()["confidence"] == 0.86


# ───────────────────────── 7. 依赖纪律严格自查（代码评审红线） ─────────────────────────

def test_agent_domain_dependency_discipline():
    """红线自查：
    1. agent/ 目录下绝对严禁直接连接 DB 或 import 任何 ORM/SQLAlchemy/sqlite3；
    2. backend/ 绝对严禁 import agent/。
    """
    # 1. 扫描 agent/ 下的 .py 文件
    forbidden_db_patterns = ["import sqlite3", "from sqlalchemy", "import sqlalchemy", "get_session", "persistence.py"]
    for p in AGENT_ROOT.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for f_kw in forbidden_db_patterns:
            assert f_kw not in text, f"agent/{p.name} 存在直连 DB 或 ORM 引用违规: {f_kw}"

    # 2. 扫描 backend/ 严禁 import agent
    import re
    pat = re.compile(r"^\s*(?:from|import)\s+agent\b")
    for p in BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in str(p) or ".venv" in str(p) or "venv" in str(p):
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not pat.search(line), f"backend/{p.name} 违规 import agent: {line}"
