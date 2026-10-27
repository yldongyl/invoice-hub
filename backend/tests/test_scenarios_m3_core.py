# -*- coding: utf-8 -*-
"""M3 E2E 场景断言（WP3.6 · P04 §2 WP3.6 官方五场景 S-M3-01~05）。

规范（P08 §2）：失败信息=「场景名+断言点+期望/实际+关联 FN 编号」（expect helper 统一输出）；
可重复执行=api_client 函数级隔离临时库 + tmp 目录 monkeypatch（零共享态、零真实外呼）。
既有 S-M3-INT-01~05 / S-M3-CMP-02~03 保留为工作包推进子场景（tests/scenarios/README.md 台账注记）。
"""

import pytest

from app.domain import models as m
from app.services import audit_chain, fusion_service, object_store, persistence, sm2_service

pytestmark = pytest.mark.scenario


def expect(cond, scen, point, want, got, fn):
    """P08 §2 失败信息规范：场景名+断言点+期望/实际+关联 FN。"""
    if not cond:
        raise AssertionError(f"[{scen}] 断言点：{point} | 期望：{want} | 实际：{got} | 关联 FN：{fn}")


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")
    monkeypatch.setattr(sm2_service, "GM_RECEIPT_DIR", tmp_path / "gm-receipts")
    return tmp_path


def mk_xml(no, gross, *, net=None, tax=None, supplier="演示供应商", buyer="澜坞（上海）采购科技有限公司"):
    net = net if net is not None else round(gross / 1.13, 2)
    tax = tax if tax is not None else round(gross - net, 2)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header><InvoiceNo>{no}</InvoiceNo><IssueDate>2026-10-27</IssueDate>
  <InvoiceType>数电票（增值税专用发票）</InvoiceType></Header>
  <Seller><Name>{supplier}</Name><TaxID>91310000MA1FL0000X</TaxID></Seller>
  <Buyer><Name>{buyer}</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Total><NetAmount>{net:.2f}</NetAmount><TaxAmount>{tax:.2f}</TaxAmount>
  <GrossAmount>{gross:.2f}</GrossAmount></Total>
</EInvoice>
"""


def upload(c, name, content, *, actor="陈铮", instance="CN"):
    meta = [{"name": name, "size": len(content), "mime": "application/xml"}]
    ch = c.post("/v1/intake/upload/risk-challenge",
                json={"actor": actor, "instance": instance, "action": "intake", "files": meta})
    assert ch.status_code == 200, ch.json()
    r = c.post("/v1/intake/upload",
               data={"actor": actor, "instance": instance, "token": ch.json()["token"],
                     "self_confirmed": "true"},
               files=[("files", (name, content, "application/xml"))])
    return r


def get_case(c, cid, inst="CN"):
    return c.get(f"/v1/cases/{cid}?instance={inst}").json()


def act(c, cid, action, actor, *, inst="CN", opinion=None, token=None, **extra):
    if token is None:
        ch = c.post(f"/v1/cases/{cid}/risk-challenge",
                    json={"actor": actor, "instance": inst, "action": action})
        assert ch.status_code == 200, ch.json()
        token = ch.json()["token"]
    body = {"actor": actor, "instance": inst, "token": token, "self_confirmed": True}
    if opinion is not None:
        body["opinion"] = opinion
    body.update(extra)
    return c.post(f"/v1/cases/{cid}/actions/{action}", json=body)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ═══════════════ S-M3-01 上传→流水线→NEEDS_REVIEW→放行→RESOLVED 全链留痕 ═══════════════

def test_s_m3_01_upload_pipeline_review_release_full_trace(api_client, tmp_dirs):
    S = "S-M3-01"
    r = upload(api_client, "扫描件_S01_77001.png", PNG)
    expect(r.status_code == 200, S, "上传受理（受控五要素）返回 200", "200", r.status_code, "FN-1-03/05/08")
    out = r.json()
    cid = (out["files"][0] or {}).get("caseId")
    expect(bool(cid), S, "流水线⑤派生 InvoiceCase", "案件号非空", out["files"][0], "FN-1-05")
    c = get_case(api_client, cid)
    expect(c["status"] == "NEEDS_REVIEW", S,
           "低置信（stub 82<阈值 85）经 FN-0-02 自动边进复核队列", "NEEDS_REVIEW", c["status"], "FN-0-02/5-05")
    tl = [e["act"] for e in c["timeline"]]
    for need in ("CHANNEL_RECEIVED", "CARRIER_ROUTED", "OCR_RECOGNIZED", "DEDUP_CHECK",
                 "STATUS_CHANGE"):
        expect(need in tl, S, f"时间线含 {need}（受理→分流→识别→查重→流转）", "存在", tl, "FN-0-10/3-07")
    # 人工放行（受控 Action 五要素）
    rr = act(api_client, cid, "release", "王莉", opinion="复核确认金额与扫描件一致，放行")
    expect(rr.status_code == 200, S, "放行命令执行", "200", rr.json(), "FN-8-04/0-08")
    c2 = get_case(api_client, cid)
    expect(c2["status"] == "RESOLVED", S, "放行后状态", "RESOLVED", c2["status"], "FN-0-02")
    acts2 = [e["act"] for e in c2["timeline"]]
    i_ar = acts2.index("ACTION_RELEASE")
    expect(acts2[-1] == "STATUS_CHANGE" and len(acts2) - 1 > i_ar
           and "NEEDS_REVIEW" in c2["timeline"][-1]["d"] and "RESOLVED" in c2["timeline"][-1]["d"],
           S, "动作事件在前、终态流转紧随（事件序完整）", "…ACTION_RELEASE→…→STATUS_CHANGE(→RESOLVED)",
           acts2[-3:], "FN-0-10")
    expect("复核确认金额与扫描件一致" in c2["timeline"][i_ar]["x"],
           S, "处置意见写入时间线（要素④）", "含意见原文", c2["timeline"][i_ar]["x"], "FN-0-08")
    with persistence.get_session() as s:
        chk = audit_chain.verify_chain(s, verifier="S-M3-01")
        expect(chk["ok"], S, "审计链完整性（全链写入后）", "ok=True", chk, "FN-0-10")


# ═══════════════ S-M3-02 重复票→DEDUP_BLOCKED→批量放行跳过→双人解除 ═══════════════

def test_s_m3_02_duplicate_blocked_batch_skip_dual_unblock(api_client, tmp_dirs):
    S = "S-M3-02"
    a = sm2_service.attach_signature(mk_xml("2444200000050002", 20000.0, supplier="重复票演示供应商A"))
    ra = upload(api_client, "数电票_S02_基准_050002.xml", a)
    cid_a = ra.json()["files"][0]["caseId"]
    b = sm2_service.attach_signature(mk_xml("2444200000050002", 20000.0,
                                             supplier="重复票演示供应商A", buyer="第二购买方（换字节避摘要幂等）"))
    rb = upload(api_client, "数电票_S02_重复_050002.xml", b)
    cid_b = rb.json()["files"][0]["caseId"]
    cb = get_case(api_client, cid_b)
    expect(cb["status"] == "BLOCKED", S, "同票面异字节件→查重硬命中红线", "BLOCKED", cb["status"], "FN-5-04/0-02")
    expect(cb["checks"]["duplicate"]["result"] == "FAILED" and "硬命中" in cb["checks"]["duplicate"]["note"],
           S, "duplicate=FAILED 注记业务键硬命中", "FAILED·硬命中", cb["checks"]["duplicate"], "FN-5-04/CON-05")
    tl = [e["act"] for e in cb["timeline"]]
    expect("DEDUP_BLOCKED" in tl, S, "DEDUP_BLOCKED 事件", "存在", tl, "FN-0-10/5-04")
    al = api_client.get("/v1/alerts?instance=CN").json()["items"]
    expect(any("重复票红线拦截" in a_["title"] for a_ in al), S, "查重命中生成红线告警", "含 B 案告警", [a_["title"] for a_ in al], "FN-5-04/5-09")
    # 不入发票池（BLOCKED 排除，解除前核证；解除回落后再入池属 FN-0-02「按结论重新流转」）
    from app.services import dedup_service
    with persistence.get_session() as s:
        pool_ids = {p["case_id"] for p in dedup_service.pool_keys(s, "CN")}
        expect(cid_a in pool_ids and cid_b not in pool_ids, S,
               "入池/不入池口径（BLOCKED 排除）", "A∈池、B∉池", sorted(pool_ids)[:8], "FN-5-04")
    # 批量放行被跳过（红线：BLOCKED 不可批量放行）
    ch = api_client.post("/v1/batch/risk-challenge", json={"actor": "王莉", "instance": "CN",
                                                           "action": "batch_release", "case_ids": [cid_b]})
    rb2 = api_client.post("/v1/batch/actions/batch_release",
                          json={"actor": "王莉", "instance": "CN", "token": ch.json()["token"],
                                "self_confirmed": True, "case_ids": [cid_b]})
    body = rb2.json()
    expect(rb2.status_code == 200 and body["processed"] == 0 and body["skipped_count"] == 1
           and "BLOCKED 不可批量放行" in body["skipped"][0]["reason"],
           S, "批量放行跳过 BLOCKED 并给原因", "processed=0·skip=1·含红线原因", body, "FN-0-08/8-06")
    # 解除需双人：缺会签拒绝 → 会签成功回落复核队列 → B 出池、A 留痕可追
    r1 = act(api_client, cid_b, "unblock", "王莉", opinion="单人尝试")
    expect(r1.status_code == 409 and r1.json()["detail"]["error_code"] == "E_COUNTERSIGN_REQUIRED",
           S, "缺会签人解除被拒", "409 E_COUNTERSIGN_REQUIRED", r1.json(), "FN-8-06/0-02")
    r2 = act(api_client, cid_b, "unblock", "王莉", opinion="复核员+管理员会签：确属重复件，人工复核处理",
             co_signer="陈铮", co_signer_self=True)
    expect(r2.status_code == 200 and r2.json()["status"] == "NEEDS_REVIEW"
           and set(r2.json()["signers"]) == {"王莉", "陈铮"},
           S, "双人会签解除→按调查结论回落复核队列", "200·NEEDS_REVIEW·会签人齐", r2.json(), "FN-8-06")
    with persistence.get_session() as s:
        expect(audit_chain.verify_chain(s, verifier="S-M3-02")["ok"], S, "审计链完整性", "ok", "", "FN-0-10")


# ═══════════════ S-M3-03 篡改票（0379 路径重放）→SM2 FAILED→BLOCKED→失败回执归档 ═══════════════

def test_s_m3_03_tampered_sm2_failed_receipt_archived(api_client, tmp_dirs):
    S = "S-M3-03"
    signed = sm2_service.attach_signature(mk_xml("2444200000050003", 20000.0))
    tampered = signed.replace(b"20000.00", b"19900.00")            # 签名后改票面金额（篡改重放）
    expect(tampered != signed, S, "篡改构造生效（金额字节替换）", "字节差异", "", "FN-5-01")
    r = upload(api_client, "数电票_S03_篡改_050003.xml", tampered)
    cid = r.json()["files"][0]["caseId"]
    c = get_case(api_client, cid)
    expect(c["status"] == "BLOCKED", S, "验签失败红线→BLOCKED", "BLOCKED", c["status"], "FN-5-01/0-02/5-05")
    expect(c["checks"]["authenticity"]["result"] == "FAILED", S, "authenticity=FAILED", "FAILED",
           c["checks"]["authenticity"], "FN-0-07/5-01")
    sm = c["meta"]["sm2"]
    expect(sm["ok"] is False and sm["receipt_no"].startswith("gm-rcpt-"), S,
           "失败回执编号随案（meta.sm2）", "ok=False·gm-rcpt-*", sm, "FN-5-01/0-13")
    expect(c["meta"]["doc_hold_pending"] is True, S, "建档挂起（CON-02 附带动作）", "True",
           c["meta"]["doc_hold_pending"], "FN-0-02")
    rf = (tmp_dirs / "gm-receipts" / f"{sm['receipt_no']}.json")
    expect(rf.exists() and '"FAILED"' in rf.read_text(encoding="utf-8"), S,
           "失败回执文件归档且状态=FAILED（可司法取证注记）", "存在·FAILED", rf.exists(), "FN-5-01")
    tl = [e["act"] for e in c["timeline"]]
    expect("SM2_VERIFY_FAILED" in tl, S, "验签失败事件", "存在", tl, "FN-0-10")
    al = api_client.get("/v1/alerts?instance=CN").json()["items"]
    expect(any("验真红线" in x["title"] for x in al), S, "高风险通知（红线告警生成）", "含验真红线", [x["title"] for x in al], "FN-5-01/5-09")
    with persistence.get_session() as s:
        expect(audit_chain.verify_chain(s, verifier="S-M3-03")["ok"], S, "审计链完整性", "ok", "", "FN-0-10")


# ═══════════════ S-M3-04 多源冲突（0381 路径）→降级→NEEDS_REVIEW→修正以 XML 为准 ═══════════════

def test_s_m3_04_multi_source_conflict_edit_adopt_xml(api_client, tmp_dirs):
    S = "S-M3-04"
    xml_no, gross = "2444200000038101", 5680.0
    signed = sm2_service.attach_signature(mk_xml(xml_no, gross, net=5000.0, tax=680.0,
                                                 supplier="冲突演示供应商（0381 路径）"))
    r = upload(api_client, "数电票_S04_0381路径.xml", signed)
    cid = r.json()["files"][0]["caseId"]
    # 服务层融合（stub OCR 票面值 ¥5,650 vs XML ¥5,680，0381 案口径）
    with persistence.get_session() as s:
        case = s.get(m.Case, cid)
        fused = fusion_service.merge(s, case, {"total.gross_amount": 5650.0})
        expect(bool(fused["conflicts"]), S, "超容差判多源字段冲突", "conflicts 非空", fused, "FN-4-02")
        from app.services import state_machine
        path = state_machine.auto_flow(s, cid, conflict=True)
        expect([t["to"] for t in path] == ["NEEDS_REVIEW"], S, "冲突→NEEDS_REVIEW（强制人工）",
               "NEEDS_REVIEW", path, "FN-0-02/4-02")
        # 预置「系统误采信 OCR 值」态（数据准备：展示/证据值暂为 ¥5,650），复现 0381 页面口径
        row = s.query(m.FieldEvidence).filter_by(case_id=cid, field="total.gross_amount").first()
        ev = dict(row.evidence_raw); ev["value"] = 5650.0
        ev["evidence"] = {**ev["evidence"], "raw_text": "误采信 OCR 展示值 5650.0（测试预置）"}
        row.evidence_raw = ev
        f = s.get(m.Case, cid)
        f.facts_raw = {**f.facts_raw, "invoiceAmount": 5650.0}
        from app.services.state_machine import set_meta
        set_meta(f, amount_display="¥5,650.00")
        s.commit()
    c = get_case(api_client, cid)
    expect(c["status"] == "NEEDS_REVIEW" and c["meta"]["confidence"] == 82, S,
           "冲突降级 82%（policy.degrade_to）且停人工队列", "82/NEEDS_REVIEW",
           (c["meta"]["confidence"], c["status"]), "FN-4-02/0-06")
    tl = [e["act"] for e in c["timeline"]]
    expect("OCR_CROSS_CHECK_CONFLICT" in tl, S, "冲突事件（不静默取舍）", "存在", tl, "FN-0-10/4-02")
    # 人工修正：以 XML 直读值为准（FN-8-05 受控 edit_field）
    rr = act(api_client, cid, "edit_field", "王莉",
             field="total.gross_amount", new_value=5680.00,
             reason="多源冲突复核：采信 XML 直读 5,680.00（OCR 5,650.00 不采信）")
    expect(rr.status_code == 200, S, "修正执行", "200", rr.json(), "FN-8-05/0-08")
    c2 = get_case(api_client, cid)
    ev = next(e for e in c2["evidence"] if e["field"] == "total.gross_amount" and e["source"] == "manual")
    expect(ev["value"] == 5680.0 and "5650" in ev["evidence"]["raw_text"] and "→" in ev["evidence"]["raw_text"],
           S, "修正后=XML 值、原值保留（5650→5680 原文）", "5680 且 raw 含 5650→", ev["evidence"]["raw_text"], "FN-8-05")
    expect(any(e["field"] == "total.gross_amount" and e["source"] == "ocr" for e in c2["evidence"]),
           S, "OCR 冲突值证据仍留存（未采信不删除）", "存在 ocr 行", [e["source"] for e in c2["evidence"]], "FN-4-02")
    tl2 = [e["act"] for e in c2["timeline"]]
    expect("FIELD_EDITED" in tl2, S, "FIELD_EDITED 留痕", "存在", tl2, "FN-0-10/8-05")
    with persistence.get_session() as s:
        expect(audit_chain.verify_chain(s, verifier="S-M3-04")["ok"], S, "审计链完整性", "ok", "", "FN-0-10")


# ═══════════════ S-M3-05 受控写五要素逐项缺失→全部拒绝 ═══════════════

def test_s_m3_05_five_elements_missing_all_rejected(api_client, tmp_dirs):
    S = "S-M3-05"
    cid = "INV-CN-2026-0387"
    # ① 权限：刘工（运营）无「受控 Action 放行/退回」位
    ch = api_client.post(f"/v1/cases/{cid}/risk-challenge",
                         json={"actor": "刘工", "instance": "CN", "action": "release"})
    r = api_client.post(f"/v1/cases/{cid}/actions/release",
                        json={"actor": "刘工", "instance": "CN", "token": ch.json()["token"],
                              "self_confirmed": True})
    expect(r.status_code == 403 and r.json()["detail"]["error_code"] == "E_PERM_DENIED", S,
           "要素①权限缺失拒绝", "403 E_PERM_DENIED", r.json(), "FN-0-08/9-02")
    # ② 风险提示凭据：缺 token / 伪造 token / 重复使用（一次性）
    ch = api_client.post(f"/v1/cases/{cid}/risk-challenge",
                         json={"actor": "王莉", "instance": "CN", "action": "release"})
    token = ch.json()["token"]
    r0 = api_client.post(f"/v1/cases/{cid}/actions/release",
                         json={"actor": "王莉", "instance": "CN", "token": "", "self_confirmed": True})
    expect(r0.status_code == 428 and r0.json()["detail"]["error_code"] == "E_RISK_NOT_SHOWN", S,
           "要素②未经风险提示（缺凭据）", "428 E_RISK_NOT_SHOWN", r0.json(), "FN-0-08")
    r1 = api_client.post(f"/v1/cases/{cid}/actions/release",
                         json={"actor": "王莉", "instance": "CN", "token": "bogus" * 8, "self_confirmed": True})
    expect(r1.status_code == 428 and r1.json()["detail"]["error_code"] == "E_CONFIRM_INVALID", S,
           "要素③伪造凭据", "428 E_CONFIRM_INVALID", r1.json(), "FN-0-08")
    # ③ 本人执行勾选缺失
    r2 = api_client.post(f"/v1/cases/{cid}/actions/release",
                         json={"actor": "王莉", "instance": "CN", "token": token, "self_confirmed": False})
    expect(r2.status_code == 422 and r2.json()["detail"]["error_code"] == "E_SELF_CONFIRM_REQUIRED", S,
           "要素③未勾选本人执行", "422 E_SELF_CONFIRM_REQUIRED", r2.json(), "FN-0-08")
    # 凭据一次性：合法执行成功后重放被拒
    ok = api_client.post(f"/v1/cases/{cid}/actions/release",
                         json={"actor": "王莉", "instance": "CN", "token": token, "self_confirmed": True,
                               "opinion": "五要素齐备放行（S-M3-05 正路径）"})
    expect(ok.status_code == 200 and ok.json()["status"] == "RESOLVED", S,
           "五要素齐备正路径（对照组）", "200 RESOLVED", ok.json(), "FN-0-08/8-04")
    replay = api_client.post(f"/v1/cases/{cid}/actions/release",
                             json={"actor": "王莉", "instance": "CN", "token": token, "self_confirmed": True})
    expect(replay.status_code == 428 and replay.json()["detail"]["error_code"] == "E_CONFIRM_INVALID", S,
           "要素③凭据一次性（已消费拒绝）", "428 E_CONFIRM_INVALID", replay.json(), "FN-0-08")
    # ④ 处置意见必填（退回/拒绝类）：0125 INVESTIGATING
    ch4 = api_client.post("/v1/cases/INV-SG-2026-0125/risk-challenge",
                          json={"actor": "王莉", "instance": "OS", "action": "return"})
    r4 = api_client.post("/v1/cases/INV-SG-2026-0125/actions/return",
                         json={"actor": "王莉", "instance": "OS", "token": ch4.json()["token"],
                               "self_confirmed": True})
    expect(r4.status_code == 422 and r4.json()["detail"]["error_code"] == "E_OPINION_REQUIRED", S,
           "要素④退回类必填备注", "422 E_OPINION_REQUIRED", r4.json(), "FN-0-08")
    # ⑤ 审计写入失败→整笔回滚（要素⑤完整性）
    def boom(*a, **k):
        raise RuntimeError("审计链不可写（注入）")
    import app.services.governed_commands as gcm
    import app.services.state_machine as smm
    orig_gc, orig_sm = gcm.append_block, smm.append_block
    gcm.append_block = boom
    smm.append_block = boom
    try:
        cid2 = "INV-CN-2026-0384"
        ch5 = api_client.post(f"/v1/cases/{cid2}/risk-challenge",
                              json={"actor": "王莉", "instance": "CN", "action": "hold"})
        r5 = api_client.post(f"/v1/cases/{cid2}/actions/hold",
                             json={"actor": "王莉", "instance": "CN", "token": ch5.json()["token"],
                                   "self_confirmed": True})
        expect(r5.status_code == 500 and r5.json()["detail"]["error_code"] == "E_AUDIT_WRITE_FAILED", S,
               "要素⑤审计缺失→拒绝并回滚", "500 E_AUDIT_WRITE_FAILED", r5.json(), "FN-0-08/0-10")
        c5 = get_case(api_client, cid2)
        expect(c5["status"] == "NEEDS_REVIEW", S, "回滚后案件状态不变", "NEEDS_REVIEW", c5["status"], "FN-0-08")
    finally:
        gcm.append_block, smm.append_block = orig_gc, orig_sm
