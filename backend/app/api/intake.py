# -*- coding: utf-8 -*-
"""受理与通道 API（WP3.2 · FN-1-01~11 运行入口）。

写路径纪律：
  - POST /v1/invoices:recognize = 机器通道（FN-1-02/FN-A-01 契约；受控定性 x-controlled-write：
    权限=AppKey+HMAC 签名演示桩、SHA-256 入审计、幂等两键）；
  - POST /v1/intake/upload = 门户人工受理提交（FN-1-08 完整五要素，经 governed_commands intake 动作）；
  - 渠道配置变更复用 /v1/config/{key}/risk-challenge + /v1/config/actions/publish（受控写，不另开口子）；
  - Job 触发（邮箱/DOX 桩）=运维入口，演示口径幂等由摘要台账保证。
"""

import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services import (batch_ops, channels_ops, governed_commands as gc, intake_kpi,
                          recognize as recognize_svc)
from app.services.audit_chain import new_trace_id
from app.services.errors import CommandError
from app.services.persistence import get_session
from app.services.tenant import TenantContext

router = APIRouter(prefix="/v1")


def _fail(e: CommandError, *, with_trace: str | None = None):
    if with_trace is not None:
        raise HTTPException(status_code=e.http,
                            detail={"code": e.code, "message": e.message, "trace_id": with_trace})
    raise HTTPException(status_code=e.http,
                        detail={"error_code": e.code, "message": e.message, **e.details})


class UploadChallengeBody(BaseModel):
    actor: str
    instance: str = Field(pattern="^(CN|OS)$")
    action: str = "intake"
    files: list[dict] = Field(min_length=1)          # [{name,size,mime}]
    po_ref: str | None = None


@router.post("/intake/upload/risk-challenge")
def upload_risk_challenge(body: UploadChallengeBody):
    if body.action != "intake":
        raise HTTPException(400, detail={"error_code": "UNKNOWN_ACTION",
                                         "message": "受理提交通道仅支持 action=intake"})
    scope = gc.intake_scope_digest(body.files, body.po_ref)
    with get_session() as session:
        try:
            chal = gc.issue_risk_challenge(session, body.actor, "intake", scope)
            chal["per_file_manifest"] = body.files      # 二次确认弹窗逐文件清单（FN-1-08）
            chal["risk_text"] = gc.RISK_TEXT["intake"]
            return chal
        except CommandError as e:
            _fail(e)


@router.post("/intake/upload")
async def upload(request: Request):
    form = await request.form()
    actor = form.get("actor"); instance = form.get("instance")
    token = form.get("token"); po_ref = form.get("po_ref") or None
    opinion = form.get("opinion") or None
    self_confirmed = str(form.get("self_confirmed", "")).lower() in ("1", "true", "on", "yes")
    files_raw = form.getlist("files")
    files: list[dict] = []
    for up in files_raw:
        # 鸭子类型判文件部件（fastapi/starlette 的 UploadFile 类不同源，isinstance 不可靠）
        if hasattr(up, "read") and hasattr(up, "filename"):
            content = await up.read()
            files.append({"name": up.filename or "unnamed", "content": content,
                          "mime": getattr(up, "content_type", None)})

    # 服务端校验（FN-1-03 同原型口径）：白名单/大小/同名同大小去重/批量上限
    if not files:
        _fail(CommandError("E_NO_FILES", "未选择文件", http=400))
    try:
        with get_session() as session:
            cfg = channels_ops.channel_config(session, "门户上传")
    except CommandError as e:
        _fail(e)
    allowed = [a.lower() for a in cfg.get("allowed_types", [])]
    cap = int(cfg.get("max_file_size_mb", 20)) * 1024 * 1024
    max_n = int(cfg.get("max_batch_files", 50))
    kept, rejected = [], []
    seen = set()
    for f in files:
        ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
        if ext not in allowed:
            rejected.append({"file": f["name"], "reason": f"类型 .{ext} 不在白名单 XML/OFD/PDF/JPG/PNG"})
            continue
        if len(f["content"]) > cap:
            rejected.append({"file": f["name"], "reason": f"超过单文件 {cap // (1024*1024)}MB 上限"})
            continue
        key = (f["name"], len(f["content"]))
        if key in seen:
            rejected.append({"file": f["name"], "reason": "同名同大小去重（FN-1-03）"})
            continue
        seen.add(key)
        kept.append(f)
    if not kept:
        raise HTTPException(400, detail={"error_code": "E_ALL_REJECTED",
                                         "message": "全部文件被校验拒绝", "rejected": rejected})
    if len(kept) > max_n:
        _fail(CommandError("E_BATCH_TOO_LARGE", f"单次批量上限 {max_n} 文件（渠道配置）", http=400))
    try:
        ctx = TenantContext.of(instance)
    except CommandError as e:
        _fail(e)
    # 凭据 scope 绑定=提交清单原文（确认弹窗所见即所发；白名单/去重过滤是其后的受理决策）
    meta = [{"name": f["name"], "size": len(f["content"]), "mime": f.get("mime")} for f in files]
    scope = gc.intake_scope_digest(meta, po_ref)
    with get_session() as session:
        try:
            out = gc.execute(session, actor=actor, action="intake", instance=ctx.instance,
                             token=token, self_confirmed=self_confirmed, opinion=opinion,
                             po_ref=po_ref, intake_files=kept, scope_override=scope)
            out["rejected"] = rejected
            out["toast"] = (f"✓ 受理完成：批次 {out['batch_id']} · 生成 "
                            f"{sum(1 for r in out['files'] if r.get('caseId'))} 个案件 · "
                            "操作已写入不可篡改审计日志")
            return out
        except CommandError as e:
            _fail(e)


# ───────────────────────── recognize（FN-A-01 北向契约面） ─────────────────────────

@router.post("/invoices:recognize")
async def invoices_recognize(request: Request):
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    headers = {k.lower(): v for k, v in request.headers.items()}
    err_trace = headers.get("x-trace-id") or new_trace_id()
    with get_session() as session:
        try:
            if ctype == "application/json":
                raw = await request.body()
                body_json = json.loads(raw) if raw else {}
                status, resp = recognize_svc.handle(session, body_json=body_json,
                                                    multipart=None, headers=headers, raw_body=raw)
            elif ctype == "multipart/form-data":
                form = await request.form()
                up = form.get("file")
                if up is None or not hasattr(up, "read"):
                    raise CommandError("E_NO_FILE", "multipart 缺少 file 字段", http=400)
                content = await up.read()
                # multipart 签名口径=文件原始字节（演示口径；JSON 为请求体原始字节）
                status, resp = recognize_svc.handle(
                    session, body_json=None,
                    multipart={"file": {"filename": up.filename, "content": content,
                                       "content_type": up.content_type},
                               "fields": {k: v for k, v in form.items() if k != "file"}},
                    headers=headers, raw_body=content)
            else:
                raise CommandError("E_CONTENT_TYPE",
                                   "请求体须为 application/json 或 multipart/form-data", http=400)
        except CommandError as e:
            _fail(e, with_trace=err_trace)
        # 契约回写 X-Trace-Id 响应头（200/202；聚合体 meta.trace_id 同源）
        trace = resp.get("trace_id") or (resp.get("meta") or {}).get("trace_id") or err_trace
        return JSONResponse(status_code=status, content=resp, headers={"X-Trace-Id": trace})


# ───────────────────────── 批次（FN-1-06/07） ─────────────────────────

@router.get("/batches")
def batches_list(instance: str | None = Query(None), channel: str | None = None,
                 status: str | None = None, limit: int = Query(50, ge=1, le=200)):
    with get_session() as session:
        try:
            return {"items": batch_ops.list_batches(session, instance=instance, channel=channel,
                                                    status=status, limit=limit),
                    "note": "进度百分比=(成功+异常)/文件数；部分异常行红色高亮由前端按 status 着色（FN-1-06）"}
        except CommandError as e:
            _fail(e)


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str, instance: str | None = Query(None)):
    with get_session() as session:
        try:
            return batch_ops.get_batch_detail(session, batch_id, instance=instance)
        except CommandError as e:
            _fail(e)


@router.post("/batches/{batch_id}/resume")
def batch_resume(batch_id: str, instance: str | None = Query(None)):
    with get_session() as session:
        try:
            return batch_ops.resume(session, batch_id, instance=instance)
        except CommandError as e:
            _fail(e)


@router.post("/batches/{batch_id}/files/{seq}/retry-steps")
def file_retry_steps(batch_id: str, seq: int, instance: str | None = Query(None)):
    with get_session() as session:
        try:
            return batch_ops.retry_file(session, batch_id, seq, instance=instance)
        except CommandError as e:
            _fail(e)


# ───────────────────────── KPI / 渠道 / 规则版本（FN-1-09/10/11） ─────────────────────────

@router.get("/intake/kpi")
def intake_kpi_snapshot(instance: str | None = Query(None)):
    with get_session() as session:
        return intake_kpi.compute(session, instance=instance)


@router.get("/intake/channels")
def intake_channels():
    with get_session() as session:
        return {"items": channels_ops.get_channel_configs(session),
                "note": "配置项清单=intake 渠道卡 ⚙ toast 同源（FN-1-11）；凭证 KMS 托管不回显（演示桩）；"
                        "变更=受控写：/v1/config/channel:{渠道}/risk-challenge → publish（五要素）"}


@router.get("/intake/rules/version")
def intake_rules_version():
    """受理规则版本徽章数据（FN-1-10 · Header「v{日期}.{序号} · 已发布」同源）。"""
    from app.services import versioning
    with get_session() as session:
        rev = versioning.latest_published(session, "intake_rules", "intake_rules")
        if rev is None:
            _fail(CommandError("E_INTAKE_RULES_MISSING", "受理规则版本化资产缺失", http=500))
        return {"asset": "intake_rules", "version": rev.version, "state": rev.state,
                "badge": f"受理规则版本 {rev.version} · 已发布",
                "updated_at": rev.updated_at, "updated_by": rev.updated_by,
                "revisions": [{"version": r.version, "diff": r.diff_json,
                               "by": r.updated_by, "at": r.updated_at}
                              for r in versioning.list_revisions(session, "intake_rules",
                                                                 asset_type="intake_rules")]}


# ───────────────────────── 通道 Job 桩手动触发（RUNBOOK 口径；15 分钟定时=演示手动等效） ─────────────────────────

@router.post("/intake/jobs/mailbox:poll")
def job_mailbox_poll():
    with get_session() as session:
        return channels_ops.poll_mailbox(session)


@router.post("/intake/jobs/dox:poll")
def job_dox_poll():
    with get_session() as session:
        return channels_ops.poll_dox(session)
