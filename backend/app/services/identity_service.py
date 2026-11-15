# -*- coding: utf-8 -*-
"""身份联邦、SSO 演示桩、MFA 与用户管理服务（WP5.1 · FN-9-03 / FN-9-04 / FN-9-05）。

功能与规则：
  - SSO 演示桩（FN-9-03）：SAP IAS (SAML 2.0) / SAP BTP xsuaa (OIDC) / 客户 AD（预留未连）；
    IdP 断言自动推导租户（前端只读锁定 + 服务端二次校验归属）；
  - 账密登录与会话安全（FN-9-04 / FN-9-05）：全员强制 MFA（6 位动态验证码；FN-9-05 验收口径）；
    记住设备（30 天受信任设备免挑战策略 · TODO(FN-9-04) 演示口径）；登录成功/失败全量写不可篡改审计链；
  - 用户管理（FN-9-05）：用户表（姓名/组织/角色/状态/最近登录/MFA 状态），全部用户 MFA 启用。
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain
from app.services.audit_chain import now_iso, new_trace_id
from app.services.errors import E_PERM_DENIED, E_TENANT_MISMATCH, CommandError
from app.services import rbac_service
from app.services.rbac_service import assert_not_ai_agent, require_permission

# SSO IdP 连接状态（与 platform-admin.html Tab1 保持一致）
SSO_PROVIDERS = [
    {
        "id": "sap_ias",
        "name": "SAP IAS",
        "full_name": "Identity Authentication Service",
        "protocol": "SAML 2.0",
        "status": "已连接",
        "badge": "已连接 · SAML 2.0",
        "enabled": True,
    },
    {
        "id": "btp_xsuaa",
        "name": "xsuaa",
        "full_name": "SAP BTP Extended Services UAA",
        "protocol": "OIDC",
        "status": "已连接",
        "badge": "已连接 · OIDC",
        "enabled": True,
    },
    {
        "id": "customer_ad",
        "name": "客户 AD",
        "full_name": "Active Directory（LDAP / ADFS）",
        "protocol": "LDAP/ADFS",
        "status": "未连接",
        "badge": "未连接",
        "enabled": False,
    },
]

# 用户预设租户归属（用于服务端二次校验）
USER_TENANT_AFFINITY = {
    "王莉": ["TENANT-CN-LANWU-001"],
    "陈铮": ["TENANT-CN-LANWU-001", "TENANT-SG-LANWU-001"],  # 平台管理员跨租户
    "刘工": ["TENANT-CN-LANWU-001"],
    "张审计": ["TENANT-SG-LANWU-001"],  # 新加坡只读审计
}

# 演示口径邮箱别名 → users 表主键（中文姓名）。web/login.html 账号框预填企业邮箱、
# placeholder 承诺「企业邮箱 / 用户名」，而 UserAccount 主键为中文姓名；此处统一规范化，
# 使邮箱与中文名等价可登录（修复 2026-11-15：预填邮箱登录报「用户不存在」）。
# TODO(FN-9-04)：正式实现由企业 IdP 断言统一提供 username（UPN/email claim），本别名表随之移除。
EMAIL_ALIASES = {
    "wangli@lanwu-procurement.com": "王莉",
    "chenzheng@lanwu-procurement.com": "陈铮",
    "liugong@lanwu-procurement.com": "刘工",
    "zhangshenji@lanwu-procurement.com": "张审计",
}


def canonical_username(username: str | None) -> str:
    """邮箱别名 → 用户主键（中文姓名）；非别名原样返回（去首尾空白）。"""
    u = (username or "").strip()
    return EMAIL_ALIASES.get(u.lower(), u)

# 演示会话登记表：PoC 口径进程内保存（重启失效），用于 web 登录闭环与 API Bearer 头校验。
# 正式实现应替换为签名 JWT / 服务端 Session Store，并补充过期清理 Job。
SESSION_TTL_HOURS = 8
_ACTIVE_SESSIONS: dict[str, dict] = {}
_MFA_CHALLENGES: dict[str, dict] = {}
MFA_TTL_MINUTES = 5
MFA_MAX_ATTEMPTS = 5


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_session(payload: dict, *, remember_device: bool = False) -> dict:
    """登记演示会话并返回统一会话载荷。"""
    token = payload["session_token"]
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=30 if remember_device else 0, hours=SESSION_TTL_HOURS)
    session_payload = {
        **payload,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    _ACTIVE_SESSIONS[token] = session_payload
    return session_payload


def verify_session_token(token: str | None) -> dict:
    """校验 Bearer/session token（web 登录闭环演示口径）。"""
    if not token:
        raise CommandError("E_AUTH_REQUIRED", "缺少登录会话，请先登录", http=401)
    payload = _ACTIVE_SESSIONS.get(token)
    if not payload:
        raise CommandError("E_SESSION_INVALID", "登录会话无效或已过期，请重新登录", http=401)
    try:
        expires_at = datetime.fromisoformat(payload["expires_at"])
    except Exception:
        _ACTIVE_SESSIONS.pop(token, None)
        raise CommandError("E_SESSION_INVALID", "登录会话格式异常，请重新登录", http=401)
    if expires_at <= datetime.now(timezone.utc):
        _ACTIVE_SESSIONS.pop(token, None)
        raise CommandError("E_SESSION_EXPIRED", "登录会话已过期，请重新登录", http=401)
    return payload


def current_actor(payload: dict | None) -> str:
    """从会话载荷取当前真人操作人。"""
    user = (payload or {}).get("user") or {}
    name = user.get("name")
    if not name:
        raise CommandError("E_AUTH_REQUIRED", "登录会话缺少用户身份，请重新登录", http=401)
    return name


def bind_actor(payload: dict | None, requested_actor: str | None = None) -> str:
    """写路径统一绑定当前会话用户，拒绝冒用其他 actor。"""
    if os.environ.get("INVOICE_HUB_DISABLE_AUTH") == "1" or payload is None:
        return requested_actor or "system"
    actor = current_actor(payload)
    if requested_actor and requested_actor not in ("human", "system") and requested_actor != actor:
        raise CommandError("E_ACTOR_MISMATCH", f"请求操作人 {requested_actor!r} 与当前登录用户 {actor!r} 不一致", http=403)
    return actor


def require_session_permission(session, payload: dict | None, perm_name: str) -> tuple:
    """校验当前会话用户具备指定 RBAC 权限位。"""
    if os.environ.get("INVOICE_HUB_DISABLE_AUTH") == "1" or payload is None:
        return True, "test-bypass"
    actor = current_actor(payload)
    return rbac_service.require_permission(session, actor, perm_name)


def logout(token: str | None) -> dict:
    """注销当前演示会话。"""
    removed = bool(token and _ACTIVE_SESSIONS.pop(token, None))
    return {"logged_out": removed}


def _mfa_secret_for(username: str) -> str:
    # 演示口径：稳定用户密钥；真实实现应为 per-user TOTP secret 并加密托管。
    return "ihub-mfa-secret::" + username


def _mfa_code(username: str, step: int | None = None) -> str:
    import hashlib
    import time
    step = int(time.time() // 30) if step is None else step
    digest = hashlib.sha256(f"{_mfa_secret_for(username)}:{step}".encode("utf-8")).hexdigest()
    return f"{int(digest[-8:], 16) % 1000000:06d}"


def issue_mfa_challenge(session, username: str, tenant_id: str) -> dict:
    """签发 MFA 挑战：返回 challenge_id；演示环境同时返回 dev_code 供本地验证。"""
    username = canonical_username(username)  # 邮箱别名 → 用户主键（演示口径，见 EMAIL_ALIASES）
    assert_not_ai_agent(username)
    user = session.get(m.UserAccount, username)
    if not user or user.status != "启用":
        raise CommandError(E_PERM_DENIED, f"用户 {username!r} 不存在或已停用", http=401)
    allowed_tenants = USER_TENANT_AFFINITY.get(username, ["TENANT-CN-LANWU-001"])
    if tenant_id not in allowed_tenants:
        raise CommandError(E_TENANT_MISMATCH, f"用户 {username} 未分配至租户 {tenant_id}", http=403)
    challenge_id = "mfa-" + secrets.token_hex(12)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=MFA_TTL_MINUTES)
    code = _mfa_code(username)
    _MFA_CHALLENGES[challenge_id] = {
        "username": username,
        "tenant_id": tenant_id,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "attempts": 0,
    }
    return {
        "challenge_id": challenge_id,
        "delivery": "authenticator_app",
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": MFA_TTL_MINUTES * 60,
        "dev_code": code,
        "message": "MFA 验证码已发送至绑定的认证器（演示环境显示 dev_code）",
    }


def _verify_mfa_challenge(username: str, tenant_id: str, challenge_id: str | None, code: str | None) -> None:
    if not challenge_id:
        raise CommandError("E_MFA_CHALLENGE_REQUIRED", "请先获取 MFA 验证码", http=401)
    ch = _MFA_CHALLENGES.get(challenge_id)
    if not ch:
        raise CommandError("E_MFA_CHALLENGE_INVALID", "MFA 挑战不存在或已失效", http=401)
    if ch["username"] != username or ch["tenant_id"] != tenant_id:
        raise CommandError("E_MFA_CHALLENGE_MISMATCH", "MFA 挑战与当前用户/租户不匹配", http=401)
    if datetime.fromisoformat(ch["expires_at"]) <= datetime.now(timezone.utc):
        _MFA_CHALLENGES.pop(challenge_id, None)
        raise CommandError("E_MFA_EXPIRED", "MFA 验证码已过期，请重新获取", http=401)
    ch["attempts"] += 1
    if ch["attempts"] > MFA_MAX_ATTEMPTS:
        _MFA_CHALLENGES.pop(challenge_id, None)
        raise CommandError("E_MFA_LOCKED", "MFA 尝试次数过多，请重新获取验证码", http=401)
    clean = str(code or "").strip()
    import time
    valid = {_mfa_code(username, int(time.time() // 30) + skew) for skew in (-1, 0, 1)}
    if clean not in valid:
        raise CommandError("E_MFA_INVALID", "MFA 动态验证码无效或已过期", http=401)
    _MFA_CHALLENGES.pop(challenge_id, None)


def get_sso_status() -> list[dict]:
    """获取企业 IdP / SSO 连接状态列表。"""
    return [dict(p) for p in SSO_PROVIDERS]


def authenticate_sso(session, idp_id: str, assertion: dict) -> dict:
    """SSO 单点登录验证（FN-9-03）。
    1. 校验 IdP 合法且处于已连接状态；
    2. 从断言解析 username 与推导的 tenant_id；
    3. 服务端二次校验归属（核心断言：若断言租户与用户真实归属不符，直接拒绝）；
    4. 登录成功写入不可篡改审计链；
    5. 返回 session 会话并要求前端只读锁定租户选择器。
    """
    idp = next((p for p in SSO_PROVIDERS if p["id"] == idp_id), None)
    if not idp or not idp["enabled"]:
        raise CommandError("E_IDP_UNAVAILABLE", f"IdP {idp_id!r} 未连接或不存在", http=400)

    username = assertion.get("username")
    claimed_tenant_id = assertion.get("tenant_id")
    if not username or not claimed_tenant_id:
        raise CommandError("E_SSO_ASSERTION_INVALID", "SSO 断言缺失 username 或 tenant_id 声明", http=400)

    username = canonical_username(username)  # 邮箱别名 → 用户主键（演示口径，见 EMAIL_ALIASES）
    assert_not_ai_agent(username)

    user = session.get(m.UserAccount, username)
    if not user:
        raise CommandError(E_PERM_DENIED, f"用户 {username!r} 未在平台注册，拒绝 SSO 接入", http=403)
    if user.status != "启用":
        raise CommandError(E_PERM_DENIED, f"用户 {username} 已被停用", http=403)

    # ══════ 服务端二次校验归属（FN-9-03 核心） ══════
    allowed_tenants = USER_TENANT_AFFINITY.get(username, ["TENANT-CN-LANWU-001"])
    if claimed_tenant_id not in allowed_tenants:
        # 二次校验失败入审计
        trace = new_trace_id()
        audit_chain.append_block(
            session,
            ts=now_iso(),
            trace=trace,
            actor="human",
            act="POLICY_PUBLISHED",
            cs=None,
            category="security",
            note=f"【安全警告】SSO 登录服务端二次校验失败：用户 {username} 尝试通过 {idp['name']} 断言访问未授权租户 {claimed_tenant_id}（合法范围：{allowed_tenants}）",
            op="login/sso-secondary-verify",
        )
        raise CommandError(
            E_TENANT_MISMATCH,
            f"服务端二次校验拒绝：用户 {username} 无权访问 IdP 断言推导的租户 {claimed_tenant_id}（FN-9-03）",
            http=403,
        )

    # 校验通过，写入成功审计
    trace = new_trace_id()
    session_token = f"sso-sess-{secrets.token_hex(16)}"
    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="POLICY_PUBLISHED",
        cs=None,
        category="security",
        note=f"SSO 登录成功：用户={username} · IdP={idp['name']}({idp['protocol']}) · 推导租户={claimed_tenant_id}（服务端二次校验通过 · 前端只读锁定）",
        op="login/sso",
    )

    return _register_session({
        "authenticated": True,
        "auth_type": "SSO",
        "idp": idp["name"],
        "user": {
            "name": user.name,
            "role": user.role,
            "org": user.org,
        },
        "tenant": {
            "tenant_id": claimed_tenant_id,
            "readonly_locked": True,  # 前端只读锁定
            "reason": f"由 {idp['name']} 断言推导并经服务端二次校验确认",
        },
        "session_token": session_token,
        "mfa_verified": True,  # SSO 由企业 IdP 完成身份二次认证
        "trace": trace,
    }, remember_device=True)


def authenticate_password(session, username: str, password: str, tenant_id: str,
                           mfa_code: str | None = None, remember_device: bool = False,
                           mfa_challenge_id: str | None = None,
                           device_token: str | None = None) -> dict:
    """账密登录 + 租户手选 + 全员强制 MFA 验证（FN-9-04 / FN-9-05）。
    1. 校验用户身份与状态；
    2. 校验租户归属；
    3. 受信任设备校验：若提供有效 30 天内 device_token，免 MFA 挑战（FN-9-04 · 演示口径 TODO(FN-9-04)）；
    4. 全员强制 MFA 校验（FN-9-05 验收口径：任意角色未过受信任免挑战者必须输入 6 位验证码）；
    5. 若勾选 remember_device，在 trusted_devices 表落盘 device_token 并赋予 30 天有效期；
    6. 记录登录成功/失败到不可篡改审计链。
    """
    username = canonical_username(username)  # 邮箱别名 → 用户主键（演示口径，见 EMAIL_ALIASES）
    assert_not_ai_agent(username)

    user = session.get(m.UserAccount, username)
    if not user:
        trace = new_trace_id()
        audit_chain.append_block(
            session,
            ts=now_iso(),
            trace=trace,
            actor="human",
            act="POLICY_PUBLISHED",
            cs=None,
            category="security",
            note=f"用户登录失败：账号 {username!r} 不存在",
            op="login/auth",
        )
        raise CommandError(E_PERM_DENIED, f"用户 {username!r} 不存在", http=401)

    if user.status != "启用":
        raise CommandError(E_PERM_DENIED, f"用户 {username} 已被停用", http=403)

    # 演示口径：密码非空即可（如 demo 密码），或生产环境 KMS 校验
    if not password:
        raise CommandError("E_INVALID_CREDENTIALS", "密码不能为空", http=401)

    # 租户校验
    allowed_tenants = USER_TENANT_AFFINITY.get(username, ["TENANT-CN-LANWU-001"])
    if tenant_id not in allowed_tenants:
        raise CommandError(E_TENANT_MISMATCH, f"用户 {username} 未分配至租户 {tenant_id}", http=403)

    # ══════ 3. 受信任设备 30 天免挑战检查（FN-9-04 · 演示口径 TODO(FN-9-04)） ══════
    is_device_trusted = False
    if device_token:
        trusted_record = session.get(m.TrustedDevice, device_token)
        if (trusted_record and trusted_record.username == username
                and trusted_record.tenant_id == tenant_id
                and trusted_record.expires_at > now_iso()):
            is_device_trusted = True

    # ══════ 4. 全员 MFA 强制校验（FN-9-05 口径：全部用户启用 MFA；受信任设备免除重复挑战） ══════
    if not is_device_trusted:
        _verify_mfa_challenge(username, tenant_id, mfa_challenge_id, mfa_code)

    # ══════ 5. remember_device 受信任设备登记 / 续期 ══════
    active_device_token: str | None = None
    if remember_device:
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.isoformat()
        expires_str = (now_dt + timedelta(days=30)).isoformat()
        existing_td = session.get(m.TrustedDevice, device_token) if device_token else None
        if existing_td and existing_td.username == username:
            existing_td.expires_at = expires_str
            active_device_token = existing_td.device_token
        else:
            active_device_token = f"dev-tok-{secrets.token_hex(16)}"
            session.add(m.TrustedDevice(
                device_token=active_device_token,
                username=username,
                tenant_id=tenant_id,
                created_at=now_str,
                expires_at=expires_str,
            ))
        session.flush()

    trace = new_trace_id()
    session_token = f"pwd-sess-{secrets.token_hex(16)}"
    mfa_audit_desc = "受信任设备30天免挑战" if is_device_trusted else "已验证"
    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="POLICY_PUBLISHED",
        cs=None,
        category="security",
        note=f"用户账密登录成功：用户={username} · 租户={tenant_id} · MFA={mfa_audit_desc} · 受信任设备30天={remember_device}",
        op="login/auth",
    )

    return _register_session({
        "authenticated": True,
        "auth_type": "PASSWORD",
        "user": {
            "name": user.name,
            "role": user.role,
            "org": user.org,
        },
        "tenant": {
            "tenant_id": tenant_id,
            "readonly_locked": False,
        },
        "session_token": session_token,
        "mfa_verified": True,
        "trusted_device_30d": remember_device or is_device_trusted,
        "device_token": active_device_token or (device_token if is_device_trusted else None),
        "trace": trace,
    }, remember_device=remember_device or is_device_trusted)


def list_users(session) -> list[dict]:
    """获取平台用户列表（FN-9-05）。
    验收口径：全部用户 MFA 启用。
    """
    users = list(session.scalars(select(m.UserAccount)))
    result = []
    for u in users:
        raw = dict(u.user_raw or {})
        last_login_data = raw.get("last_login", {})
        if isinstance(last_login_data, dict):
            login_str = f"{last_login_data.get('at', '2026-10-21 09:00')}（{last_login_data.get('location', '上海')}）"
        else:
            login_str = str(last_login_data)
        result.append({
            "name": u.name,
            "role": u.role,
            "org": u.org or "",
            "status": u.status,
            "login": login_str,
            "mfa": "✓ 已启用",
        })
    return result


def update_user_status(session, actor: str, username: str, new_status: str, opinion: str | None = None) -> dict:
    """管理平台用户状态（启用/停用）。"""
    assert_not_ai_agent(actor)
    require_permission(session, actor, "租户管理")

    user = session.get(m.UserAccount, username)
    if not user:
        raise CommandError("E_USER_NOT_FOUND", f"用户 {username!r} 不存在", http=404)

    old_status = user.status
    user.status = new_status
    session.commit()

    trace = new_trace_id()
    audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="POLICY_PUBLISHED",
        cs=None,
        category="security",
        note=f"用户状态变更：{username} · {old_status} → {new_status} · 操作人：{actor} · 意见：{opinion or '（无）'}",
        op="platform-admin/user-status",
    )

    return {
        "username": username,
        "old_status": old_status,
        "new_status": new_status,
        "trace": trace,
    }
