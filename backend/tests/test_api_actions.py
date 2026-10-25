# -*- coding: utf-8 -*-
"""受控写 API 面测试（P02 §3 actions 端点 + risk-challenge，经 WP1.5 框架；隔离库冒烟）。"""


def _challenge(c, cid, actor, action="release"):
    r = c.post(f"/v1/cases/{cid}/risk-challenge", json={"actor": actor, "action": action})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert "本人" in body["self_confirm_label"] and body["risk_text"]
    return body["token"]


def test_api_release_flow(api_client):
    tok = _challenge(api_client, "INV-CN-2026-0387", "王莉")
    r = api_client.post("/v1/cases/INV-CN-2026-0387/actions/release",
                        json={"actor": "王莉", "token": tok, "self_confirmed": True,
                              "opinion": "口径差异确认"})
    assert r.status_code == 200, r.json()
    out = r.json()
    assert out["to"] == "RESOLVED" and out["trace_id"].startswith("tr-")
    tl = api_client.get("/v1/cases/INV-CN-2026-0387/timeline").json()["items"]
    assert tl[-2]["act"] == "ACTION_RELEASE" and tl[-1]["act"] == "STATUS_CHANGE"
    assert tl[-1]["v"].startswith("case-machine")


def test_api_missing_self_confirm_422(api_client):
    tok = _challenge(api_client, "INV-CN-2026-0384", "王莉")
    r = api_client.post("/v1/cases/INV-CN-2026-0384/actions/release",
                        json={"actor": "王莉", "token": tok, "self_confirmed": False})
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "E_SELF_CONFIRM_REQUIRED"


def test_api_missing_token_428(api_client):
    r = api_client.post("/v1/cases/INV-CN-2026-0384/actions/release",
                        json={"actor": "王莉", "token": "", "self_confirmed": True})
    assert r.status_code == 428
    assert r.json()["detail"]["error_code"] == "E_RISK_NOT_SHOWN"


def test_api_batch_release_skips_blocked(api_client):
    ids = ["INV-CN-2026-0384", "INV-CN-2026-0385"]
    r = api_client.post("/v1/batch/risk-challenge",
                        json={"actor": "王莉", "action": "batch_release", "case_ids": ids})
    tok = r.json()["token"]
    r2 = api_client.post("/v1/batch/actions/batch_release",
                         json={"actor": "王莉", "token": tok, "case_ids": ids,
                               "self_confirmed": True})
    assert r2.status_code == 200
    out = r2.json()
    assert [x["caseId"] for x in out["released"]] == ["INV-CN-2026-0384"]
    assert out["skipped"][0]["caseId"] == "INV-CN-2026-0385"
    assert "BLOCKED 不可批量放行" in out["skipped"][0]["reason"]


def test_api_edit_field(api_client):
    r = api_client.post("/v1/cases/INV-CN-2026-0387/risk-challenge",
                        json={"actor": "王莉", "action": "edit_field"})
    tok = r.json()["token"]
    r2 = api_client.post("/v1/cases/INV-CN-2026-0387/actions/edit_field",
                         json={"actor": "王莉", "token": tok, "self_confirmed": True,
                               "field": "total.gross_amount", "new_value": 113500.0,
                               "reason": "票面模糊，以复核测量为准"})
    assert r2.status_code == 200, r2.json()
    ev = api_client.get("/v1/cases/INV-CN-2026-0387/evidence",
                        params={"field": "total.gross_amount"}).json()["items"][0]
    assert ev["source"] == "manual" and ev["confidence"] == 1.0
    assert "113500.0" in ev["evidence"]["raw_text"] and "（票面模糊，以复核测量为准）" in ev["evidence"]["raw_text"]


def test_api_unblock_requires_cosigner(api_client):
    r = api_client.post("/v1/cases/INV-CN-2026-0379/risk-challenge",
                        json={"actor": "王莉", "action": "unblock"})
    tok = r.json()["token"]
    r2 = api_client.post("/v1/cases/INV-CN-2026-0379/actions/unblock",
                         json={"actor": "王莉", "token": tok, "self_confirmed": True})
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "E_COUNTERSIGN_REQUIRED"
