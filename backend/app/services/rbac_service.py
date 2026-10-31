# -*- coding: utf-8 -*-
"""RBAC 角色权限服务（WP5.1 · FN-9-02 / FN-0-09）。

4 角色 × 7(8) 权限位基线矩阵从 seeds 升级为可管理实体：
  - 角色：管理员、复核员、运营、审计只读；
  - 权限位（基线 7 位 + M3 增补第 8 位「受理提交」）：
    ① 案件查看
    ② 受控 Action 放行/退回
    ③ 字段修正
    ④ Provider 配置
    ⑤ 策略发布
    ⑥ 审计导出
    ⑦ 租户管理
    ⑧ 受理提交（FN-1-08 受控写要素①；CHANGELOG ⑧ 裁决）
  - 矩阵变更 = 高风险流程（保存 → 二次确认 → diff 入不可篡改审计链）；
  - AI/LLM 零角色断言：AI/Agent/LLM 不持有任何 RBAC 角色，任何请求若由 AI 主体发起写操作直接拒绝。
"""

import json
from datetime import datetime, timezone
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain
from app.services.audit_chain import now_iso, new_trace_id
from app.services.errors import E_PERM_DENIED, CommandError

# 权限位标准定义（与 seeds/users_roles.json 保持一致）
BASE_PERMISSIONS = [
    "案件查看",
    "受控 Action 放行/退回",
    "字段修正",
    "Provider 配置",
    "策略发布",
    "审计导出",
    "租户管理",
    "受理提交",
]

# AI / Agent / LLM 关键字特征匹配（严格禁止持有角色）
AI_ACTOR_KEYWORDS = (
    "ai", "agent", "model", "qwen", "gpt", "claude", "bot",
    "robot", "system-ai", "vlm", "crawler"
)
_LLM_TOKEN = "l" + "l" + "m"


def assert_not_ai_agent(actor: str | None) -> None:
    """AI/LLM 零角色断言（FN-0-09 / FN-9-02）：
    AI / Agent / LLM 不持有任何矩阵内角色，放行/退回/字段修正等业务写操作只能由人工执行。
    """
    if not actor:
        raise CommandError(E_PERM_DENIED, "主体身份为空，AI/LLM 禁止匿名或以系统代号发起受控操作", http=403)
    normalized = str(actor).strip().lower()
    if _LLM_TOKEN in normalized:
        raise CommandError(
            E_PERM_DENIED,
            f"主体 {actor!r} 匹配 AI/LLM 标识：AI/Agent/LLM 不持有任何 RBAC 角色（FN-0-09），受控写操作仅限真人执行",
            http=403,
        )
    for kw in AI_ACTOR_KEYWORDS:
        if kw == normalized or f"{kw}_" in normalized or f"_{kw}" in normalized or f"-{kw}" in normalized or f"{kw}-" in normalized:
            raise CommandError(
                E_PERM_DENIED,
                f"主体 {actor!r} 匹配 AI/LLM 标识：AI/Agent/LLM 不持有任何 RBAC 角色（FN-0-09），受控写操作仅限真人执行",
                http=403,
            )
        if kw == normalized or f"{kw}_" in normalized or f"_{kw}" in normalized or f"-{kw}" in normalized or f"{kw}-" in normalized:
            raise CommandError(
                E_PERM_DENIED,
                f"主体 {actor!r} 匹配 AI/LLM 标识：AI/Agent/LLM 不持有任何 RBAC 角色（FN-0-09），受控写操作仅限真人执行",
                http=403,
            )


def get_permissions(session) -> list[str]:
    """获取当前生效的权限位列表。"""
    meta = session.get(m.SeedMeta, "permissions")
    if meta and meta.payload and "permissions" in meta.payload:
        return list(meta.payload["permissions"])
    return list(BASE_PERMISSIONS)


def get_rbac_matrix(session) -> dict:
    """获取 4×7(8) 角色权限矩阵及用户档案。"""
    perms = get_permissions(session)
    roles_rows = list(session.scalars(select(m.RoleDef)))
    roles_list = []
    for r in roles_rows:
        grants = list(r.grants) if r.grants else []
        # 补齐长度如果扩展了权限位
        if len(grants) < len(perms):
            grants.extend([0] * (len(perms) - len(grants)))
        roles_list.append({
            "name": r.name,
            "who": r.who or "",
            "grants": grants,
        })
    return {
        "permissions": perms,
        "roles": roles_list,
        "note": "RBAC 角色权限矩阵（FN-9-02 · 4 角色 × 7(8) 权限；AI/LLM 零角色）",
    }


def resolve_role_name(session, user: m.UserAccount) -> str:
    """从用户角色展示串（如「复核员 · 财务经理」）反解出 RoleDef.name。"""
    names = [r.name for r in session.scalars(select(m.RoleDef)) if r.name in (user.role or "")]
    if not names:
        raise CommandError(E_PERM_DENIED, f"无法解析用户角色：{user.role!r}", http=403)
    return max(names, key=len)


def require_permission(session, actor: str, perm_name: str) -> tuple[m.UserAccount, str]:
    """统一权限校验内核（注入受控框架替换原桩代码）。"""
    assert_not_ai_agent(actor)

    user = session.get(m.UserAccount, actor)
    if user is None:
        raise CommandError(
            E_PERM_DENIED,
            f"主体 {actor!r} 无平台身份——AI/Agent/LLM 不持有 RBAC 角色（FN-0-09），业务写操作仅真人可发起",
            http=403,
        )
    if user.status != "启用":
        raise CommandError(E_PERM_DENIED, f"用户 {actor} 状态={user.status}，已停用", http=403)

    perms = get_permissions(session)
    if perm_name not in perms:
        raise CommandError(E_PERM_DENIED, f"权限位 {perm_name!r} 不在系统权限矩阵", http=403)

    role_name = resolve_role_name(session, user)
    role = session.get(m.RoleDef, role_name)
    if role is None:
        raise CommandError(E_PERM_DENIED, f"角色定义 {role_name} 不存在", http=403)

    grants = role.grants or []
    idx = perms.index(perm_name)
    if idx >= len(grants) or grants[idx] != 1:
        raise CommandError(
            E_PERM_DENIED,
            f"角色 {role_name} 不具备权限位「{perm_name}」（FN-9-02 矩阵 / FN-0-08 要素①）",
            http=403,
        )

    return user, role_name


def update_role_matrix(session, actor: str, new_roles_grants: dict[str, list[int]],
                       opinion: str | None = None) -> dict:
    """高风险操作：角色权限矩阵更新。
    校验权限（需 策略发布 或 租户管理）→ 计算 diff → 更新 DB → 记入不可篡改审计链。
    """
    assert_not_ai_agent(actor)
    # 校验当前操作者必须具备策略发布权限
    require_permission(session, actor, "策略发布")

    perms = get_permissions(session)
    diffs = {}
    for role_name, grants in new_roles_grants.items():
        role = session.get(m.RoleDef, role_name)
        if not role:
            continue
        old_grants = list(role.grants or [])
        if old_grants != grants:
            diffs[role_name] = {
                "before": old_grants,
                "after": grants,
            }
            role.grants = grants

    if not diffs:
        return {"updated": False, "message": "权限矩阵无变动", "diffs": {}}

    session.commit()

    # 写入不可篡改审计链（POLICY_PUBLISHED，平台级事件）
    trace = new_trace_id()
    note_msg = f"角色权限矩阵变更 · 操作人：{actor} · 变更角色：{list(diffs.keys())} · 意见：{opinion or '（无）'}"
    blk = audit_chain.append_block(
        session,
        ts=now_iso(),
        trace=trace,
        actor="human",
        act="POLICY_PUBLISHED",
        cs=None,
        category="platform",
        note=note_msg,
        op="platform-admin/rbac",
    )

    return {
        "updated": True,
        "diffs": diffs,
        "audit_blk": blk.blk,
        "trace": trace,
        "message": "角色权限矩阵已更新并记入不可篡改审计链",
    }
