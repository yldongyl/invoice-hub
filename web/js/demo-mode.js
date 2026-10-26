/* invoice-hub web · demo-mode 回退（M2 WP2.3 · ADR-0003/P03：探测 GET /healthz
 * 失败/不可达 → 页面回落内嵌 mock 常量，顶部显示「演示模式（未连接后台）」角标；
 * file:// 双击打开亦直接判定演示态——两种使用形态详见 docs/RUNBOOK.md）。 */
window.IHUB_DEMO = (function () {
  let live = null;                 // null=未探测；true=后台可达；false=演示态

  function probe(timeoutMs) {
    if (window.IHUB_API && IHUB_API.IS_FILE) {
      live = false;
      paint();
      return Promise.resolve(false);
    }
    return IHUB_API.getJSON('/healthz', null, timeoutMs || 1500)
      .then(j => { live = !!(j && j.status === 'ok'); paint(); return live; })
      .catch(() => { live = false; paint(); return false; });
  }

  function isLive() { return live === true; }
  function state() { return live; }

  function paint() {
    document.body && document.body.setAttribute('data-ihub-mode', live ? 'live' : 'demo');
    const old = document.getElementById('ihub-demo-badge');
    if (old) old.remove();
    if (live === false) {
      const el = document.createElement('div');
      el.id = 'ihub-demo-badge';
      el.textContent = '演示模式（未连接后台）· 页面显示内嵌种子数据（L2 演示口径）';
      /* 修复 P09 UI-M2-F01（2026-10-26 用户授权）：原 top:0 居中横条覆盖 header（h-14=56px）
       * 中线，遮挡 dashboard 实例切换按钮，独立演示态真实点击被吞。角标下移至 header 之下、
       * 恢复四边圆角，并加 pointer-events:none——纯展示件不得拦截交互。 */
      el.style.cssText = 'position:fixed;top:60px;left:50%;transform:translateX(-50%);z-index:9999;' +
        'pointer-events:none;background:#FFF7E8;color:#FF7D00;border:1px solid #FF7D00;' +
        'padding:4px 16px;border-radius:8px;font-size:12px;white-space:nowrap;' +
        'box-shadow:0 2px 8px rgba(0,0,0,.08)';
      document.body.appendChild(el);
    }
  }

  return { probe, isLive, state };
})();
