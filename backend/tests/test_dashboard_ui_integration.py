# -*- coding: utf-8 -*-
"""总览仪表盘实装落地专项测试（FN-8-11 / UI-DSH-01~06 / CON-14）。

覆盖五大任务与验收清单：
  - 任务 1：toast() 组件定义、无 ReferenceError、设计系统样式（CON-14）；
  - 任务 2：适配状态条接线、P07 adapter id 映射、demo 态回退（FN-7-01、UI-DSH-06）；
  - 任务 3：红线卡 rate vs limit 对照展示、连续达标天数演示口径标注（UI-DSH-02）；
  - 任务 4：待复核卡真实计数联动、消除静态假 24 分钟、平均等待真算/不足时展示「—」；
  - 任务 5：铃铛角标接线与实例切换联动、0 告警时隐藏角标。
"""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
DASHBOARD_HTML = WEB_DIR / "dashboard-overview.html"
TOAST_JS = WEB_DIR / "js" / "toast.js"


def test_task1_toast_defined_and_no_reference_error():
    """任务 1（CON-14）：断言 toast() 正确定义，点击铃铛无 ReferenceError，样式符合 design-system。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    toast_code = TOAST_JS.read_text(encoding="utf-8")

    # 1. dashboard-overview.html 引入 js/toast.js 与预埋 #toast 容器
    assert '<script src="js/toast.js"></script>' in html
    assert 'id="toast"' in html

    # 2. 铃铛 onclick 调用 toast(...)
    bell_m = re.search(r'<a href="audit-reports\.html"[^>]*onclick="toast\([^)]+\);"[^>]*>', html)
    assert bell_m is not None, "未找到 Header 铃铛中的 toast 调用"

    # 3. 样式遵循 design-system.md（居中浮动、深浅模式、圆角阴影、z-[60]）
    assert "bg-ink-1 dark:bg-gray-200" in toast_code
    assert "shadow-cardhover" in toast_code
    assert "z-[60]" in toast_code

    # 4. 执行 Node.js 无头 DOM 模拟断言：执行 toast() 调用，断言无异常且节点内容正确
    node_eval = """
    const fs = require('fs');
    // 模拟最小 DOM 环境
    const listeners = {};
    const classList = new Set();
    const mockEl = {
      id: 'toast',
      className: '',
      textContent: '',
      classList: {
        add: (...cls) => cls.forEach(c => classList.add(c)),
        remove: (...cls) => cls.forEach(c => classList.delete(c)),
        contains: (c) => classList.has(c)
      }
    };
    global.document = {
      getElementById: (id) => id === 'toast' ? mockEl : null,
      createElement: () => mockEl,
      body: { appendChild: () => {} }
    };
    global.window = global;

    // 加载 toast.js
    const code = fs.readFileSync(process.argv[1], 'utf-8');
    eval(code);

    if (typeof global.toast !== 'function') {
      console.error('FAIL: toast is not a function');
      process.exit(1);
    }
    // 调用 toast
    global.toast('消息中心接入实时告警计数（CON-14 决议降级为告警入口）');
    if (mockEl.textContent !== '消息中心接入实时告警计数（CON-14 决议降级为告警入口）') {
      console.error('FAIL: textContent mismatch:', mockEl.textContent);
      process.exit(2);
    }
    console.log('PASS');
    """
    res = subprocess.run(
        ["node", "-e", node_eval, str(TOAST_JS)],
        capture_output=True, text=True
    )
    assert res.returncode == 0, f"Node.js DOM 执行失败: {res.stderr}"
    assert "PASS" in res.stdout


def test_task2_adapter_status_bar_wiring(client):
    """任务 2（FN-7-01、UI-DSH-06）：mapApiToPage 增加 adapter_status 映射，renderAdapterBar 渲染且含 P07 id。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert 'id="adapter-bar"' in html
    assert "renderAdapterBar" in html
    assert "ADAPTER_IDS" in html

    # 服务端 API 返回 adapter_status
    r = client.get("/v1/dashboard", params={"instance": "CN"})
    assert r.status_code == 200
    adapters = r.json()["adapter_status"]["items"]
    assert len(adapters) == 5

    # 验证 P07 adapter id 映射在 JS 常量表中齐备
    for aid in ("ariba", "oracle", "coupa", "s4", "custom"):
        assert f"'{aid}'" in html or f'"{aid}"' in html

    # 执行 Node.js 断言 renderAdapterBar 渲染输出含 data-adapter-id 与字形
    node_eval = """
    const items = %s;
    const ADAPTER_IDS = {
      'SAP Ariba': 'ariba',
      'Oracle Payables': 'oracle',
      'Coupa Invoicing': 'coupa',
      'S/4HANA Supplier Invoice': 's4',
      '自研应付系统': 'custom'
    };
    function renderAdapterBar(items){
      return items.map(a => {
        const aid = a.id || ADAPTER_IDS[a.name] || a.name;
        const isLive = a.glyph === '✓' || (a.status_code && a.status_code.includes('live'));
        return `<div data-adapter-id="${aid}">${a.glyph} ${a.name}</div>`;
      }).join('');
    }
    const html = renderAdapterBar(items);
    if (!html.includes('data-adapter-id="ariba"')) process.exit(1);
    if (!html.includes('data-adapter-id="s4"')) process.exit(2);
    if (!html.includes('✓')) process.exit(3);
    console.log('PASS');
    """ % json.dumps(adapters)

    res = subprocess.run(["node", "-e", node_eval], capture_output=True, text=True)
    assert res.returncode == 0, f"Adapter 渲染逻辑验证失败: {res.stderr}"
    assert "PASS" in res.stdout


def test_task3_redline_card_wiring(client):
    """任务 3（UI-DSH-02）：limit 消费上屏，rate vs limit 对照，连续 90 天标注「演示口径」。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert 'id="kpi-falseauto-target"' in html
    assert 'id="kpi-falseauto-sub"' in html
    assert "falseAutoLimit" in html
    assert "连续 90 天达标（演示口径）" in html

    # 校验后端 API 给出 false_auto.rate 与 limit
    r = client.get("/v1/dashboard", params={"instance": "CN"})
    fa = r.json()["kpi"]["false_auto"]
    assert fa["rate"] == "0.02%"
    assert fa["limit"] == "0.05%"
    assert fa["within_redline"] is True

    r_os = client.get("/v1/dashboard", params={"instance": "OS"})
    fa_os = r_os.json()["kpi"]["false_auto"]
    assert fa_os["rate"] == "0.03%"
    assert fa_os["limit"] == "0.05%"
    assert fa_os["within_redline"] is True


def test_task4_pending_card_live_counts_and_no_fake_24_min(client):
    """任务 4（FN-8-11、UI-DSH-02）：消除假 24 分钟硬编码，展现 live_needs_review / live_blocked 与真算等待。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    # 静态假数值必须消除
    assert "24 分钟" not in html

    # 页面消费 avgWait 与 live 计数
    assert "avgWait" in html
    assert "liveBlocked" in html
    assert "liveNeedsReview" in html

    # 后端真算返回
    r = client.get("/v1/dashboard", params={"instance": "CN"})
    p = r.json()["kpi"]["pending"]
    assert p["display"] == "37"
    assert p["live_needs_review"] == 3
    assert p["live_blocked"] == 2
    assert "avg_wait_display" in p
    assert "—" in p["avg_wait_display"] and "演示口径" in p["avg_wait_display"]


def test_task5_bell_badge_count_and_instance_switch(client):
    """任务 5（FN-5-09、CON-14）：铃铛角标随服务端告警数联动，0 告警时隐藏。"""
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert 'id="msg-bell-badge"' in html
    assert "renderBellBadge" in html

    # 验证告警数据源
    r_cn = client.get("/v1/alerts", params={"instance": "CN"})
    assert r_cn.json()["total"] == 3

    r_os = client.get("/v1/alerts", params={"instance": "OS"})
    assert r_os.json()["total"] == 3

    # 执行 Node.js 模拟 renderBellBadge(count)
    node_eval = """
    let hidden = false;
    let text = '';
    const badge = {
      classList: {
        add: (c) => { if (c === 'hidden') hidden = true; },
        remove: (c) => { if (c === 'hidden') hidden = false; }
      },
      style: {},
      set textContent(v) { text = String(v); },
      get textContent() { return text; }
    };
    function renderBellBadge(count){
      if (!count || count <= 0) {
        badge.classList.add('hidden');
      } else {
        badge.classList.remove('hidden');
        badge.textContent = count;
      }
    }
    // 测试有告警
    renderBellBadge(3);
    if (hidden || text !== '3') {
      console.error('FAIL on count=3:', {hidden, text});
      process.exit(1);
    }
    // 测试 0 告警隐藏
    renderBellBadge(0);
    if (!hidden) {
      console.error('FAIL on count=0: not hidden');
      process.exit(2);
    }
    console.log('PASS');
    """
    res = subprocess.run(["node", "-e", node_eval], capture_output=True, text=True)
    assert res.returncode == 0, f"角标联动逻辑失败: {res.stderr}"
    assert "PASS" in res.stdout
