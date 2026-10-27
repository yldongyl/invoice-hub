# -*- coding: utf-8 -*-
"""WP3.3 合规服务测试（FN-5-01~05 + FN-4-02/03 · P04 指定四用例+边界）。

覆盖：SM2 真实验签红线（FAILED→BLOCKED+失败回执归档）；授权查验超时→NOT_VERIFIED→
单独排定重试且识别不重跑（调用计数断言）；CON-05 两键构造与相似度阈值边界（含 sim==阈值
含边界、跨实例分池）；多源冲突→OCR_CROSS_CHECK_CONFLICT+置信度降级+NEEDS_REVIEW+
采信规则配置化；勾稽实跑超容差转人工；红线告警生成。
"""

import pytest
from sqlalchemy import func, select

from app.domain import models as m
from app.services import (audit_chain, compliance_service, config_center, dedup_service,
                          fusion_service, intake_pipeline as ip, object_store, sm2_service,
                          state_machine, verify_channel)

from tests.conftest import schema_errors


def mk_xml(no: str, gross: float, *, tax=1300.0, net=10000.0, supplier="测试供应商甲",
           buyer="澜坞（上海）采购科技有限公司") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header><InvoiceNo>{no}</InvoiceNo><IssueDate>2026-10-26</IssueDate>
  <InvoiceType>数电票（增值税专用发票）</InvoiceType></Header>
  <Seller><Name>{supplier}</Name><TaxID>91320500MA1MXY7N5K</TaxID></Seller>
  <Buyer><Name>{buyer}</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Total><NetAmount>{net:.2f}</NetAmount><TaxAmount>{tax:.2f}</TaxAmount>
  <GrossAmount>{gross:.2f}</GrossAmount></Total>
</EInvoice>
"""


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")
    monkeypatch.setattr(sm2_service, "GM_RECEIPT_DIR", tmp_path / "gm-receipts")
    verify_channel.reset_calls()
    return tmp_path


def accept(fresh_session, name, content, *, channel="门户上传", instance="CN"):
    payload, _ = ip.current_intake_rules(fresh_session)
    batch = ip.create_batch(fresh_session, channel=channel, instance=instance)
    frow = ip.add_file(fresh_session, batch, name=name, content=content, mime=None,
                       po_ref=None, target_doc_ref=None)
    out = ip.run_file(fresh_session, batch, frow, rules_payload=payload)
    return batch, frow, out


# ───────────────────────── 指定用例①：SM2 FAILED → 红线 BLOCKED + 失败回执归档 ─────────────────────────

def test_sm2_failed_redline_blocked_with_failed_receipt(fresh_session, tmp_dirs):
    xml = mk_xml("2431200000088001", 11300.0)
    signed_bytes = sm2_service.attach_signature(xml)
    # 篡改=签名后改票面金额（原件替换检测场景，0379 路径重放口径）
    tampered = signed_bytes.replace(b"11300.00", b"11299.00")
    assert tampered != signed_bytes
    batch, frow, out = accept(fresh_session, "数电票_篡改_88001.xml", tampered)
    cid = out["caseId"]
    case = fresh_session.get(m.Case, cid)
    # 红线链路：SM2 FAILED → authenticity FAILED → BLOCKED（apply_results 唯一通道）+ 建档挂起
    assert case.status == "BLOCKED"
    assert case.checks_raw["authenticity"]["result"] == "FAILED"
    assert case.doc_hold_pending is True                    # CON-02 建档挂起
    # 失败回执**也**产生并归档（FN-5-01）
    rc = case.meta_raw["sm2"]
    assert rc["ok"] is False and rc["receipt_no"].startswith("gm-rcpt-")
    rf = tmp_dirs / "gm-receipts" / f"{rc['receipt_no']}.json"
    assert rf.exists() and '"FAILED"' in rf.read_text(encoding="utf-8")
    # 高风险通知（告警生成）+ 时间线 FAILED 事件 + 状态流转留痕
    acts = [t.act for t in fresh_session.scalars(select(m.TimelineEvent).where(
        m.TimelineEvent.case_id == cid).order_by(m.TimelineEvent.seq))]
    assert "SM2_VERIFY_FAILED" in acts and "STATUS_CHANGE" in acts
    alert = fresh_session.scalars(select(m.Alert).where(m.Alert.case_ref == cid)).all()
    assert any("验真红线" in a.title for a in alert)
    # 审计链完整性（篡改写入后全链可验）
    assert audit_chain.verify_chain(fresh_session, verifier="wp33-sm2")["ok"]


# ───────────────────────── 指定用例②：查验超时→NOT_VERIFIED→单独排定重试（识别不重跑） ─────────────────────────

def test_verify_timeout_retry_without_rerun(fresh_session, tmp_dirs):
    # 通道置超时模式（配置中心演示模式项）
    row = config_center.get_effective(fresh_session, "auth_verify_channel_mode")
    row.value_raw = {**row.value_raw, "value": "timeout"}
    fresh_session.commit()
    content = sm2_service.attach_signature(mk_xml("2431200000088002", 11300.0))
    batch, frow, out = accept(fresh_session, "数电票_超时_88002.xml", content)
    cid = out["caseId"]
    case = fresh_session.get(m.Case, cid)
    # 超时→NOT_VERIFIED（案件仍 RECOGNIZED——无红线条件）+ AUTH_QUERY_TIMEOUT 事件 + 排定重试任务
    assert case.status == "RECOGNIZED"
    assert case.checks_raw["authenticity"]["result"] == "NOT_VERIFIED"
    task = fresh_session.scalar(select(m.VerifyRetryTask).where(
        m.VerifyRetryTask.case_id == cid, m.VerifyRetryTask.step == "verify_auth"))
    assert task is not None and task.state == "queued"
    receipts_before = len(list((tmp_dirs / "gm-receipts").glob("*.json")))
    eg_recog_before = fresh_session.scalar(select(func.count()).select_from(m.EgressLog).where(
        m.EgressLog.purpose == "recognize"))
    assert eg_recog_before == 0                              # 直读零识别外发
    # 执行重试（越过 next_run_at=now+5min 的演示时钟）：只重发查验
    verify_channel.reset_calls()
    res = verify_channel.run_due_retries(fresh_session, now="2099-01-01T00:00:00+08:00")
    assert res["processed"] == 1
    case = fresh_session.get(m.Case, cid)
    assert case.checks_raw["authenticity"]["result"] == "PASSED"
    assert fresh_session.scalar(select(m.VerifyRetryTask).where(
        m.VerifyRetryTask.case_id == cid)).state == "done"
    # 调用计数断言（识别不重跑）：SM2 回执文件数不变、recognize 外发不变、查验通道+1
    assert len(list((tmp_dirs / "gm-receipts").glob("*.json"))) == receipts_before
    assert fresh_session.scalar(select(func.count()).select_from(m.EgressLog).where(
        m.EgressLog.purpose == "recognize")) == eg_recog_before
    assert len(verify_channel.calls()) == 1
    # 同票缓存生效（FN-5-02 避免重复计费）：再次查验零通道调用
    before = len(verify_channel.calls())
    case2 = fresh_session.get(m.Case, cid)
    r, _ = verify_channel.verify(fresh_session, case2)
    assert r == "PASSED" and len(verify_channel.calls()) == before


# ───────────────────────── 指定用例③：CON-05 两键+相似度阈值边界+DEDUP_BLOCKED+不入池 ─────────────────────────

def test_dedup_cn_two_key_construct_and_hard_hit(fresh_session):
    a = sm2_service.attach_signature(mk_xml("2431200000088010", 11300.0))
    batch, frow, out = accept(fresh_session, "数电票_入池_88010.xml", a)
    cid_a = out["caseId"]
    bk = dedup_service.biz_key(fresh_session, fresh_session.get(m.Case, cid_a))
    assert bk["key"] == "|2431200000088010|11300.00"          # CN=代码(null→空)+号码+价税合计
    pool = dedup_service.pool_keys(fresh_session, "CN")
    assert any(p["case_id"] == cid_a for p in pool)           # 正常件入池
    # 同票面重复：不同字节（换购买方）→ 摘要幂等不拦截，查重红线拦截
    b = sm2_service.attach_signature(mk_xml("2431200000088010", 11300.0, buyer="第二购买方"))
    _, frow_b, out_b = accept(fresh_session, "数电票_重复_88010B.xml", b)
    case_b = fresh_session.get(m.Case, out_b["caseId"])
    assert case_b.status == "BLOCKED"
    assert case_b.checks_raw["duplicate"]["result"] == "FAILED"
    assert "硬命中" in case_b.checks_raw["duplicate"]["note"] and f"{cid_a}" in case_b.checks_raw["duplicate"]["note"]
    acts = [t.act for t in fresh_session.scalars(select(m.TimelineEvent).where(
        m.TimelineEvent.case_id == case_b.case_id).order_by(m.TimelineEvent.seq))]
    assert "DEDUP_CHECK" in acts and "DEDUP_BLOCKED" in acts and "STATUS_CHANGE" in acts
    # 不入发票池（BLOCKED 排除——后续同键件命中 A 不命中 B）
    pool2 = {p["case_id"] for p in dedup_service.pool_keys(fresh_session, "CN")}
    assert case_b.case_id not in pool2 and cid_a in pool2
    # 红线告警生成 + FN-5-09 读侧兼容（builder 可消费运行期告警，展示级词汇/evidence 要素齐备）
    assert fresh_session.scalars(select(m.Alert).where(
        m.Alert.case_ref == case_b.case_id)).first() is not None
    from app.services import dashboard as dash
    from app.services.tenant import TenantContext
    items = dash.build_alert_items(fresh_session, TenantContext.of("CN"))
    assert any("重复票红线拦截" in i["title"] for i in items)
    assert all(i["level"] in ("danger", "warning") and "evidence" in i for i in items)


def test_dedup_similarity_threshold_boundary(fresh_session):
    a = sm2_service.attach_signature(mk_xml("1234567890", 11300.0))     # 10 位老票号形态
    _, _, out = accept(fresh_session, "数电票_基准_10.xml", a)
    # 默认阈值 1.0：票号差 1 位（sim=0.9）→ 模糊不命中，仅硬命中拦截
    c = sm2_service.attach_signature(mk_xml("1234567891", 11300.0))
    _, _, out_c = accept(fresh_session, "数电票_差1位_11.xml", c)
    assert fresh_session.get(m.Case, out_c["caseId"]).status == "RECOGNIZED"
    # 阈值降到 0.9：sim==0.9 **恰等于阈值 → 命中**（≥ 边界语义，含等于判命中，tolerance_check 同口径）
    row = config_center.get_effective(fresh_session, "dedup_similarity_threshold")
    row.value_raw = {**row.value_raw, "value": 0.9}
    fresh_session.commit()
    d = sm2_service.attach_signature(mk_xml("1234567892", 11300.0))
    _, _, out_d = accept(fresh_session, "数电票_差1位_12.xml", d)
    case_d = fresh_session.get(m.Case, out_d["caseId"])
    assert case_d.status == "BLOCKED" and "相似度命中" in case_d.checks_raw["duplicate"]["note"]
    # sim=0.8 < 0.9 → 不命中（阈值上方拦截、下方放行——边界两侧；两位差异）
    e = sm2_service.attach_signature(mk_xml("1234557790", 11300.0))
    _, _, out_e = accept(fresh_session, "数电票_差2位_x.xml", e)
    assert fresh_session.get(m.Case, out_e["caseId"]).status == "RECOGNIZED"
    # 金额不同不触发模糊（键含价税合计）：no=…891 gross=11400 sim≥阈值但金额≠ → 不命中
    f = sm2_service.attach_signature(mk_xml("1234567899", 11400.0, net=10100.0, tax=1300.0))
    _, _, out_f = accept(fresh_session, "数电票_异额.xml", f)
    assert fresh_session.get(m.Case, out_f["caseId"]).status == "RECOGNIZED"
    # P95 目标（sla 200ms）内完成池比对
    assert dedup_service.check(fresh_session, fresh_session.get(m.Case, out_f["caseId"]))["elapsed_ms"] < 200


def test_dedup_os_key_and_tenant_isolation(fresh_session):
    ubl = """<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>SG-DUP-9001</ID><IssueDate>2026-10-20</IssueDate>
  <DocumentCurrencyCode>SGD</DocumentCurrencyCode>
  <AccountingSupplierParty><Party><PartyName><Name>OS Supplier X</Name></PartyName>
  <PartyTaxScheme><TaxID>S24LE3399E</TaxID></PartyTaxScheme></Party></AccountingSupplierParty>
  <TaxExclusiveAmount>1000.00</TaxExclusiveAmount><TaxAmount>80.00</TaxAmount>
  <PayableAmount>1080.00</PayableAmount></Invoice>""".encode()
    _, _, o1 = accept(fresh_session, "SG_INV_9001.xml", ubl, channel="SAP DOX", instance="OS")
    bk = dedup_service.biz_key(fresh_session, fresh_session.get(m.Case, o1["caseId"]))
    assert bk["key"] == "SG-DUP-9001|1080.00|OS Supplier X"    # OS=号码+金额+供应商
    _, _, o2 = accept(fresh_session, "SG_INV_9001_copy.xml",
                      ubl + "\n<!--副本-->".encode("utf-8"),
                      channel="SAP DOX", instance="OS")
    assert fresh_session.get(m.Case, o2["caseId"]).status == "BLOCKED"
    # 四隔离④分池：CN 借用同票号件不受 OS 池影响（CN 键结构含空代码段，天然与 OS 键不同型）
    cn_same = sm2_service.attach_signature(mk_xml("SG-DUP-9001", 11300.0))
    _, _, c1 = accept(fresh_session, "CN_借号件.xml", cn_same, instance="CN")
    assert fresh_session.get(m.Case, c1["caseId"]).status == "RECOGNIZED"


# ───────────────────────── 指定用例④：多源冲突→事件+降级+NEEDS_REVIEW+采信配置化 ─────────────────────────

def test_fusion_conflict_degrade_and_review(fresh_session):
    content = sm2_service.attach_signature(mk_xml("2431200000088020", 11300.0))
    _, _, out = accept(fresh_session, "数电票_冲突母本.xml", content)
    case = fresh_session.get(m.Case, out["caseId"])
    assert case.confidence == 99
    # OCR stub 值 ¥11,270 vs XML ¥11,300（差 30 > 容差 0.06；0381 案口径）
    fused = fusion_service.merge(fresh_session, case, {"total.gross_amount": 11270.0})
    assert fused["conflicts"] and fused["degraded"]
    case = fresh_session.get(m.Case, out["caseId"])
    assert case.confidence == 82                                 # 降级=policy.degrade_to（配置化）
    # 不静默取舍：OCR 值另立证据行（source=ocr，注记未采信）
    ev = fresh_session.scalars(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id, m.FieldEvidence.source == "ocr")).all()
    assert len(ev) == 1 and "未采信" in ev[0].evidence_raw["label"]
    assert "采信=xml_direct" in ev[0].evidence_raw["evidence"]["rule"]   # 结构化原件优先（配置）
    # 冲突→NEEDS_REVIEW（auto_flow conflict 通道）+ OCR_CROSS_CHECK_CONFLICT 事件
    path = state_machine.auto_flow(fresh_session, case.case_id, conflict=True)
    assert [t["to"] for t in path] == ["NEEDS_REVIEW"]
    acts = [t.act for t in fresh_session.scalars(select(m.TimelineEvent).where(
        m.TimelineEvent.case_id == case.case_id).order_by(m.TimelineEvent.seq))]
    assert "OCR_CROSS_CHECK_CONFLICT" in acts


def test_fusion_consistent_cross_check_annotation(fresh_session):
    content = sm2_service.attach_signature(mk_xml("2431200000088021", 11300.0))
    _, _, out = accept(fresh_session, "数电票_互证.xml", content)
    case = fresh_session.get(m.Case, out["caseId"])
    fused = fusion_service.merge(fresh_session, case, {"total.gross_amount": 11300.00})
    assert fused["consistent"] and not fused["conflicts"]
    case = fresh_session.get(m.Case, out["caseId"])
    assert case.confidence == 99                                 # 互证支撑置信度，不降级
    xml_ev = fresh_session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id,
        m.FieldEvidence.field == "total.gross_amount"))
    assert "XML 直读 + OCR 互证一致" in xml_ev.evidence_raw["evidence"]["rule"]
    acts = [t.act for t in fresh_session.scalars(select(m.TimelineEvent).where(
        m.TimelineEvent.case_id == case.case_id))]
    assert "OCR_CROSS_CHECK" in acts


def test_fusion_adoption_policy_configurable(fresh_session):
    # 采信方向配置化：priority 首元素改为 ocr → 冲突注记采信=ocr（双方证据仍都留存）
    row = config_center.get_effective(fresh_session, "fusion_adoption_policy")
    pol = dict(row.value_raw["value"])
    pol["priority"] = ["ocr", "xml_direct"]
    row.value_raw = {**row.value_raw, "value": pol}
    fresh_session.commit()
    content = sm2_service.attach_signature(mk_xml("2431200000088022", 11300.0))
    _, _, out = accept(fresh_session, "数电票_反转采信.xml", content)
    case = fresh_session.get(m.Case, out["caseId"])
    fused = fusion_service.merge(fresh_session, case, {"total.gross_amount": 11270.0})
    assert fused["conflicts"]
    ev = fresh_session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id, m.FieldEvidence.source == "ocr",
        m.FieldEvidence.field == "total.gross_amount"))
    assert "采信=ocr" in ev.evidence_raw["evidence"]["rule"]


# ───────────────────────── FN-4-03 勾稽实跑（超容差转人工） ─────────────────────────

def test_amount_reconcile_over_tolerance_review(fresh_session):
    # net+tax=11300 ≠ gross 11301（差 1 > 容差 0.06）：SM2 有效签名（对篡改和的文本签名）
    xml = mk_xml("2431200000088030", 11301.0, net=10000.0, tax=1300.0)
    content = sm2_service.attach_signature(xml)
    _, _, out = accept(fresh_session, "数电票_勾稽不平.xml", content)
    case = fresh_session.get(m.Case, out["caseId"])
    assert case.checks_raw["authenticity"]["result"] == "PASSED"   # 验签本身通过
    assert case.status == "NEEDS_REVIEW"                           # 勾稽冲突→转人工（FN-4-03）
    gross_ev = fresh_session.scalar(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id,
        m.FieldEvidence.field == "total.gross_amount"))
    assert "amount_tax_sum_check ✗" in gross_ev.evidence_raw["evidence"]["rule"]
