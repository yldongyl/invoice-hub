/**
 * invoice-hub 共享轻量 Toast 组件（CON-14）
 *
 * 遵循 design-system：
 * - 居中浮动（bottom-6 left-1/2 -translate-x-1/2）
 * - 深浅色模式切换兼容（bg-ink-1 dark:bg-gray-200 text-white dark:text-ink-1）
 * - 阴影与圆角（rounded-card shadow-cardhover）
 * - 层级安全（z-[60] 高于普通卡片但低于全屏遮罩）
 * - 若页面缺失 #toast DOM 节点，自动创建挂载至 document.body
 */
(function (window) {
  let toastTimer = null;

  function getOrCreateToast() {
    let el = document.getElementById('toast');
    if (!el && document.body) {
      el = document.createElement('div');
      el.id = 'toast';
      el.className = 'toast fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] px-4 py-2.5 rounded-card bg-ink-1 dark:bg-gray-200 text-white dark:text-ink-1 text-[13px] shadow-cardhover opacity-0 pointer-events-none translate-y-2 max-w-[720px] text-center transition-all duration-200';
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(msg, duration) {
    if (!msg) return;
    const el = getOrCreateToast();
    if (!el) return;

    if (typeof msg === 'string' && (msg.includes('<') && msg.includes('>'))) {
      el.innerHTML = msg;
    } else {
      el.textContent = msg;
    }

    el.classList.remove('opacity-0', 'translate-y-2', 'pointer-events-none');

    if (toastTimer) {
      clearTimeout(toastTimer);
    }

    toastTimer = setTimeout(function () {
      el.classList.add('opacity-0', 'translate-y-2', 'pointer-events-none');
    }, duration || 3200);
  }

  window.toast = toast;
})(typeof window !== 'undefined' ? window : this);
