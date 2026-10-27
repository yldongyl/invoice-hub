# -*- coding: utf-8 -*-
"""M3 场景断言（P04 收工硬性项 × WP3.1/3.2 部分 · make test-e2e 即 pytest -m scenario）。

场景编号 S-M3-INT-01~05（对应本会话完成条件；S-M3-01~05 全链五场景的合规链部分待 WP3.3+ 补齐）：
  01 现场造 seeds 外新 XML → 上传 API 全链 → 新案件号 + 五步状态逐步可查 + 审计链完整性通过；
  02 直读路径零外发（EgressLog=0），OCR 路由外发恰一条（数据最小外发断言，FN-5-08 台账）；
  03 摘要幂等：同文件重复提交不重复受理（409，案件计数不变，既有案件可追）；
  04 批次中断 → 检查点续跑：识别不重跑（外发调用计数断言）+ 不重复受理 + 已完成步骤不重做；
  05 邮箱/DOX 通道桩按 RUNBOOK 手动触发等效（本地目录投递 → 批次/案件生成；非发票退回 outbox）。
方法论参考旧 S01~S16 场景断言（仅方法论，代码不复用）。
"""

import base64
import hashlib
import hmac
import json

import pytest
from sqlalchemy import func, select

from app.domain import models as m
from app.services import audit_chain, intake_pipeline, object_store
from app.services import channels_ops

pytestmark = pytest.mark.scenario

SECRET = "invoice-hub-demo-webhook-secret"

# 现场造：seeds 之外的新数电票 XML（供应商/票号/金额均为新值）
FRESH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header><InvoiceNo>2451200000066101</InvoiceNo><IssueDate>2026-10-27</IssueDate>
  <InvoiceType>数电票（增值税专用发票）</InvoiceType></Header>
  <Seller><Name>宁波北仑精密铸造有限公司</Name><TaxID>91330206MA2AB7K93M</TaxID></Seller>
  <Buyer><Name>澜坞（上海）采购科技有限公司</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Items><Item lineNo="1"><Name>*金属制品*泵壳铸件</Name><Spec>DN80</Spec><Unit>件</Unit>
  <Qty>40</Qty><Price>250.00</Price><TaxRate>0.13</TaxRate><Amount>10000.00</Amount></Item></Items>
  <Total><NetAmount>10000.00</NetAmount><TaxAmount>1300.00</TaxAmount>
  <GrossAmount>11300.00</GrossAmount></Total>
</EInvoice>
""".encode("utf-8")


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")
    monkeypatch.setattr(channels_ops, "MAILBOX_INBOX", tmp_path / "mb" / "inbox")
    monkeypatch.setattr(channels_ops, "MAILBOX_OUTBOX", tmp_path / "mb" / "outbox")
    monkeypatch.setattr(channels_ops, "MAILBOX_PROCESSED", tmp_path / "mb" / "processed")
    monkeypatch.setattr(channels_ops, "DOX_INBOX", tmp_path / "dox" / "inbox")
    monkeypatch.setattr(channels_ops, "DOX_REJECT", tmp_path / "dox" / "rejected")
    monkeypatch.setattr(channels_ops, "DOX_PROCESSED", tmp_path / "dox" / "processed")
    monkeypatch.setattr(channels_ops, "WEBHOOK_OUTBOX", tmp_path / "wh")
    return tmp_path


def _sig(b: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), b, hashlib.sha256).hexdigest()


def _upload(client, content=FRESH_XML, name="数电票_宁波北仑_66101.xml", po_ref=None):
    meta = [{"name": name, "size": len(content), "mime": "application/xml"}]
    ch = client.post("/v1/intake/upload/risk-challenge",
                     json={"actor": "陈铮", "instance": "CN", "action": "intake",
                           "files": meta, "po_ref": po_ref})
    assert ch.status_code == 200, ch.json()
    r = client.post("/v1/intake/upload",
                    data={"actor": "陈铮", "instance": "CN", "token": ch.json()["token"],
                          "self_confirmed": "true", **({"po_ref": po_ref} if po_ref else {})},
                    files=[("files", (name, content, "application/xml"))])
    return r


def test_s_m3_int_01_new_xml_full_chain(api_client, tmp_dirs):
    """01 新 XML→上传 API 全链→新案件号+五步逐步持久化+审计链完整性。"""
    r = _upload(api_client, po_ref="PO-DEMO-66001")
    assert r.status_code == 200, r.json()
    out = r.json()
    cid = out["files"][0]["caseId"]
    assert cid == "INV-CN-2026-0388"                      # seeds 外新案件（域内无碰撞）
    # 五步逐步状态：序完整、全 DONE、detail 可查（步骤级持久化）
    steps = out["files"][0]["steps"]
    assert [s["no"] for s in steps] == [1, 2, 3, 4, 5]
    assert [s["status"] for s in steps] == ["DONE"] * 5
    assert steps[1]["detail"]["hit_type"] is None         # ②未命中非发票
    assert steps[2]["detail"]["route"] == "L1_xml_direct"  # ③直读分流
    assert len(steps[3]["detail"]["sha256"]) == 64         # ④64hex 摘要
    assert steps[4]["detail"]["case_id"] == cid            # ⑤派生案件
    # 案件深链可读 + 状态=RECOGNIZED（合规链 WP3.3 前不自动流转）
    d = api_client.get(f"/v1/cases/{cid}?instance=CN")
    assert d.status_code == 200 and d.json()["status"] == "RECOGNIZED"
    assert d.json()["meta"]["po"] == "PO-DEMO-66001"
    acts = [e["act"] for e in d.json()["timeline"]]
    assert acts == ["CHANNEL_RECEIVED", "CARRIER_ROUTED", "XML_PARSED", "INBOUND_ACCEPTED"]
    # 审计链完整性校验通过（本场景写链后 CN/OS/PLATFORM 三域全验）
    from app.services.persistence import get_session
    with get_session() as session:
        chk = audit_chain.verify_chain(session, verifier="scenario-S-M3-INT-01")
        assert chk["ok"], chk
        # 受理事件在案件链域入块（trace 贯穿）
        trace = d.json()["meta"]["trace_id"]
        blks = session.scalars(select(m.AuditBlock).where(m.AuditBlock.trace == trace)).all()
        assert len(blks) == len(acts)


def test_s_m3_int_02_direct_read_zero_egress_ocr_single(api_client, tmp_dirs):
    """02 直读零外发；OCR 路由外发恰一条（调用计数断言的台账形态）。"""
    assert _upload(api_client).status_code == 200
    from app.services.persistence import get_session
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(m.EgressLog)) == 0  # 直读：零
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48
    assert _upload(api_client, content=png, name="扫描件_宁波_66102.png").status_code == 200
    with get_session() as session:
        eg = session.scalars(select(m.EgressLog)).all()
        assert len(eg) == 1 and eg[0].provider_id == "selfhosted-ocr-vlm-stub"
        assert eg[0].purpose == "recognize" and eg[0].bytes_out > 0


def test_s_m3_int_03_digest_idempotent(api_client, tmp_dirs):
    """03 同文件重复提交不重复受理：409 + 案件计数不变 + 回执指认既有案件。"""
    assert _upload(api_client).status_code == 200
    from app.services.persistence import get_session
    with get_session() as session:
        n1 = session.scalar(select(func.count()).select_from(m.Case))
    r2 = _upload(api_client)
    assert r2.status_code == 409
    det = r2.json()["detail"]
    assert det["error_code"] == "E_INTAKE_DUP"
    assert det["duplicates"][0]["existing_case"] == "INV-CN-2026-0388"
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(m.Case)) == n1
        assert session.scalar(select(func.count()).select_from(m.IntakeLedger)) == 1


def test_s_m3_int_04_checkpoint_resume_no_rerun(api_client, tmp_dirs):
    """04 批次中断→检查点续跑：识别不重跑（外发计数=1）、摘要不重复登记（台账=1）。"""
    from app.services.persistence import get_session
    with get_session() as session:
        payload, _ = intake_pipeline.current_intake_rules(session)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48
        batch = intake_pipeline.create_batch(session, channel="供应商邮箱", instance="CN")
        frow = intake_pipeline.add_file(session, batch, name="扫描件_中断_66103.png",
                                        content=png, mime=None, po_ref=None, target_doc_ref=None)
        with pytest.raises(intake_pipeline.IntakeInterrupt):
            intake_pipeline.run_file(session, batch, frow, rules_payload=payload,
                                     fail_after_step=4)
        # 中断态：①-④ DONE、⑤未跑；识别外发未发生
        steps = {s.step_no: s.status for s in session.scalars(
            select(m.FileStep).where(m.FileStep.batch_id == batch.batch_id))}
        assert [steps[i] for i in (1, 2, 3, 4)] == ["DONE"] * 4 and steps.get(5, "PENDING") == "PENDING"
        assert session.scalar(select(func.count()).select_from(m.EgressLog)) == 0
        assert session.scalar(select(func.count()).select_from(m.IntakeLedger)) == 1
        # 续跑：从检查点继续
        res = intake_pipeline.resume_batch(session, batch.batch_id)
        assert res["files"][0]["caseId"].startswith("INV-CN-2026-")
        assert session.scalar(select(func.count()).select_from(m.EgressLog)) == 1
        # 二次续跑：无事可做（已完成步骤不重做、不重复受理）
        res2 = intake_pipeline.resume_batch(session, batch.batch_id)
        assert res2["files"][0]["reason"] == "检查点已完成，续跑跳过"
        assert session.scalar(select(func.count()).select_from(m.EgressLog)) == 1
        assert session.scalar(select(func.count()).select_from(m.IntakeLedger)) == 1


def test_s_m3_int_05_channel_jobs_manual_trigger(api_client, tmp_dirs):
    """05 邮箱/DOX 桩手动触发（RUNBOOK 命令的 HTTP 等效入口）：本地投递→批次/案件/退回。"""
    # —— 邮箱：一封合法发票 + 一封合同 + 一封非白名单域
    inbox = tmp_dirs / "mb" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "env-a.json").write_text(json.dumps({
        "from": "ap@supplier-partners.com", "subject": "10 月发票",
        "attachments": [
            {"name": "数电票_宁波北仑_66104.xml",
             "content_b64": base64.b64encode(FRESH_XML).decode()},
            {"name": "框架协议_宁波.xml",
             "content_b64": base64.b64encode(
                 "<?xml version='1.0'?><Contract><Title>框架协议</Title></Contract>".encode(
                     "utf-8")).decode()}]}, ensure_ascii=False), encoding="utf-8")
    (inbox / "env-b.json").write_text(json.dumps({
        "from": "spam@unknown-domain.cn", "subject": "x",
        "attachments": [{"name": "y.xml",
                         "content_b64": base64.b64encode(FRESH_XML).decode()}]},
        ensure_ascii=False), encoding="utf-8")
    r = api_client.post("/v1/intake/jobs/mailbox:poll")
    assert r.status_code == 200
    out = r.json()
    assert len(out["skipped"]) == 1 and "白名单" in out["skipped"][0]["reason"]
    bid = out["batches"][0]["batch_id"]
    det = api_client.get(f"/v1/batches/{bid}").json()
    assert det["channel"] == "供应商邮箱"
    by = {f["file"]: f for f in det["files_detail"]}
    assert by["数电票_宁波北仑_66104.xml"]["case_id"].startswith("INV-CN-2026-")
    assert by["框架协议_宁波.xml"]["disposition"] == "FILTERED"
    assert list((tmp_dirs / "mb" / "outbox").glob("reject-*.json"))      # 退回通知桩
    # —— DOX：合法 UBL 发票 + Order Response + 参与方不符
    dox = tmp_dirs / "dox" / "inbox"
    dox.mkdir(parents=True, exist_ok=True)
    ubl = ("<Invoice xmlns=\"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2\">"
           "<ID>SG-INV-66105</ID><IssueDate>2026-10-26</IssueDate>"
           "<DocumentCurrencyCode>SGD</DocumentCurrencyCode>"
           "<AccountingSupplierParty><Party><PartyName><Name>Test SG Parts</Name></PartyName>"
           "</Party></AccountingSupplierParty>"
           "<TaxExclusiveAmount>1000.00</TaxExclusiveAmount><TaxAmount>80.00</TaxAmount>"
           "<PayableAmount>1080.00</PayableAmount></Invoice>").encode("utf-8")
    (dox / "inv.json").write_text(json.dumps(
        {"participant_id": "0130:SG-LANWU-APAC", "document_type": "Supplier Invoice",
         "name": "SGParts_INV-66105.xml", "mime": "application/xml",
         "document_number": "SG-INV-66105",
         "content_b64": base64.b64encode(ubl).decode()}, ensure_ascii=False), encoding="utf-8")
    (dox / "or.json").write_text(json.dumps(
        {"participant_id": "0130:SG-LANWU-APAC", "document_type": "Order Response",
         "name": "OR-66105.json", "document_number": "OR-66105",
         "content_b64": base64.b64encode(b"{}").decode()}, ensure_ascii=False), encoding="utf-8")
    (dox / "bad.json").write_text(json.dumps(
        {"participant_id": "0130:OTHER", "document_type": "Supplier Invoice", "name": "z.xml",
         "content_b64": base64.b64encode(ubl).decode()}, ensure_ascii=False), encoding="utf-8")
    r2 = api_client.post("/v1/intake/jobs/dox:poll")
    assert r2.status_code == 200, r2.json()
    out2 = r2.json()
    assert out2["batches"] and any("参与方" in x["reason"] for x in out2["rejected"])
    det2 = api_client.get(f"/v1/batches/{out2['batches'][0]['batch_id']}").json()
    by2 = {f["file"]: f for f in det2["files_detail"]}
    assert by2["SGParts_INV-66105.xml"]["case_id"].startswith("INV-SG-2026-")   # OS 实例发号
    assert by2["OR-66105.json"]["disposition"] == "FILTERED"
    # KPI 联动：运行期四渠道计数
    k = api_client.get("/v1/intake/kpi").json()["runtime"]["by_channel"]
    assert k.get("供应商邮箱") == 2 and k.get("SAP DOX") == 2
