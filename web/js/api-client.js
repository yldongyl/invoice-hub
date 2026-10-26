/* invoice-hub web · API 客户端（M2 WP2.3 · P03：fetch 封装——base 同源、错误处理、超时）。
 * 纪律：web 只消费 REST API（依赖纪律③）；file:// 独立演示态直接抛错，由 demo-mode 回退内嵌 mock。 */
window.IHUB_API = (function () {
  const IS_FILE = location.protocol === 'file:';

  /** GET JSON：params 对象拼 query；AbortController 超时；非 2xx 抛 Error(status/detail)。 */
  async function getJSON(path, params, timeoutMs) {
    if (IS_FILE) {
      const e = new Error('FILE_PROTOCOL：独立演示态（双击打开），不连接后台');
      e.demo = true;
      throw e;
    }
    let url = path;
    if (params) {
      const q = new URLSearchParams(params);
      url = path + '?' + q.toString();
    }
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs || 4000);
    try {
      const r = await fetch(url, { signal: ctl.signal, headers: { Accept: 'application/json' } });
      let body = null;
      try { body = await r.json(); } catch (_) { /* 空体/非 JSON */ }
      if (!r.ok) {
        const e = new Error('HTTP ' + r.status + ' ' + path);
        e.status = r.status;
        e.code = body && body.detail && body.detail.error_code;
        e.message_cn = body && body.detail && body.detail.message;
        throw e;
      }
      return body;
    } finally { clearTimeout(t); }
  }

  /** 案件号 → 实例（CON-04 域段口径，与后端 TenantContext 同源规则） */
  function instanceOfCase(caseId) {
    return caseId && caseId.startsWith('INV-CN') ? 'CN' : 'OS';
  }

  return { getJSON, instanceOfCase, IS_FILE };
})();
