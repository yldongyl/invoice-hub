# -*- coding: utf-8 -*-
"""工作台支撑服务（WP3.4 · FN-8-01 队列归属 / FN-8-07 导出闭环 / FN-8-06 会签人）。

导出自审计口径（FN-0-08 附加规则）：AUDIT_EXPORT 块先入链（governed._do_export），
链头拿到 blk 后才发放下载票据——ticket.blk 即链头块高，供断言；CSV 落 runtime/exports/，
链接 24h 失效（演示口径：到期 410，重导重签发重入链）。
"""

import csv
import io
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.domain import models as m
from app.services import config_center, state_machine
from app.services.errors import CommandError
from app.services.tenant import TenantContext

STATUS = state_machine.STATUS

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "runtime" / "exports"

QUEUE_LABEL = {"CN": "亚太采购共享中心", "OS": "新加坡共享中心"}   # workbench Header 队列归属展示口径
EXPORT_TTL_HOURS = 24                                             # FN-8-07 页面口径「24 小时后失效（演示口径）」


def queue_stats(session, ctx: TenantContext) -> dict:
    """队列归属 + 待复核数 + BLOCKED 高风险数（SLA 30 分钟认领口径=sla_targets）。"""
    from app.services import case_repository as repo
    def _count(status: str) -> int:
        return session.scalar(select(func.count()).select_from(m.Case).where(
            m.Case.instance == ctx.instance, m.Case.status == status)) or 0
    sla = config_center.get_effective(session, "__sla_targets")
    return {
        "instance": ctx.instance,
        "queue": QUEUE_LABEL.get(ctx.instance, ctx.instance),
        "pending_review": _count(STATUS.NEEDS_REVIEW) + _count(STATUS.INVESTIGATING),
        "needs_review": _count(STATUS.NEEDS_REVIEW),
        "investigating": _count(STATUS.INVESTIGATING),
        "blocked": _count(STATUS.BLOCKED),
        "claim_high_risk_minutes": (sla.value_raw or {}).get("claim_high_risk_minutes", 30)
                                   if sla else 30,
        "claimed_by_me": 0,   # 会话身份演示桩：actor 级认领统计待 M5 身份（FN-9-05）
        "note": "待复核数=NEEDS_REVIEW+INVESTIGATING 队列态合计（CON-11）；"
                "BLOCKED 高风险案件 30 分钟内认领 SLA（FN-8-02）",
    }


def _filters_to_kwargs(filters: dict | None) -> dict:
    """检索条件→列表过滤（导出留痕与实发内容同源；未知键忽略并入链注记）。"""
    f = filters or {}
    kw = {}
    for key in ("status", "keyword", "risk"):
        if f.get(key):
            kw[key] = str(f[key])
    return kw


def build_csv(session, ctx: TenantContext, filters: dict | None) -> tuple[str, int]:
    """按条件拉全量匹配案件生成 CSV（列=FN-8-01 列表口径）；返回 (csv_text, rows)。"""
    from app.services import case_repository as repo
    items, total, _, _ = repo.list_cases(session, ctx, page=1, page_size=500,
                                          **_filters_to_kwargs(filters))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["案件号", "供应商", "金额", "地区", "状态", "风险标签", "置信度",
                "Provider", "票种", "摘要（规则引擎结论）"])
    for it in items:
        meta = it.get("meta") or {}
        w.writerow([it.get("caseId"), meta.get("supplier"), meta.get("amount_display"),
                    meta.get("region"), it.get("status"), meta.get("risk_label") or "",
                    meta.get("confidence"), meta.get("provider"), meta.get("type"),
                    it.get("summary") or ""])
    return buf.getvalue(), total


def create_ticket(session, *, actor: str, ctx: TenantContext, filters: dict | None,
                  blk: int, trace: str) -> dict:
    """导出落盘+限时票据发放（在 AUDIT_EXPORT 入链之后调用——链头在前，票据在后）。"""
    content, rows = build_csv(session, ctx, filters)
    token = secrets.token_hex(12)
    now_dt = datetime.now(timezone.utc).astimezone()
    fname = f"audit-export-{now_dt.strftime('%Y%m%d-%H%M')}-{token[:8]}.csv"
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / fname).write_text(content, encoding="utf-8-sig")   # BOM：Excel 中文兼容（演示口径）
    session.add(m.ExportTicket(
        token=token, actor=actor, instance=ctx.instance, filters_raw=filters, rows=rows,
        filename=fname, created_ts=now_dt.isoformat(timespec="seconds"),
        expires_ts=(now_dt + timedelta(hours=EXPORT_TTL_HOURS)).isoformat(timespec="seconds"),
        blk=blk, trace=trace))
    session.commit()
    return {"token": token, "file": fname, "rows_exported": rows,
            "url": f"/v1/exports/{token}",
            "expires_at": (now_dt + timedelta(hours=EXPORT_TTL_HOURS)).isoformat(timespec="seconds")}


def download(session, token: str) -> tuple[bytes, str]:
    """限时下载：过期 410（重导重签发）；命中返回 (csv_bytes, filename)。"""
    t = session.get(m.ExportTicket, token)
    if t is None:
        raise CommandError("E_EXPORT_NOT_FOUND", "导出链接无效（未签发或已清除）", http=404)
    if t.expires_ts <= datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"):
        raise CommandError("E_EXPORT_EXPIRED",
                           f"导出链接已于 {t.expires_ts} 失效（24h 限时，FN-8-07）——请重新导出", http=410)
    path = EXPORT_DIR / t.filename
    if not path.exists():
        raise CommandError("E_EXPORT_FILE", "导出文件缺失（对象目录被清理）", http=410)
    return path.read_bytes(), t.filename


def co_signers(session) -> list[dict]:
    """BLOCKED 双人解除可选会签人（管理员角色、启用状态真人——FN-8-06；身份服务 M5 实装前为演示桩）。"""
    out = []
    for u in session.scalars(select(m.UserAccount)):
        if u.status == "启用" and "管理员" in (u.role or ""):
            out.append({"name": u.name, "role": u.role, "org": u.org,
                        "mfa": (u.user_raw or {}).get("mfa")})
    return out
