/* invoice-hub web · 登录态守卫（FN-9-04：登录会话 + MFA 演示闭环）。
 * live backend 可达时强制业务页先登录；file:// 或独立静态 http.server 演示态不拦截，继续交给 demo-mode 回退。 */
window.IHUB_AUTH = (function () {
  const KEY = 'ihub.auth';
  const IS_FILE = location.protocol === 'file:';
  const page = (location.pathname.split('/').pop() || 'dashboard-overview.html').toLowerCase();
  const PUBLIC = new Set(['login.html', 'demo-landing.html']);

  function get() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); }
    catch (_) { return null; }
  }
  function save(s) { sessionStorage.setItem(KEY, JSON.stringify(s)); }
  function token() { const s = get(); return s && s.session_token; }
  function authHeaders() { const t = token(); return t ? { Authorization: 'Bearer ' + t } : {}; }
  function nextParam() {
    return encodeURIComponent(location.pathname.split('/').pop() + location.search + location.hash);
  }
  function redirectLogin() {
    if (PUBLIC.has(page)) return;
    location.href = 'login.html?next=' + nextParam();
  }
  async function backendLive() {
    if (IS_FILE) return false;
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 900);
    try {
      const r = await fetch('/healthz', { signal: ctl.signal, headers: { Accept: 'application/json' } });
      if (!r.ok) return false;
      const j = await r.json();
      return j && j.status === 'ok';
    } catch (_) { return false; }
    finally { clearTimeout(t); }
  }
  async function requireSession() {
    if (PUBLIC.has(page) || IS_FILE) return null;
    const live = await backendLive();
    if (!live) return null; // 独立静态演示态：不强制登录，允许 demo-mode 渲染内嵌 mock
    if (!token()) { redirectLogin(); return null; }
    try {
      const r = await fetch('/api/platform/auth/session', { headers: { Accept: 'application/json', ...authHeaders() } });
      const body = await r.json().catch(() => null);
      if (!r.ok) throw body;
      save(body);
      return body;
    } catch (_) {
      sessionStorage.removeItem(KEY);
      redirectLogin();
      return null;
    }
  }
  async function logout() {
    try { await fetch('/api/platform/auth/logout', { method: 'POST', headers: { ...authHeaders() } }); }
    catch (_) { /* logout 本地兜底 */ }
    sessionStorage.removeItem(KEY);
    location.href = 'login.html';
  }
  function actor(defaultName) {
    const s = get();
    return (s && s.user && s.user.name) || defaultName || '王莉';
  }
  function role() {
    const s = get();
    return (s && s.user && s.user.role) || '';
  }
  function roleKey() {
    const r = role();
    if (r.includes('管理员')) return 'admin';
    if (r.includes('运营')) return 'ops';
    if (r.includes('审计')) return 'audit';
    if (r.includes('复核员')) return 'reviewer';
    return 'guest';
  }
  const NAV_POLICY = {
    dashboard: ['admin','ops','audit','reviewer'],
    workbench: ['admin','reviewer'],
    matching: ['admin','reviewer'],
    audit: ['admin','audit','reviewer'],
    intake: ['admin','ops'],
    provider: ['admin','ops'],
    adapter: ['admin','ops'],
    outbound: ['admin','ops'],
    admin: ['admin'],
    api: ['admin'],
  };
  function applyNavigationPolicy() {
    const key = roleKey();
    document.querySelectorAll('#sb a[data-k]').forEach(a => {
      const k = a.getAttribute('data-k');
      const allowed = !NAV_POLICY[k] || NAV_POLICY[k].includes(key);
      if (!allowed) {
        a.style.display = 'none';
        a.setAttribute('aria-hidden', 'true');
      } else {
        a.style.display = '';
        a.removeAttribute('aria-hidden');
      }
    });
    // 二次收敛分组标题：必须等组内所有 a[data-k] 都完成显示/隐藏后再判断，避免空组残留。
    document.querySelectorAll('#sb .sb-group').forEach(group => {
      let n = group.nextElementSibling, visible = false;
      while (n && !(n.classList && n.classList.contains('sb-group'))) {
        if (n.matches && n.matches('a[data-k]') && n.style.display !== 'none') visible = true;
        n = n.nextElementSibling;
      }
      group.style.display = visible ? '' : 'none';
    });
  }
  function initUserMenu() {
    const s = get();
    if (!s || PUBLIC.has(page)) return;
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', initUserMenu, { once: true });
      return;
    }
    applyNavigationPolicy();
    const userHtml = `<span style="width:24px;height:24px;border-radius:999px;background:#165DFF;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11px;flex-shrink:0" data-auth-avatar>${s.user.name.slice(0,2)}</span><span><b data-auth-name>${s.user.name}</b> · <span data-auth-role>${s.user.role}</span></span><button type="button" onclick="IHUB_AUTH.logout()" style="border:1px solid #F53F3F;color:#F53F3F;background:#fff;border-radius:6px;padding:3px 8px;font-weight:600;cursor:pointer;flex-shrink:0">退出</button>`;
    document.querySelectorAll('[data-auth-name]').forEach(el => { el.textContent = s.user.name; });
    document.querySelectorAll('[data-auth-role]').forEach(el => { el.textContent = s.user.role; });
    document.querySelectorAll('[data-auth-avatar]').forEach(el => { el.textContent = s.user.name.slice(0, 2); });
    const staticUsers = Array.from(document.querySelectorAll('.ihub-static-user'));
    staticUsers.forEach(el => {
      el.id = el.id || 'ihub-auth-inline';
      el.style.cssText = 'display:flex;align-items:center;gap:8px;height:36px;padding:0 8px 0 6px;border:1px solid #BEDAFF;border-radius:8px;background:#F0F5FF;color:#165DFF;font-size:12px;white-space:nowrap;box-shadow:0 1px 4px rgba(22,93,255,.12);flex-shrink:0';
      el.innerHTML = userHtml;
    });
    if (!staticUsers.length && !document.getElementById('ihub-auth-pill')) {
      const pill = document.createElement('div');
      pill.id = 'ihub-auth-pill';
      pill.setAttribute('role', 'navigation');
      pill.setAttribute('aria-label', '当前登录用户与退出登录');
      pill.style.cssText = 'display:flex;align-items:center;gap:8px;height:36px;padding:0 8px 0 6px;border:1px solid #BEDAFF;border-radius:8px;background:#F0F5FF;color:#165DFF;font-size:12px;white-space:nowrap;box-shadow:0 1px 4px rgba(22,93,255,.12);flex-shrink:0';
      pill.innerHTML = userHtml;
      const header = document.querySelector('header');
      const right = header && (header.querySelector(':scope > div:last-child') || header);
      if (right) right.appendChild(pill);
      else document.body.appendChild(pill);
    }
    document.querySelectorAll('[data-perm]').forEach(el => {
      const perm = el.getAttribute('data-perm');
      const allowed = !perm || (perm === 'admin' ? role().includes('管理员') : true);
      if (!allowed) {
        el.classList.add('opacity-50', 'pointer-events-none');
        el.setAttribute('title', '当前角色无此操作权限');
      }
    });
  }

  if (!PUBLIC.has(page)) requireSession().then(initUserMenu);
  return { get, save, token, authHeaders, requireSession, logout, actor, role, roleKey, initUserMenu, applyNavigationPolicy };
})();
