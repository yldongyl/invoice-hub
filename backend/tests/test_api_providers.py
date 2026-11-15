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


def test_api_draft_crud_and_simulation_consistency(api_client):
    """测试草稿全套 CRUD 与模拟推演优先采用草稿（FN-2-08/09/11/12）。"""
    # 1. 初始读取草稿应为空
    r_init = api_client.get("/v1/routing/policy/draft")
    assert r_init.status_code == 200
    assert r_init.json()["has_draft"] is False

    # 2. 获取当前已发布策略
    base_pol = api_client.get("/v1/routing/policy").json()

    # 3. 校验非法草稿保存被 Schema 拦截（422）
    bad_draft = dict(base_pol)
    bad_draft["rules"] = [{"bad_rule": 123}]  # 不满足 required
    r_bad = api_client.post("/v1/routing/policy/draft?actor=陈铮", json=bad_draft)
    assert r_bad.status_code == 422
    assert r_bad.json()["detail"]["error_code"] == "E_ROUTING_CONFIG_INVALID"

    # 4. 保存有效草稿：上调纸质专票阈值至 0.95
    new_draft = dict(base_pol)
    rules = [dict(r) for r in new_draft["rules"]]
    for r in rules:
        if r.get("route_id") == "cn_vat_paper_recognize":
            r["strategies"] = [dict(s) for s in r["strategies"]]
            for s in r["strategies"]:
                if s.get("threshold") is not None:
                    s["threshold"] = 0.95
    new_draft["rules"] = rules
    r_save = api_client.post("/v1/routing/policy/draft?actor=陈铮", json=new_draft)
    assert r_save.status_code == 200
    assert r_save.json()["saved"] is True

    # 5. 读取草稿，断言已持久化
    r_draft = api_client.get("/v1/routing/policy/draft")
    assert r_draft.status_code == 200
    assert r_draft.json()["has_draft"] is True
    draft_pol = r_draft.json()["draft"]
    p_rule = next(r for r in draft_pol["rules"] if r.get("route_id") == "cn_vat_paper_recognize")
    assert p_rule["strategies"][0]["threshold"] == 0.95

    # 6. 执行模拟推演 /v1/routing/simulate，断言草稿优先生效：
    # 0.95 高阈值下，诺诺 0.91 亦不达标 → 降级人工兜底！且标注 policy_version
    sim_req = {
        "region": "CN 中国",
        "invoice_type": "增值税专票/普票（纸质扫描）",
        "carrier": "纸质扫描 / 图片",
        "doc_type_hint": "增值税专票/普票（纸质扫描）",
    }
    r_sim = api_client.post("/v1/routing/simulate", json=sim_req)
    assert r_sim.status_code == 200
    sim_res = r_sim.json()
    assert sim_res["status"] == "manual"
    assert sim_res["final_provider"] == "human-fallback"
    assert sim_res["policy_state"] == "draft"

    # 7. 测试全局降级卡 direct_human 改动进入草稿并影响推演
    new_draft["global_fallback"]["mode"] = "direct_human"
    r_save2 = api_client.post("/v1/routing/policy/draft?actor=陈铮", json=new_draft)
    assert r_save2.status_code == 200
    r_sim2 = api_client.post("/v1/routing/simulate", json=sim_req)
    assert r_sim2.status_code == 200
    sim_res2 = r_sim2.json()
    assert sim_res2["status"] == "manual"
    assert any("直接人工兜底" in s["t"] for s in sim_res2["steps"])

    # 8. 丢弃草稿
    r_del = api_client.delete("/v1/routing/policy/draft")
    assert r_del.status_code == 200
    assert r_del.json()["deleted"] is True
    assert api_client.get("/v1/routing/policy/draft").json()["has_draft"] is False


def test_api_controlled_publish_and_rollback_lifecycle(api_client):
    """测试受控发布五要素链与回滚生命周期（FN-2-12 · FN-0-08 · CON-B7）。"""
    base_pol = api_client.get("/v1/routing/policy").json()
    orig_ver = base_pol["version"]

    # 1. 保存草稿
    new_draft = dict(base_pol)
    rules = [dict(r) for r in new_draft["rules"]]
    for r in rules:
        if r.get("route_id") == "cn_vat_paper_recognize":
            r["strategies"] = [dict(s) for s in r["strategies"]]
            for s in r["strategies"]:
                if s.get("threshold") is not None:
                    s["threshold"] = 0.93
    new_draft["rules"] = rules
    api_client.post("/v1/routing/policy/draft?actor=陈铮", json=new_draft)

    # 2. 请求 risk-challenge 签发 token
    r_ch = api_client.post(
        "/v1/config/routing_policy/risk-challenge",
        json={"actor": "陈铮", "instance": "CN", "action": "publish"},
    )
    assert r_ch.status_code == 200
    token = r_ch.json()["token"]
    assert token

    # 3. 未勾选 self_confirmed 拒绝执行（五要素核心）
    r_rej = api_client.post(
        "/v1/config/actions/publish",
        json={
            "actor": "陈铮",
            "instance": "CN",
            "token": token,
            "self_confirmed": False,
            "opinion": "尝试未经确认发布",
            "config_key": "routing_policy",
        },
    )
    assert r_rej.status_code == 422

    # 4. 五要素齐备执行发布
    r_pub = api_client.post(
        "/v1/config/actions/publish",
        json={
            "actor": "陈铮",
            "instance": "CN",
            "token": token,
            "self_confirmed": True,
            "opinion": "受控发布：上调纸质专票阈值至 0.93",
            "config_key": "routing_policy",
        },
    )
    assert r_pub.status_code == 200
    pub_res = r_pub.json()
    assert pub_res["published"] is True
    new_ver = pub_res["version"]
    assert new_ver != orig_ver
    assert "diff" in pub_res
    assert "blk" in pub_res

    # 5. 读取当前生效策略确认版本递增
    curr_pol = api_client.get("/v1/routing/policy").json()
    assert curr_pol["version"] == new_ver

    # 6. 查看历史版本列表
    r_vers = api_client.get("/v1/routing/policy/versions")
    assert r_vers.status_code == 200
    v_list = [v["version"] for v in r_vers.json()["versions"]]
    assert new_ver in v_list
    assert orig_ver in v_list

    # 7. 受控回滚至原版本
    r_rb_ch = api_client.post(
        "/v1/config/routing_policy/risk-challenge",
        json={"actor": "陈铮", "instance": "CN", "action": "rollback"},
    )
    assert r_rb_ch.status_code == 200
    rb_tok = r_rb_ch.json()["token"]

    r_rb = api_client.post(
        "/v1/config/actions/rollback",
        json={
            "actor": "陈铮",
            "instance": "CN",
            "token": rb_tok,
            "self_confirmed": True,
            "opinion": f"受控回滚至原基准版本 {orig_ver}",
            "config_key": "routing_policy",
            "to_version": orig_ver,
        },
    )
    assert r_rb.status_code == 200
    rb_res = r_rb.json()
    assert rb_res["rolled_back"] is True
    restored_ver = rb_res["version"]

    # 8. 确认生效策略已恢复
    restored_pol = api_client.get("/v1/routing/policy").json()
    assert restored_pol["version"] == restored_ver
    p_rule_restored = next(r for r in restored_pol["rules"] if r.get("route_id") == "cn_vat_paper_recognize")
    assert p_rule_restored["strategies"][0]["threshold"] == 0.88


def test_api_register_provider_lifecycle(api_client):
    """测试新 Provider 注册与生命周期（FN-2-02 Option A 最小实装）。"""
    # 1. 注册新 Provider，非法 capabilities 拒绝 (422)
    bad_pv_req = {
        "provider_id": "test-bad-pv",
        "display_name": "测试无效能力 Provider",
        "capabilities": {"invalid": "shape"},
        "actor": "陈铮",
    }
    r_bad = api_client.post("/v1/providers", json=bad_pv_req)
    assert r_bad.status_code == 422
    assert r_bad.json()["detail"]["error_code"] == "E_SPI_CAPABILITIES_INVALID"

    # 2. 注册合法新 Provider（默认停用，凭证 KMS 掩码）
    reg_req = {
        "provider_id": "custom-vlm-test",
        "display_name": "客户自研测试 VLM",
        "provider_label": "客户已有",
        "type": "OCR / VLM 文档理解",
        "deploy_mode": "私有化自托管（GPU）",
        "compliance_note": "合同含「不留存、不训练」条款 ✓",
        "actor": "陈铮",
        "opinion": "注册用于测试的新 Provider",
    }
    r_reg = api_client.post("/v1/providers", json=reg_req)
    assert r_reg.status_code == 200
    reg_res = r_reg.json()
    assert reg_res["registered"] is True
    assert reg_res["enabled"] is False

    # 3. 在 Provider 列表中能够查到该实例，且默认停用
    r_list = api_client.get("/v1/providers")
    assert r_list.status_code == 200
    p_map = {p["provider_id"]: p for p in r_list.json()["providers"]}
    assert "custom-vlm-test" in p_map
    new_p = p_map["custom-vlm-test"]
    assert new_p["enabled"] is False
    assert new_p["lock"] is False
    assert "KMS 托管" in new_p["credentials"]["kms_key_arn"]

    # 4. 重复注册相同 provider_id 被拒 (409)
    r_dup = api_client.post("/v1/providers", json=reg_req)
    assert r_dup.status_code == 409
    assert r_dup.json()["detail"]["error_code"] == "E_PROVIDER_EXISTS"

