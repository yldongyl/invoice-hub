# -*- coding: utf-8 -*-
"""WP3.4 工作台 API 测试（FN-8-01/02/04/05/06/07/09 · 队列侧全交互面）。

覆盖：队列归属与待复核计数；四维筛选（状态/关键词/风险 any|none/实例=地区维）；
单/批认领（claimed_by/at 子态+锁）；放行/挂起/退回全链双写留痕；人工修正字段
（原因必填/原值保留/来源徽章=人工）；AI 不采纳留痕；批量放行 BLOCKED 跳过明细；
导出 CSV 自审计入链头+24h 限时链接失效 410；双人解除（缺会签 409 / 会签成功）。
"""

import pytest
from sqlalchemy import select

from app.domain import models as m
from app.services import audit_chain, persistence, workbench


@pytest.fixture(autouse=True)
def tmp_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "EXPORT_DIR", tmp_path / "exports")
    return tmp_path


def _challenge(c, path, body):
    r = c.post(path, json=body)
    assert r.status_code == 200, r.json()
    return r.json()["token"]


def _act(c, cid, action, body):
    return c.post(f"/v1/cases/{cid}/actions/{action}", json=body)


def base(actor, instance, token, **kw):
    return {"actor": actor, "instance": instance, "token": token,
            "self_confirmed": True, **kw}


# ── FN-8-01 队列与四维筛选 ──────────────────────────────────────────────

def test_queue_stats(api_client):
    q = api_client.get("/v1/workbench/queue?instance=CN").json()
    assert q["queue"] == "亚太采购共享中心"
    assert q["needs_review"] == 3 and q["blocked"] == 2          # 0387/0384/0381 · 0385/0379
    assert q["pending_review"] == q["needs_review"] + q["investigating"]
    assert q["claim_high_risk_minutes"] == 30                    # 高风险 30 分钟认领 SLA
    os_q = api_client.get("/v1/workbench/queue?instance=OS").json()
    assert os_q["queue"] == "新加坡共享中心"


def test_list_four_dim_filters(api_client):
    r = api_client.get("/v1/cases?instance=CN&status=NEEDS_REVIEW")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3 and all(i["status"] == "NEEDS_REVIEW" for i in items)
    # 关键词维（案件号/供应商）
    k = api_client.get("/v1/cases?instance=CN&keyword=中科").json()
    assert [x["caseId"] for x in k["items"]] == ["INV-CN-2026-0387"]
    # 风险维：any / none
    any_r = api_client.get("/v1/cases?instance=CN&risk=any&status=NEEDS_REVIEW").json()
    assert all((x["meta"].get("risk_label")) for x in any_r["items"])
    none_r = api_client.get("/v1/cases?instance=CN&risk=none").json()
    assert all(not (x["meta"].get("risk_label")) for x in none_r["items"])
    # 组合+计数
    comb = api_client.get("/v1/cases?instance=CN&status=NEEDS_REVIEW&risk=any").json()
    assert comb["total"] == len(comb["items"])
    bad = api_client.get("/v1/cases?instance=CN").json()
    assert bad["total"] == 7                                     # CN 七案
    assert api_client.get("/v1/cases").status_code == 400        # 缺租户上下文→E_TENANT_MISSING


# ── FN-8-02 认领（单/批，claimed 子态与锁） ────────────────────────────

def test_claim_single_and_lock(api_client):
    tok = _challenge(api_client, "/v1/cases/INV-CN-2026-0387/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "claim"})
    r = _act(api_client, "INV-CN-2026-0387", "claim", base("王莉", "CN", tok))
    assert r.status_code == 200, r.json()
    assert "王莉" in r.json()["claimed_by"] and r.json()["status"] == "NEEDS_REVIEW"

    c = api_client.get("/v1/cases/INV-CN-2026-0387?instance=CN").json()
    assert "王莉" in c["meta"]["claimed_by"] and c["meta"]["claimed_at"]
    acts = [e["act"] for e in c["timeline"]]
    assert acts[-1] == "REVIEW_OPENED"                           # 认领事件实时追加（复核员+中心）
    assert "亚太采购共享中心" in c["timeline"][-1]["x"]
    # 锁：他人未超时被拒
    tok2 = _challenge(api_client, "/v1/cases/INV-CN-2026-0387/risk-challenge",
                      {"actor": "刘工", "instance": "CN", "action": "claim"})
    r2 = _act(api_client, "INV-CN-2026-0387", "claim", base("刘工", "CN", tok2))
    assert r2.status_code == 409 and r2.json()["detail"]["error_code"] == "CLAIM_LOCKED"


def test_batch_claim(api_client):
    ids = ["INV-CN-2026-0387", "INV-CN-2026-0384", "INV-CN-2026-0381"]
    tok = _challenge(api_client, "/v1/batch/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "batch_claim", "case_ids": ids})
    r = api_client.post("/v1/batch/actions/batch_claim",
                        json={"actor": "王莉", "instance": "CN", "token": tok,
                              "self_confirmed": True, "case_ids": ids})
    assert r.status_code == 200
    assert len(r.json()["claimed"]) == 3 and r.json()["skipped_count"] == 0


# ── FN-8-04 受控 Action 全链留痕（放行/挂起/退回，时间线+审计链双写） ───

def test_release_full_chain(api_client):
    tok = _challenge(api_client, "/v1/cases/INV-CN-2026-0381/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "release"})
    r = _act(api_client, "INV-CN-2026-0381", "release",
             base("王莉", "CN", tok, opinion="口径差异已电话确认，放行"))
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["status"] == "RESOLVED" and body["to"] == "RESOLVED"
    acts = [e["act"] for e in body["case"]["timeline"]]
    assert "ACTION_RELEASE" in acts and "STATUS_CHANGE" in acts  # 双事件：动作+流转
    c1 = acts.index("ACTION_RELEASE")
    assert acts[c1 + 1] == "STATUS_CHANGE"   # 动作在前、流转紧随（seed 历史中另有前序 STATUS_CHANGE）
    assert "五要素" in body["case"]["timeline"][c1]["d"] or "受控 Action：放行" in body["case"]["timeline"][c1]["d"]
    x = body["case"]["timeline"][c1]["x"]
    assert "处置意见：口径差异已电话确认，放行" in x and "五要素齐备" in x
    with persistence.get_session() as s:
        blks = s.scalars(select(m.AuditBlock).where(
            m.AuditBlock.case_id == "INV-CN-2026-0381").order_by(m.AuditBlock.blk.desc())).all()
        assert {b.act for b in blks[:2]} == {"STATUS_CHANGE", "ACTION_RELEASE"}
        assert audit_chain.verify_chain(s, verifier="wp34-release")["ok"]


def test_hold_and_return_chain(api_client):
    cid = "INV-CN-2026-0384"
    tok = _challenge(api_client, f"/v1/cases/{cid}/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "hold"})
    r = _act(api_client, cid, "hold", base("王莉", "CN", tok))
    assert r.json()["status"] == "INVESTIGATING"
    # 退回=对外动作理由必填（缺→422）
    t2 = _challenge(api_client, f"/v1/cases/{cid}/risk-challenge",
                    {"actor": "王莉", "instance": "CN", "action": "return"})
    r2 = _act(api_client, cid, "return", base("王莉", "CN", t2))
    assert r2.status_code == 422 and r2.json()["detail"]["error_code"] == "E_OPINION_REQUIRED"
    r3 = _act(api_client, cid, "return", base("王莉", "CN", t2, opinion="税额口径无法确认，退回重开"))
    assert r3.json()["status"] == "BLOCKED"
    c = r3.json()["case"]
    assert c["meta"]["doc_hold_pending"] is True                 # 退回→建档挂起
    assert any("ACTION_RETURN" == e["act"] for e in c["timeline"])


# ── FN-8-05 人工修正字段 ────────────────────────────────────────────────

def test_edit_field_required_reason_and_trace(api_client):
    cid = "INV-CN-2026-0387"
    tok = _challenge(api_client, f"/v1/cases/{cid}/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "edit_field"})
    r = _act(api_client, cid, "edit_field",
             base("王莉", "CN", tok, field="total.gross_amount", new_value=113000.00))
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "E_EDIT_PARAM_REQUIRED"
    r2 = _act(api_client, cid, "edit_field",
              base("王莉", "CN", tok, field="total.gross_amount", new_value=113000.00,
                   reason="票面模糊，经供应商邮件确认含税总额"))
    assert r2.status_code == 200, r2.json()
    ev = next(e for e in r2.json()["case"]["evidence"] if e["field"] == "total.gross_amount")
    assert ev["source"] == "manual" and ev["confidence"] == 1.0  # 来源徽章=人工
    assert "→" in ev["evidence"]["raw_text"] and "票面模糊" in ev["evidence"]["raw_text"]
    assert ev["evidence"]["bbox"]                                # 原 page/bbox 保留可追溯
    acts = [e["act"] for e in r2.json()["case"]["timeline"]]
    assert acts[-1] == "FIELD_EDITED"
    # 未知字段被拒
    t3 = _challenge(api_client, f"/v1/cases/{cid}/risk-challenge",
                    {"actor": "王莉", "instance": "CN", "action": "edit_field"})
    r4 = _act(api_client, cid, "edit_field",
              base("王莉", "CN", t3, field="not.a.field", new_value="x", reason="r"))
    assert r4.status_code == 422 and r4.json()["detail"]["error_code"] == "E_FIELD_NOT_FOUND"


# ── FN-8-07 批量放行 BLOCKED 跳过明细 ──────────────────────────────────

def test_batch_release_blocked_skip_detail(api_client):
    ids = ["INV-CN-2026-0387", "INV-CN-2026-0385", "INV-CN-2026-0379"]
    tok = _challenge(api_client, "/v1/batch/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "batch_release", "case_ids": ids})
    r = api_client.post("/v1/batch/actions/batch_release",
                        json={"actor": "王莉", "instance": "CN", "token": tok,
                              "self_confirmed": True, "opinion": "S-M3 批量",
                              "case_ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert [x["caseId"] for x in body["released"]] == ["INV-CN-2026-0387"]
    skipped = {s["caseId"]: s["reason"] for s in body["skipped"]}
    assert set(skipped) == {"INV-CN-2026-0385", "INV-CN-2026-0379"}
    assert all("BLOCKED 不可批量放行" in v for v in skipped.values())
    assert body["skipped_count"] == 2


# ── FN-8-07 导出：入链头 + 限时链接 ─────────────────────────────────────

def test_export_self_audit_head_and_link(api_client):
    tok = _challenge(api_client, "/v1/audit/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "export"})
    r = api_client.post("/v1/audit/actions/export", json={
        "actor": "王莉", "instance": "CN", "token": tok, "self_confirmed": True,
        "filters": {"status": "NEEDS_REVIEW", "keyword": ""}, "rows": 3})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["rows_exported"] == 3 and body["url"].startswith("/v1/exports/")
    # AUDIT_EXPORT 位于链头（PLATFORM 域最大 blk）
    with persistence.get_session() as s:
        head = s.scalars(select(m.AuditBlock).where(
            m.AuditBlock.chain_scope == audit_chain.PLATFORM_SCOPE)
            .order_by(m.AuditBlock.blk.desc())).first()
        assert head.act == "AUDIT_EXPORT" and head.blk == body["blk"]
        assert "检索条件：" in head.from_state and head.trace == body["trace"]
    dl = api_client.get(body["url"])
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("text/csv")
    import csv as _csv
    import io as _io
    rows = list(_csv.reader(_io.StringIO(dl.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["案件号", "供应商", "金额"]
    assert len(rows) == 1 + body["rows_exported"]                  # 摘要含换行→以 csv 解析计数
    assert any(r and r[0] == "INV-CN-2026-0387" for r in rows[1:])
    # 限时失效：把票据到期时间拨到过去 → 410，重导重签发
    with persistence.get_session() as s:
        t = s.get(m.ExportTicket, body["token"])
        t.expires_ts = "2020-01-01T00:00:00+08:00"
        s.commit()
    g = api_client.get(body["url"])
    assert g.status_code == 410
    assert g.json()["detail"]["error_code"] == "E_EXPORT_EXPIRED"


def test_export_requires_filters_and_rows(api_client):
    tok = _challenge(api_client, "/v1/audit/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "export"})
    r = api_client.post("/v1/audit/actions/export", json={
        "actor": "王莉", "instance": "CN", "token": tok, "self_confirmed": True})
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "E_EXPORT_PARAM"


# ── FN-8-09 不采纳 AI 建议留痕 ──────────────────────────────────────────

def test_advice_reject_records_and_noop(api_client):
    cid = "INV-CN-2026-0387"
    tok = _challenge(api_client, f"/v1/cases/{cid}/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "advice_reject"})
    r = _act(api_client, cid, "advice_reject",
             base("王莉", "CN", tok, advice_id="ai-card-0387", reason="需外部函证后再定"))
    assert r.status_code == 200, r.json()
    c = r.json()["case"]
    assert c["status"] == "NEEDS_REVIEW"                          # 状态不变
    last = c["timeline"][-1]
    assert last["act"] == "LLM_ADVICE_REJECTED" and last["a"] == "human"
    assert "建议未被执行" in last["x"] or "未被执行" in last["x"]
    assert "需外部函证后再定" in last["x"]
    with persistence.get_session() as s:
        assert s.scalars(select(m.AuditBlock).where(
            m.AuditBlock.act == "LLM_ADVICE_REJECTED")).first() is not None


# ── FN-8-06 双人解除（HTTP 全序）与会签人目录 ──────────────────────────

def test_cosigners_and_unblock_http(api_client):
    cs = api_client.get("/v1/workbench/co-signers").json()["items"]
    assert [u["name"] for u in cs] == ["陈铮"]
    cid = "INV-CN-2026-0385"
    tok = _challenge(api_client, f"/v1/cases/{cid}/risk-challenge",
                     {"actor": "王莉", "instance": "CN", "action": "unblock"})
    r = _act(api_client, cid, "unblock", base("王莉", "CN", tok))
    assert r.status_code == 409 and r.json()["detail"]["error_code"] == "E_COUNTERSIGN_REQUIRED"
    r2 = _act(api_client, cid, "unblock",
              base("王莉", "CN", tok, co_signer="陈铮", co_signer_self=True,
                   opinion="会签复核：误拦截，转人工复核"))
    assert r2.status_code == 200, r2.json()
    body = r2.json()
    assert body["status"] == "NEEDS_REVIEW" and set(body["signers"]) == {"王莉", "陈铮"}
    tl = [e["act"] for e in body["case"]["timeline"]]
    assert "REVIEW_OPENED" in tl[-2:] and "STATUS_CHANGE" in tl[-1:]
    with persistence.get_session() as s:
        assert audit_chain.verify_chain(s, verifier="wp34-unblock")["ok"]
