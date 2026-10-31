# -*- coding: utf-8 -*-
"""Agent 域 FastAPI 服务入口（WP5.5 · ADR-0001 双轨制 · 端口 8001）。

红线与纪律：
  - 零 DB 直连：全量通过 BackendClient 调用 backend REST API；
  - LLM 输出不直接写入 checks/status/字段值；
  - AI 不持有任何 RBAC 角色；
  - 包含对话图、主动调查编排、LLM 映射推荐与归因分析服务。
"""

from typing import Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.backend_client import BackendClient
from agent.conversation_graph import AgentConversationResponse, ConversationGraph
from agent.investigation_graph import AISuggestionCard, InvestigationGraph
from agent.mapping_assistant import MappingAssistant, MappingRecommendation
from agent.attribution_agent import AnomalyAttributionReport, AttributionAgent
from agent.model_client import get_model_client

app = FastAPI(
    title="invoice-hub agent",
    description="全球采购平台票据智能与合规中台 · LangGraph Agent 域（端口 8001）",
    version="0.5.0-m5-wp5.5",
)

# 允许跨域（前端可直连或由代理转发）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

backend_client = BackendClient()
conv_graph = ConversationGraph(backend_client)
invest_graph = InvestigationGraph(backend_client)
mapping_assistant = MappingAssistant()
attribution_agent = AttributionAgent()


class ChatRequest(BaseModel):
    query: str = Field(..., description="用户自然语言输入")
    actor: str = Field("王莉", description="提问用户（用于审计）")
    session_id: Optional[str] = Field(None, description="会话上下文 ID")


class InvestigateRequest(BaseModel):
    case_id: str = Field(..., description="待调查案件号（需处于 INVESTIGATING 态）")


class MappingRecommendRequest(BaseModel):
    src_field: str = Field(..., description="来源发票字段名称")
    doc_type_hint: Optional[str] = Field(None, description="票种提示")


class CleanupRequest(BaseModel):
    retention_days: int = Field(30, description="保留天数（默认 30 天，FN-9-11）")


@app.get("/healthz")
def healthz():
    return {
        "status": "healthy",
        "service": "invoice-hub-agent",
        "model": get_model_client().model_name,
        "model_version": get_model_client().model_version,
    }


@app.post("/v1/agent/chat", response_model=AgentConversationResponse)
def chat(req: ChatRequest):
    """对话图推理入口（FN-8-08 · 三意图路由 + 蓝橙标分离 + 免责块 + 零写事件断言）。"""
    return conv_graph.run(req.query, actor=req.actor)


@app.post("/v1/agent/investigate", response_model=AISuggestionCard)
def investigate(req: InvestigateRequest):
    """主动调查编排与 AI 建议卡生成（FN-6-12 / FN-8-09）。"""
    return invest_graph.investigate_case(req.case_id)


@app.post("/v1/agent/mapping/recommend", response_model=MappingRecommendation)
def recommend_mapping(req: MappingRecommendRequest):
    """LLM 字段映射推荐（FN-6-08 · 替换 M4 规则桩）。"""
    return mapping_assistant.recommend(req.src_field, req.doc_type_hint)


@app.get("/v1/agent/mapping/recommendations")
def list_recommendations():
    """获取待确认映射推荐队列（全量队列展示）。"""
    return {"items": mapping_assistant.get_full_recommendation_queue()}


@app.get("/v1/agent/attribution", response_model=AnomalyAttributionReport)
def get_attribution_analysis():
    """周期异常归因分析（FN-8-14 · 建议类）。"""
    return attribution_agent.analyze()


@app.post("/v1/agent/prompts/cleanup")
def cleanup_prompts(req: CleanupRequest):
    """Prompt / 响应 30 天清理任务接口（FN-9-11）。"""
    cleaned = get_model_client().cleanup_expired_prompts(req.retention_days)
    return {
        "cleaned_count": cleaned,
        "remaining_count": get_model_client().get_audit_log_count(),
        "retention_days": req.retention_days,
        "message": f"成功清理 {cleaned} 条过期 Prompt/响应记录",
    }
