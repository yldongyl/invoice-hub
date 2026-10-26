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


def test_list_cases_filtered(client, list_projection_validator):
    r = client.get("/v1/cases", params={"instance": "CN"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7  # CN 实例 7 案（0387/0386/0385/0384/0383/0381/0379）
    # 响应整体过 case-read.schema（M2 WP2.1 列表投影契约，M-M1-005 瘦身）
    assert not schema_errors(list_projection_validator, body), [e.message for e in schema_errors(list_projection_validator, body)][:3]
    for item in body["items"]:
        assert item["meta"]["instance"] == "CN"
        # 投影形态：六键、full 案件不再内嵌全要素（瘦身断言）
        assert set(item) == {"caseId", "detail_level", "status", "summary", "meta", "facts"}
        if item["detail_level"] == "full":
            assert "checks" not in item and "evidence" not in item
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


def test_switcher_view(client, switcher_validator, seeds_cases):
    """案件切换器（WP2.1 · FN-8-03/FN-0-14）：本实例 full 案件 号+票种+状态，load_seq 原序。
    页面三案=前端合并双实例各请求一次（四隔离①数据强制，口径见 M2-self-check）。"""
    r = client.get("/v1/cases", params={"instance": "CN", "view": "switcher"})
    assert r.status_code == 200
    body = r.json()
    assert not schema_errors(switcher_validator, body)
    assert [i["caseId"] for i in body["items"]] == ["INV-CN-2026-0387", "INV-CN-2026-0379"]
    assert body["items"][0]["type_short"] == "数电票"
    assert body["items"][0]["status"] == "NEEDS_REVIEW"
    assert body["items"][0]["invoice_type_machine"] == "E_INVOICE_VAT_SPECIAL"
    r = client.get("/v1/cases", params={"instance": "OS", "view": "switcher"})
    assert not schema_errors(switcher_validator, r.json())
    assert [i["caseId"] for i in r.json()["items"]] == ["INV-SG-2026-0125"]
    assert r.json()["items"][0]["status"] == "INVESTIGATING"
    assert r.json()["items"][0]["type_short"] == "Supplier Invoice"
    # 全库 full 案件三案合计（跨页合并口径的库内完整性）
    full_ids = {c["caseId"] for c in seeds_cases["cases"] if c["detail_level"] == "full"}
    assert full_ids == {"INV-CN-2026-0387", "INV-CN-2026-0379", "INV-SG-2026-0125"}


def test_switcher_requires_tenant(client):
    r = client.get("/v1/cases", params={"view": "switcher"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "E_TENANT_MISSING"


def test_timeline(client, events_validator):
    r = client.get("/v1/cases/INV-SG-2026-0125/timeline", params={"instance": "OS"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 10
    for ev in body["items"]:
        assert not schema_errors(events_validator, ev)
