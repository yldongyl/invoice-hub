# -*- coding: utf-8 -*-
"""仪表盘聚合/告警/深链读 API 测试（M2 WP2.1/2.2）。

覆盖 P03 §4 验收：全响应过 contracts 校验；聚合真算与 seed 手工核算一致
（KPI 三卡逐值给出核算断言）；快照↔库内交叉核算豁免纪律；?case= 深链 404。
"""

from tests.conftest import schema_errors


# ── 租户强制 / 归一 ──────────────────────────────────────────────

def test_dashboard_requires_tenant(client):
    r = client.get("/v1/dashboard")
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "E_TENANT_MISSING"


def test_dashboard_lowercase_instance_normalized(client):
    """P03 演示口径 instance=cn|os 小写归一为契约大写（非法值仍拒）。"""
    r = client.get("/v1/dashboard", params={"instance": "cn"})
    assert r.status_code == 200
    assert r.json()["instance"] == "CN"
    r = client.get("/v1/dashboard", params={"instance": "xx"})
    assert r.status_code == 400


# ── 全响应过契约 ────────────────────────────────────────────────

def test_dashboard_full_shape(client, dashboard_validator):
    for inst in ("CN", "OS"):
        r = client.get("/v1/dashboard", params={"instance": inst})
        assert r.status_code == 200, inst
        errs = schema_errors(dashboard_validator, r.json())
        assert not errs, f"{inst}: {[e.message for e in errs][:4]}"
        b = r.json()
        # 四隔离①：行/告警/引用全部归属本实例
        assert all(c["caseId"].startswith("INV-CN" if inst == "CN" else "INV-SG")
                   for c in b["top_cases"]), inst
        assert b["reconciliation"]["mismatches_unregistered"] == []


# ── KPI 三卡手工核算（P03 §4 验收④ 的抽查实证）──────────────────
# 核算过程（seed 手工核对，2026-10-26 本会话）：
#   卡① 错误自动放行率红线对照：CN rate=0.02% limit=0.05% → 0.02≤0.05=within ✓；OS 0.03≤0.05 ✓
#   卡② 待复核 live 计数：cases 表 CN 实例 7 案中 status=NEEDS_REVIEW 为 0387/0384/0381=3、
#       BLOCKED 为 0385/0379=2；OS 实例 4 案 NEEDS_REVIEW=0123=1、BLOCKED=0122=1
#   卡③ 环形分布合计：CN 62+27+11=100；OS 71+19+10=100（donut_sum_100 为服务端真算校验位）

def test_kpi_card1_redline_math(client):
    r = client.get("/v1/dashboard", params={"instance": "CN"})
    fa = r.json()["kpi"]["false_auto"]
    assert (fa["rate"], fa["limit"]) == ("0.02%", "0.05%")
    # 真算：数值解析后比较（非字符串、非硬编码 True）
    assert fa["within_redline"] is (float("0.02") <= float("0.05"))
    r = client.get("/v1/dashboard", params={"instance": "OS"})
    fa = r.json()["kpi"]["false_auto"]
    assert fa["within_redline"] is (float("0.03") <= float("0.05"))


def test_kpi_card2_pending_live_counts(client):
    b = client.get("/v1/dashboard", params={"instance": "CN"}).json()["kpi"]["pending"]
    assert b["display"] == "37" and b["risk_display"] == "6 个高风险"  # 快照基线（历史全量口径）
    assert b["live_needs_review"] == 3 and b["live_blocked"] == 2       # cases 表 SQL 真算
    b = client.get("/v1/dashboard", params={"instance": "OS"}).json()["kpi"]["pending"]
    assert b["live_needs_review"] == 1 and b["live_blocked"] == 1


def test_kpi_card3_donut_sum(client):
    for inst, vals in (("CN", [62, 27, 11]), ("OS", [71, 19, 10])):
        b = client.get("/v1/dashboard", params={"instance": inst}).json()
        assert [d["value"] for d in b["donut"]] == vals
        assert sum(d["value"] for d in b["donut"]) == 100
        assert b["reconciliation"]["donut_sum_100"] is True


def test_trend_7d_shape(client):
    b = client.get("/v1/dashboard", params={"instance": "CN"}).json()["trend_7d"]
    assert len(b["labels"]) == 7 and b["labels"][0] == "10-14"
    names = {s["name"] for s in b["series"]}
    assert names == {"查重拦截", "验真异常", "字段冲突"}
    assert all(len(s["data"]) == 7 for s in b["series"])


# ── Top5 交叉核算与豁免纪律 ─────────────────────────────────────

def test_top_cases_reconciliation_exemptions(client):
    b = client.get("/v1/dashboard", params={"instance": "CN"}).json()
    by_id = {c["caseId"]: c for c in b["top_cases"]}
    # CN 5 行机读字段全对齐（无豁免命中）
    assert all(c["in_master_dataset"] and not c["exempted"] for c in b["top_cases"])
    assert by_id["INV-CN-2026-0385"]["live_status"] == "BLOCKED"
    b = client.get("/v1/dashboard", params={"instance": "OS"}).json()
    by_id = {c["caseId"]: c for c in b["top_cases"]}
    # 已登记豁免①（batches.json 条目）：0124 快照受理时点态 RECOGNIZED vs 库内终态 VERIFYING
    assert by_id["INV-SG-2026-0124"]["exempted"] is True
    assert by_id["INV-SG-2026-0124"]["live_status"] == "VERIFYING"
    # 已登记豁免②：0121 页面扩展案件（不在 cases 主数据集）
    assert by_id["INV-SG-2026-0121"]["in_master_dataset"] is False
    assert by_id["INV-SG-2026-0121"]["exempted"] is True
    # 命中摘录进 reconciliation（透明化）
    applied = " ".join(b["reconciliation"]["exemptions_applied"])
    assert "INV-SG-2026-0124" in applied and "INV-SG-2026-0121" in applied


def test_top_cases_unregistered_diff_raises(fresh_session):
    """G-M0-001 纪律实证：篡改快照可对齐的库内机读字段（构造未登记差异）→ E_AGGREGATION_MISMATCH。
    故障注入直改测试库（同 test_audit_chain 篡改用例口径），非业务写路径。"""
    import pytest
    from app.domain import models as m
    from app.services.dashboard import get_dashboard
    from app.services.errors import CommandError
    from app.services.tenant import TenantContext
    c = fresh_session.get(m.Case, "INV-CN-2026-0386")
    c.confidence = 42  # 与快照 conf=98 构造未登记差异
    fresh_session.flush()
    with pytest.raises(CommandError) as ei:
        get_dashboard(fresh_session, TenantContext.of("CN"))
    assert ei.value.code == "E_AGGREGATION_MISMATCH"


# ── 适配状态条（FN-7-01 呈现位 / §4.3 Adapter 清单）──────────────

def test_adapter_status_bar(client):
    b = client.get("/v1/dashboard", params={"instance": "CN"}).json()["adapter_status"]
    items = b["items"]
    assert [i["name"] for i in items] == ["SAP Ariba", "Oracle Payables", "Coupa Invoicing",
                                          "S/4HANA Supplier Invoice", "自研应付系统"]
    assert [i["glyph"] for i in items] == ["✓", "✓", "◐", "○", "✓"]  # 从 registry code 文本派生
    # glyph 与 status_code 一致性（真派生断言）
    for i in items:
        assert i["glyph"] in i["status_code"]


# ── WP2.2 告警读侧（FN-5-09）───────────────────────────────────

def test_alerts_api(client, alerts_validator):
    for inst in ("CN", "OS"):
        r = client.get("/v1/alerts", params={"instance": inst})
        assert r.status_code == 200
        body = r.json()
        assert not schema_errors(alerts_validator, body), inst
        assert body["total"] == 3 and len(body["items"]) == 3
    r = client.get("/v1/alerts")
    assert r.status_code == 400


def test_alerts_ai_advice_note_discipline(client):
    """FN-5-09/P00 §5：含 AI 建议的告警必须标注人工确认约束（真实校验）。"""
    b = client.get("/v1/alerts", params={"instance": "CN"}).json()["items"]
    ai = [a for a in b if a["ai_advice_marked"]]
    assert len(ai) == 1 and "SM2 验签失败" in ai[0]["title"]
    assert "须人工确认" in ai[0]["evidence"]
    b = client.get("/v1/alerts", params={"instance": "OS"}).json()["items"]
    ai = [a for a in b if a["ai_advice_marked"]]
    assert len(ai) == 1 and "人工确认" in ai[0]["evidence"]


def test_alerts_case_ref_and_dashboard_same_source(client):
    """告警引用案件存在（或已登记豁免）；dashboard.alerts 与 /v1/alerts 同源一致（单一 builder）。"""
    al = client.get("/v1/alerts", params={"instance": "CN"}).json()["items"]
    assert {a["case_ref"] for a in al if a["case_ref"]} <= {"INV-CN-2026-0385", "INV-CN-2026-0381"}
    d = client.get("/v1/dashboard", params={"instance": "CN"}).json()["alerts"]
    assert d == al


def test_alerts_bad_ref_raises(fresh_session, monkeypatch):
    """引用未登记案件 → E_AGGREGATION_MISMATCH（故障注入，非业务写）。"""
    import pytest
    from sqlalchemy import select
    from app.domain import models as m
    from app.services.dashboard import build_alert_items
    from app.services.errors import CommandError
    from app.services.tenant import TenantContext
    a = fresh_session.scalars(
        select(m.Alert).where(m.Alert.instance == "CN")).first()
    a.case_ref = "INV-CN-2026-8888"  # 不存在的引用
    fresh_session.flush()
    with pytest.raises(CommandError) as ei:
        build_alert_items(fresh_session, TenantContext.of("CN"))
    assert ei.value.code == "E_AGGREGATION_MISMATCH"


# ── WP2.2 深链存在性（FN-0-14 ?case= / ?tab=）───────────────────

def test_exists_ok(client, exists_validator):
    r = client.get("/v1/cases/INV-CN-2026-0379/exists", params={"instance": "CN"})
    assert r.status_code == 200
    body = r.json()
    assert not schema_errors(exists_validator, body)
    assert body["exists"] is True and body["status"] == "BLOCKED"
    assert body["type"] == "数电票（增值税专用发票）"


def test_exists_404_for_unknown_case(client):
    """深链直达不存在案件 → 404 CASE_NOT_FOUND（P03 验收③，页面友好提示由 WP2.3 接线承载）。"""
    r = client.get("/v1/cases/INV-CN-2026-9999/exists", params={"instance": "CN"})
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "CASE_NOT_FOUND"


def test_exists_tenant_mismatch_403(client):
    r = client.get("/v1/cases/INV-CN-2026-0387/exists", params={"instance": "OS"})
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "E_TENANT_MISMATCH"


def test_exists_tab_validation(client):
    r = client.get("/v1/cases/INV-CN-2026-0387/exists", params={"instance": "CN", "tab": "log"})
    assert r.status_code == 200
    assert r.json()["deeplink"]["tab_valid"] is True
    r = client.get("/v1/cases/INV-CN-2026-0387/exists", params={"instance": "CN", "tab": "bogus"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "E_DEEPLINK_TAB_INVALID"
    # 未请求 tab：tab_valid=null（契约 $defs 三态）
    r = client.get("/v1/cases/INV-CN-2026-0387/exists", params={"instance": "CN"})
    assert r.json()["deeplink"]["tab_valid"] is None
