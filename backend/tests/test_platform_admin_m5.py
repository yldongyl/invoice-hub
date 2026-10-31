# -*- coding: utf-8 -*-
"""M5 平台支撑域全量测试套件（WP5.1–WP5.2 · FN-9-01~11）。

覆盖内容：
  - FN-9-01 租户管理与四隔离验证 + 边界变更审计；
  - FN-9-02 RBAC 4×7(8) 矩阵实装、受控命令框架注入与 AI/LLM 零角色严格断言；
  - FN-9-03 SSO 演示桩（SAP IAS / xsuaa）+ 前端只读锁定 + 服务端二次校验归属；
  - FN-9-04 登录会话、MFA 强制校验与审计留痕；
  - FN-9-05 平台用户管理与全部用户 MFA 启用断言；
  - FN-9-06 服务健康自监控（6 卡探测 + 24h 序列）；
  - FN-9-07 异步队列治理（4 队列真实统计 + 健康判定）；
  - FN-9-08 告警引擎 4 基线规则 + P0 红线不可停用强制拦截（开关回弹 + 审计留痕）；
  - FN-9-09 配置中心 diff 弹窗 API + 发布版本递增 + 适配器兼容性校验通知 + 重置草稿零审计 + 红线拦截；
  - FN-9-10 KMS 凭证全掩码不回显 + 轮换流程状态机留痕；
  - FN-9-11 模型数据边界管控 + 30 天清理任务。
"""

import pytest

from app.domain import models as m
from app.services import (
    alert_engine,
    audit_chain,
    governed_commands,
    identity_service,
    monitoring_service,
    persistence,
    platform_config_service,
    rbac_service,
    tenant_service,
)
from app.services.errors import CommandError, E_CONFIG_REDLINE_BYPASS, E_PERM_DENIED, E_TENANT_MISMATCH


# ───────────────────────── 1. 租户管理与四隔离 (FN-9-01) ─────────────────────────

def test_tenant_list_and_isolations(api_client):
    """验证双租户档案及四隔离完整性。"""
    res = api_client.get("/api/platform/tenants")
    assert res.status_code == 200
    tenants = res.json()["tenants"]
    assert len(tenants) == 2
    t_cn = next(t for t in tenants if t["tenant_id"] == "TENANT-CN-LANWU-001")
    t_os = next(t for t in tenants if t["tenant_id"] == "TENANT-SG-LANWU-001")

    assert t_cn["instance"] == "CN"
    assert "境内存储" in t_cn["region"]
    assert t_cn["status"] == "生产"
    assert all(t_cn["isolations"].values())  # 四隔离均为 True

    assert t_os["instance"] == "OS"
    assert "新加坡" in t_os["region"]
    assert t_os["status"] == "生产"
    assert all(t_os["isolations"].values())


def test_tenant_verification_endpoint(api_client):
    """测试四隔离探测验证端点。"""
    res = api_client.get("/api/platform/tenants/TENANT-CN-LANWU-001/verify")
    assert res.status_code == 200
    data = res.json()
    assert data["verified"] is True
    assert data["checks"]["data_isolation"]["status"] == "PASSED"
    assert data["checks"]["config_isolation"]["status"] == "PASSED"
    assert data["checks"]["provider_key_isolation"]["status"] == "PASSED"
    assert data["checks"]["invoice_pool_isolation"]["status"] == "PASSED"


def test_tenant_boundary_change_high_risk_audit(api_client):
    """高风险操作：变更租户隔离边界须记入不可篡改审计链。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/platform/tenants/TENANT-CN-LANWU-001/isolation", json={
        "actor": "陈铮",
        "boundary_patch": {"config_override_scope": "enhanced"},
        "opinion": "境内实例安全加固",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["updated"] is True
    assert data["audit_blk"] > old_head

    # 验证审计链记录
    with persistence.get_session() as s:
        blk = s.get(m.AuditBlock, data["audit_blk"])
        assert blk is not None
        assert "隔离边界" in blk.note
        assert blk.op_component == "platform-admin/tenant"


# ───────────────────────── 2. RBAC 实装与 AI 零角色断言 (FN-9-02) ─────────────────────────

def test_rbac_matrix_and_permissions(api_client):
    """验证 4×7(8) 角色权限矩阵结构。"""
    res = api_client.get("/api/platform/rbac")
    assert res.status_code == 200
    data = res.json()
    assert len(data["permissions"]) >= 7
    assert "案件查看" in data["permissions"]
    assert "受控 Action 放行/退回" in data["permissions"]
    assert "受理提交" in data["permissions"]
    assert len(data["roles"]) == 4

    admin_role = next(r for r in data["roles"] if r["name"] == "管理员")
    assert all(g == 1 for g in admin_role["grants"])  # 管理员全权限


def test_ai_agent_zero_role_strictly_enforced(api_client):
    """红线断言：AI / Agent / LLM 不持有任何 RBAC 角色，任何请求若由 AI 主体发起写操作直接拒绝。"""
    ai_actors = ["ai", "LLM-Agent", "qwen-finance-v2", "bot_assistant", "system-ai"]
    with persistence.get_session() as s:
        for actor in ai_actors:
            with pytest.raises(CommandError) as exc_info:
                rbac_service.require_permission(s, actor, "受控 Action 放行/退回")
            assert exc_info.value.code == E_PERM_DENIED
            assert "AI/Agent/LLM 不持有任何 RBAC 角色" in exc_info.value.message

        # 验证受控命令框架同样拦截 AI 标识发起受控写
        with pytest.raises(CommandError) as exc_info2:
            governed_commands.require_permission(s, "ai-agent", "release")
        assert exc_info2.value.code == E_PERM_DENIED


def test_rbac_update_matrix_and_audit(api_client):
    """角色权限矩阵更新生成 diff 并记入审计链。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/platform/rbac/matrix", json={
        "actor": "陈铮",
        "grants": {
            "运营": [1, 0, 0, 1, 0, 1, 0, 1],
        },
        "opinion": "微调运营权限",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["updated"] is True
    assert data["audit_blk"] > old_head


# ───────────────────────── 3. SSO 演示桩与服务端二次校验 (FN-9-03) ─────────────────────────

def test_sso_status_endpoint(api_client):
    """获取 SSO IdP 状态列表。"""
    res = api_client.get("/api/platform/sso/status")
    assert res.status_code == 200
    providers = res.json()["providers"]
    assert any(p["id"] == "sap_ias" and p["status"] == "已连接" for p in providers)
    assert any(p["id"] == "btp_xsuaa" and p["status"] == "已连接" for p in providers)
    assert any(p["id"] == "customer_ad" and p["status"] == "未连接" for p in providers)


def test_sso_login_success_and_locked_tenant(api_client):
    """SSO 登录成功：断言推导租户并在前端只读锁定。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/platform/sso/login", json={
        "idp_id": "sap_ias",
        "assertion": {
            "username": "王莉",
            "tenant_id": "TENANT-CN-LANWU-001",
        },
    })
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert data["tenant"]["readonly_locked"] is True
    assert "SAP IAS" in data["tenant"]["reason"]
    assert data["session_token"].startswith("sso-sess-")
    session_res = api_client.get("/api/platform/auth/session", headers={"Authorization": f"Bearer {data['session_token']}"})
    assert session_res.status_code == 200
    assert session_res.json()["auth_type"] == "SSO"
    with persistence.get_session() as s:
        assert audit_chain.head_blk(s) > old_head


def test_sso_secondary_verification_rejects_mismatch(api_client):
    """核心断言：若 IdP 断言推导租户与用户真实归属不符，服务端二次校验拒绝（E_TENANT_MISMATCH）。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    # 王莉为中国境内租户，断言声称为海外租户 TENANT-SG-LANWU-001
    res = api_client.post("/api/platform/sso/login", json={
        "idp_id": "sap_ias",
        "assertion": {
            "username": "王莉",
            "tenant_id": "TENANT-SG-LANWU-001",
        },
    })
    assert res.status_code == 403
    assert "服务端二次校验拒绝" in res.json()["detail"]
    # 违例尝试写入安全审计
    with persistence.get_session() as s:
        assert audit_chain.head_blk(s) > old_head


# ───────────────────────── 4. 登录、MFA 与用户管理 (FN-9-04, FN-9-05) ─────────────────────────

def test_password_login_mfa_enforced(api_client):
    """复核员/管理员角色强制要求 MFA 动态验证码。"""
    # 复核员王莉，未填 MFA 验证码 -> 401 拦截
    res = api_client.post("/api/platform/auth/login", json={
        "username": "王莉",
        "password": "valid_password",
        "tenant_id": "TENANT-CN-LANWU-001",
    })
    assert res.status_code == 401
    assert "MFA" in res.json()["detail"]

    # 先签发 MFA 挑战，再携带有效动态验证码 -> 成功登录
    chal = api_client.post("/api/platform/auth/mfa/challenge", json={
        "username": "王莉",
        "tenant_id": "TENANT-CN-LANWU-001",
    })
    assert chal.status_code == 200
    c = chal.json()
    res_ok = api_client.post("/api/platform/auth/login", json={
        "username": "王莉",
        "password": "valid_password",
        "tenant_id": "TENANT-CN-LANWU-001",
        "mfa_challenge_id": c["challenge_id"],
        "mfa_code": c["dev_code"],
        "remember_device": True,
    })
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["authenticated"] is True
    assert data["mfa_verified"] is True
    assert data["trusted_device_30d"] is True
    assert data["session_token"].startswith("pwd-sess-")

    session_res = api_client.get("/api/platform/auth/session", headers={"Authorization": f"Bearer {data['session_token']}"})
    assert session_res.status_code == 200
    assert session_res.json()["user"]["name"] == "王莉"


def test_users_list_all_mfa_enabled(api_client):
    """验收口径：全部用户 MFA 启用（FN-9-05）。"""
    res = api_client.get("/api/platform/users")
    assert res.status_code == 200
    users = res.json()["users"]
    assert len(users) == 4
    for u in users:
        assert u["mfa"] == "✓ 已启用"
        assert u["status"] == "启用"


# ───────────────────────── 5. 监控与队列 (FN-9-06, FN-9-07) ─────────────────────────

def test_service_health_six_cards(api_client):
    """验证服务健康 6 卡及 24h 时序序列。"""
    res = api_client.get("/api/platform/health")
    assert res.status_code == 200
    data = res.json()
    assert "6/6 在线" in data["status"]
    assert len(data["cards"]) == 6
    for card in data["cards"]:
        assert card["ok"] is True
        assert len(card["data"]) == 24  # 24 小时点


def test_async_queue_governance(api_client):
    """验证 4 异步队列真实统计与健康状态。"""
    res = api_client.get("/api/platform/queues")
    assert res.status_code == 200
    data = res.json()
    assert data["broker"] == "Redis Streams"
    assert len(data["queues"]) == 4
    queue_names = [q["name"] for q in data["queues"]]
    assert "识别任务" in queue_names
    assert "归档任务" in queue_names
    assert "回调重试" in queue_names
    assert "Provider 超时重试" in queue_names


# ───────────────────────── 6. 告警引擎与红线不可停用 (FN-9-08) ─────────────────────────

def test_alert_rules_list(api_client):
    """验证告警规则 4 基线规则。"""
    res = api_client.get("/api/platform/alerts/rules")
    assert res.status_code == 200
    rules = res.json()["rules"]
    assert len(rules) == 4
    redline_rule = next(r for r in rules if r.get("redline"))
    assert redline_rule["name"] == "错误自动放行率 > 0.05%"
    assert redline_rule["level"] == "danger"


def test_redline_alert_disable_blocked_and_audited(api_client):
    """验收要点①：产品红线告警不可停用，关闭被拦截、开关回弹且尝试行为记入审计日志。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/platform/alerts/rules/false_auto_release_rate/toggle", json={
        "actor": "陈铮",
        "new_state": False,  # 尝试关闭红线告警
        "opinion": "测试停用红线",
    })
    # 期望 403 拦截
    assert res.status_code == 403
    assert "不可停用" in res.json()["detail"]
    assert "已记入审计日志" in res.json()["detail"]

    # 验证审计链确实记录了违规尝试
    with persistence.get_session() as s:
        new_head = audit_chain.head_blk(s)
        assert new_head > old_head
        blk = s.get(m.AuditBlock, new_head)
        assert "【红线告警拦截】" in blk.note
        assert blk.op_component == "platform-admin/redline-guard"

    # 验证规则本身保持 on=True（回弹）
    rules_res = api_client.get("/api/platform/alerts/rules")
    redline_rule = next(r for r in rules_res.json()["rules"] if r["rule_id"] == "false_auto_release_rate")
    assert redline_rule["on"] is True


def test_normal_alert_toggle_success(api_client):
    """普通告警规则允许切换并审计留痕。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    res = api_client.post("/api/platform/alerts/rules/queue_backlog/toggle", json={
        "actor": "陈铮",
        "new_state": False,
        "opinion": "排查运维",
    })
    assert res.status_code == 200
    assert res.json()["on"] is False
    with persistence.get_session() as s:
        assert audit_chain.head_blk(s) > old_head


# ───────────────────────── 7. 配置中心与适配器兼容校验 (FN-9-09) ─────────────────────────

def test_config_diff_and_reset_zero_audit(api_client):
    """配置 diff 计算及重置草稿零审计断言。"""
    # 1. 存草稿
    api_client.post("/api/platform/config/draft", json={
        "actor": "陈铮",
        "values": {
            "threshold": 0.90,
            "tolerance": "±0.08",
            "po_tolerance": "±S$50",
            "lowConfManual": True,
            "newCustReview": True,
            "regionRoute": "中国票据 → 境内 Provider 优先 / 海外票据 → 新加坡区域",
        },
    })
    # 2. 查询 diff
    diff_res = api_client.get("/api/platform/config/diff")
    assert diff_res.status_code == 200
    diffs = diff_res.json()["diffs"]
    assert len(diffs) >= 2
    keys = [d["key"] for d in diffs]
    assert "threshold" in keys
    assert "newCustReview" in keys

    # 3. 重置草稿
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    reset_res = api_client.post("/api/platform/config/reset", json={})
    assert reset_res.status_code == 200
    assert reset_res.json()["audit_produced"] is False

    # 断言链头完全未变（零审计）
    with persistence.get_session() as s:
        assert audit_chain.head_blk(s) == old_head


def test_config_publish_version_diff_and_adapter_notifications(api_client):
    """配置发布：版本递增 + 审计留痕 + 联动 5 大目标适配器兼容性校验通知。"""
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    pub_res = api_client.post("/api/platform/config/publish", json={
        "actor": "陈铮",
        "values": {
            "threshold": 0.88,
            "tolerance": "±0.06",
            "po_tolerance": "±S$50",
            "lowConfManual": True,
            "newCustReview": False,
            "regionRoute": "中国票据 → 境内 Provider 优先 / 海外票据 → 新加坡区域",
        },
        "opinion": "微调置信度阈值至 0.88",
    })
    assert pub_res.status_code == 200
    data = pub_res.json()
    assert data["published"] is True
    assert data["version"].startswith("v2026-")
    assert data["audit_blk"] > old_head

    # 验证联动适配器兼容性校验通知
    notifs = data["adapter_notifications"]
    assert len(notifs) >= 5
    adapter_names = [n["adapter"] for n in notifs]
    assert "SAP Ariba" in adapter_names
    assert "Oracle ERP" in adapter_names
    assert "Coupa" in adapter_names
    assert "SAP S/4HANA" in adapter_names
    assert all(n["status"] == "COMPATIBLE" for n in notifs)


def test_config_redline_bypass_prevented(api_client):
    """红线项关闭拦截：lowConfManual 不得设为 False。"""
    res = api_client.post("/api/platform/config/publish", json={
        "actor": "陈铮",
        "values": {
            "threshold": 0.85,
            "tolerance": "±0.06",
            "po_tolerance": "±S$50",
            "lowConfManual": False,  # 违例尝试关闭低置信强制人工
            "newCustReview": False,
            "regionRoute": "中国票据 → 境内 Provider 优先 / 海外票据 → 新加坡区域",
        },
        "opinion": "尝试关闭低置信人工",
    })
    assert res.status_code == 403
    assert "配置红线违例" in res.json()["detail"]


# ───────────────────────── 8. KMS 密钥与模型数据边界 (FN-9-10, FN-9-11) ─────────────────────────

def test_kms_keys_masked_and_rotate(api_client):
    """KMS 凭证全掩码显示与轮换流程留痕。"""
    res = api_client.get("/api/platform/kms/keys")
    assert res.status_code == 200
    keys = res.json()["keys"]
    assert len(keys) == 4
    for k in keys:
        assert k["masked_value"].startswith("****")

    # 申请轮换
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    rot_res = api_client.post("/api/platform/kms/keys/bw-cloud-key/rotate", json={
        "actor": "陈铮",
        "reason": "定期密钥轮换",
    })
    assert rot_res.status_code == 200
    with persistence.get_session() as s:
        assert rot_res.json()["audit_blk"] > old_head


def test_model_data_boundary_and_cleanup(api_client):
    """模型数据边界管控与 30 天清理任务。"""
    res = api_client.get("/api/platform/model-boundary")
    assert res.status_code == 200
    b = res.json()["boundary"]
    assert b["prompt_retention_days"] == 30
    assert b["audit_enabled"] is True

    # 执行清理
    with persistence.get_session() as s:
        old_head = audit_chain.head_blk(s)

    clean_res = api_client.post("/api/platform/model-boundary/cleanup", json={"actor": "陈铮"})
    assert clean_res.status_code == 200
    assert clean_res.json()["cleaned_records"] > 0
    with persistence.get_session() as s:
        assert audit_chain.head_blk(s) > old_head
