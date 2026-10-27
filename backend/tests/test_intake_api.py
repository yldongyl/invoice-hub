# -*- coding: utf-8 -*-
"""WP3.2 通道与批次 API 测试（FN-1-01~11 · FN-A-01 契约形态 · FN-1-08 五要素）。

覆盖：门户上传受控全序与校验/幂等；recognize 契约（200/202/400/401/409/重放）；
批次列表/明细/续跑/重试端点；KPI；渠道配置读取（凭证掩码）与受控发布；规则版本徽章；
邮箱/DOX 桩手动触发；Webhook outbox 桩。对象存储/信箱/DOX/outbox 目录均 monkeypatch tmp。
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app.services import channels_ops, object_store

NEW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header><InvoiceNo>2431200000077888</InvoiceNo><IssueDate>2026-10-26</IssueDate>
  <InvoiceType>数电票（增值税专用发票）</InvoiceType></Header>
  <Seller><Name>佛山数控装备有限公司</Name><TaxID>91440600MA4UGQ2X8B</TaxID></Seller>
  <Buyer><Name>澜坞（上海）采购科技有限公司</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Items><Item lineNo="1"><Name>*金属制品*精密结构件</Name><Spec>CNC</Spec><Unit>件</Unit>
  <Qty>100</Qty><Price>80.00</Price><TaxRate>0.13</TaxRate><Amount>8000.00</Amount></Item></Items>
  <Total><NetAmount>8000.00</NetAmount><TaxAmount>1040.00</TaxAmount>
  <GrossAmount>9040.00</GrossAmount></Total>
</EInvoice>
""".encode()

SECRET = "invoice-hub-demo-webhook-secret"


@pytest.fixture(autouse=True)
def tmp_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")
    monkeypatch.setattr(channels_ops, "MAILBOX_INBOX", tmp_path / "mb" / "inbox")
    monkeypatch.setattr(channels_ops, "MAILBOX_OUTBOX", tmp_path / "mb" / "outbox")
    monkeypatch.setattr(channels_ops, "MAILBOX_PROCESSED", tmp_path / "mb" / "processed")
    monkeypatch.setattr(channels_ops, "DOX_INBOX", tmp_path / "dox" / "inbox")
    monkeypatch.setattr(channels_ops, "DOX_REJECT", tmp_path / "dox" / "rejected")
    monkeypatch.setattr(channels_ops, "DOX_PROCESSED", tmp_path / "dox" / "processed")
    monkeypatch.setattr(channels_ops, "WEBHOOK_OUTBOX", tmp_path / "wh")
    return tmp_path


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _upload(api_client, name="数电票_佛山数控_77888.xml", content=NEW_XML,
            actor="陈铮", instance="CN", po_ref=None, self_confirmed=True, token=None,
            opinion=None, extra_files=None):
    files = [(name, content)] + list(extra_files or [])
    meta = [{"name": n, "size": len(c), "mime": "application/xml"} for n, c in files]
    ch = api_client.post("/v1/intake/upload/risk-challenge",
                         json={"actor": actor, "instance": instance, "action": "intake",
                               "files": meta, "po_ref": po_ref})
    assert ch.status_code == 200, ch.json()
    tok = token if token is not None else ch.json()["token"]
    data = {"actor": actor, "instance": instance, "token": tok,
            "self_confirmed": "true" if self_confirmed else "false"}
    if po_ref:
        data["po_ref"] = po_ref
    if opinion:
        data["opinion"] = opinion
    form_files = [("files", (n, c, "application/xml")) for n, c in files]
    r = api_client.post("/v1/intake/upload", data=data, files=form_files)
    return ch.json(), r


# ───────────────────────── 门户上传：受控全序 + 校验（FN-1-03/08） ─────────────────────────

def test_upload_full_five_elements_flow(api_client):
    chal, r = _upload(api_client)
    assert r.status_code == 200, r.json()
    out = r.json()
    assert out["batch_id"].startswith("BT-")
    assert out["files"][0]["disposition"] == "ACCEPTED"
    assert out["files"][0]["caseId"] == "INV-CN-2026-0388"
    assert out["opinion"] == "（未填写处置意见）"
    assert "不可篡改" in chal["risk_text"] and "本人" in chal["self_confirm_label"]
    assert chal["per_file_manifest"] == [{"name": "数电票_佛山数控_77888.xml",
                                          "size": len(NEW_XML), "mime": "application/xml"}]
    assert "已写入不可篡改审计日志" in out["toast"]


def test_upload_missing_token_rejected(api_client):
    r = api_client.post("/v1/intake/upload",
                        data={"actor": "陈铮", "instance": "CN", "self_confirmed": "true"},
                        files=[("files", ("a.xml", NEW_XML, "application/xml"))])
    assert r.status_code == 428
    assert r.json()["detail"]["error_code"] == "E_RISK_NOT_SHOWN"


def test_upload_consumed_or_bogus_token_rejected(api_client):
    ch, r = _upload(api_client, token="not-a-real-token")
    assert r.status_code == 428
    assert r.json()["detail"]["error_code"] == "E_CONFIRM_INVALID"


def test_upload_missing_self_confirm_rejected(api_client):
    _, r = _upload(api_client, self_confirmed=False)
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "E_SELF_CONFIRM_REQUIRED"


def test_upload_permission_denied_for_reviewer(api_client):
    # 王莉=复核员（无「受理提交」位）——要素①拒绝
    meta = [{"name": "x.xml", "size": 10, "mime": "application/xml"}]
    c = api_client.post("/v1/intake/upload/risk-challenge",
                        json={"actor": "王莉", "instance": "CN", "action": "intake", "files": meta})
    assert c.status_code == 200                       # 签发允许（真人即可请求提示）
    tok = c.json()["token"]
    r = api_client.post("/v1/intake/upload",
                        data={"actor": "王莉", "instance": "CN", "token": tok,
                              "self_confirmed": "true"},
                        files=[("files", ("x.xml", b"<a/>", "application/xml"))])
    assert r.status_code == 403
    assert "受理提交" in r.json()["detail"]["message"]


def test_upload_scope_tampering_rejected(api_client):
    # 要素③绑定：确认清单与实际字节不符 → 凭据错绑拒绝
    meta_ok = [{"name": "a.xml", "size": 3, "mime": "application/xml"}]
    c = api_client.post("/v1/intake/upload/risk-challenge",
                        json={"actor": "陈铮", "instance": "CN", "action": "intake",
                              "files": meta_ok})
    tok = c.json()["token"]
    r = api_client.post("/v1/intake/upload",
                        data={"actor": "陈铮", "instance": "CN", "token": tok,
                              "self_confirmed": "true"},
                        files=[("files", ("a.xml", b"XXXXXXXXXX", "application/xml"))])
    assert r.status_code == 428
    assert r.json()["detail"]["error_code"] == "E_CONFIRM_INVALID"


def test_upload_validation_rejects_bad_types_dedup(api_client):
    docx = b"PK\x03\x04xx"
    c1 = api_client.post("/v1/intake/upload/risk-challenge",
                         json={"actor": "陈铮", "instance": "CN", "action": "intake",
                               "files": [{"name": "发票.pdf", "size": 5, "mime": None},
                                         {"name": "手册.docx", "size": len(docx), "mime": None},
                                         {"name": "发票.pdf", "size": 5, "mime": None}]})
    tok = c1.json()["token"]
    r = api_client.post("/v1/intake/upload",
                        data={"actor": "陈铮", "instance": "CN", "token": tok,
                              "self_confirmed": "true"},
                        files=[("files", ("发票.pdf", b"%PDF!", "application/pdf")),
                               ("files", ("手册.docx", docx, "application/octet")),
                               ("files", ("发票.pdf", b"%PDF!", "application/pdf"))])
    # docx 类型白名单拒绝 + 同名同大小去重 → 仅 pdf 入批次
    assert r.status_code == 200, r.json()
    rejected = r.json()["rejected"]
    assert any("白名单" in x["reason"] for x in rejected)
    assert any("去重" in x["reason"] for x in rejected)
    assert len(r.json()["files"]) == 1


def test_upload_size_cap_rejected(api_client):
    big = b"x" * (21 * 1024 * 1024)
    c1 = api_client.post("/v1/intake/upload/risk-challenge",
                         json={"actor": "陈铮", "instance": "CN", "action": "intake",
                               "files": [{"name": "巨大.pdf", "size": len(big), "mime": None}]})
    r = api_client.post("/v1/intake/upload",
                        data={"actor": "陈铮", "instance": "CN", "token": c1.json()["token"],
                              "self_confirmed": "true"},
                        files=[("files", ("巨大.pdf", big, "application/pdf"))])
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "E_ALL_REJECTED"


def test_upload_duplicate_digest_409(api_client):
    _, r1 = _upload(api_client)
    assert r1.status_code == 200
    _, r2 = _upload(api_client)
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "E_INTAKE_DUP"
    d = r2.json()["detail"]["duplicates"][0]
    assert d["existing_case"] == "INV-CN-2026-0388"


# ───────────────────────── recognize（FN-A-01 / openapi 契约形态） ─────────────────────────

def _openapi_component(name):
    import yaml
    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts"
                           / "openapi.yaml").read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator
    s = spec["components"]["schemas"][name]
    Draft202012Validator.check_schema(s)
    return Draft202012Validator(s)


def test_recognize_json_sync_200_contract(api_client):
    digest, _rel = object_store.save(NEW_XML)
    body = json.dumps({"file": {"ref": f"oss://intake/2026/10/27/f-{digest[:8]}.xml",
                                "mime_type": "application/xml", "sha256": digest},
                       "instance": "CN", "doc_type_hint": "e_invoice",
                       "po_ref": "PO-2026-07788"}).encode()
    r = api_client.post("/v1/invoices:recognize", content=body,
                        headers={"Content-Type": "application/json", "X-Request-Id": "req-001",
                                 "X-Signature": _sig(body)})
    assert r.status_code == 200, r.json()
    agg = r.json()
    assert agg["caseId"] == "INV-CN-2026-0388" and agg["status"] == "RECOGNIZED"
    assert agg["meta"]["po"] == "PO-2026-07788"
    assert _openapi_component("RecognizeRequest")
    # 200 响应=完整 invoice-case 聚合（北向承诺）；trace 回写头
    assert r.headers["X-Trace-Id"].startswith("tr-")


def test_recognize_multipart_ocr_202_and_webhook_stub(api_client, tmp_runtime):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    r = api_client.post("/v1/invoices:recognize",
                        files={"file": ("扫描件_测试_88001.png", png, "image/png")},
                        data={"instance": "CN"},
                        headers={"X-Request-Id": "req-002", "X-Signature": _sig(png)})
    assert r.status_code == 202, r.json()
    body = r.json()
    errs1 = list(_openapi_component("AcceptedResponse").iter_errors(body)); assert not errs1, errs1
    assert body["caseId"] == "INV-CN-2026-0388" and body["status"] == "RECOGNIZED"
    wh = list((tmp_runtime / "wh").glob("*.json"))
    assert len(wh) == 1
    payload = json.loads(wh[0].read_text(encoding="utf-8"))
    assert payload["body"]["event"] == "case.recognized"
    assert payload["headers"]["X-Signature"].startswith("sha256=")


def test_recognize_signature_and_requestid_guards(api_client):
    digest, _ = object_store.save(NEW_XML)
    body = json.dumps({"file": {"ref": "oss://x/y.xml", "mime_type": "application/xml",
                                "sha256": digest}, "instance": "CN"}).encode()
    r = api_client.post("/v1/invoices:recognize", content=body,
                        headers={"Content-Type": "application/json", "X-Request-Id": "r1",
                                 "X-Signature": "sha256=deadbeef"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "E_SIGNATURE_INVALID"
    assert r.json()["detail"]["trace_id"].startswith("tr-")
    r2 = api_client.post("/v1/invoices:recognize", content=body,
                         headers={"Content-Type": "application/json", "X-Signature": _sig(body)})
    assert r2.status_code == 400
    assert r2.json()["detail"]["code"] == "E_REQUEST_ID_REQUIRED"


def test_recognize_business_dedup_409_shape(api_client):
    digest, _ = object_store.save(NEW_XML)
    hdr = {"Content-Type": "application/json"}

    def post(rid, target="TGT-001"):
        body = json.dumps({"file": {"ref": "oss://x/a.xml", "mime_type": "application/xml",
                                    "sha256": digest}, "instance": "CN",
                           "target_doc_ref": target}).encode()
        return api_client.post("/v1/invoices:recognize", content=body,
                               headers={**hdr, "X-Request-Id": rid, "X-Signature": _sig(body)})
    r1 = post("req-d1")
    assert r1.status_code == 200, r1.json()
    r2 = post("req-d2", target="TGT-001")
    assert r2.status_code == 409
    errs2 = list(_openapi_component("DedupAcceptedResponse").iter_errors(r2.json())); assert not errs2, errs2
    assert r2.json()["idempotent"] is True
    assert r2.json()["caseId"] == r1.json()["caseId"]


def test_recognize_transport_replay_same_case(api_client):
    digest, _ = object_store.save(NEW_XML)
    body = json.dumps({"file": {"ref": "oss://x/b.xml", "mime_type": "application/xml",
                                "sha256": digest}, "instance": "CN"}).encode()
    headers = {"Content-Type": "application/json", "X-Request-Id": "req-replay-1",
               "X-Signature": _sig(body)}
    r1 = api_client.post("/v1/invoices:recognize", content=body, headers=headers)
    assert r1.status_code == 200
    # 同 X-Request-Id 重放：返回首发结果（不重复派生——案件计数不变）
    body2 = json.dumps({"file": {"ref": "oss://x/b.xml", "mime_type": "application/xml",
                                 "sha256": digest}, "instance": "CN"}).encode()
    r2 = api_client.post("/v1/invoices:recognize", content=body2,
                         headers={"Content-Type": "application/json",
                                  "X-Request-Id": "req-replay-1",
                                  "X-Signature": _sig(body2)})
    assert r2.status_code == 200 and r2.json()["caseId"] == r1.json()["caseId"]
    assert "幂等重放" in r2.json().get("note", "")


def test_recognize_unresolved_ref_400(api_client):
    body = json.dumps({"file": {"ref": "oss://x/missing.xml", "mime_type": "application/xml",
                                "sha256": "f" * 64}, "instance": "CN"}).encode()
    r = api_client.post("/v1/invoices:recognize", content=body,
                        headers={"Content-Type": "application/json", "X-Request-Id": "req-404",
                                 "X-Signature": _sig(body)})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "E_OBJECT_REF_UNRESOLVED"


# ───────────────────────── 批次列表/明细/续跑/重试（FN-1-06/07） ─────────────────────────

def test_batches_list_detail_resume_retry_endpoints(api_client):
    _, r = _upload(api_client)
    bid = r.json()["batch_id"]
    lst = api_client.get(f"/v1/batches?instance=CN&channel=门户上传&status=已完成")
    assert lst.status_code == 200
    hit = [x for x in lst.json()["items"] if x["batch_id"] == bid]
    assert hit and hit[0]["files"] == 1 and hit[0]["progress_pct"] == 100
    det = api_client.get(f"/v1/batches/{bid}")
    assert det.status_code == 200
    fd = det.json()["files_detail"][0]
    assert [s["status"] for s in fd["steps"]] == ["DONE"] * 5
    assert fd["case_id"] == "INV-CN-2026-0388"
    res = api_client.post(f"/v1/batches/{bid}/resume")
    assert res.status_code == 200
    assert res.json()["files"][0]["reason"] == "检查点已完成，续跑跳过"
    retry = api_client.post(f"/v1/batches/{bid}/files/0/retry-steps")
    assert retry.status_code == 200
    assert retry.json()["retried_steps"] == []
    bad = api_client.get("/v1/batches?status=不存在的态")
    assert bad.status_code == 400


def test_batches_status_filter_channel_x_status(api_client):
    _, r = _upload(api_client)
    bid = r.json()["batch_id"]
    lst = api_client.get("/v1/batches?channel=门户上传")
    items = lst.json()["items"]
    assert all(set(x.keys()) >= {"batch_id", "status_enum", "progress_pct", "ok", "err", "filtered"}
               for x in items)
    assert any(x["batch_id"] == bid for x in items)
    # seed 批次（受理中/识别中/部分异常）同列可读，status_enum 归一到 batch_status 三值
    enums = {x["status_enum"] for x in items}
    assert enums <= {"受理中 / 识别中", "已完成", "部分异常"}
    filt = api_client.get("/v1/batches?channel=API 集成&status=已完成")
    assert filt.status_code == 200
    assert all(x["channel"] == "API 集成" for x in filt.json()["items"])


# ───────────────────────── KPI / 渠道 / 规则版本（FN-1-09/10/11） ─────────────────────────

def test_kpi_endpoint_baseline_plus_runtime(api_client):
    _, r = _upload(api_client)
    k = api_client.get("/v1/intake/kpi?instance=CN")
    assert k.status_code == 200
    body = k.json()
    assert body["baseline"]["kpi"]["daily_received_total"] == 540   # 页面锚点
    assert body["runtime"]["files_in"] == 1 and body["runtime"]["accepted"] == 1
    assert body["runtime"]["by_channel"]["门户上传"] == 1
    assert body["merged"]["daily_received_total"] == 541
    assert body["calibers"]["latency"].startswith("接入 → 摘要登记")


def test_channels_endpoint_masks_credentials(api_client):
    c = api_client.get("/v1/intake/channels")
    assert c.status_code == 200
    text = c.text
    assert "invoice-hub-demo-webhook-secret" not in text
    api_ch = next(x for x in c.json()["items"] if x["channel"] == "API 集成")
    assert "KMS 托管" in api_ch["config"]["appkey_credential"]
    assert api_ch["today"]["received"] == 412                        # 渠道卡今日接收锚点
    portal = next(x for x in c.json()["items"] if x["channel"] == "门户上传")
    assert portal["config"]["max_file_size_mb"] == 20


def test_channel_config_publish_controlled(api_client):
    key = "channel:门户上传"
    ch = api_client.post(f"/v1/config/{key}/risk-challenge",
                         json={"actor": "陈铮", "instance": "CN", "action": "publish"})
    tok = ch.json()["token"]
    r = api_client.post("/v1/config/actions/publish",
                        json={"actor": "陈铮", "instance": "CN", "token": tok,
                              "self_confirmed": True, "config_key": key,
                              "config_payload": {"allowed_types": ["xml", "ofd", "pdf"],
                                                 "max_file_size_mb": 10,
                                                 "max_batch_files": 20, "upload_perm_groups": ["管理员"]},
                              "opinion": "收紧上传口径（演示发布）"})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["asset_type"] == "channel_config"
    assert body["version"].startswith("v")            # v{今日}.1
    assert body["diff"]["max_batch_files"]["from"] == 50
    # 生效配置已同步：再读取 KPI/渠道显示新值
    c = api_client.get("/v1/intake/channels").json()
    portal = next(x for x in c["items"] if x["channel"] == "门户上传")
    assert portal["config"]["max_file_size_mb"] == 10
    assert portal["config_version"] == body["version"]


def test_channel_publish_denied_for_reviewer(api_client):
    ch = api_client.post("/v1/config/channel:门户上传/risk-challenge",
                         json={"actor": "王莉", "instance": "CN", "action": "publish"})
    assert ch.status_code == 200
    r = api_client.post("/v1/config/actions/publish",
                        json={"actor": "王莉", "instance": "CN", "token": ch.json()["token"],
                              "self_confirmed": True, "config_key": "channel:门户上传",
                              "config_payload": {"max_batch_files": 9}})
    assert r.status_code == 403                       # 策略发布位缺失（矩阵⑤）


def test_rules_version_badge(api_client):
    r = api_client.get("/v1/intake/rules/version")
    assert r.status_code == 200
    assert r.json()["badge"] == "受理规则版本 v2026-10-20.2 · 已发布"


# ───────────────────────── 邮箱 / DOX 通道桩（FN-1-01/04 · 手动触发） ─────────────────────────

def test_mailbox_job_end_to_end(api_client, tmp_runtime):
    import base64 as b64
    inbox = tmp_runtime / "mb" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    env = {"from": "billing@supplier-partners.com", "subject": "10 月发票",
           "attachments": [
               {"name": "数电票_无锡光电_90001.xml", "content_b64": b64.b64encode(NEW_XML).decode()},
               {"name": "框架合同_无锡光电.xml",
                "content_b64": b64.b64encode(
                    "<?xml version='1.0'?><Contract><Title>合同</Title></Contract>".encode(
                        "utf-8")).decode()}]}
    (inbox / "env-1.json").write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
    r = api_client.post("/v1/intake/jobs/mailbox:poll")
    assert r.status_code == 200, r.json()
    out = r.json()
    assert out["batches"][0]["status"] in ("已完成", "部分异常")
    bid = out["batches"][0]["batch_id"]
    det = api_client.get(f"/v1/batches/{bid}").json()
    disp = {f["file"]: f["disposition"] for f in det["files_detail"]}
    assert disp["数电票_无锡光电_90001.xml"] == "ACCEPTED"
    assert disp["框架合同_无锡光电.xml"] == "FILTERED"
    # 非发票退回邮件桩落 outbox；已处理信封移入 processed
    assert list((tmp_runtime / "mb" / "outbox").glob("reject-*.json"))
    assert list((tmp_runtime / "mb" / "processed").glob("*.json"))
    # 二拉：信箱空→不产生批次（幂等口径）
    r2 = api_client.post("/v1/intake/jobs/mailbox:poll")
    assert r2.json()["batches"] == []


def test_mailbox_whitelist_and_oversize_skipped(api_client, tmp_runtime):
    import base64 as b64
    inbox = tmp_runtime / "mb" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "bad-domain.json").write_text(json.dumps(
        {"from": "x@not-a-supplier.com", "subject": "s",
         "attachments": [{"name": "a.xml", "content_b64": b64.b64encode(NEW_XML).decode()}]}),
        encoding="utf-8")
    r = api_client.post("/v1/intake/jobs/mailbox:poll")
    assert r.json()["batches"] == []
    assert "白名单" in r.json()["skipped"][0]["reason"]


def test_dox_job_participant_and_order_response(api_client, tmp_runtime):
    import base64 as b64
    dox = tmp_runtime / "dox" / "inbox"
    dox.mkdir(parents=True, exist_ok=True)
    ubl = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>SG-INV-77001</ID><IssueDate>2026-10-25</IssueDate>
  <DocumentCurrencyCode>SGD</DocumentCurrencyCode>
  <AccountingSupplierParty><Party><PartyName><Name>Keppel Parts Pte</Name></PartyName>
  <PartyTaxScheme><TaxID>S00EP1234X</TaxID></PartyTaxScheme></Party></AccountingSupplierParty>
  <TaxExclusiveAmount>5000.00</TaxExclusiveAmount><TaxAmount>400.00</TaxAmount>
  <PayableAmount>5400.00</PayableAmount>
</Invoice>"""
    (dox / "inv.json").write_text(json.dumps(
        {"participant_id": "0130:SG-LANWU-APAC", "document_type": "Supplier Invoice",
         "name": "Keppel_INV-77001.xml", "mime": "application/xml",
         "document_number": "SG-INV-77001", "content_b64": b64.b64encode(ubl).decode()},
        ensure_ascii=False), encoding="utf-8")
    (dox / "or.json").write_text(json.dumps(
        {"participant_id": "0130:SG-LANWU-APAC", "document_type": "Order Response",
         "name": "OR-77001.json", "document_number": "OR-77001",
         "content_b64": b64.b64encode(b"{}").decode()}, ensure_ascii=False), encoding="utf-8")
    (dox / "bad-participant.json").write_text(json.dumps(
        {"participant_id": "0130:SOMEONE-ELSE", "document_type": "Supplier Invoice",
         "name": "x.xml", "content_b64": b64.b64encode(ubl).decode()},
        ensure_ascii=False), encoding="utf-8")
    r = api_client.post("/v1/intake/jobs/dox:poll")
    assert r.status_code == 200, r.json()
    out = r.json()
    assert any("参与方 ID" in x["reason"] for x in out["rejected"])
    bid = out["batches"][0]["batch_id"]
    det = api_client.get(f"/v1/batches/{bid}").json()
    assert det["channel"] == "SAP DOX" and det["instance"] == "海外"
    by_file = {f["file"]: f for f in det["files_detail"]}
    inv_row = by_file["Keppel_INV-77001.xml"]
    assert inv_row["case_id"].startswith("INV-SG-2026")            # OS 实例发号 SG 段
    assert by_file["OR-77001.json"]["disposition"] == "FILTERED"
    assert by_file["OR-77001.json"]["note"].startswith("非发票（Order Response）")
