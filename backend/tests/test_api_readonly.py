# -*- coding: utf-8 -*-
"""最小只读 API 面测试（P02 §3 · R5 收尾：全部响应过契约校验 + WP1.7 租户强制）。"""

from tests.conftest import schema_errors

FULL_IDS = ["INV-CN-2026-0387", "INV-CN-2026-0379", "INV-SG-2026-0125"]


def _inst(cid: str) -> str:
    return "CN" if cid.startswith("INV-CN") else "OS"


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["enum_registry_version"] == "1.1.0"  # M2 v1.1.0：兼容增补 link_type（CHANGELOG ⑦）
    assert body["database"] == "reachable"


def test_list_cases_requires_tenant(client):
    """WP1.7：缺 instance → E_TENANT_MISSING→400。"""
    r = client.get("/v1/cases")
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "E_TENANT_MISSING"


def test_list_cases_filtered(client, case_validator):
    r = client.get("/v1/cases", params={"instance": "CN"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7  # CN 实例 7 案（0387/0386/0385/0384/0383/0381/0379）
    for item in body["items"]:
        assert item["meta"]["instance"] == "CN"
        # 列表项=契约合法 list 级案件形态（§3：响应过 Schema）
        assert not schema_errors(case_validator, item), item["caseId"]
    r = client.get("/v1/cases", params={"status": "BLOCKED", "instance": "CN"})
    assert {i["caseId"] for i in r.json()["items"]} == {"INV-CN-2026-0385", "INV-CN-2026-0379"}
    r = client.get("/v1/cases", params={"instance": "CN", "risk": "重复票"})
    assert r.json()["total"] == 1
    r = client.get("/v1/cases", params={"instance": "OS", "keyword": "Siemens"})
    assert [i["caseId"] for i in r.json()["items"]] == ["INV-SG-2026-0125"]


def test_get_case_full_passes_schema(client, seeds_cases, case_validator):
    for cid in FULL_IDS:
        r = client.get(f"/v1/cases/{cid}", params={"view": "full", "instance": _inst(cid)})
        assert r.status_code == 200, cid
        errs = schema_errors(case_validator, r.json())
        assert not errs, f"{cid}: {[e.message for e in errs]}"
        seed = next(c for c in seeds_cases["cases"] if c["caseId"] == cid)
        assert r.json() == seed  # API 输出逐字段 = 种子


def test_get_case_summary_contract_shape(client, case_validator):
    r = client.get("/v1/cases/INV-CN-2026-0387",
                   params={"view": "summary", "instance": "CN"})
    assert r.status_code == 200
    body = r.json()
    assert {"caseId", "status", "detail_level", "summary", "meta", "facts"} <= set(body)
    assert body["meta"]["risk_label"] == "PO 金额差异"
    assert not schema_errors(case_validator, body)   # §3：summary 响应亦过 Schema


def test_get_case_tenant_mismatch_403(client):
    """四隔离越权：OS 上下文取 CN 案件 → 拒绝。"""
    r = client.get("/v1/cases/INV-CN-2026-0387", params={"instance": "OS"})
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "E_TENANT_MISMATCH"


def test_get_case_404(client):
    r = client.get("/v1/cases/INV-CN-2026-9999", params={"instance": "CN"})
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "CASE_NOT_FOUND"


def test_evidence_by_field(client, case_validator):
    r = client.get("/v1/cases/INV-CN-2026-0387/evidence",
                   params={"field": "total.gross_amount", "instance": "CN"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert all(i["field"] == "total.gross_amount" for i in body["items"])
    entry_def = case_validator.schema["$defs"]["evidenceEntry"]
    from jsonschema import Draft202012Validator
    for it in body["items"]:
        assert not list(Draft202012Validator(entry_def).iter_errors(it))


def test_timeline(client, events_validator):
    r = client.get("/v1/cases/INV-SG-2026-0125/timeline", params={"instance": "OS"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10
    for ev in body["items"]:
        assert not schema_errors(events_validator, ev)
