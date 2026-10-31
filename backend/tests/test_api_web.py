# -*- coding: utf-8 -*-
"""web/ 同源静态托管与三页接线标记测试（M2 WP2.3 · P03：单端口免 CORS，demo-mode 回退在位）。"""

WEB_PAGES = ["login.html", "demo-landing.html", "dashboard-overview.html", "case-detail.html",
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
    for js in ("js/auth-guard.js", "js/api-client.js", "js/demo-mode.js"):
        r = client.get(f"/web/{js}")
        assert r.status_code == 200, js
        assert "javascript" in r.headers["content-type"] or "text/plain" in r.headers["content-type"]
    guard = client.get("/web/js/auth-guard.js").text
    assert "/api/platform/auth/session" in guard and "login.html?next=" in guard
    demo = client.get("/web/js/demo-mode.js").text
    assert "/healthz" in demo and "演示模式（未连接后台）" in demo   # 探测与角标口径在位


def test_dashboard_wired_markers(client):
    t = client.get("/web/dashboard-overview.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "IHUB_DEMO.probe" in t                                    # 探测→联动
    assert "/v1/dashboard" in t and "mapApiToPage" in t               # 数据入口=API
    assert "const DATA = {" in t                                      # 内嵌 mock 保留为 fallback


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
    """login 已接入后端认证闭环，页面保持简洁且登录后跳 dashboard。"""
    t = client.get("/web/login.html").text
    for marker in ("dashboard-overview.html", "MFA", "/api/platform/auth/login", "/api/platform/sso/login", "sessionStorage"):
        assert marker in t, marker
    for removed in ("快速选择演示角色", "演示环境", "H39"):
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

    # 3. adapter-management
    t_ad = client.get("/web/adapter-management.html").text
    assert "js/api-client.js" in t_ad and "js/demo-mode.js" in t_ad
    assert "IHUB_DEMO.probe" in t_ad
    assert "/v1/adapters" in t_ad and "/file" in t_ad
    assert "const ADAPTERS = [" in t_ad   # demo mock 保留


def test_outbound_filing_page_wired_markers(client):
    """断言新增出站建档与回写页接线标记在位（Adapter 运行台账 + demo mock 回退）。"""
    t = client.get("/web/outbound-filing.html").text
    assert "js/api-client.js" in t and "js/demo-mode.js" in t
    assert "IHUB_DEMO.probe" in t
    assert "/v1/adapters" in t and "/queue" in t and "/file" in t
    assert "const OUTBOUND_BATCHES = [" in t
    assert "data-k=\"outbound\"" in t and "出站建档与回写" in t


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


def test_case_detail_manual_verify_con13(client):
    """断言 case-detail 按 CON-13 决议实装「人工查验」操作区与留痕。"""
    t = client.get("/web/case-detail.html").text
    assert "CON-13 决议" in t
    assert "openManualVerifyModal" in t
    assert "doManualVerify" in t
    assert "method=manual" in t


