# -*- coding: utf-8 -*-
"""API 接入通道编排（WP3.2 · FN-1-02 / FN-A-01 POST /v1/invoices:recognize）。

契约形态（openapi.yaml v1 FROZEN，逐字段）：
  - application/json（file{ref,mime_type,sha256} 引用）与 multipart/form-data 文件直传双请求体；
  - 头：X-Request-Id 必填（传输层幂等，与业务摘要键分离——CON-05/06）；X-Signature 必填
    （演示密钥 HMAC，KMS 桩 TODO(FN-9-10)）；X-Trace-Id 可选（缺省平台生成并回写）；
  - 200=同步直读快速路径完成（P95<3s，返回完整 InvoiceCase=invoice-case.schema）；
  - 202=已受理转异步（先返 caseId+trace，完成推送 Webhook——outbox 桩）；
  - 409=幂等命中返回既有 caseId（DedupAcceptedResponse）；400/401/429 同契约。
本通道为机器提交：受控定性 x-controlled-write 的要素①=AppKey+签名（演示桩），要素⑤=SHA-256
登记入审计（intake_ledger+流水线 CHANNEL_RECEIVED/INBOUND_ACCEPTED 块）；门户人工提交的完整
五要素路径见 governed_commands action=intake（FN-1-08）。
"""

from app.domain import models as m
from app.domain.registry import get_contract_enums, get_registry
from app.services import (case_repository, channels_ops, intake_pipeline, object_store)
from app.services.audit_chain import new_trace_id
from app.services.errors import CommandError
from app.services.tenant import TenantContext

DIRECT_ROUTES = ("L1_xml_direct", "L1_ofd_direct", "L1_pdf_text")


def _sla_upload_cap(session) -> int:
    from app.services import config_center
    row = config_center.get_effective(session, "__sla_targets")
    return int((row.value_raw or {}).get("upload_file_size_max_mb", 20)) * 1024 * 1024 if row else 20 * 1024 * 1024


def _validate_declared(mime: str | None, name: str, size: int, session) -> None:
    wl = ("application/xml", "text/xml", "application/pdf", "image/jpeg", "image/png",
          "application/ofd", "application/x-ofd", "application/octet-stream")
    if mime and not any(mime.lower().startswith(w) for w in wl):
        raise CommandError("E_MIME_NOT_ALLOWED", f"mime {mime!r} 不在白名单（FN-1-03/02 校验口径）", http=400)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    allowed = ("xml", "ofd", "pdf", "jpg", "jpeg", "png")
    if ext and ext not in allowed:
        raise CommandError("E_TYPE_NOT_ALLOWED", f"类型 .{ext} 不在白名单 XML/OFD/PDF/JPG/PNG", http=400)
    cap = _sla_upload_cap(session)
    if size > cap:
        raise CommandError("E_SIZE_LIMIT", f"超过单文件 {cap // (1024 * 1024)}MB 上限", http=400)


def handle(session, *, body_json: dict | None, multipart: dict | None, headers: dict,
           raw_body: bytes) -> tuple[int, dict]:
    """recognize 主入口，返回 (status_code, response_json)。"""
    request_id = headers.get("x-request-id")
    if not request_id:
        raise CommandError("E_REQUEST_ID_REQUIRED", "缺少 X-Request-Id（传输层幂等键必填，FN-1-02）", http=400)
    channels_ops.check_rate_limit(session)
    channels_ops.verify_signature(session, raw_body, headers.get("x-signature"))

    trace = headers.get("x-trace-id") or new_trace_id()
    if trace and get_registry().id_pattern("trace ID") and not _trace_ok(trace):
        raise CommandError("E_TRACE_FORMAT", "X-Trace-Id 不符 tr-{8hex}（FN-0-13）", http=400)

    # 传输层幂等重放（有效期内返回首发结果，_ 前缀为内部信封元数据不外泄）
    replay = channels_ops.transport_dup(session, request_id)
    if replay is not None and replay.response_raw:
        raw = dict(replay.response_raw)
        status = raw.pop("_status", 200)
        return status, {**{k: v for k, v in raw.items() if not k.startswith("_")},
                        "note": "X-Request-Id 幂等重放（有效期内返回首发结果）"}

    # 请求体归一（json 引用 / multipart 直传）
    if multipart is not None:
        f = multipart["file"]
        name, content, mime = f["filename"], f["content"], f.get("content_type")
        instance = (multipart.get("fields") or {}).get("instance")
        po_ref = (multipart.get("fields") or {}).get("po_ref")
        callback_url = (multipart.get("fields") or {}).get("callback_url")
        target_doc_ref = (multipart.get("fields") or {}).get("target_doc_ref")
        options = {}
    else:
        req = body_json or {}
        instance = req.get("instance")
        po_ref = req.get("po_ref")
        callback_url = req.get("callback_url")
        target_doc_ref = req.get("target_doc_ref")
        options = req.get("options") or {}
        finfo = req.get("file") or {}
        mime = finfo.get("mime_type")
        name = (finfo.get("ref") or "unnamed").rsplit("/", 1)[-1]
        sha_decl = finfo.get("sha256")
        local = object_store.find_by_digest(sha_decl) if sha_decl else None
        if local is None:
            raise CommandError("E_OBJECT_REF_UNRESOLVED",
                               f"oss 引用在对象库无对应原件（sha256={str(sha_decl)[:12]}…）——"
                               "演示口径：先经 multipart/门户/信箱落盘，ref 按摘要反查（ADR-0002 本地目录=MinIO 可替换）",
                               http=400)
        content = object_store.read(local)
        if object_store.sha256_of(content) != sha_decl:
            raise CommandError("E_SHA_MISMATCH", "引用件与声明摘要不一致（替换检测，FN-1-05④）", http=400)

    ctx = TenantContext.of(instance)
    instance = ctx.instance
    if instance not in get_contract_enums().instance:
        raise CommandError("E_INSTANCE_INVALID", "instance 必须为 CN|OS（契约内联枚举）", http=400)
    if not content:
        raise CommandError("E_EMPTY_FILE", "文件内容为空", http=400)
    _validate_declared(mime, name, len(content), session)

    sha = object_store.sha256_of(content)

    # 业务层幂等（摘要+目标单据，CON-05）
    dup = intake_pipeline.find_business_dup(session, sha, target_doc_ref)
    if dup is not None:
        resp = {"caseId": dup.case_id or "", "idempotent": True,
                "duplicate_of_trace": dup.trace_id or "",
                "note": "幂等命中：同摘要+同目标单据已受理，不重复入池（FN-1-02 重复提交去重）"}
        channels_ops.record_request(session, request_id, case_id=dup.case_id, batch_id=dup.batch_id,
                                    instance=instance, response={**resp, "_status": 409})
        return 409, resp

    payload, rules_ver = intake_pipeline.current_intake_rules(session)
    batch = intake_pipeline.create_batch(session, channel="API 集成", instance=instance, trace=trace)
    frow = intake_pipeline.add_file(session, batch, name=name, content=content, mime=mime,
                                    po_ref=po_ref, target_doc_ref=target_doc_ref)
    try:
        out = intake_pipeline.run_file(session, batch, frow, rules_payload=payload)
    except CommandError as e:
        if e.code == "E_INTAKE_DUP":
            existing = (e.details or {}).get("existing_case_id")
            resp = {"caseId": existing or "", "idempotent": True,
                    "duplicate_of_trace": trace, "note": e.message}
            return 409, resp
        raise
    except Exception:
        intake_pipeline.recompute_batch(session, batch.batch_id)
        raise

    case = session.get(m.Case, out["caseId"]) if out.get("caseId") else None
    route = frow.carrier_route
    sync_fast = options.get("sync_fast_path_only", False)
    is_direct = route in DIRECT_ROUTES and case is not None and frow.disposition == "ACCEPTED"

    if case is not None:
        agg = case_repository.aggregate_case(session, ctx, case.case_id)
        # AcceptedResponse.callback_url 契约必填：缺省回落 API 渠道 Webhook 默认地址（FN-1-11 渠道配置）
        cb = callback_url or channels_ops.channel_config(
            session, "API 集成").get("webhook_default_url") or "runtime://webhook-outbox"
        if is_direct:  # 直读快速路径：200 完整聚合（P95<3s 语义）
            resp = agg
            status = 200
        elif sync_fast:
            resp = {"caseId": case.case_id, "status": case.status, "trace_id": trace,
                    "callback_url": cb,
                    "message": "载体非直读快速路径（sync_fast_path_only）——转异步，完成推送 Webhook（演示 outbox 桩）"}
            status = 202
        else:
            resp = {"caseId": case.case_id, "status": case.status, "trace_id": trace,
                    "callback_url": cb,
                    "message": "已受理转异步：stub OCR/直读合成完成（P95<3s 语义演示口径），"
                               "完成事件已推送 Webhook（FN-A-03 桩）"}
            status = 202
        if status == 202:
            channels_ops.emit_webhook(session, "case.recognized", case, cb)
        # options.verify_authenticity：授权查验编排属 WP3.3（FN-5-01/02），本会话不接线——TODO 注记入 checks 占位
        if not options.get("verify_authenticity", True):
            resp["note"] = resp.get("note", "") + " · verify_authenticity=false：验真编排未触发（属 WP3.3）"
    else:
        # 无案件的两类处置均按 400 Error 契约形态返回（AcceptedResponse 要求 caseId，不可伪造）：
        # ① 非发票=受理阶段即拒绝入池（FN-1-03）；② 加密/损坏=人工分拣+回执索取（FN-1-05③）
        code = "E_NON_INVOICE" if frow.disposition == "FILTERED" else "E_MANUAL_SORT"
        msg = (f"非发票文档（{frow.doc_type}）在受理阶段即拒绝入池（FN-1-03/05②）"
               if frow.disposition == "FILTERED" else frow.note)
        err = {"code": code, "message": f"{msg} · 批次 {batch.batch_id}", "trace_id": trace}
        channels_ops.record_request(session, request_id, case_id=None, batch_id=batch.batch_id,
                                    instance=instance, response={**err, "_status": 400})
        return 400, err

    channels_ops.record_request(session, request_id, case_id=case.case_id,
                                batch_id=batch.batch_id, instance=instance,
                                response={**resp, "_status": status})
    return status, resp


def _trace_ok(t: str) -> bool:
    import re
    return bool(re.match(get_registry().id_pattern("trace ID"), t))
