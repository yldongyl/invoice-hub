# -*- coding: utf-8 -*-
"""web/ 同源静态托管与三页接线标记测试（M2 WP2.3 · P03：单端口免 CORS，demo-mode 回退在位）。"""

from sqlalchemy import select
from app.domain import models as m

# demo-landing.html 已移出交付范围（2026-11-15 业务口径），web/ 现存 11 页
WEB_PAGES = ["login.html", "dashboard-overview.html", "case-detail.html",
             "agent-workbench.html", "invoice-intake.html", "matching-mapping.html",
             "provider-orchestration.html", "adapter-management.html", "outbound-filing.html", "audit-reports.html",
             "platform-admin.html", "api-portal.html"]


def test_root_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/web/login.html"


def test_all_web_pages_served(client):
    """web 运行副本齐备（P03 WP2.3：保持文件名；新增运行页按同风格追加）。"""
    for name in WEB_PAGES:
        r = client.get(f"/web/{name}")
        assert r.status_code == 200, name
        assert "text/html" in r.headers["content-type"], name


def test_shared_runtime_scripts_served(client):
    for js in ("js/auth-guard.js", "js/api-client.js", "js/demo-mode.js", "js/toast.js"):
        r = client.get(f"/web/{js}")
        assert r.status_code == 200, js
        assert "javascript" in r.headers["content-type"] or "text/plain" in r.headers["content-type"]
    guard = client.get("/web/js/auth-guard.js").text
    assert "/api/platform/auth/session" in guard and "login.html?next=" in guard
    demo = client.get("/web/js/demo-mode.js").text
    assert "/healthz" in demo and "演示模式（未连接后台）" in demo   # 探测与角标口径在位
    toast_js = client.get("/web/js/toast.js").text
    assert "window.toast" in toast_js and "toastTimer" in toast_js   # 共享轻量 toast 组件在位（CON-14）


def test_dashboard_wired_markers(client):
    t = client.get("/web/dashboard-overview.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t and "js/toast.js" in t
    assert "IHUB_DEMO.probe" in t                                    # 探测→联动
    assert "/v1/dashboard" in t and "mapApiToPage" in t               # 数据入口=API
    assert "const DATA = {" in t                                      # 内嵌 mock 保留为 fallback
    # 任务 1：toast DOM 与铃铛 onclick 无 ReferenceError
    assert 'onclick="toast(' in t and 'id="toast"' in t
    # 任务 2：适配状态条接线与 P07 adapter id 映射
    assert 'id="adapter-bar"' in t and "renderAdapterBar" in t and "ADAPTER_IDS" in t
    # 任务 3：红线卡 limit 对照与 streak 演示口径
    assert 'id="kpi-falseauto-target"' in t and 'id="kpi-falseauto-sub"' in t
    assert "falseAutoLimit" in t and "连续 90 天达标（演示口径）" in t
    # 任务 4：待复核卡消除假 24 分钟硬编码，采用真算与实况注记
    assert "24 分钟" not in t and "avgWait" in t and "liveNeedsReview" in t
    # 任务 5：铃铛角标根据告警数真实联动与 0 隐藏
    assert 'id="msg-bell-badge"' in t and "renderBellBadge" in t


def test_case_detail_wired_markers(client):
    t = client.get("/web/case-detail.html").text
    assert "apiToPageCase" in t and "/v1/cases/" in t                 # view=full 取数 + 契约形态 adapter
    assert "loadCaseAsync" in t and "replaceState" in t               # 深链 ?case= 同步保持
    assert "CASE_NOT_FOUND" in t and "ihub-deeplink-banner" in t      # 不存在案件友好提示
    assert "M3_GATE" not in t                                         # WP3.5 写路径激活，M2 门禁注记退役
    assert "submitControlled" in t and "risk-challenge" in t          # 受控链：challenge→actions 执行
    assert "doUnblock" in t and "co-signers" in t                     # BLOCKED 双人解除（FN-8-06 新增弹窗）
    assert "advice_reject" in t                                       # 不采纳留痕（FN-8-09）
    assert "已写入不可篡改时间线" in t                               # toast 全局口径（P04 §2 WP3.5）
    assert "const CASES = {" in t                                     # 三案 mock 保留为 fallback
    # 原型交互/口径保留：证据弹窗七要素、原件定位、双 Tab
    for marker in ("openEv", "locate(", "switchTab", "ev-locate"):
        assert marker in t, marker


def test_workbench_wired_markers(client):
    t = client.get("/web/agent-workbench.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "wbReload" in t and "/v1/workbench/queue" in t             # 队列归属+待复核数取数
    assert "/v1/cases" in t and "wbMap" in t                          # 四维筛选=服务端参数
    assert "risk-challenge" in t and "batch_release" in t             # 认领/放行经五要素链
    assert "已写入不可篡改案件时间线" in t                          # toast 原型口径保持
    assert "rows_exported" in t and "expires_at" in t                 # 导出限时链接
    assert "const WB = [" in t                                        # 原型 mock 保留为 fallback
    assert "Agent 对话唤起 · 只读定位，未修改任何数据" in t         # Agent 侧（M5）口径零改动


def test_intake_wired_markers(client):
    t = client.get("/web/invoice-intake.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "/v1/intake/kpi" in t and "/v1/intake/channels" in t       # KPI/渠道卡取数
    assert "rules/version" in t and "受理规则版本" in t              # 版本徽章
    assert "intake/upload/risk-challenge" in t and "/v1/intake/upload" in t  # 上传五要素链
    assert "不可篡改审计日志" in t                                   # 完成面板审计口径
    assert "/v1/batches" in t and "resume" in t                       # 批次列表+断点续跑
    assert "fakeSha" in t and "规则引擎确定性判断（非模型推断）" in t  # 原型声明与 fallback 保留


def test_login_backend_auth_wired(client):
    """login 已接入后端认证闭环，全员强制 MFA、受信任设备与 H39/四隔离注记在位。"""
    t = client.get("/web/login.html").text
    for marker in (
        "dashboard-overview.html",
        "MFA",
        "/api/platform/auth/login",
        "/api/platform/sso/login",
        "/api/platform/tenants",
        "loadTenants",
        "sessionStorage",
        "H39",
        "四隔离",
        "全员强制 MFA 校验",
        "受信任 30 天",
        "python scripts/hub.py run",
    ):
        assert marker in t, marker
    for removed in ("快速选择演示角色",):
        assert removed not in t, removed


def test_m4_three_pages_wired_markers(client):
    """断言 M4 三页接线标记在位（provider-orchestration, matching-mapping, adapter-management）。"""
    # 1. provider-orchestration
    t_pv = client.get("/web/provider-orchestration.html").text
    assert "js/api-client.js" in t_pv and "js/demo-mode.js" in t_pv
    assert "IHUB_DEMO.probe" in t_pv
    assert "/v1/providers" in t_pv and "/v1/routing/simulate" in t_pv
    assert "const PROVIDERS = [" in t_pv  # demo mock 保留

    # 2. matching-mapping
    t_mm = client.get("/web/matching-mapping.html").text
    assert "js/api-client.js" in t_mm and "js/demo-mode.js" in t_mm
    assert "IHUB_DEMO.probe" in t_mm
    assert "/v1/matching/queue" in t_mm and "/v1/matching/recommendations" in t_mm
    assert "/v1/matching/links" in t_mm
    assert "const QUEUE = [" in t_mm      # demo mock 保留

    # 3. adapter-management（FN-7 接线与治理）
    t_ad = client.get("/web/adapter-management.html").text
    assert "js/api-client.js" in t_ad and "js/demo-mode.js" in t_ad
    assert "IHUB_DEMO.probe" in t_ad
    assert "/v1/adapters" in t_ad and "/file" in t_ad
    assert "/mapping" in t_ad and "/queue" in t_ad
    assert "/v1/outbound/batches" in t_ad
    assert "const ADAPTERS = [" in t_ad   # demo mock 保留
    # 任务 1：统一 id=s4，淘汰 s4hana
    assert "id:'s4'" in t_ad
    assert "id:'s4hana'" not in t_ad
    # 任务 3：顶部统计卡接线 id
    assert "id=\"kpi-live\"" in t_ad and "id=\"kpi-wip\"" in t_ad
    assert "id=\"kpi-plan\"" in t_ad and "id=\"kpi-month-filing\"" in t_ad
    # 任务 4：生产建档入口消除误读说明与链接
    assert "case-detail.html" in t_ad
    assert "正式建档由案件放行链路自动触发" in t_ad
    # 任务 5：契约治理条与 api-portal 互链
    assert "href=\"api-portal.html\"" in t_ad
    assert "查看 Adapter API 契约文档" in t_ad
    # 任务 6：Ariba 主数据与 PO 订单同步 Job
    assert "PO 与供应商主数据同步" in t_ad
    assert "符合 S5 第 4 条要求" in t_ad
    assert "cached_po_count" in t_ad and "cached_supplier_count" in t_ad


def test_outbound_filing_page_wired_markers(api_client, fresh_session):
    """断言新增出站建档与回写页接线标记在位，并升级为真实行为断言（端点返回结构、KPI 聚合正确性、受控重推五要素反例）。"""
    t = api_client.get("/web/outbound-filing.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "IHUB_DEMO.probe" in t
    assert "/v1/adapters" in t and "/queue" in t and "/file" in t
    assert "/v1/outbound/batches" in t
    assert "const OUTBOUND_BATCHES = [" in t
    assert "data-k=\"outbound\"" in t and "出站建档与回写" in t
    assert "openRepushModal" in t
    assert "submitRepush" in t
    assert "Invoice(Credit Memo)" in t

    # 1. 真实行为断言：GET /v1/outbound/batches 端点结构与 KPI 聚合正确性
    res = api_client.get("/v1/outbound/batches")
    assert res.status_code == 200
    b_data = res.json()
    assert b_data["total"] >= 4
    kpi = b_data["kpi"]
    assert kpi["ok"] >= 31
    assert kpi["bad"] >= 2
    assert "avg_latency_display" in kpi

    # 2. 真实行为断言：GET /v1/outbound/batches/{id} 4 类单据枚举
    res_b = api_client.get("/v1/outbound/batches/OB-20261029-001")
    assert res_b.status_code == 200
    detail = res_b.json()["detail"]
    doc_types = {d["docType"] for d in detail}
    assert {"Invoice(PO)", "Invoice(Contract)", "Invoice(Non-PO)", "Invoice(Credit Memo)"}.issubset(doc_types)

    # 3. 真实行为断言：受控重推五要素反例（复核员无权重推 403、未勾选确认 422）
    rec = fresh_session.scalar(
        select(m.OutboundFilingRecord).where(m.OutboundFilingRecord.case_id == "INV-CN-2026-0381")
    )
    assert rec is not None

    # 反例①：复核员（王莉）发起重推挑战 → 403 权限拒绝
    ch_rev = api_client.post(f"/v1/outbound/records/{rec.id}/risk-challenge", json={"actor": "王莉"})
    assert ch_rev.status_code == 403
    assert "复核员不直接重推出站" in ch_rev.json()["detail"]["message"]

    # 反例②：运营（刘工）签发挑战后，未勾选 self_confirmed 执行重推 → 422 拒绝
    ch_ops = api_client.post(f"/v1/outbound/records/{rec.id}/risk-challenge", json={"actor": "刘工"})
    assert ch_ops.status_code == 200
    token = ch_ops.json()["token"]

    act_no_chk = api_client.post(
        f"/v1/outbound/records/{rec.id}/repush",
        json={"actor": "刘工", "token": token, "self_confirmed": False, "opinion": "重推"},
    )
    assert act_no_chk.status_code == 422
    assert "必须勾选二次确认" in act_no_chk.json()["detail"]["message"]


def test_platform_admin_wired_markers(client):
    """断言 platform-admin 接线标记在位（四 Tab API 取数 + 告警红线拦截 + demo mock 回退）。"""
    t = client.get("/web/platform-admin.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "IHUB_DEMO.probe" in t
    assert "/api/platform/rbac" in t
    assert "/api/platform/alerts/rules" in t
    assert "/api/platform/config" in t
    assert "const ALERT_RULES = [" in t   # demo fallback 保留
    assert "const ROLES = [" in t


def test_audit_reports_wired_markers(client):
    """断言 audit-reports 接线标记在位（三 Tab 深链 ?tab= + 审计检索/导出 + demo mock 回退）。"""
    t = client.get("/web/audit-reports.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "IHUB_DEMO.probe" in t
    assert "/api/audit/logs" in t
    assert "/api/audit/export" in t
    assert "?tab=" in t or "q.get('tab')" in t
    assert "const LOGS = [" in t          # demo fallback 保留


def test_dashboard_message_bell_con14(client):
    """断言 dashboard Header 消息铃铛按 CON-14 决议降级为告警入口并接入计数。"""
    t = client.get("/web/dashboard-overview.html").text
    assert "CON-14 决议" in t
    assert "audit-reports.html" in t
    assert "msg-bell-badge" in t


def test_case_detail_manual_verify_con13(api_client):
    """断言 case-detail 按 CON-13 决议实装「人工查验」操作区与留痕（升级为真实行为断言）。"""
    t = api_client.get("/web/case-detail.html").text
    assert "CON-13 决议" in t
    assert "openManualVerifyModal" in t
    assert "doManualVerify" in t
    assert "submitControlled('manual_verify'" in t
    assert "renderChecks" not in t  # 确保未定义的 renderChecks 已被彻底修复移除

    # 真实行为断言：五要素受控链（challenge → actions）+ checks 落库 + 时间线留痕
    cid = "INV-CN-2026-0387"
    ch_res = api_client.post(f"/v1/cases/{cid}/risk-challenge", json={
        "actor": "王莉",
        "instance": "CN",
        "action": "manual_verify"
    })
    assert ch_res.status_code == 200
    ch_data = ch_res.json()
    assert "token" in ch_data
    assert "risk_text" in ch_data
    assert "authenticity" in ch_data["risk_text"]

    act_res = api_client.post(f"/v1/cases/{cid}/actions/manual_verify", json={
        "actor": "王莉",
        "instance": "CN",
        "token": ch_data["token"],
        "self_confirmed": True,
        "channel": "国家税务总局全国增值税发票查验平台",
        "result": "PASSED",
        "receipt": "manual-rcpt-web-001",
        "note": "税务局手工查验核对通过，截图留存"
    })
    assert act_res.status_code == 200
    res_data = act_res.json()
    assert res_data["manual_verified"] is True
    assert res_data["case"]["checks"]["authenticity"]["result"] == "PASSED"
    assert "method=manual" in res_data["case"]["checks"]["authenticity"]["note"]
    assert "manual-rcpt-web-001" in res_data["case"]["checks"]["authenticity"]["note"]

    # 时间线真实落库断言
    tl_res = api_client.get(f"/v1/cases/{cid}/timeline?instance=CN")
    assert tl_res.status_code == 200
    events = tl_res.json()["items"]
    mv_events = [e for e in events if e.get("act") == "SM2_VERIFY" and e.get("a") == "human"]
    assert len(mv_events) >= 1
    assert "manual-rcpt-web-001" in mv_events[-1].get("x", "")


def test_case_detail_evidence_and_original_endpoints(api_client):
    """断言字段级证据端点与原件查看通道（FN-3-01/02、FN-3-08）。"""
    cid = "INV-CN-2026-0387"
    # 1. 字段级证据端点
    ev_res = api_client.get(f"/v1/cases/{cid}/evidence?field=header.invoice_no&instance=CN")
    assert ev_res.status_code == 200
    ev_data = ev_res.json()
    assert ev_data["field"] == "header.invoice_no"
    assert len(ev_data["items"]) == 1
    assert ev_data["items"][0]["value"] == "24112000000387"

    # 2. 案件切换器端点
    sw_res = api_client.get("/v1/cases?view=switcher&instance=CN")
    assert sw_res.status_code == 200
    sw_items = sw_res.json()["items"]
    assert any(it["caseId"] == cid for it in sw_items)

    # 3. 原件查看端点（FN-3-08 通道）
    orig_res = api_client.get(f"/v1/cases/{cid}/original?instance=CN")
    assert orig_res.status_code == 200
    assert "attachment" in orig_res.headers.get("content-disposition", "") or "inline" in orig_res.headers.get("content-disposition", "")
    assert len(orig_res.content) > 0


