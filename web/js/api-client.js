/* invoice-hub web · API 客户端（M2 WP2.3 · P03：fetch 封装——base 同源、错误处理、超时）。
 * 纪律：web 只消费 REST API（依赖纪律③）；file:// 独立演示态直接抛错，由 demo-mode 回退内嵌 mock。 */
window.IHUB_API = (function () {
  const IS_FILE = location.protocol === 'file:';

  function authHeaders(extra) {
    return Object.assign({}, extra || {}, window.IHUB_AUTH ? IHUB_AUTH.authHeaders() : {});
  }

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
      const r = await fetch(url, { signal: ctl.signal, headers: authHeaders({ Accept: 'application/json' }) });
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

  function currentActor(fallback) {
    return window.IHUB_AUTH ? IHUB_AUTH.actor(fallback || '王莉') : (fallback || '王莉');
  }

  function bindActor(body) {
    if (body && Object.prototype.hasOwnProperty.call(body, 'actor')) {
      body = Object.assign({}, body, { actor: currentActor(body.actor) });
    }
    return body;
  }

  /** POST JSON（受控写命令链：risk-challenge → /actions/*；错误同 getJSON 挂 status/code/message_cn）。 */
  async function postJSON(path, body, timeoutMs) {
    if (IS_FILE) {
      const e = new Error('FILE_PROTOCOL：独立演示态（双击打开），不连接后台');
      e.demo = true;
      throw e;
    }
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs || 15000);
    try {
      const r = await fetch(path, {
        method: 'POST', signal: ctl.signal,
        headers: authHeaders({ 'Content-Type': 'application/json', Accept: 'application/json' }),
        body: JSON.stringify(bindActor(body || {})),
      });
      let out = null;
      try { out = await r.json(); } catch (_) { /* 空体 */ }
      if (!r.ok) {
        const e = new Error('HTTP ' + r.status + ' ' + path);
        e.status = r.status;
        const d = out && out.detail;
        e.code = d && (d.error_code || d.code);
        e.message_cn = d && d.message;
        throw e;
      }
      return out;
    } finally { clearTimeout(t); }
  }

  /** POST multipart/form-data（门户上传；FormData 直传） */
  async function postForm(path, formData, timeoutMs) {
    if (IS_FILE) {
      const e = new Error('FILE_PROTOCOL：独立演示态（双击打开），不连接后台');
      e.demo = true;
      throw e;
    }
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs || 30000);
    try {
      const r = await fetch(path, { method: 'POST', signal: ctl.signal, headers: authHeaders(), body: formData });
      let out = null;
      try { out = await r.json(); } catch (_) { /* 空体 */ }
      if (!r.ok) {
        const e = new Error('HTTP ' + r.status + ' ' + path);
        e.status = r.status;
        const d = out && out.detail;
        e.code = d && (d.error_code || d.code);
        e.message_cn = d && d.message;
        e.body = out;
        throw e;
      }
      return out;
    } finally { clearTimeout(t); }
  }

  /** 演示身份（P00 §6：SSO/MFA 演示桩——操作人以参数声明，M5 会话身份替换；与页内权限行文案同源） */
  const ACTOR = {
    get reviewer(){ return currentActor('王莉'); },
    get admin(){ return currentActor('陈铮'); },
    get audit(){ return currentActor('张审计'); },
  };

  return { getJSON, postJSON, postForm, instanceOfCase, currentActor, IS_FILE, ACTOR };
})();
