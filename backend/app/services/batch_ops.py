# -*- coding: utf-8 -*-
"""批次读侧聚合（WP3.2 · FN-1-06 批次/文件双层状态 + 进度 + 组合过滤）。

口径（intake 批次列表逐字）：进度百分比=(成功+异常)/文件数；「部分异常」行红色高亮由前端
按 status 着色；渠道×状态组合过滤；文件级明细含载体路径、案件号深链、状态快照、置信度、异常备注；
异常文件不阻断批次内其他文件。实例过滤走租户上下文（四隔离①，FN-0-11/WP1.7）。
"""

from sqlalchemy import select

from app.domain import models as m
from app.services import intake_pipeline
from app.services.errors import CommandError

# 页面状态词汇 ↔ 枚举合并态（seed_loader.BATCH_STATUS_ALIAS 同口径反向）
_STATUS_TO_ENUM = {"受理中": "受理中 / 识别中", "识别中": "受理中 / 识别中",
                   "已完成": "已完成", "部分异常": "部分异常"}


def _status_enum(raw: str) -> str:
    return _STATUS_TO_ENUM.get(raw, raw)


def list_batches(session, *, instance: str | None = None, channel: str | None = None,
                 status: str | None = None, limit: int = 50):
    """批次列表（渠道×状态过滤）。status 入参取页面四值或枚举合并值。"""
    q = select(m.Batch)
    if instance:
        q = q.where(m.Batch.instance == instance)
    if channel:
        q = q.where(m.Batch.channel == channel)
    rows = list(session.scalars(q.order_by(m.Batch.batch_id.desc()).limit(limit)))
    if status:
        accepted = ({"受理中": ("受理中",), "识别中": ("识别中",),
                     "受理中 / 识别中": ("受理中", "识别中"),
                     "已完成": ("已完成",), "部分异常": ("部分异常",)}.get(status))
        if accepted is None:
            raise CommandError("E_BATCH_STATUS",
                               f"批次状态过滤值 {status!r} 不在 batch_status 词汇（enum-registry）", http=400)
        rows = [b for b in rows if b.status in accepted]
    out = []
    for b in rows:
        out.append({"batch_id": b.batch_id, "channel": b.channel,
                    "instance": b.instance_display, "instance_code": b.instance,
                    "files": b.files, "status": b.status, "status_enum": _status_enum(b.status),
                    "progress_pct": (100 if b.status == "已完成"
                                     else round((b.ok + b.err) / b.files * 100) if b.files else 0),
                    "ok": b.ok, "err": b.err, "filtered": b.filtered,
                    "time": b.time, "created_ts": b.created_ts, "trace_id": b.trace_id})
    return out


def get_batch_detail(session, batch_id: str, *, instance: str | None = None) -> dict:
    """批次行展开：文件级受理明细（载体路径/案件号深链/状态快照/置信度/备注）+ 步骤时间线。"""
    b = session.get(m.Batch, batch_id)
    if b is None:
        raise CommandError("E_BATCH_NOT_FOUND", f"批次 {batch_id} 不存在", http=404)
    if instance and b.instance and b.instance != instance.upper():
        raise CommandError("E_TENANT_MISMATCH", "批次归属实例与租户上下文不符（四隔离①）", http=403)
    rows = session.scalars(select(m.FileIntake).where(
        m.FileIntake.batch_id == batch_id).order_by(m.FileIntake.seq)).all()
    files = []
    for r in rows:
        steps = session.scalars(select(m.FileStep).where(
            m.FileStep.batch_id == batch_id, m.FileStep.file_seq == r.seq)
            .order_by(m.FileStep.step_no)).all()
        ir = r.intake_raw or {}
        files.append({"seq": r.seq, "file": r.file, "carrier": ir.get("carrier"),
                      "case_id": r.case_id, "status_snapshot": r.status_snapshot,
                      "conf": r.conf, "note": r.note or ir.get("note"),
                      "disposition": r.disposition, "carrier_route": r.carrier_route,
                      "sha256_display": (f"{r.sha256[:4]}…{r.sha256[-4:]}" if r.sha256 else None),
                      "accepted_ts": r.accepted_ts, "digest_ts": r.digest_ts,
                      "bad": bool(ir.get("bad")),
                      "steps": [{"no": s.step_no, "name": intake_pipeline.STEP_NAMES[s.step_no],
                                 "status": s.status, "detail": s.detail_raw} for s in steps]})
    head = list_batches(session, instance=instance, limit=10000)
    head = next(x for x in head if x["batch_id"] == batch_id)
    return {**head, "files_detail": files}


def resume(session, batch_id: str, *, instance: str | None = None) -> dict:
    b = session.get(m.Batch, batch_id)
    if b is None:
        raise CommandError("E_BATCH_NOT_FOUND", f"批次 {batch_id} 不存在", http=404)
    if instance and b.instance and b.instance != instance.upper():
        raise CommandError("E_TENANT_MISMATCH", "跨实例续跑被拒绝（四隔离①）", http=403)
    return intake_pipeline.resume_batch(session, batch_id)


def retry_file(session, batch_id: str, seq: int, *, instance: str | None = None) -> dict:
    b = session.get(m.Batch, batch_id)
    if b is None:
        raise CommandError("E_BATCH_NOT_FOUND", f"批次 {batch_id} 不存在", http=404)
    if instance and b.instance and b.instance != instance.upper():
        raise CommandError("E_TENANT_MISMATCH", "跨实例重试被拒绝（四隔离①）", http=403)
    return intake_pipeline.retry_file_failed_steps(session, batch_id, seq)
