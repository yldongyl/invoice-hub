# -*- coding: utf-8 -*-
"""最小只读 API 面测试（P02 §3 · 响应过契约校验）。

范围（用户确认）：只读四端点 + /healthz；POST actions 属 WP1.5，本会话不落。
"""

from tests.conftest import schema_errors

FULL_IDS = ["INV-CN-2026-0387", "INV-CN-2026-0379", "INV-SG-2026-0125"]


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["enum_registry_version"] == "1.0.0"
    assert body["database"] == "reachable"


def test_list_cases(client):
    r = client.get("/v1/cases", params={"instance": "CN"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7  # CN 实例 7 案（0387/0386/0385/0384/0383/0381/0379）
    assert all(i["instance"] == "CN" for i in body["items"])
    r = client.get("/v1/cases", params={"status": "BLOCKED", "instance": "CN"})
    assert {i["caseId"] for i in r.json()["items"]} == {"INV-CN-2026-0385", "INV-CN-2026-0379"}
    r = client.get("/v1/cases", params={"risk": "重复票"})
    assert r.json()["total"] == 2
    r = client.get("/v1/cases", params={"keyword": "Siemens"})
    assert [i["caseId"] for i in r.json()["items"]] == ["INV-SG-2026-0125"]


def test_get_case_full_passes_schema(client, seeds_cases, case_validator):
    for cid in FULL_IDS:
        r = client.get(f"/v1/cases/{cid}", params={"view": "full"})
        assert r.status_code == 200, cid
        errs = schema_errors(case_validator, r.json())
        assert not errs, f"{cid}: {[e.message for e in errs]}"
        seed = next(c for c in seeds_cases["cases"] if c["caseId"] == cid)
        assert r.json() == seed  # API 输出逐字段 = 种子


def test_get_case_summary(client):
    r = client.get("/v1/cases/INV-CN-2026-0387", params={"view": "summary"})
    assert r.status_code == 200
    body = r.json()
    assert {"caseId", "status", "amount", "risk_label", "confidence"} <= set(body)


def test_get_case_404(client):
    r = client.get("/v1/cases/INV-CN-2026-9999")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "CASE_NOT_FOUND"


def test_evidence_by_field(client):
    r = client.get("/v1/cases/INV-CN-2026-0387/evidence", params={"field": "total.gross_amount"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(i["field"] == "total.gross_amount" for i in body["items"])


def test_timeline(client, events_validator):
    r = client.get("/v1/cases/INV-SG-2026-0125/timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10
    for ev in body["items"]:
        assert not schema_errors(events_validator, ev)
