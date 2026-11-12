(() => {
  const body = document.body;
  const locale = (body?.dataset?.locale || 'en').toLowerCase();
  const statusEl = document.getElementById('fcp-auth-status');
  const homeBtn = document.getElementById('fcp-go-home');
  const closeBtn = document.getElementById('fcp-close-portal');
  const loginBtn = document.getElementById('fcp-login-action');

  const labels = {
    en: { authed: 'Authenticated Workspace', guest: 'Guest Preview Mode' },
    ja: { authed: '認証済みワークスペース', guest: 'ゲストプレビュー' },
    ko: { authed: '인증된 워크스페이스', guest: '게스트 미리보기' },
  }[locale] || { authed: 'Authenticated Workspace', guest: 'Guest Preview Mode' };

  const expectedOrigin = window.location?.origin || '';

  window.addEventListener('message', (event) => {
    if (expectedOrigin && event?.origin !== expectedOrigin) return;
    if (window.parent && event?.source !== window.parent) return;
    const data = event?.data;
    if (!data || typeof data !== 'object') return;
    if (data.type === 'fcp-auth-state' && statusEl) {
      statusEl.textContent = data.authenticated
        ? `${labels.authed} (${data.actor || 'member'})`
        : labels.guest;
    }
  });

  const postToParent = (payload) => {
    if (!expectedOrigin) return;
    window.parent?.postMessage(payload, expectedOrigin);
  };

  homeBtn?.addEventListener('click', () => {
    postToParent({ type: 'fcp-navigate-home', locale });
  });
  closeBtn?.addEventListener('click', () => {
    postToParent({ type: 'fcp-close-home', locale });
  });
  loginBtn?.addEventListener('click', () => {
    postToParent({ type: 'fcp-action', action: 'login', locale });
  });

  postToParent({ type: 'fcp-request-auth', locale });
})();
