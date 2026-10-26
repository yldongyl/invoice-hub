# -*- coding: utf-8 -*-
"""受控写 API 面测试（P02 §3 actions 端点 + risk-challenge + WP1.7 租户 + WP1.8 发布；隔离库冒烟）。

§3 收尾：单案动作响应附契约合规 full 聚合（case 字段）并逐一过 Schema 校验。
"""

from tests.conftest import schema_errors


def _inst(cid):
    return "CN" if cid.startswith("INV-CN") else "OS"


def _challenge(c, cid, actor, action="release"):
    r = c.post(f"/v1/cases/{cid}/risk-challenge",
               json={"actor": actor, "instance": _inst(cid), "action": action})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert "本人" in body["self_confirm_label"] and body["risk_text"]
    return body["token"]


def test_api_release_flow_with_case_envelope(api_client, case_validator):
    cid = "INV-CN-2026-0387"
    tok = _challenge(api_client, cid, "王莉")
    r = api_client.post(f"/v1/cases/{cid}/actions/release",
                        json={"actor": "王莉", "instance": "CN", "token": tok,
                              "self_confirmed": True, "opinion": "口径差异确认"})
    assert r.status_code == 200, r.json()
    out = r.json()
    assert out["to"] == "RESOLVED" and out["trace_id"].startswith("tr-")
    # §3 收尾：响应内嵌 full 聚合过契约校验
    assert not schema_errors(case_validator, out["case"])
    assert out["case"]["status"] == "RESOLVED"
    tl = api_client.get(f"/v1/cases/{cid}/timeline", params={"instance": "CN"}).json()["items"]
    assert tl[-2]["act"] == "ACTION_RELEASE" and tl[-1]["act"] == "STATUS_CHANGE"
    assert tl[-1]["v"].startswith("case-machine")


def test_api_missing_self_confirm_422(api_client):
    cid = "INV-CN-2026-0384"
    tok = _challenge(api_client, cid, "王莉")
    r = api_client.post(f"/v1/cases/{cid}/actions/release",
                        json={"actor": "王莉", "instance": "CN", "token": tok,
                              "self_confirmed": False})
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "E_SELF_CONFIRM_REQUIRED"


def test_api_missing_token_428(api_client):
    cid = "INV-CN-2026-0384"
    r = api_client.post(f"/v1/cases/{cid}/actions/release",
                        json={"actor": "王莉", "instance": "CN", "token": "",
                              "self_confirmed": True})
    assert r.status_code == 428
    assert r.json()["detail"]["error_code"] == "E_RISK_NOT_SHOWN"


def test_api_cross_tenant_403(api_client):
    """OS 上下文放行 CN 案件 → 越权拒绝（四隔离①）。"""
    cid = "INV-CN-2026-0384"
    tok = _challenge(api_client, cid, "王莉")
    r = api_client.post(f"/v1/cases/{cid}/actions/release",
                        json={"actor": "王莉", "instance": "OS", "token": tok,
                              "self_confirmed": True})
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "E_TENANT_MISMATCH"


def test_api_batch_release_skips_blocked(api_client):
    ids = ["INV-CN-2026-0384", "INV-CN-2026-0385"]
    r = api_client.post("/v1/batch/risk-challenge",
                        json={"actor": "王莉", "instance": "CN", "action": "batch_release",
                              "case_ids": ids})
    tok = r.json()["token"]
    r2 = api_client.post("/v1/batch/actions/batch_release",
                         json={"actor": "王莉", "instance": "CN", "token": tok,
                               "case_ids": ids, "self_confirmed": True})
    assert r2.status_code == 200
    out = r2.json()
    assert [x["caseId"] for x in out["released"]] == ["INV-CN-2026-0384"]
    assert out["skipped"][0]["caseId"] == "INV-CN-2026-0385"
    assert "BLOCKED 不可批量放行" in out["skipped"][0]["reason"]


def test_api_edit_field(api_client):
    cid = "INV-CN-2026-0387"
    r = api_client.post(f"/v1/cases/{cid}/risk-challenge",
                        json={"actor": "王莉", "instance": "CN", "action": "edit_field"})
    tok = r.json()["token"]
    r2 = api_client.post(f"/v1/cases/{cid}/actions/edit_field",
                         json={"actor": "王莉", "instance": "CN", "token": tok,
                               "self_confirmed": True, "field": "total.gross_amount",
                               "new_value": 113500.0, "reason": "票面模糊，以复核测量为准"})
    assert r2.status_code == 200, r2.json()
    ev = api_client.get(f"/v1/cases/{cid}/evidence",
                        params={"field": "total.gross_amount", "instance": "CN"}).json()["items"][0]
    assert ev["source"] == "manual" and ev["confidence"] == 1.0
    assert "113500.0" in ev["evidence"]["raw_text"] and "（票面模糊，以复核测量为准）" in ev["evidence"]["raw_text"]


def test_api_unblock_requires_cosigner(api_client):
    cid = "INV-CN-2026-0379"
    r = api_client.post(f"/v1/cases/{cid}/risk-challenge",
                        json={"actor": "王莉", "instance": "CN", "action": "unblock"})
    tok = r.json()["token"]
    r2 = api_client.post(f"/v1/cases/{cid}/actions/unblock",
                         json={"actor": "王莉", "instance": "CN", "token": tok,
                               "self_confirmed": True})
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "E_COUNTERSIGN_REQUIRED"


def test_api_config_publish_and_rollback(api_client):
    """WP1.8 经 API：管理员发布配置 → POLICY_PUBLISHED 入链；回滚恢复旧值。"""
    key = "confidence_threshold_default"
    r = api_client.post(f"/v1/config/{key}/risk-challenge",
                        json={"actor": "陈铮", "instance": "CN", "action": "publish"})
    tok = r.json()["token"]
    new_payload = {"label": "置信度阈值（全局默认）", "value": 0.9, "range": [0.5, 0.99]}
    r2 = api_client.post("/v1/config/actions/publish",
                         json={"actor": "陈铮", "instance": "CN", "token": tok,
                               "self_confirmed": True, "config_key": key,
                               "config_payload": new_payload, "opinion": "校准提升"})
    assert r2.status_code == 200, r2.json()
    body = r2.json()
    assert body["diff"]["value"] == {"from": 0.85, "to": 0.9}
    eff = api_client.get("/v1/cases", params={"instance": "CN"})  # 顺带健康路径不报错
    assert eff.status_code == 200
    # 回滚
    r3 = api_client.post(f"/v1/config/{key}/risk-challenge",
                         json={"actor": "陈铮", "instance": "CN", "action": "rollback"})
    tok3 = r3.json()["token"]
    r4 = api_client.post("/v1/config/actions/rollback",
                         json={"actor": "陈铮", "instance": "CN", "token": tok3,
                               "self_confirmed": True, "config_key": key,
                               "to_version": body["prev_version"], "opinion": "恢复基线"})
    assert r4.status_code == 200, r4.json()
    assert r4.json()["diff"]["value"] == {"from": 0.9, "to": 0.85}


def test_api_config_publish_redline_bypass_denied(api_client):
    key = "low_confidence_force_human"
    r = api_client.post(f"/v1/config/{key}/risk-challenge",
                        json={"actor": "陈铮", "instance": "CN", "action": "publish"})
    tok = r.json()["token"]
    r2 = api_client.post("/v1/config/actions/publish",
                         json={"actor": "陈铮", "instance": "CN", "token": tok,
                               "self_confirmed": True, "config_key": key,
                               "config_payload": {"label": "低置信强制人工", "value": False}})
    assert r2.status_code == 403
    assert r2.json()["detail"]["error_code"] == "E_CONFIG_REDLINE_BYPASS"
