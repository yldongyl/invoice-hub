# -*- coding: utf-8 -*-
"""Provider 管理与路由调度 API 接口测试（WP4.1/4.2）。"""

import pytest


def test_api_list_providers(api_client):
    """GET /v1/providers 返回 6 个 Provider 及 SLA / 成本。"""
    r = api_client.get("/v1/providers")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 6
    p_ids = {p["provider_id"] for p in data["providers"]}
    assert "bwyun-cn" in p_ids
    assert "human-fallback" in p_ids


def test_api_human_fallback_lock(api_client):
    """POST /v1/providers/human-fallback/toggle 停用被拒绝 (400)。"""
    r = api_client.post("/v1/providers/human-fallback/toggle", json={"enabled": False, "actor": "human"})
    assert r.status_code == 400
    det = r.json()["detail"]
    assert det["error_code"] == "E_PROVIDER_LOCKED"
    assert "不可停用" in det["message"]


def test_api_toggle_and_test_provider(api_client):
    """测试常规 Provider 启停与连通测试端点。"""
    # 1. 连通测试
    r_test = api_client.post("/v1/providers/bwyun-cn/test", json={"actor": "human"})
    assert r_test.status_code == 200
    res = r_test.json()
    assert res["ok"] is True
    assert res["normalized_valid"] is True

    # 2. 停用百望云
    r_off = api_client.post("/v1/providers/bwyun-cn/toggle", json={"enabled": False, "actor": "human", "opinion": "测试停用"})
    assert r_off.status_code == 200
    assert r_off.json()["enabled"] is False

    # 3. 重新启用百望云
    r_on = api_client.post("/v1/providers/bwyun-cn/toggle", json={"enabled": True, "actor": "human"})
    assert r_on.status_code == 200
    assert r_on.json()["enabled"] is True


def test_api_metrics(api_client):
    """测试 SLA 与成本指标端点。"""
    r_sla = api_client.get("/v1/providers/metrics/sla")
    assert r_sla.status_code == 200
    assert r_sla.json()["warn_count"] >= 1

    r_cost = api_client.get("/v1/providers/metrics/costs")
    assert r_cost.status_code == 200
    assert "CNY" in r_cost.json()["currencies"]


def test_api_routing_policy_and_evaluate(api_client):
    """测试路由策略读取与推演评估端点。"""
    # 1. 读取策略
    r_pol = api_client.get("/v1/routing/policy")
    assert r_pol.status_code == 200
    pol = r_pol.json()
    assert pol["version"] == "v2026-10-20.3"
    assert len(pol["rules"]) >= 4

    # 2. 推演评估纸质专票
    eval_req = {
        "region": "CN 中国",
        "invoice_type": "增值税专票/普票（纸质扫描）",
        "carrier": "纸质扫描 / 图片",
        "doc_type_hint": "增值税专票/普票（纸质扫描）",
    }
    r_eval = api_client.post("/v1/routing/evaluate", json=eval_req)
    assert r_eval.status_code == 200
    eval_res = r_eval.json()
    assert eval_res["status"] == "done"
    assert eval_res["final_provider"] == "nuonuo-cn"
    assert eval_res["confidence"] == 0.91
    assert len(eval_res["steps"]) >= 4
