# -*- coding: utf-8 -*-
"""平台支撑管理 API（WP5.1-5.2 · FN-9-01~11）。

承接 platform-admin.html 四 Tab 及登录/会话交互：
  - 租户管理与四隔离验证（FN-9-01）；
  - 角色权限矩阵与 RBAC 实装（FN-9-02）；
  - SSO 演示桩与服务端二次校验（FN-9-03）；
  - 登录会话与 MFA（FN-9-04）；
  - 平台用户列表（FN-9-05）；
  - 服务健康自监控（FN-9-06）；
  - 异步队列治理（FN-9-07）；
  - 告警规则与红线不可停用拦截留痕（FN-9-08）；
  - 配置中心 diff、发布与适配器兼容校验通知（FN-9-09）；
  - KMS 凭证掩码与轮换（FN-9-10）；
  - 模型数据边界管控与清理（FN-9-11）。
"""

from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import (
    alert_engine,
    identity_service,
    monitoring_service,
    persistence,
    platform_config_service,
    rbac_service,
    tenant_service,
)
from app.services.errors import CommandError

router = APIRouter(prefix="/api/platform", tags=["platform-admin"])


def get_db():
    session = persistence.get_session()
    try:
        yield session
    finally:
        session.close()


# ───────────────────────── 请求体模型 ─────────────────────────

class IsolationBoundaryReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    boundary_patch: dict = Field(..., description="隔离边界变更内容")
    opinion: str | None = Field(None, description="处置意见")


class RbacMatrixReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    grants: dict[str, list[int]] = Field(..., description="各角色权限授权向量字典")
    opinion: str | None = Field(None, description="变更处置意见")


class SsoLoginReq(BaseModel):
    idp_id: str = Field(..., description="IdP 标识：sap_ias | btp_xsuaa")
    assertion: dict = Field(..., description="SAML/OIDC 模拟断言 payload")


class PasswordLoginReq(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    tenant_id: str = Field(..., description="租户 ID")
    mfa_code: str | None = Field(None, description="6 位动态 MFA 验证码")
    mfa_challenge_id: str | None = Field(None, description="MFA 挑战 ID")
    remember_device: bool = Field(False, description="是否记住设备 30 天")


class MfaChallengeReq(BaseModel):
    username: str = Field(..., description="用户名")
    tenant_id: str = Field(..., description="租户 ID")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


class UserStatusReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    new_status: str = Field(..., description="新状态：启用 | 停用")
    opinion: str | None = Field(None, description="处置意见")


class AlertToggleReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    new_state: bool = Field(..., description="目标启用状态")
    opinion: str | None = Field(None, description="处置意见")


class ConfigDraftReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    values: dict = Field(..., description="配置草稿内容")


class ConfigPublishReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    values: dict | None = Field(None, description="若直接发布传入新值，缺省使用当前草稿")
    opinion: str | None = Field(None, description="发布说明或处置意见")


class ConfigRollbackReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    target_version: str = Field(..., description="回滚目标版本号")
    target_values: dict = Field(..., description="目标版本的配置载荷")
    opinion: str | None = Field(None, description="回滚原因")


class KmsRotateReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")
    reason: str | None = Field(None, description="轮换申请说明")


class ModelCleanupReq(BaseModel):
    actor: str = Field(..., description="操作人姓名")


# ───────────────────────── 租户管理 (FN-9-01) ─────────────────────────

@router.get("/tenants")
def list_tenants(session=Depends(get_db)):
    """获取租户列表与隔离状态。"""
    return {"tenants": tenant_service.list_tenants(session)}


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, session=Depends(get_db)):
    """获取单个租户详情。"""
    t = tenant_service.get_tenant(session, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"租户 {tenant_id} 不存在")
    return t


@router.get("/tenants/{tenant_id}/verify")
def verify_tenant_isolations(tenant_id: str, session=Depends(get_db)):
    """验证租户四隔离状态。"""
    try:
        return tenant_service.verify_four_isolations(session, tenant_id)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/tenants/{tenant_id}/isolation")
def change_tenant_isolation(tenant_id: str, req: IsolationBoundaryReq, session=Depends(get_db)):
    """变更租户隔离边界（高风险操作）。"""
    try:
        return tenant_service.change_isolation_boundary(
            session, req.actor, tenant_id, req.boundary_patch, req.opinion
        )
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── RBAC 角色权限 (FN-9-02) ─────────────────────────

@router.get("/rbac")
def get_rbac_matrix(session=Depends(get_db)):
    """获取 4×7(8) 角色权限矩阵。"""
    return rbac_service.get_rbac_matrix(session)


@router.post("/rbac/matrix")
def update_rbac_matrix(req: RbacMatrixReq, session=Depends(get_db)):
    """高风险变更：更新角色权限矩阵。"""
    try:
        return rbac_service.update_role_matrix(session, req.actor, req.grants, req.opinion)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── SSO / MFA / 用户 (FN-9-03, 04, 05) ─────────────────────────

@router.get("/sso/status")
def get_sso_status():
    """获取 SSO IdP 连接状态。"""
    return {"providers": identity_service.get_sso_status()}


@router.post("/sso/login")
def sso_login(req: SsoLoginReq, session=Depends(get_db)):
    """SSO 认证接入（含服务端二次校验）。"""
    try:
        return identity_service.authenticate_sso(session, req.idp_id, req.assertion)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/auth/mfa/challenge")
def issue_mfa_challenge(req: MfaChallengeReq, session=Depends(get_db)):
    """签发 MFA 挑战。"""
    try:
        return identity_service.issue_mfa_challenge(session, req.username, req.tenant_id)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/auth/login")
def password_login(req: PasswordLoginReq, session=Depends(get_db)):
    """账密登录 + 租户手选 + MFA 校验。"""
    try:
        return identity_service.authenticate_password(
            session, req.username, req.password, req.tenant_id, req.mfa_code, req.remember_device, req.mfa_challenge_id
        )
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.get("/auth/session")
def get_auth_session(authorization: str | None = Header(None)):
    """校验当前登录会话（web auth-guard 使用）。"""
    try:
        return identity_service.verify_session_token(_bearer_token(authorization))
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail={"error_code": e.code, "message": e.message})


@router.post("/auth/logout")
def logout(authorization: str | None = Header(None)):
    """注销当前登录会话。"""
    return identity_service.logout(_bearer_token(authorization))


@router.get("/users")
def list_users(session=Depends(get_db)):
    """获取平台用户列表。"""
    return {"users": identity_service.list_users(session)}


@router.post("/users/{username}/status")
def update_user_status(username: str, req: UserStatusReq, session=Depends(get_db)):
    """更新平台用户状态。"""
    try:
        return identity_service.update_user_status(session, req.actor, username, req.new_status, req.opinion)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 监控与队列 (FN-9-06, 07) ─────────────────────────

@router.get("/health")
def get_service_health(session=Depends(get_db)):
    """获取 6 服务健康监控指标及 24h 序列。"""
    return monitoring_service.get_health_overview(session)


@router.get("/queues")
def get_queues(session=Depends(get_db)):
    """获取 4 异步任务队列统计与健康状态。"""
    return monitoring_service.get_queue_governance(session)


# ───────────────────────── 告警引擎与红线不可停用 (FN-9-08) ─────────────────────────

@router.get("/alerts/rules")
def get_alert_rules(session=Depends(get_db)):
    """获取告警规则及当前触发状态。"""
    return {"rules": alert_engine.get_alert_rules(session)}


@router.post("/alerts/rules/{rule_id}/toggle")
def toggle_alert_rule(rule_id: str, req: AlertToggleReq, session=Depends(get_db)):
    """切换告警规则启用状态（红线不可停用拦截）。"""
    try:
        return alert_engine.toggle_alert_rule(session, req.actor, rule_id, req.new_state, req.opinion)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 配置中心 (FN-9-09) ─────────────────────────

@router.get("/config")
def get_config(session=Depends(get_db)):
    """获取当前配置（发布版与草稿版）。"""
    return platform_config_service.get_config_view(session)


@router.post("/config/draft")
def save_config_draft(req: ConfigDraftReq, session=Depends(get_db)):
    """保存配置草稿（不产生审计日志）。"""
    try:
        return platform_config_service.save_config_draft(session, req.actor, req.values)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/config/reset")
def reset_config_draft(req: BaseModel, session=Depends(get_db)):
    """重置配置草稿（零审计）。"""
    # 请求体可为空，默认操作人为当前用户
    return platform_config_service.reset_config_draft(session, "operator")


@router.get("/config/diff")
def get_config_diff(session=Depends(get_db)):
    """获取草稿与发布版的 diff 列表（供二次确认弹窗）。"""
    return {"diffs": platform_config_service.get_config_diff(session)}


@router.post("/config/publish")
def publish_config(req: ConfigPublishReq, session=Depends(get_db)):
    """发布配置（版本递增 + 审计 + 适配器兼容性校验通知）。"""
    try:
        return platform_config_service.publish_config(session, req.actor, req.values, req.opinion)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


@router.post("/config/rollback")
def rollback_config(req: ConfigRollbackReq, session=Depends(get_db)):
    """回滚配置至指定历史版本。"""
    try:
        return platform_config_service.rollback_config(
            session, req.actor, req.target_version, req.target_values, req.opinion
        )
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── KMS 密钥管理 (FN-9-10) ─────────────────────────

@router.get("/kms/keys")
def list_kms_keys():
    """获取 KMS 托管凭证清单（全掩码呈现）。"""
    return {"keys": platform_config_service.list_kms_keys()}


@router.post("/kms/keys/{key_id}/rotate")
def rotate_kms_key(key_id: str, req: KmsRotateReq, session=Depends(get_db)):
    """申请并执行 KMS 凭证轮换。"""
    try:
        return platform_config_service.rotate_kms_key(session, req.actor, key_id, req.reason)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)


# ───────────────────────── 模型数据边界 (FN-9-11) ─────────────────────────

@router.get("/model-boundary")
def get_model_boundary():
    """获取模型数据边界管控配置。"""
    return {"boundary": platform_config_service.get_model_data_boundary()}


@router.post("/model-boundary/cleanup")
def cleanup_model_data(req: ModelCleanupReq, session=Depends(get_db)):
    """执行清理过期模型数据任务。"""
    try:
        return platform_config_service.cleanup_expired_model_data(session, req.actor)
    except CommandError as e:
        raise HTTPException(status_code=e.http, detail=e.message)
