# -*- coding: utf-8 -*-
"""审计报表、归档合规与标注沉淀 API（WP5.3–WP5.4 · FN-5-06~11, FN-8-12~14）。

承接 audit-reports.html 三 Tab 与 platform-admin.html Tab4：
  - Tab 1 审计日志检索、统计条聚合、链重验与自审计导出（FN-5-08）；
  - Tab 2 SLA 分链路 P95 六卡、可用性/吞吐、§9.2 质量指标表、红线 12 周序列与 AI 归因建议卡（FN-8-12/14）；
  - Tab 3 归档统计、10/7/2 年保留策略实体、双实例独立成链校验、周期抽检与异常冻结联动、数据合规导出（FN-5-06/07/10/11）；
  - 平台 Tab 4 错误样本自动回流、标注任务四态流转、规则沉淀与不出控制域合规拦截（FN-8-13）。
"""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import (
    annotation_service,
    archival_service,
    audit_service,
    persistence,
    sampling_service,
    sla_reporting_service,
)
from app.services.errors import CommandError

router = APIRouter(prefix="/api/audit", tags=["audit-reports"])
anno_router = APIRouter(prefix="/api/platform/annotation", tags=["annotation-governance"])


def get_db():
    session = persistence.get_session()
    try:
        yield session
    finally:
        session.close()


# ───────────────────────── 请求体模型 ─────────────────────────

class VerifyChainReq(BaseModel):
    verifier: str = Field("王莉", description="校验人姓名")


class AuditExportReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    filters: dict | None = Field(None, description="检索过滤条件")


class AttributionReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    action: str = Field(..., description="处置动作：adopt | reject")
    opinion: str | None = Field(None, description="处置意见")


class ArchivalCleanupReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")


class ComplianceExportReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")


class RunSamplingReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    target_scope: str = Field("CN_XML", description="抽检范围：CN_XML | OS_PDF | INTERMEDIATE")
    sample_size: int = Field(500, description="抽检样本量")


class SamplingAnomalyReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    batch_no: str = Field(..., description="抽检批次号")
    anomaly_reason: str = Field(..., description="异常原因说明")


class RefluxSampleReq(BaseModel):
    case_id: str = Field(..., description="来源案件号")
    error_type: str = Field(..., description="错误类型：FIELD_EDITED | AUTHENTICITY_FAILED | VARIANCE_CONFLICT")
    detail: str = Field(..., description="错误明细描述")


class CreateTaskReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    doc_type: str = Field(..., description="票种")
    samples_count: int = Field(..., description="样本数")
    annotator: str = Field("待分派", description="标注员/组")


class UpdateTaskStatusReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    new_status: str = Field(..., description="新状态：排队中 | 标注中 | 三审仲裁 | 已完成已沉淀")
    progress_pct: int | None = Field(None, description="进度百分比 (0-100)")


class ConvertRuleReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    rule_id: str = Field(..., description="规则 ID")
    usage: str = Field(..., description="规则说明")
    ref_version: str = Field("v1.0", description="条款版本")


class DataStayToggleReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    new_state: bool = Field(..., description="目标开启状态")


# ───────────────────────── 1. 审计检索与导出 (FN-5-08) ─────────────────────────

@router.get("/logs")
def search_logs(
    time_range: str = Query("7d", description="时间范围：today | 7d | 30d | custom"),
    actor: str | None = Query(None, description="操作主体：system | provider | human | ai"),
    action_type: str | None = Query(None, description="动作分类：parse | verify | dedup | match | status | field | action | policy | export"),
    keyword: str | None = Query(None, description="案件号 / trace ID / 关键词搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    session=Depends(get_db),
):
    """四维检索审计日志与统计条实时聚合（FN-5-08）。"""
    return audit_service.search_audit_logs(
        session,
        time_range=time_range,
        actor=actor,
        action_type=action_type,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.post("/verify-chain")
def verify_chain(req: VerifyChainReq, session=Depends(get_db)):
    """重新校验哈希链并登记（FN-5-08）。"""
    try:
        return audit_service.verify_chain_and_record(session, req.verifier)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/export")
def export_audit_csv(req: AuditExportReq, session=Depends(get_db)):
    """CSV 导出自审计入链头（FN-5-08 / FN-0-10）。"""
    try:
        return audit_service.export_audit_csv(session, req.actor, req.filters)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 2. SLA 与质量报表 (FN-8-12, FN-8-14) ─────────────────────────

@router.get("/sla-quality")
def get_sla_quality_report(session=Depends(get_db)):
    """获取分链路 P95 六卡、质量指标与 12 周红线序列。"""
    return sla_reporting_service.get_sla_and_quality_report(session)


@router.post("/attribution")
def handle_attribution(req: AttributionReq, session=Depends(get_db)):
    """处置 AI 异常归因建议（FN-8-14）。"""
    try:
        return sla_reporting_service.handle_attribution_advice(session, req.actor, req.action, req.opinion)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 3. 归档与保留策略 (FN-5-06, 10, 11) ─────────────────────────

@router.get("/archival")
def get_archival_overview(session=Depends(get_db)):
    """获取归档统计、10/7/2年保留策略与区域驻留信息。"""
    return archival_service.get_archival_overview(session)


@router.post("/archival/cleanup")
def cleanup_archival(req: ArchivalCleanupReq, session=Depends(get_db)):
    """执行已满 2 年中间结果生命周期清理任务。"""
    try:
        return archival_service.cleanup_expired_intermediate_archives(session, req.actor)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.get("/archival/verify-dual-chains")
def verify_dual_chains(session=Depends(get_db)):
    """双实例独立成链完整性校验。"""
    return archival_service.verify_dual_instance_chains(session)


@router.post("/archival/export-compliance")
def export_compliance(req: ComplianceExportReq, session=Depends(get_db)):
    """导出归档合规说明文档。"""
    try:
        return archival_service.export_compliance_summary(session, req.actor)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 4. 周期抽检任务 (FN-5-07) ─────────────────────────

@router.get("/sampling")
def list_samplings(session=Depends(get_db)):
    """获取历史抽检记录列表。"""
    return {"records": sampling_service.list_sampling_records(session)}


@router.post("/sampling/run")
def run_sampling(req: RunSamplingReq, session=Depends(get_db)):
    """执行新一轮周期抽检任务并记入审计链。"""
    try:
        return sampling_service.run_periodic_sampling(session, req.actor, req.target_scope, req.sample_size)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/sampling/anomaly")
def report_sampling_anomaly(req: SamplingAnomalyReq, session=Depends(get_db)):
    """抽检异常联动：高风险告警 + 联动冻结自动放行。"""
    try:
        return sampling_service.trigger_sampling_anomaly_freeze(session, req.actor, req.batch_no, req.anomaly_reason)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 5. 标注与数据沉淀 (FN-8-13) ─────────────────────────

@anno_router.get("")
def get_annotation_overview(session=Depends(get_db)):
    """获取标注中心总体指标与任务列表。"""
    return annotation_service.get_annotation_dashboard(session)


@anno_router.post("/reflux")
def reflux_sample(req: RefluxSampleReq, session=Depends(get_db)):
    """错误样本自动回流接入。"""
    return annotation_service.reflux_error_sample(
        session, case_id=req.case_id, error_type=req.error_type, detail=req.detail
    )


@anno_router.post("/tasks")
def create_task(req: CreateTaskReq, session=Depends(get_db)):
    """创建标注任务（ANNO 发号器）。"""
    try:
        return annotation_service.create_annotation_task(session, req.actor, req.doc_type, req.samples_count, req.annotator)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@anno_router.post("/tasks/{task_id}/status")
def update_task_status(task_id: str, req: UpdateTaskStatusReq, session=Depends(get_db)):
    """更新标注任务状态（四态流转）。"""
    try:
        return annotation_service.update_annotation_task_status(session, req.actor, task_id, req.new_status, req.progress_pct)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@anno_router.post("/rules/convert")
def convert_rule(req: ConvertRuleReq, session=Depends(get_db)):
    """沉淀规则转化接入规则引擎。"""
    try:
        return annotation_service.convert_annotation_to_rule(session, req.actor, req.rule_id, req.usage, req.ref_version)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@anno_router.post("/data-stay/toggle")
def toggle_data_stay(req: DataStayToggleReq, session=Depends(get_db)):
    """切换「标注数据不出客户控制域」开关（合规拦截）。"""
    try:
        return annotation_service.toggle_data_stay_in_domain(session, req.actor, req.new_state)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)
