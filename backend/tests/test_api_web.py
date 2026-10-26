# -*- coding: utf-8 -*-
"""web/ 同源静态托管与三页接线标记测试（M2 WP2.3 · P03：单端口免 CORS，demo-mode 回退在位）。"""

WEB_PAGES = ["login.html", "demo-landing.html", "dashboard-overview.html", "case-detail.html",
             "agent-workbench.html", "invoice-intake.html", "matching-mapping.html",
             "provider-orchestration.html", "adapter-management.html", "audit-reports.html",
             "platform-admin.html", "api-portal.html"]


def test_root_redirects_to_dashboard(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/web/dashboard-overview.html"


def test_all_12_pages_served(client):
    """ui-design 12 页运行副本齐备（P03 WP2.3：保持文件名；接线仅三页，其余保持原型口径）。"""
    for name in WEB_PAGES:
        r = client.get(f"/web/{name}")
        assert r.status_code == 200, name
        assert "text/html" in r.headers["content-type"], name


def test_shared_runtime_scripts_served(client):
    for js in ("js/api-client.js", "js/demo-mode.js"):
        r = client.get(f"/web/{js}")
        assert r.status_code == 200, js
        assert "javascript" in r.headers["content-type"] or "text/plain" in r.headers["content-type"]
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
    assert "M3_GATE" in t                                             # 受控 Action 指向待 M3（用户裁决）
    assert "const CASES = {" in t                                     # 三案 mock 保留为 fallback
    # 原型交互/口径保留：证据弹窗七要素、原件定位、双 Tab
    for marker in ("openEv", "locate(", "switchTab", "ev-locate"):
        assert marker in t, marker


def test_login_demo_stub_unchanged(client):
    """login 演示桩保持全部口径（SSO/租户注记/MFA/H39 推断标注，登录跳 dashboard）。"""
    t = client.get("/web/login.html").text
    for marker in ("dashboard-overview.html", "MFA", "H39"):
        assert marker in t, marker
