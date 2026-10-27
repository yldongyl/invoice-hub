# -*- coding: utf-8 -*-
"""通道运行件与渠道配置读侧（WP3.2 · FN-1-01/02/04/11 + FN-A-03 Webhook 桩）。

演示口径（P00 §6，必须如实标注）：
  - 邮箱通道=本地信箱目录模拟（runtime/mailbox/inbox/*.json 信封；15 分钟定时 Job 以 RUNBOOK
    手动触发等效——不做真实 IMAP）；退回/通知落 runtime/mailbox/outbox（不真实外呼）；
  - SAP DOX 桥接=目录投递模拟（runtime/dox/inbox/*.json 传输信封；Peppol/UBL 信封校验、
    参与方 ID 核对、Order Response/对账类退回为确定性真实执行，回执模拟）；
  - X-Signature/回调 HMAC=演示密钥（KMS 桩 TODO(FN-9-10)），secret 一律不回显 API；
  - Webhook 投递=outbox 落盘即记 delivered（真实退避消费者属 FN-9-07/M4+）；
  - 限流=进程内秒桶（演示口径）。
"""

import base64
import hashlib
import hmac
import json
import re
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.domain import models as m
from app.services import config_center, intake_pipeline, object_store
from app.services.audit_chain import new_trace_id, now_iso
from app.services.errors import CommandError

REPO_ROOT = Path(__file__).resolve().parents[3]           # backend/app/services -> invoice-hub/（与 object_store/registry 同基准）
MAILBOX_INBOX = REPO_ROOT / "runtime" / "mailbox" / "inbox"
MAILBOX_OUTBOX = REPO_ROOT / "runtime" / "mailbox" / "outbox"
MAILBOX_PROCESSED = REPO_ROOT / "runtime" / "mailbox" / "processed"
DOX_INBOX = REPO_ROOT / "runtime" / "dox" / "inbox"
DOX_REJECT = REPO_ROOT / "runtime" / "dox" / "rejected"
DOX_PROCESSED = REPO_ROOT / "runtime" / "dox" / "processed"
WEBHOOK_OUTBOX = REPO_ROOT / "runtime" / "webhook-outbox"


# ───────────────────────── 渠道配置读侧（凭证掩码，FN-1-11/9-10） ─────────────────────────

_SENSITIVE = re.compile(r"(secret|credential|cert|appkey|token)", re.I)


def masked_config(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        out[k] = ("***（KMS 托管 · 演示桩不回显）***" if _SENSITIVE.search(k) else v)
    return out


def get_channel_configs(session) -> list[dict]:
    """四渠道卡数据（配置=已发布版本化资产现值 + 今日计数）。"""
    meta = session.get(m.SeedMeta, "intake_kpi_baseline")
    display = {d["channel"]: d for d in (meta.payload.get("channels_display") or [])} if meta else {}
    counters = (meta.payload.get("today_counters") or {}) if meta else {}
    out = []
    for ch in ("供应商邮箱", "API 集成", "门户上传", "SAP DOX"):
        item = config_center.get_effective(session, f"channel:{ch}")
        rev = _latest_channel_rev(session, ch)
        out.append({"channel": ch, **(display.get(ch) or {}),
                    "config": masked_config(item.value_raw or {}) if item else {},
                    "config_version": rev.version if rev else None,
                    "today": counters.get(ch, {})})
    return out


def _latest_channel_rev(session, ch: str):
    from app.services import versioning
    return versioning.latest_published(session, "channel_config", f"channel:{ch}")


def channel_config(session, ch: str) -> dict:
    item = config_center.get_effective(session, f"channel:{ch}")
    if item is None:
        raise CommandError("E_CHANNEL_NOT_FOUND", f"渠道 {ch!r} 配置缺失", http=404)
    return item.value_raw or {}


def api_secret(session) -> str:
    return channel_config(session, "API 集成").get("signature_demo_secret_plain", "")


def webhook_secret(session) -> str:
    return channel_config(session, "API 集成").get("signature_demo_secret_plain", "")


# ───────────────────────── API 通道请求防线（FN-1-02 头校验，演示桩） ─────────────────────────

def verify_signature(session, body_bytes: bytes, signature: str | None) -> None:
    """X-Signature: sha256=<hex>（HMAC-SHA256，演示密钥）。真实凭证 KMS 托管——TODO(FN-9-10)。"""
    cfg = channel_config(session, "API 集成")
    if not cfg.get("signature_check", True) and "signature_check" in cfg:
        return
    secret = api_secret(session).encode()
    expect = "sha256=" + hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
    if not signature or signature != expect:
        raise CommandError("E_SIGNATURE_INVALID",
                           "签名校验失败（X-Signature 需 sha256=<HMAC-SHA256 hex>，演示密钥 KMS 桩）", http=401)


def check_rate_limit(session, *, max_qps: int | None = None) -> None:
    """进程内秒级令牌桶（演示口径限流；QPS=渠道配置）。"""
    cfg = channel_config(session, "API 集成")
    cap = max_qps or int(cfg.get("rate_limit_qps", 50))
    sec = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    _RATE.setdefault("sec", sec)
    if _RATE["sec"] != sec:
        _RATE.update({"sec": sec, "n": 0})
    _RATE["n"] += 1
    if _RATE["n"] > cap:
        raise CommandError("E_RATE_LIMITED", f"超过限流 QPS={cap}（渠道配置可改，FN-1-02）", http=429)


_RATE: dict = {"sec": "", "n": 0}


def transport_dup(session, request_id: str):
    """传输层幂等（X-Request-Id，与业务摘要键分离——CON-05/06）。TTL=渠道配置幂等键有效期。"""
    row = session.get(m.RequestIdLedger, request_id)
    if row is None:
        return None
    ttl = int(channel_config(session, "API 集成").get("idempotent_key_ttl_days", 7))
    expired = row.expires_at <= now_iso()
    if expired:
        session.delete(row)
        session.commit()
        return None
    return row


def record_request(session, request_id: str, *, case_id: str | None, batch_id: str | None,
                   instance: str, response: dict):
    ttl = int(channel_config(session, "API 集成").get("idempotent_key_ttl_days", 7))
    now_dt = datetime.now(timezone.utc).astimezone()
    session.add(m.RequestIdLedger(request_id=request_id, case_id=case_id, batch_id=batch_id,
                                  instance=instance, response_raw=response,
                                  created_at=now_iso(),
                                  expires_at=(now_dt + timedelta(days=ttl)).isoformat(timespec="seconds")))
    session.commit()


# ───────────────────────── Webhook 回调桩（FN-A-03） ─────────────────────────

def emit_webhook(session, event: str, case: m.Case, callback_url: str | None) -> dict:
    """四事件之一入 outbox（本地落盘=演示投递完成；X-Signature HMAC 计算留痕）。
    消费方 2xx 约定与 ≤8 次退避重放属真实通道（消费者 M4+/FN-9-07）。"""
    from app.domain.registry import get_registry
    get_registry().validate("webhook_event", event, where="emit_webhook")
    url = callback_url or channel_config(session, "API 集成").get("webhook_default_url")
    payload = {
        "event": event, "event_id": f"evt-{_secrets.token_hex(8)}", "caseId": case.case_id,
        "status": case.status, "t": now_iso(), "trace_id": case.trace_id,
        "payload": {"facts": case.facts_raw, "checks": case.checks_raw}
        if event == "case.recognized" else
        ({"blockReason": "见案件红线注记", "ruleId": None, "evidenceRef": None}
         if event == "case.blocked" else
         ({"resolution": None, "operator": None, "actionTrailRef": None}
          if event == "case.resolved" else {"checkName": None, "result": None, "variance": None})),
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    sig = "sha256=" + hmac.new(webhook_secret(session).encode(), body, hashlib.sha256).hexdigest()
    WEBHOOK_OUTBOX.mkdir(parents=True, exist_ok=True)
    (WEBHOOK_OUTBOX / f"{payload['event_id']}.json").write_bytes(
        json.dumps({"headers": {"X-Signature": sig, "X-Event-Id": payload["event_id"],
                               "X-Trace-Id": payload["trace_id"]}, "body": payload},
                   ensure_ascii=False, indent=2).encode())
    row = m.WebhookDelivery(event_id=payload["event_id"], event=event, case_id=case.case_id,
                            delivered_to=url, payload_raw=payload, signature=sig, attempts=1,
                            state="delivered", ts=now_iso())
    session.add(row)
    session.add(m.EgressLog(ts=now_iso(), batch_id=None, file_seq=None, case_id=case.case_id,
                             provider_id="webhook-outbox-stub", purpose="webhook." + event,
                             payload_digest=hashlib.sha256(body).hexdigest(), bytes_out=len(body),
                             note="演示口径：outbox 落盘替代真实外呼（FN-A-03 桩；消费者与退避属 M4+）"))
    session.commit()
    return {"event_id": payload["event_id"], "event": event, "delivered": True,
            "note": "演示 outbox（runtime/webhook-outbox/），非真实外呼"}


# ───────────────────────── 邮箱通道桩：本地信箱 15 分钟 Job（RUNBOOK 手动触发） ─────────────────────────

def _read_envelope(path: Path) -> dict:
    env = json.loads(path.read_text(encoding="utf-8"))
    if not all(k in env for k in ("from", "subject", "attachments")):
        raise CommandError("E_MAIL_ENVELOPE", f"信封结构非法：{path.name}", http=400)
    return env


def poll_mailbox(session, *, inbox_dir: Path | None = None) -> dict:
    """邮箱 Job 一次拉取：拆附件为独立文件 → 一个批次（FN-1-01/05①拆分在通道层完成）。"""
    inbox = inbox_dir or MAILBOX_INBOX
    if not inbox.exists():
        return {"batches": [], "skipped": [], "note": f"信箱目录不存在（演示桩）：{inbox}"}
    cfg = channel_config(session, "供应商邮箱")
    whitelist = [d.lower() for d in cfg.get("sender_domain_whitelist", [])]
    size_cap = int(cfg.get("max_attachment_size_mb", 20)) * 1024 * 1024
    payload, _ver = intake_pipeline.current_intake_rules(session)
    batches, skipped, dup_skips = [], [], []
    files = sorted(inbox.glob("*.json"))
    if not files:
        return {"batches": [], "skipped": [], "note": "信箱为空"}
    batch = intake_pipeline.create_batch(session, channel="供应商邮箱", instance="CN",
                                         trace=new_trace_id())
    added = 0
    for path in files:
        env = _read_envelope(path)
        domain = (env["from"].split("@")[-1] or "").lower()
        if domain not in whitelist:
            skipped.append({"envelope": path.name, "reason": f"发件域 {domain} 不在白名单（FN-1-01）"})
            _move(path, MAILBOX_PROCESSED)
            continue
        for att in env["attachments"]:
            name = att["name"]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in cfg.get("attachment_type_whitelist", []):
                _reject_mail(env["from"], name, f"附件类型 .{ext} 受限（FN-1-01 类型限制）")
                skipped.append({"envelope": path.name, "file": name, "reason": "附件类型不在允许集"})
                continue
            content = base64.b64decode(att["content_b64"])
            if len(content) > size_cap:
                _reject_mail(env["from"], name, "单附件超过 20MB 上限（FN-1-01）")
                skipped.append({"envelope": path.name, "file": name, "reason": "超过大小上限"})
                continue
            dup = intake_pipeline.find_business_dup(session, object_store.sha256_of(content), None)
            if dup is not None:
                dup_skips.append({"file": name, "existing_case": dup.case_id,
                                  "reason": "摘要幂等：已受理不重复（FN-1-07 断点续跑口径）"})
                continue
            frow = intake_pipeline.add_file(session, batch, name=name, content=content,
                                            mime=None, po_ref=None,
                                            target_doc_ref=att.get("target_doc_ref"))
            out = intake_pipeline.run_file(session, batch, frow, rules_payload=payload)
            if out.get("disposition") == "FILTERED":
                _reject_mail(env["from"], name, "非发票附件自动退回（FN-1-01/05②，规则引擎判定）")
            added += 1
        _move(path, MAILBOX_PROCESSED)
    if added == 0:
        session.delete(batch)
        session.commit()
        return {"batches": [], "skipped": skipped, "duplicates_skipped": dup_skips,
                "note": "本封/本轮无可受理新文件（白名单/类型/幂等过滤后）"}
    batch = intake_pipeline.recompute_batch(session, batch.batch_id)
    batches.append({"batch_id": batch.batch_id, "files": batch.files, "status": batch.status})
    return {"batches": batches, "skipped": skipped, "duplicates_skipped": dup_skips,
            "note": "演示口径：本地信箱目录模拟 15 分钟 Job（RUNBOOK intake:poll-mailbox 手动触发）"}


def _reject_mail(to_addr: str, filename: str, reason: str):
    """退回邮件模板渲染（演示 outbox，不真实外呼）。"""
    MAILBOX_OUTBOX.mkdir(parents=True, exist_ok=True)
    tpl = "非发票附件自动退回通知 · 默认模板（可配）"
    body = {"to": to_addr, "subject": f"[Rejection] {filename}", "template": tpl,
            "reason": reason, "t": now_iso(),
            "note": "退回邮件模板可配（FN-1-01）；演示桩通道不外呼"}
    (MAILBOX_OUTBOX / f"reject-{object_store.sha256_of(filename.encode())[:12]}.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def _move(path: Path, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / path.name
    if target.exists():
        target = dest_dir / f"{path.stem}.{object_store.sha256_of(path.read_bytes())[:8]}{path.suffix}"
    path.rename(target)


# ───────────────────────── SAP DOX 桥接桩：目录投递（FN-1-04，海外实例） ─────────────────────────

def poll_dox(session, *, inbox_dir: Path | None = None) -> dict:
    """DOX 轮询一次：传输信封校验+参与方 ID 核对（真实执行、确定性），回执/投递模拟。"""
    inbox = inbox_dir or DOX_INBOX
    if not inbox.exists():
        return {"batches": [], "rejected": [], "note": f"DOX 投递目录不存在（演示桩）：{inbox}"}
    cfg = channel_config(session, "SAP DOX")
    payload, _ver = intake_pipeline.current_intake_rules(session)
    participant_base = (cfg.get("participant_id") or "").split("（")[0]
    files = sorted(inbox.glob("*.json"))
    if not files:
        return {"batches": [], "rejected": [], "note": "DOX 目录为空"}
    batch = intake_pipeline.create_batch(session, channel="SAP DOX", instance="OS",
                                         trace=new_trace_id())
    rejected, added = [], 0
    for path in files:
        env = json.loads(path.read_text(encoding="utf-8"))
        pid = (env.get("participant_id") or "").split("（")[0]
        if pid != participant_base:
            rejected.append({"file": path.name, "reason": f"参与方 ID 核对不符（{pid} ≠ {participant_base}）"
                             "· Peppol 信封 strict 校验退回"})
            _move(path, DOX_REJECT)
            continue
        doc_type = env.get("document_type")
        if doc_type in cfg.get("return_doc_types", []):
            DOX_REJECT.mkdir(parents=True, exist_ok=True)
            (DOX_REJECT / f"{path.stem}.return.json").write_text(json.dumps(
                {"returned": True, "document_type": doc_type, "reason": "Order Response/对账类自动退回（FN-1-04）",
                 "t": now_iso()}, ensure_ascii=False), encoding="utf-8")
            # 仍入批次为 FILTERED 文件行（批次非发票过滤计数留痕，FN-1-06）
            frow = intake_pipeline.add_file(session, batch, name=env.get("name", path.name),
                                            content=json.dumps(env, ensure_ascii=False).encode(),
                                            mime="application/json", po_ref=None,
                                            target_doc_ref=env.get("document_number"))
            frow.disposition = "FILTERED"
            frow.doc_type = doc_type
            frow.note = f"非发票（{doc_type}）· 已经 DOX 通道自动退回"
            ir = dict(frow.intake_raw or {})
            ir.update({"carrier": "—", "note": frow.note})
            frow.intake_raw = ir
            for n in (3, 4, 5):
                intake_pipeline._set_step(session, batch.batch_id, frow.seq, n, "SKIPPED",
                                          {"skipped_reason": "DOX 传输层非发票退回"}, commit=False)
            session.commit()
            added += 1
            _move(path, DOX_PROCESSED)
            continue
        content = base64.b64decode(env["content_b64"])
        dup = intake_pipeline.find_business_dup(session, object_store.sha256_of(content),
                                                env.get("document_number"))
        if dup is not None:
            rejected.append({"file": path.name, "reason": "摘要幂等：已受理不重复",
                             "existing_case": dup.case_id})
            _move(path, DOX_PROCESSED)
            continue
        frow = intake_pipeline.add_file(session, batch, name=env.get("name", path.name),
                                        content=content, mime=env.get("mime"),
                                        po_ref=env.get("po_ref"),
                                        target_doc_ref=env.get("document_number"))
        intake_pipeline.run_file(session, batch, frow, rules_payload=payload)
        added += 1
        _move(path, DOX_PROCESSED)
    if added == 0:
        session.delete(batch)
        session.commit()
        return {"batches": [], "rejected": rejected, "note": "本轮 DOX 投递无可受理新单据"}
    batch = intake_pipeline.recompute_batch(session, batch.batch_id)
    return {"batches": [{"batch_id": batch.batch_id, "files": batch.files, "status": batch.status}],
            "rejected": rejected,
            "note": "演示口径：目录投递模拟 DOX；回执归档注记见批次文件明细（FN-1-04）"}
