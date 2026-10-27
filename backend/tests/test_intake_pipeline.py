# -*- coding: utf-8 -*-
"""WP3.1 五步受理流水线单测（FN-1-05/06/07 · FN-5-08 外发台账 · 案件派生）。

数据锚点：现场造 seeds 之外新 XML（含 demo XML）；对象存储目录经 monkeypatch 走 tmp（测试零污染）。
"""

import pytest
from sqlalchemy import func, select

from app.domain import models as m
from app.services import intake_pipeline as ip, object_store, state_machine
from app.services.errors import CommandError

from tests.conftest import schema_errors


NEW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header>
    <InvoiceNo>2431200000077701</InvoiceNo>
    <IssueDate>2026-10-26</IssueDate>
    <InvoiceType>数电票（增值税专用发票）</InvoiceType>
  </Header>
  <Seller><Name>苏州东方光电有限公司</Name><TaxID>91320500MA1MXY7N5K</TaxID></Seller>
  <Buyer><Name>澜坞（上海）采购科技有限公司</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Items>
    <Item lineNo="1"><Name>*光学元件*工业镜头</Name><Spec>12mm</Spec><Unit>件</Unit>
      <Qty>10</Qty><Price>1000.00</Price><TaxRate>0.13</TaxRate><Amount>10000.00</Amount></Item>
  </Items>
  <Total><NetAmount>10000.00</NetAmount><TaxAmount>1300.00</TaxAmount>
    <GrossAmount>11300.00</GrossAmount></Total>
  <Signature alg="SM2">（测试样例）</Signature>
</EInvoice>
"""

CONTRACT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Contract><Title>框架协议</Title><Note>本件为合同，非供应商发票</Note></Contract>
"""

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def tmp_objects(tmp_path, monkeypatch):
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")


def _run_one(fresh_session, name="数电票_苏州东方_77701.xml", content=NEW_XML.encode(),
             channel="门户上传", instance="CN", po_ref=None, target=None):
    payload, ver = ip.current_intake_rules(fresh_session)
    batch = ip.create_batch(fresh_session, channel=channel, instance=instance)
    frow = ip.add_file(fresh_session, batch, name=name, content=content, mime=None,
                       po_ref=po_ref, target_doc_ref=target)
    out = ip.run_file(fresh_session, batch, frow, rules_payload=payload)
    return batch, frow, out


def test_rules_asset_loaded(fresh_session):
    payload, ver = ip.current_intake_rules(fresh_session)
    assert ver == "v2026-10-20.2"
    assert "合同" in payload["non_invoice_filter"]["keywords_by_type"]


def test_xml_full_chain_derives_case(fresh_session, case_validator, events_validator):
    batch, frow, out = _run_one(fresh_session)
    assert out["disposition"] == "ACCEPTED"
    cid = out["caseId"]
    assert cid == "INV-CN-2026-0388"                      # 发号从 seed CN 域现值 0387 续起
    case = fresh_session.get(m.Case, cid)
    assert case.status == "RECOGNIZED" and case.detail_level == "full"
    assert case.channel == "门户上传（运行期受理）"
    # 步骤 1–5 全部 DONE，检查点留存
    steps = fresh_session.scalars(select(m.FileStep).where(
        m.FileStep.batch_id == batch.batch_id)).all()
    assert sorted(s.step_no for s in steps) == [1, 2, 3, 4, 5]
    assert all(s.status == "DONE" for s in steps)
    # 摘要登记（id_format.原件摘要 64hex）
    assert len(frow.sha256) == 64 and frow.digest_ts and frow.accepted_ts
    # 聚合过契约
    from app.services import case_repository as repo
    from app.services.tenant import TenantContext
    agg = repo.aggregate_case(fresh_session, TenantContext.of("CN"), cid)
    assert not schema_errors(case_validator, agg), schema_errors(case_validator, agg)
    for tl in agg["timeline"]:
        assert not schema_errors(events_validator, tl)
    # 时间线事件序：受理→分流→解析→接收
    acts = [e["act"] for e in agg["timeline"]]
    assert acts == ["CHANNEL_RECEIVED", "CARRIER_ROUTED", "XML_PARSED", "INBOUND_ACCEPTED"]
    assert frow.status_snapshot == "RECOGNIZED" and frow.conf == 99
    # 外发台账为零（直读路径数据最小外发断言）
    assert fresh_session.scalar(select(func.count()).select_from(m.EgressLog)) == 0
    # 查重池/合规检查占位（WP3.3 激活）——四槽位 NOT_VERIFIED，绝不伪装 PASSED
    for item, chk in agg["checks"].items():
        assert chk["result"] == "NOT_VERIFIED"


def test_direct_read_zero_egress_and_no_llm(fresh_session):
    _run_one(fresh_session)
    assert fresh_session.scalar(select(func.count()).select_from(m.EgressLog)) == 0


def test_non_invoice_filtered(fresh_session):
    batch, frow, out = _run_one(fresh_session, name="框架协议_苏州东方_HT-01.xml",
                                content=CONTRACT_XML.encode())
    assert out["disposition"] == "FILTERED"
    assert frow.doc_type == "合同"
    steps = {s.step_no: s.status for s in fresh_session.scalars(select(m.FileStep).where(
        m.FileStep.batch_id == batch.batch_id))}
    assert steps[1] == "DONE" and steps[2] == "DONE"
    assert steps[3] == steps[4] == steps[5] == "SKIPPED"
    assert "可申诉重提" in (frow.note or "")
    assert frow.case_id is None
    blk = fresh_session.scalars(select(m.AuditBlock).where(m.AuditBlock.act == "CHANNEL_RECEIVED",
                                                           m.AuditBlock.case_id.is_(None))).all()
    assert blk, "非发票退回须入审计链（PLATFORM 域）"


def test_digest_idempotent_no_double_accept(fresh_session):
    batch, frow, out = _run_one(fresh_session)
    sha = frow.sha256
    dup = ip.find_business_dup(fresh_session, sha, None)
    assert dup is not None and dup.case_id == out["caseId"]
    # 二次提交同文件：preflight 命中 + 步内终检双防护
    b2 = ip.create_batch(fresh_session, channel="门户上传", instance="CN")
    f2 = ip.add_file(fresh_session, b2, name="same.xml", content=NEW_XML.encode(),
                     mime=None, po_ref=None, target_doc_ref=None)
    with pytest.raises(CommandError) as ei:
        ip.run_file(fresh_session, b2, f2, rules_payload=ip.current_intake_rules(fresh_session)[0])
    assert ei.value.code == "E_INTAKE_DUP"


def test_encrypted_pdf_manual_sort_still_registers_digest(fresh_session):
    fake_pdf = b"%PDF-1.7\n" + b"1 0 obj <</Encrypt /StdCF>> endobj " + b"x" * 200
    batch, frow, out = _run_one(fresh_session, name="扫描件_加密.pdf", content=fake_pdf)
    assert out["disposition"] == "MANUAL_SORT"
    assert frow.carrier_route == "L4_manual_review"
    assert frow.sha256 and frow.digest_ts                      # ④受理即登记仍执行
    steps = {s.step_no: s.status for s in fresh_session.scalars(select(m.FileStep).where(
        m.FileStep.batch_id == batch.batch_id))}
    assert steps[4] == "DONE" and steps[5] == "SKIPPED"
    assert fresh_session.scalar(select(func.count()).select_from(m.Case)) == 11  # 未派生新案件


def test_scan_image_ocr_stub_egress_logged(fresh_session):
    batch, frow, out = _run_one(fresh_session, name="扫描件_苏州东方_77702.png", content=PNG_MAGIC)
    assert out["disposition"] == "ACCEPTED"
    assert frow.carrier_route == "L2_ocr_vlm"
    eg = fresh_session.scalars(select(m.EgressLog)).all()
    assert len(eg) == 1 and eg[0].provider_id == "selfhosted-ocr-vlm-stub"
    case = fresh_session.get(m.Case, out["caseId"])
    assert case.confidence == 82 and case.provider == "自托管 OCR-VLM（SPI stub · 演示口径）"
    evs = fresh_session.scalars(select(m.FieldEvidence).where(
        m.FieldEvidence.case_id == case.case_id)).all()
    assert evs and all(e.source == "ocr" for e in evs)          # 来源徽章=OCR，不冒充直读
    acts = [t.act for t in fresh_session.scalars(select(m.TimelineEvent).where(
        m.TimelineEvent.case_id == case.case_id).order_by(m.TimelineEvent.seq))]
    assert "OCR_RECOGNIZED" in acts


def test_batch_checkpoint_resume_stepwise(fresh_session):
    """断点续跑：中断于③后→resume 仅续做④⑤，stub 外发调用计数不变（识别不重跑）。"""
    payload, _ = ip.current_intake_rules(fresh_session)
    batch = ip.create_batch(fresh_session, channel="供应商邮箱", instance="CN")
    frow = ip.add_file(fresh_session, batch, name="扫描件_中断_77703.png", content=PNG_MAGIC,
                       mime=None, po_ref=None, target_doc_ref=None)
    with pytest.raises(ip.IntakeInterrupt):
        ip.run_file(fresh_session, batch, frow, rules_payload=payload, fail_after_step=3)
    # 中断后：④⑤ 未 DONE；批次状态=受理中；外发计数=0（⑤未跑）
    steps = {s.step_no: s.status for s in fresh_session.scalars(select(m.FileStep).where(
        m.FileStep.batch_id == batch.batch_id))}
    assert steps[1] == steps[2] == steps[3] == "DONE"
    assert steps.get(4) is None or steps.get(4) == "PENDING"   # ④未开跑（检查点停在③）
    assert fresh_session.scalar(select(func.count()).select_from(m.EgressLog)) == 0
    # resume：从检查点继续
    res = ip.resume_batch(fresh_session, batch.batch_id)
    assert res["files"][0]["caseId"]
    # ①-③ 未重跑：步骤行仍是 DONE（无第二次 RUNNING 痕迹——detail 的 sha 不变）
    again = ip.resume_batch(fresh_session, batch.batch_id)
    assert again["files"][0].get("reason") == "检查点已完成，续跑跳过"
    assert fresh_session.scalar(select(func.count()).select_from(m.EgressLog)) == 1  # 识别不重跑


def test_resume_no_double_register_after_digest_step(fresh_session):
    """中断于④（摘要已登记）→resume 仅派生⑤；不重复登记、不重复派生。"""
    payload, _ = ip.current_intake_rules(fresh_session)
    batch = ip.create_batch(fresh_session, channel="门户上传", instance="CN")
    frow = ip.add_file(fresh_session, batch, name="数电票_中断续跑.xml", content=NEW_XML.encode(),
                       mime=None, po_ref=None, target_doc_ref=None)
    with pytest.raises(ip.IntakeInterrupt):
        ip.run_file(fresh_session, batch, frow, rules_payload=payload, fail_after_step=4)
    assert ip.find_business_dup(fresh_session, frow.sha256, None) is not None
    ip.resume_batch(fresh_session, batch.batch_id)
    ledgers = fresh_session.scalars(select(m.IntakeLedger).where(
        m.IntakeLedger.sha256 == frow.sha256)).all()
    assert len(ledgers) == 1 and ledgers[0].case_id            # 摘要幂等：一摘要一条
    assert fresh_session.scalar(select(func.count()).select_from(m.Case)) == 12


def test_recompute_batch_progress_and_partial_error(fresh_session):
    batch, frow, out = _run_one(fresh_session)
    b = fresh_session.get(m.Batch, batch.batch_id)
    assert b.status == "已完成" and b.files == 1 and b.ok == 1
    # 同批次追加异常件（加密）→部分异常
    payload, _ = ip.current_intake_rules(fresh_session)
    f2 = ip.add_file(fresh_session, b, name="扫描件_加密.pdf",
                     content=b"%PDF-1.7 <</Encrypt /X>> " + b"z" * 100,
                     mime=None, po_ref=None, target_doc_ref=None)
    ip.run_file(fresh_session, b, f2, rules_payload=payload)
    b = fresh_session.get(m.Batch, batch.batch_id)
    assert b.status == "部分异常" and b.err == 1
    assert b.files == 2 and b.ok == 1


def test_recognized_case_has_no_auto_release(fresh_session):
    """红线回归：派生案件（占位 checks 全 NOT_VERIFIED、低置信 stub 82）无任何自动放行出口。"""
    batch, frow, out = _run_one(fresh_session, name="扫描件_低置信.png", content=PNG_MAGIC)
    cands = state_machine.evaluate(fresh_session, out["caseId"])
    assert all(c["to"] != "RESOLVED" for c in cands)            # 不存在 →RESOLVED 自动边
    assert not any(c["to"] == "RESOLVED" and c["reason"].startswith("自动") for c in cands)


def test_batch_no_trace_poison_and_tenant(fresh_session):
    from app.services import batch_ops
    batch, frow, out = _run_one(fresh_session)
    detail = batch_ops.get_batch_detail(fresh_session, batch.batch_id, instance="CN")
    assert detail["files_detail"][0]["case_id"] == out["caseId"]
    with pytest.raises(CommandError) as ei:
        batch_ops.get_batch_detail(fresh_session, batch.batch_id, instance="OS")
    assert ei.value.code == "E_TENANT_MISMATCH"
