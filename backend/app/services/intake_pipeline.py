# -*- coding: utf-8 -*-
"""五步受理流水线（WP3.1 · FN-1-05/07 + FN-0-13 发号 + FN-0-10 留痕）。

步骤（规则引擎确定性判断，非模型推断；清单 §3.1 FN-1-05 逐字口径）：
  ① 信封解析：文件头/传输信封、拆分（邮件多附件由通道层完成）、类型与大小校验；
  ② 非发票过滤：non_invoice_doc_filter 规则命中 → 退回+通知留痕+可申诉重提标记，不入发票池；
  ③ 载体检测分流：carrier_route_detect 规则 → 直读/OCR 路由（加密/损坏 → L4_manual_review 人工分拣+回执注记）；
  ④ 原件摘要登记：SHA-256 受理即登记入 intake_ledger（业务幂等键=摘要+目标单据，CON-05；重复提交不重复受理）；
  ⑤ 路由识别引擎：直读解析派生 InvoiceCase（RECOGNIZED）；扫描/图片走 stub Provider（M4 前演示口径，
     每次外发登记 EgressLog——FN-5-08 数据最小外发断言台账；直读路径外发必须为零）。

断点续跑（FN-1-07）：每步 FileStep 行持久化（PENDING/RUNNING/DONE/FAILED/SKIPPED + 结果快照），
步边界提交；resume_batch 从最后成功检查点续做未完成步骤——已 DONE 跳过（识别不重跑、摘要不重复登记）；
文件级 retry 仅重跑 FAILED 步骤。

红线纪律（本会话范围）：案件派生后停在 RECOGNIZED——查重/验真/红线流转属 WP3.3 合规服务，
checks 四槽位以「合规服务未激活」NOT_VERIFIED 占位写入（唯一业务写入口 orchestrator.apply_results）；
低置信 <80 无任何自动放行路径（本模块不产生放行出口）。
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain import models as m
from app.domain.registry import get_registry
from app.services import (intake_parsers, object_store, orchestrator, rules, state_machine,
                          versioning)
from app.services.audit_chain import append_block, now_iso
from app.services.errors import CommandError

# 流水线步序显示名（intake 页五步动画文案同源，PL_STEPS）
STEP_NAMES = {1: "① 信封解析", 2: "② 非发票过滤", 3: "③ 载体检测分流",
              4: "④ 原件摘要登记", 5: "⑤ 路由识别引擎"}

# 载体路由 → 整案置信度（演示口径常量表；真实置信度模型归 M4 FN-2-01/06）
_CONF_BY_ROUTE = {"L1_xml_direct": 99, "L1_ofd_direct": 98, "L1_pdf_text": 97, "L2_ocr_vlm": 82}

# 路由链组件版本（versions.json 附录 B 基线，经 component_version 引用不硬编码）
_V_EVENT = "ingest-service"          # CHANNEL_RECEIVED
_V_ROUTE = "router-policy"           # CARRIER_ROUTED
_V_PARSER = "cn-xml-parser"          # XML_PARSED
_V_OCR = "ocr-vlm-2026-10"           # OCR_RECOGNIZED（stub，版本 null→组件名口径）
_V_NORMALIZE = "normalize-service"   # INBOUND_ACCEPTED


class IntakeInterrupt(Exception):
    """断点续跑测试用：模拟 Job 在指定步后中断（步已提交，状态留存）。"""


# ───────────────────────── 版本化受理规则读取（FN-1-10 资产消费） ─────────────────────────

def current_intake_rules(session) -> tuple[dict, str]:
    """受理规则已发布载荷+版本号（v{日期}.{序号}；seed 装载基线 v2026-10-20.2）。"""
    rev = versioning.latest_published(session, "intake_rules", "intake_rules")
    if rev is None:
        raise CommandError("E_INTAKE_RULES_MISSING", "intake_rules 版本化资产缺失（seed 装载未包含受理规则基线）",
                           http=500)
    return rev.payload, rev.version


# ───────────────────────── 批次/文件登记 ─────────────────────────

def create_batch(session, *, channel: str, instance: str, po_ref: str | None = None,
                 trace: str | None = None) -> m.Batch:
    """BT 发号 + 批次行（受理中）。channel 写入即校验（intake_channel 枚举，依赖纪律④）。"""
    get_registry().validate("intake_channel", channel, where="create_batch")
    batch_id = _next_batch(session, instance)
    row = m.Batch(batch_id=batch_id, channel=channel,
                  instance_display="中国" if instance == "CN" else "海外",
                  instance=instance, files=0, status="受理中", ok=0, err=0, filtered=0,
                  time=datetime.now(timezone.utc).astimezone().strftime("%H:%M"),
                  created_ts=now_iso(), trace_id=trace)
    session.add(row)
    session.commit()
    return row


def _next_batch(session, instance: str) -> str:
    """BT-YYYYMMDD-NNN 全库唯一（编号规则不含实例段）：分实例计数域同日可能同序，
    碰撞则向本域继续重发（intake 页「今日 31 批次」为跨渠道全局序的演示口径防御）。"""
    from app.services.issuer import next_batch_no
    for _ in range(16):
        bid = next_batch_no(session, instance)
        if session.get(m.Batch, bid) is None:
            return bid
    raise CommandError("E_BATCH_ISSUE", "批次发号连续碰撞（>16 次），请检查发号域状态", http=500)


def find_business_dup(session, sha256_hex: str, target_doc_ref: str | None):
    """CON-05 业务幂等键命中查询（同摘要+同目标单据不重复受理）。target 缺省以空串参与唯一键。"""
    t = target_doc_ref or ""
    return session.scalar(select(m.IntakeLedger).where(
        m.IntakeLedger.sha256 == sha256_hex, m.IntakeLedger.target_doc_ref == t))


def add_file(session, batch: m.Batch, *, name: str, content: bytes,
             mime: str | None, po_ref: str | None, target_doc_ref: str | None) -> m.FileIntake:
    """登记文件行（原件落对象存储；受理时刻=接入时刻）。业务幂等命中由调用方先行 find_business_dup。"""
    digest, rel = object_store.save(content)
    used = [r.seq for r in session.scalars(select(m.FileIntake).where(
        m.FileIntake.batch_id == batch.batch_id))]
    seq = (max(used) + 1) if used else 0
    frow = m.FileIntake(batch_id=batch.batch_id, seq=seq, file=name,
                        intake_raw={"carrier": None, "note": None,
                                    "po_ref": po_ref, "target_doc_ref": target_doc_ref},
                        sha256=digest, mime_type=mime, local_path=rel, accepted_ts=now_iso())
    session.add(frow)
    session.commit()
    return frow


# ───────────────────────── 步骤级状态持久化（断点续跑检查点） ─────────────────────────

def _step_row(session, batch_id, seq, step_no):
    return session.scalar(select(m.FileStep).where(
        m.FileStep.batch_id == batch_id, m.FileStep.file_seq == seq,
        m.FileStep.step_no == step_no))


def _set_step(session, batch_id, seq, step_no, status, detail=None, *, commit=True):
    get_registry().validate("pipeline_step_status", status, where=f"FileStep {step_no}")
    row = _step_row(session, batch_id, seq, step_no)
    if row is None:
        row = m.FileStep(batch_id=batch_id, file_seq=seq, step_no=step_no, status="PENDING")
        session.add(row)
    row.status = status
    if detail is not None:
        row.detail_raw = detail
    row.ts = now_iso()
    if commit:
        session.commit()          # 步边界提交：中断后状态留存（检查点语义）
    else:
        session.flush()
    return row


# ───────────────────────── 流水线主驱动 ─────────────────────────

def run_file(session, batch: m.Batch, frow: m.FileIntake, *, rules_payload: dict,
             fail_after_step: int | None = None) -> dict:
    """驱动单文件走完（或续做）五步；已 DONE/SKIPPED 步骤跳过（幂等）。

    返回 {file, disposition, caseId, sha256, steps:[{no,name,status,detail}], note}。
    """
    content = object_store.read(frow.local_path)
    for no in (1, 2, 3, 4, 5):
        if _step_row(session, batch.batch_id, frow.seq, no) is None:
            _set_step(session, batch.batch_id, frow.seq, no, "PENDING", commit=False)
        st = _step_row(session, batch.batch_id, frow.seq, no)
        if st.status in ("DONE", "SKIPPED"):
            continue
        if frow.disposition == "FILTERED":
            # ②命中退回后未执行步骤一律 SKIPPED（不入发票池，摘要不登记——非发票无幂等对象）
            _set_step(session, batch.batch_id, frow.seq, no, "SKIPPED",
                      {"skipped_reason": "非发票已退回（FN-1-05②），后续步骤跳过"}, commit=False)
            continue
        if no == 5 and frow.disposition == "MANUAL_SORT":
            # ③人工分拣件：④摘要仍受理即登记（防替换），⑤派生跳过（无案件）
            _set_step(session, batch.batch_id, frow.seq, 5, "SKIPPED",
                      {"skipped_reason": "转人工分拣（FN-1-05③），派生待人工处置"}, commit=False)
            continue
        _set_step(session, batch.batch_id, frow.seq, no, "RUNNING", commit=False)
        try:
            outcome = _EXEC[no](session, batch, frow, content, rules_payload)
        except Exception as e:
            _set_step(session, batch.batch_id, frow.seq, no, "FAILED", {"error": str(e)}, commit=True)
            raise
        detail = outcome or {}
        _set_step(session, batch.batch_id, frow.seq, no, "DONE", detail, commit=True)
        if fail_after_step == no:
            raise IntakeInterrupt(f"模拟中断：第 {no} 步已完成并提交")
    session.commit()
    recompute_batch(session, batch.batch_id)
    steps = [{"no": s.step_no, "name": STEP_NAMES[s.step_no], "status": s.status,
              "detail": s.detail_raw} for s in session.scalars(
        select(m.FileStep).where(m.FileStep.batch_id == batch.batch_id,
                                 m.FileStep.file_seq == frow.seq).order_by(m.FileStep.step_no))]
    return {"file": frow.file, "disposition": frow.disposition, "caseId": frow.case_id,
            "sha256": frow.sha256, "steps": steps, "note": frow.note}


# ── 步 ①：信封解析 ──
def _s1(session, batch, frow, content, payload):
    flags = intake_parsers.detect_kind(content)
    ext = (frow.file.rsplit(".", 1)[-1] or "").lower() if "." in frow.file else ""
    allowed = (payload.get("carrier_routing", {}) or {}).get("allowed_types") or \
        ["xml", "ofd", "pdf", "jpg", "jpeg", "png"]
    if ext and ext not in allowed:
        raise CommandError("E_INTAKE_TYPE", f"类型 .{ext} 不在白名单（FN-1-03/05①）", http=400)
    detail = {"kind": flags["kind"], "ext": ext, "size": len(content),
              "header_ok": flags["header_ok"], "channel": batch.channel,
              "d": f"文件头探测 → {flags['kind']} · {len(content)} B"}
    return detail


# ── 步 ②：非发票过滤 ──
def _s2(session, batch, frow, content, payload):
    s1 = _step_row(session, batch.batch_id, frow.seq, 1).detail_raw or {}
    kws = payload["non_invoice_filter"]["keywords_by_type"]
    text_head = intake_parsers.text_head(content, s1.get("kind", "corrupt"))
    r = rules.run_rule("non_invoice_doc_filter",
                       {"filename": frow.file, "text_head": text_head, "keywords_by_type": kws})
    detail = {"rule": r["rule_id"], "result": r["result"], "hit_type": r["doc_type"], "d": r["note"]}
    if r["result"] == "FAILED":
        frow.disposition = "FILTERED"
        frow.doc_type = r["doc_type"]
        frow.note = (f"非发票 · 已自动退回并通知{'供应商（邮箱/DOX 通道）' if batch.channel != '门户上传' else '上传人'}"
                     f"（规则引擎 · 可申诉重提）· 命中类型：{r['doc_type']}")
        ir = dict(frow.intake_raw or {})
        ir.update({"carrier": "—", "note": frow.note, "appealable": True})
        frow.intake_raw = ir
        # 退回留痕：审计链事件（无案件，落 PLATFORM 链；通知为桩注记——演示口径本地 outbox）
        trace = _file_trace(session, batch, frow)
        append_block(session, ts=now_iso(), trace=trace, actor="system", act="CHANNEL_RECEIVED",
                     cs=None, from_state="信封解析完成", to_state="非发票退回",
                     note=f"{batch.channel} · {frow.file} · {r['note']} · 退回通知模板见渠道配置（桩）",
                     op=state_machine.component_version(session, _V_EVENT), category="intake")
        detail["terminal"] = True
        session.commit()
    return detail


# ── 步 ③：载体检测分流 ──
def _s3(session, batch, frow, content, payload):
    s1 = _step_row(session, batch.batch_id, frow.seq, 1).detail_raw or {}
    flags = intake_parsers.detect_kind(content)
    r = rules.run_rule("carrier_route_detect", {"kind": s1.get("kind"), "flags": flags})
    route = r["route"]
    # OFD 演示口径内嵌 XML 探测失败 → 派生不可行（FN-2-01 完整解包归 M4）：转人工分拣注记保留分流事实
    if route == "L1_ofd_direct" and _ofd_embedded_xml(content) is None:
        route = "L4_manual_review"
        r = {"rule_id": r["rule_id"], "result": r["result"],
             "note": r["note"] + " · 内嵌 XML 未探得（演示口径），转人工分拣（完整 OFD 抽取归 FN-2-01/M4）"}
    frow.carrier_route = route
    ir = dict(frow.intake_raw or {})
    ir["carrier"] = _carrier_display(route, frow.file)
    frow.intake_raw = ir
    detail = {"route": route, "rule": r["rule_id"], "d": r["note"]}
    if route == "L4_manual_review":
        frow.disposition = "MANUAL_SORT"
        frow.note = "异常 · 转人工分拣，已向来源渠道回执索取" + ("（加密件）" if flags.get("pdf_encrypt") else "（损坏/无法机读）")
        ir = dict(frow.intake_raw or {})
        ir.update({"note": frow.note, "bad": True})
        frow.intake_raw = ir
        trace = _file_trace(session, batch, frow)
        append_block(session, ts=now_iso(), trace=trace, actor="system", act="CARRIER_ROUTED",
                     cs=None, from_state="非发票过滤通过", to_state="人工分拣队列",
                     note=f"{batch.channel} · {frow.file} · {r['note']}",
                     op=state_machine.component_version(session, _V_ROUTE), category="intake")
        detail["terminal"] = True
        session.commit()
    return detail


# ── 步 ④：原件摘要登记 ──
def _s4(session, batch, frow, content, payload):
    sha = object_store.sha256_of(content)
    if frow.sha256 != sha:
        raise CommandError("E_INTAKE_OBJECT", "对象存储内容与登记摘要不一致（替换检测）", http=400)
    target = _target_for(session, batch, frow)
    dup = find_business_dup(session, sha, target or None)
    if dup is not None:
        raise CommandError("E_INTAKE_DUP",
                           f"摘要幂等命中：同摘要+同目标单据已于批次 {dup.batch_id} 受理（不重复受理，CON-05）",
                           http=409, details={"existing_case_id": dup.case_id, "existing_batch": dup.batch_id})
    ledger = m.IntakeLedger(sha256=sha, target_doc_ref=target or "", batch_id=batch.batch_id,
                            file_seq=frow.seq, channel=batch.channel, instance=batch.instance,
                            trace_id=_file_trace(session, batch, frow), accepted_at=now_iso())
    session.add(ledger)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise CommandError("E_INTAKE_DUP", "摘要幂等命中（并发重复提交）：不重复受理（CON-05）", http=409)
    frow.digest_ts = now_iso()
    session.commit()
    return {"sha256": sha, "display": f"{sha[:4]}…{sha[-4:]}", "target_doc_ref": target or "",
            "d": f"SHA-256 摘要登记完成 · {sha[:4]}…{sha[-4:]}（任何替换可被检测）"}


# ── 步 ⑤：路由识别引擎 → 派生 InvoiceCase ──
def _s5(session, batch, frow, content, payload):
    route = frow.carrier_route
    s4 = _step_row(session, batch.batch_id, frow.seq, 4).detail_raw or {}
    sha = s4["sha256"]
    trace = _file_trace(session, batch, frow)
    # 摘要幂等终检：他批次已登记同摘要+同目标 → 不重复受理（中断恢复/并发防护）
    lrow = find_business_dup(session, sha, (frow.intake_raw or {}).get("target_doc_ref"))
    if lrow is not None and (lrow.batch_id, lrow.file_seq) != (batch.batch_id, frow.seq):
        raise CommandError("E_INTAKE_DUP",
                           f"摘要幂等命中：既有受理 {lrow.batch_id}#L{lrow.file_seq}"
                           f"（案件 {lrow.case_id}）——不重复受理（CON-05）",
                           http=409, details={"existing_case_id": lrow.case_id,
                                              "existing_batch": lrow.batch_id})
    if route == "L2_ocr_vlm":
        doc, provider_disp, source_code = _ocr_stub_recognize(session, batch, frow, content, trace)
        parse_event = "OCR_RECOGNIZED"
        parse_v = _V_OCR
    elif route == "L1_ofd_direct":
        xml_bytes = _ofd_embedded_xml(content)
        doc = intake_parsers.parse_einvoice_xml(xml_bytes)
        provider_disp, source_code = "OFD 解包直读（平台内置 · 演示口径）", "xml_direct"
        parse_event, parse_v = "XML_PARSED", _V_PARSER
    elif route == "L1_pdf_text":
        text = intake_parsers.extract_pdf_text(content)
        doc = intake_parsers.parse_pdf_fields(text)
        provider_disp, source_code = "PDF 文本层直读（平台内置）", "xml_direct"   # field-alias §1 pdf_text→xml_direct
        parse_event, parse_v = None, _V_PARSER
    else:  # L1_xml_direct
        doc = intake_parsers.parse_einvoice_xml(content)
        if doc is None and b"<" in content[:2000] and (b"Invoice" in content or b"EInvoice" in content):
            doc = intake_parsers.parse_ubl_minimal(content)
            provider_disp, source_code = "UBL/Peppol 传输信封直读（演示口径）", "xml_direct"
        else:
            provider_disp, source_code = "XML 直读（免 Provider）", "xml_direct"
        parse_event, parse_v = "XML_PARSED", _V_PARSER
    if doc is None or doc.get("gross") is None:
        # 直读路径抽取不可行：不造数，转人工分拣（FN-2-01 完整抽取归 M4）
        frow.disposition = "MANUAL_SORT"
        frow.note = "直读未获票面金额字段 · 转人工分拣（完整抽取归 FN-2-01/M4，演示口径不造数）"
        ir = dict(frow.intake_raw or {})
        ir.update({"note": frow.note, "bad": True})
        frow.intake_raw = ir
        for ev, d, x in (
                ("CHANNEL_RECEIVED", "渠道受理 · 信封解析 · SHA-256 摘要登记",
                 f"{batch.channel} · {frow.file} · 摘要 {sha[:4]}…{sha[-4:]} 登记"),
                ("CARRIER_ROUTED", "载体检测分流（能直读的不送OCR）", f"分流至 {route}"),
        ):
            append_block(session, ts=now_iso(), trace=trace, actor="system", act=ev, cs=None,
                         from_state="受理流水线", to_state="人工分拣队列", note=x,
                         op=state_machine.component_version(session, _V_EVENT), category="intake")
        session.commit()
        return {"terminal": True, "manual_sort": True, "d": frow.note}

    case = _derive_case(session, batch, frow, doc, route, sha, trace,
                        provider_disp, source_code, parse_event, parse_v)
    ledger = session.scalar(select(m.IntakeLedger).where(
        m.IntakeLedger.sha256 == sha, m.IntakeLedger.target_doc_ref == (_target_for(session, batch, frow) or "")))
    if ledger is not None:
        ledger.case_id = case.case_id
    frow.case_id = case.case_id
    frow.status_snapshot = case.status
    frow.conf = case.confidence
    frow.disposition = "ACCEPTED"
    session.commit()
    return {"case_id": case.case_id, "confidence": case.confidence, "route": route,
            "d": f"派生案件 {case.case_id}（RECOGNIZED）· 置信度 {case.confidence} · trace {trace}"}


_EXEC = {1: _s1, 2: _s2, 3: _s3, 4: _s4, 5: _s5}


# ───────────────────────── 辅助件 ─────────────────────────

def _carrier_display(route: str, filename: str) -> str:
    return {"L1_xml_direct": "XML 原件 → 直读", "L1_ofd_direct": "OFD 原件 → 直读",
            "L1_pdf_text": "PDF 文本层 → 直读", "L2_ocr_vlm": "纸质扫描 → OCR（stub）",
            "L4_manual_review": "加密 PDF · 无法机读"}.get(route, route)


def _ofd_embedded_xml(content: bytes) -> bytes | None:
    """OFD=zip 容器；演示口径取首个 .xml 条目字节（真实 OFD 解包归 FN-2-01/M4）。"""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for n in z.namelist():
                if n.lower().endswith(".xml"):
                    return z.read(n)
    except Exception:
        return None
    return None


def _file_trace(session, batch, frow) -> str:
    """一文件一 trace（FN-0-13 trace 贯穿受理全链）；登记于 intake_raw 保幂等。"""
    ir = dict(frow.intake_raw or {})
    if not ir.get("trace_id"):
        from app.services.issuer import new_trace_id
        ir["trace_id"] = new_trace_id()
        frow.intake_raw = ir
        session.commit()
    return ir["trace_id"]


def _target_for(session, batch, frow) -> str:
    ir = frow.intake_raw or {}
    return ir.get("target_doc_ref") or ""


# ───────────────────────── stub Provider OCR 外发（FN-5-08 台账） ─────────────────────────

def _ocr_stub_recognize(session, batch, frow, content, trace):
    """M4 前 OCR 路由 stub Provider（P00 §6 演示口径）：每次调用登记一条 EgressLog。

    直读路径绝不调用本函数（零外发断言对照）；stub 输出为演示合成值——来源/证据均显式标注，
    不伪装真实识别（TODO(M4)：SPI 契约 provider-spi.schema.json 正式接入）。
    """
    sha = object_store.sha256_of(content)
    import re
    m2 = re.search(r"(?<!\d)(\d{8,20})(?!\d)", frow.file)
    invoice_no = m2.group(1) if m2 else f"STUB{sha[:8].upper()}"
    gross = round(1000 + int(sha[:6], 16) % 89000 + (int(sha[6:10], 16) % 100) / 100, 2)
    doc = {"invoice_no": invoice_no, "issue_date": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
           "invoice_type": "票种待认定（stub）", "seller_name": None, "seller_tax_id": None,
           "buyer_name": None, "buyer_tax_id": None, "net": None, "tax": None, "gross": gross,
           "currency": "CNY", "lines": [], "xml": None, "ns": "ocr_stub"}
    session.add(m.EgressLog(
        ts=now_iso(), batch_id=batch.batch_id, file_seq=frow.seq, case_id=None,
        provider_id="selfhosted-ocr-vlm-stub", purpose="recognize", payload_digest=sha,
        bytes_out=len(content),
        note="演示口径：M4 前 OCR 路由 stub Provider 外发登记（数据最小外发台账 FN-5-08；"
             "直读路径零外发为 E2E 断言项）"))
    session.commit()
    return doc, "自托管 OCR-VLM（SPI stub · 演示口径）", "ocr"


# ───────────────────────── 案件派生（⑤ 路由识别引擎） ─────────────────────────

def _derive_case(session, batch, frow, doc, route, sha, trace,
                 provider_disp, source_code, parse_event, parse_v):
    """结构化/归一化输出 → InvoiceCase 全量聚合（RECOGNIZED；checks 占位归编排器唯一写入口）。"""
    from app.services.issuer import next_case_no
    inst = batch.instance
    year = datetime.now(timezone.utc).astimezone().year
    case_id = next_case_no(session, inst, year)
    conf = _CONF_BY_ROUTE.get(route, 82)
    currency = doc.get("currency") or ("CNY" if inst == "CN" else "SGD")
    gross = float(doc["gross"])
    po_ref = (frow.intake_raw or {}).get("po_ref")
    meta = {
        "region": "CN · 中国" if inst == "CN" else "SG · 新加坡",
        "instance": inst,
        "ext": ("CN Extension · 数电票" if (doc.get("ns") == "einvoice") else
                ("OS Extension · 海外票" if inst == "OS" else "CN Extension · 增值税票")),
        "type": doc["invoice_type"],
        "invoice_type_machine": None,
        "po": po_ref, "supplier": doc.get("seller_name") or "（供应商待核）",
        "supplier_id": None,
        "amount_display": intake_parsers.amount_display(currency, gross),
        "received_at": (frow.accepted_ts or now_iso())[:16].replace("T", " "),
        "channel": f"{batch.channel}（运行期受理）",
        "adapter": None, "sm2": None, "vat": None,
        "risk_label": None, "confidence": conf,
        "provider": provider_disp,
        "claimed_by": None, "claimed_at": None, "claim_lock_expire_at": None,
        "doc_hold_pending": False, "document_created_receipt": None,
        "trace_id": trace,
    }
    facts = {"invoiceAmount": gross, "poAmount": None,
             "taxAmount": doc.get("tax"), "currency": currency, "variance": None}
    evidence = _build_evidence(session, doc, source_code, provider_disp)
    items = _build_items(doc, currency)
    file_obj = {
        "display": f"{frow.file} · {'1' if route != 'L2_ocr_vlm' else '—'} 页 · SHA-256 {sha[:4]}…{sha[-4:]}",
        "name": frow.file, "pages": 1, "sha256": f"{sha[:4]}…{sha[-4:]}",
        "has_xml_original": bool(doc.get("xml")),
        "note": "原件摘要（SHA-256）于受理时登记，任何替换可被检测（intake_ledger 幂等台账同源）。",
    }
    links = {"invoice": case_id, "supplier": meta["supplier"], "supplier_id": None,
             "po": po_ref, "po_state": None, "grn": [],
             "credit_note": {"relation": "NONE", "ref": None, "match_score": None,
                             "partial": None, "confirmed": False}}
    next_action = {
        "type": "HUMAN_REVIEW",
        "reason": "受理派生完成 · 合规校验链（查重/验真/红线）属 WP3.3 未激活，checks 占位 NOT_VERIFIED",
        "assign_to": "共享中心复核队列（演示口径归属；激活后按 FN-0-02 自动流转）",
    }
    case = m.Case(
        case_id=case_id, detail_level="full", status="RECOGNIZED",
        summary=f"受理派生：{meta['type']} · {meta['supplier']} · {meta['amount_display']} · 载体 {route}",
        instance=inst, region=meta["region"], ext=meta["ext"], invoice_type=meta["type"],
        po=po_ref, supplier=meta["supplier"], amount_display=meta["amount_display"],
        currency=currency, invoice_amount=gross, confidence=conf, provider=provider_disp,
        channel=meta["channel"], trace_id=trace, doc_hold_pending=False, load_seq=1000,
        meta_raw=meta, facts_raw=facts,
        links_raw=links, items_raw=items, file_raw=file_obj,
        source_xml=doc.get("xml"), seed_keys=[
            "caseId", "detail_level", "status", "summary", "meta", "facts", "checks",
            "evidence", "timeline", "links", "items", "file", "nextAction"]
        + (["source_xml"] if doc.get("xml") else []),
    )
    session.add(case)
    session.flush()
    for i, ev in enumerate(evidence):
        session.add(m.FieldEvidence(case_id=case_id, seq=i, field=ev["field"],
                                    source=ev["source"], confidence=float(ev["confidence"]),
                                    evidence_raw=ev))
    # checks 四槽位占位（唯一业务写入口=编排器；红线逻辑保留：任何 FAILED 自动 BLOCKED 由 WP3.3 激活后生效）
    placeholder = {item: {"result": "NOT_VERIFIED",
                          "note": "合规服务（WP3.3）未激活 · 受理派生占位（不代表查验结论）"}
                   for item in orchestrator.check_items()}
    orchestrator.apply_results(session, case, placeholder, transition=True, commit=False)
    # 时间线 + 审计链（双写）
    s1 = _step_row(session, batch.batch_id, frow.seq, 1).detail_raw or {}
    timeline_evts = [
        ("CHANNEL_RECEIVED", "渠道受理 · 信封解析 · SHA-256 摘要登记",
         f"{batch.channel} · {frow.file} · 文件头 {s1.get('kind')} · 摘要 {sha[:4]}…{sha[-4:]} 登记（幂等台账 intake_ledger）",
         _V_EVENT),
        ("CARRIER_ROUTED", "载体检测分流（能直读的不送OCR）",
         f"分流至 {route}（规则引擎确定性判断 · carrier_route_detect）", _V_ROUTE),
    ]
    if parse_event:
        timeline_evts.append((parse_event,
                              "OCR识别（Provider，字段带坐标+原文证据）" if parse_event == "OCR_RECOGNIZED"
                              else "XML结构化直读解析完成（演示口径关键字段子集，完整23字段归FN-2-01/M4）",
                              f"载体字节外发登记 {len(session.scalars(select(m.EgressLog).where(
                                  m.EgressLog.batch_id == batch.batch_id,
                                  m.EgressLog.file_seq == frow.seq)).all())} 条" if parse_event == "OCR_RECOGNIZED"
                              else f"Schema 归一前置：{provider_disp}",
                              parse_v))
    timeline_evts.append(("INBOUND_ACCEPTED", "识别结果接收 · Schema归一化",
                          f"{len(evidence)} 字段入证据链 · source={source_code} · trace {trace}", _V_NORMALIZE))
    for act, d, x, comp in timeline_evts:
        v = state_machine.component_version(session, comp)
        state_machine.append_case_event(session, case, a="system", act=act, d=d, x=x, v=v, commit=False)
        append_block(session, ts=now_iso(), trace=trace, actor="system", act=act, cs=case_id,
                     from_state="受理流水线", to_state="RECOGNIZED", note=x, op=v,
                     category="intake", commit=False)
    session.commit()
    return case


def _build_evidence(session, doc, source_code, provider_disp):
    """字段级证据（FN-0-05）：直读值附原文节点/正则出处；格式类确定性规则跑注（checks 归 WP3.3）。"""
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    cur = doc.get("currency")
    entries = [
        ("header.invoice_no", "发票号码", doc.get("invoice_no"), "invoice_no_format_check",
         {"instance": "CN" if source_code == "xml_direct" and cur == "CNY" else "OS",
          "invoice_no": doc.get("invoice_no")}),
        ("header.issue_date", "开票日期", doc.get("issue_date"), "date_valid_range",
         {"issue_date": doc.get("issue_date"), "today": today}),
        ("seller.name", "销售方名称", doc.get("seller_name"), None, None),
        ("seller.tax_id", "销售方税号", doc.get("seller_tax_id"), "tax_id_checksum",
         {"tax_id": doc.get("seller_tax_id"), "instance": "CN" if cur == "CNY" else "OS"}),
        ("buyer.name", "购买方名称", doc.get("buyer_name"), None, None),
        ("buyer.tax_id", "购买方税号", doc.get("buyer_tax_id"), None, None),
        ("total.net_amount", "合计金额（不含税）", doc.get("net"), None, None),
        ("total.tax_amount", "合计税额", doc.get("tax"), None, None),
        ("total.gross_amount", "价税合计（含税）", doc.get("gross"), None, None),
    ]
    out_ev = []
    conf = 0.99 if source_code == "xml_direct" else 0.82
    for field, label, value, rule_id, rctx in entries:
        if value is None:
            continue
        rule_note = None
        if rule_id:
            try:
                rr = rules.run_rule(rule_id, rctx)
                rule_note = f"{rule_id} {'✓' if rr['result'] == 'PASSED' else '✗'}"
            except Exception:
                rule_note = None
        raw = (f"XML 节点 {field} = {value}" if source_code == "xml_direct"
               else f"stub OCR 合成值（演示口径）= {value}")
        ev = {"field": field, "label": label, "value": value, "source": source_code,
              "confidence": conf if source_code == "xml_direct" else 0.82,
              "evidence": {"page": 1, "bbox": "—（XML 节点）" if source_code == "xml_direct" else "—（stub 无坐标）",
                           "raw_text": raw, "rule": rule_note,
                           "model_version": (f"{provider_disp}" if source_code != "xml_direct" else
                                             "cn-xml-parser v3.2"),
                           "provider": provider_disp}}
        if doc.get("ns") == "ocr_stub":
            ev["evidence"]["model_version"] = "qwen-ocr-stub（演示）"
        out_ev.append(ev)
    # 含税+税额勾稽注记（规则跑注入证据；checks 写入归 WP3.3 orchestrator）
    for e in out_ev:
        if e["field"] == "total.gross_amount" and doc.get("net") is not None and doc.get("tax") is not None:
            try:
                rr = rules.run_rule("amount_tax_sum_check",
                                    {"net": doc["net"], "tax": doc["tax"], "gross": doc["gross"],
                                     "tolerance_reconcile": 0.06})
                e["evidence"]["rule"] = f"amount_tax_sum_check {'✓' if rr['result'] == 'PASSED' else '✗'}"
            except Exception:
                pass
    return out_ev


def _build_items(doc, currency):
    sym = {"CNY": "¥", "SGD": "S$", "USD": "US$"}.get(currency or "CNY", "")
    if not doc.get("lines"):
        return {"note": "来源：" + ("XML 直读" if doc.get("xml") else "stub/文本层") +
                " · 无行项目或行级抽取归 FN-2-01（M4）",
                "layout": "CN8" if (currency or "CNY") == "CNY" else "OS6",
                "columns": ["#", "货物或应税项目名称", "规格型号", "单位", "数量", "单价", "税率", "金额"]
                if (currency or "CNY") == "CNY" else ["#", "描述", "数量", "单价", "税率", "金额"],
                "rows": []}
    cn = (currency or "CNY") == "CNY"
    rows = []
    for l in doc["lines"]:
        if cn:
            rows.append([str(l.get("line") or ""), str(l.get("name") or ""), "—", "—",
                         str(l.get("qty") if l.get("qty") is not None else "—"),
                         f"{sym}{(l.get('price') or 0):,.2f}" if l.get("price") is not None else "—",
                         f"{(l.get('tax_rate') or 0)*100:.0f}%" if l.get("tax_rate") is not None else "—",
                         f"{sym}{(l.get('amount') or 0):,.2f}" if l.get("amount") is not None else "—"])
        else:
            rows.append([str(l.get("line") or ""), str(l.get("name") or ""),
                         str(l.get("qty") or "—"), str(l.get("price") or "—"),
                         str(l.get("tax_rate") or "—"), str(l.get("amount") or "—")])
    return {"note": "来源：XML 直读 · 行级勾稽归 WP3.3/M4", "layout": "CN8" if cn else "OS6",
            "columns": (["#", "货物或应税项目名称", "规格型号", "单位", "数量", "单价", "税率", "金额"]
                        if cn else ["#", "描述", "数量", "单价", "税率", "金额"]),
            "rows": rows}


# ───────────────────────── 批次汇总与断点续跑 API（FN-1-06/07） ─────────────────────────

def recompute_batch(session, batch_id: str) -> m.Batch:
    """批次双层状态与进度重算：文件数/成功/异常/非发票过滤 + 状态迁移。"""
    batch = session.get(m.Batch, batch_id)
    rows = session.scalars(select(m.FileIntake).where(m.FileIntake.batch_id == batch_id)).all()
    batch.files = len(rows)
    batch.ok = sum(1 for r in rows if r.disposition == "ACCEPTED")
    batch.err = sum(1 for r in rows if r.disposition in ("FAILED", "MANUAL_SORT"))
    batch.filtered = sum(1 for r in rows if r.disposition == "FILTERED")
    unfinished = 0
    for r in rows:
        steps = session.scalars(select(m.FileStep).where(
            m.FileStep.batch_id == batch_id, m.FileStep.file_seq == r.seq)).all()
        if r.disposition is None and (not steps or any(s.status not in ("DONE", "SKIPPED") for s in steps)):
            unfinished += 1
    if unfinished:
        progressed = any(any(s.step_no >= 4 and s.status == "DONE" for s in session.scalars(
            select(m.FileStep).where(m.FileStep.batch_id == batch_id, m.FileStep.file_seq == r.seq)))
            for r in rows if r.disposition is None)
        batch.status = "识别中" if progressed else "受理中"
    else:
        batch.status = "部分异常" if batch.err else "已完成"
    # 写入即校验（存储态为合并前词汇，对照 enum-registry.batch_status 走别名归一——与 seed_loader 同口径）
    from app.services.seed_loader import BATCH_STATUS_ALIAS
    get_registry().validate("batch_status", BATCH_STATUS_ALIAS.get(batch.status, batch.status),
                            where=f"recompute_batch {batch_id}")
    session.commit()
    return batch


def resume_batch(session, batch_id: str) -> dict:
    """批次级断点续跑：从各文件最后成功检查点继续（DONE 步跳过；已登记摘要不重复受理）。"""
    payload, _ver = current_intake_rules(session)
    batch = session.get(m.Batch, batch_id)
    if batch is None:
        raise CommandError("E_BATCH_NOT_FOUND", f"批次 {batch_id} 不存在", http=404)
    results = []
    for r in session.scalars(select(m.FileIntake).where(
            m.FileIntake.batch_id == batch_id).order_by(m.FileIntake.seq)):
        steps = session.scalars(select(m.FileStep).where(
            m.FileStep.batch_id == batch_id, m.FileStep.file_seq == r.seq)).all()
        if r.disposition is not None and (not steps or all(s.status in ("DONE", "SKIPPED") for s in steps)):
            results.append({"file": r.file, "resumed": False, "disposition": r.disposition,
                            "reason": "检查点已完成，续跑跳过"})
            continue
        if r.disposition is None and (not steps or all(s.status in ("PENDING",) for s in steps)):
            # 从未开始的文件：若摘要已在台账（中断于登记步之后回滚的极端态），直接标注重复防护
            dup = find_business_dup(session, r.sha256, (r.intake_raw or {}).get("target_doc_ref"))
            if dup is not None and dup.batch_id != batch_id:
                r.disposition = "ACCEPTED"
                r.case_id = dup.case_id
                r.note = "摘要幂等命中既有受理（不重复受理）"
                session.commit()
                results.append({"file": r.file, "resumed": False, "disposition": "ACCEPTED",
                                "reason": "摘要幂等命中"})
                continue
        out = run_file(session, batch, r, rules_payload=payload)
        out["resumed"] = True
        results.append(out)
    recompute_batch(session, batch_id)
    return {"batch": batch_id, "status": batch.status, "files": results}


def retry_file_failed_steps(session, batch_id: str, seq: int) -> dict:
    """文件级步骤重试（FN-1-07）：FAILED 步重置后续跑；DONE/SKIPPED 不动（识别不重跑）。"""
    batch = session.get(m.Batch, batch_id)
    if batch is None:
        raise CommandError("E_BATCH_NOT_FOUND", f"批次 {batch_id} 不存在", http=404)
    frow = session.scalar(select(m.FileIntake).where(
        m.FileIntake.batch_id == batch_id, m.FileIntake.seq == seq))
    if frow is None:
        raise CommandError("E_FILE_NOT_FOUND", f"批次 {batch_id} 文件序 {seq} 不存在", http=404)
    steps = session.scalars(select(m.FileStep).where(
        m.FileStep.batch_id == batch_id, m.FileStep.file_seq == seq)).all()
    failed = [s for s in steps if s.status == "FAILED"]
    if not failed:
        # 无 FAILED 步：等价于检查点续跑（未 DONE 步继续）
        return {"batch": batch_id, "seq": seq, "retried_steps": [], "result":
                resume_batch(session, batch_id)["files"]}
    for s in failed:
        _set_step(session, batch_id, seq, s.step_no, "PENDING", None, commit=False)
    if frow.disposition == "FAILED":
        frow.disposition = None
    session.commit()
    payload, _ = current_intake_rules(session)
    out = run_file(session, batch, frow, rules_payload=payload)
    out["retried_steps"] = [s.step_no for s in failed]
    return out
