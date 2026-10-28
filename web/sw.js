// Reelio shell cache. Fast start: the app files come from this cache and only refresh when a new version is published.
// Your data is never cached here; it always comes fresh from GitHub. BUILD is stamped by the publish workflow.
const BUILD = '__BUILD__';
const V = 'reelio-' + BUILD;
const SHELL = ['app.html', 'style.css', 'icon.svg', 'fonts/figtree-latin-wght-normal.woff2', 'fonts/bricolage-grotesque-latin-wght-normal.woff2', 'app-config.js',
  'js/app.js', 'js/core.js', 'js/i18n.js', 'js/setup.js', 'js/v_home.js', 'js/v_pages.js', 'js/v_queue.js', 'js/links.js', 'js/v_flows.js', 'js/v_accounts.js', 'js/v_more.js', 'js/v_long.js', 'js/v_grab.js', 'js/cookies.js', 'js/palette.js', 'js/heal.js', 'js/login.js'];
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(V).then((c) => Promise.all(SHELL.map((u) => c.add(new Request(u, { cache: 'reload' })).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((x) => x !== V).map((x) => caches.delete(x)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.endsWith('/sw.js')) return;
  // pages: network first (so the site is always current), cached copy only when offline
  if (r.mode === 'navigate') {
    e.respondWith(fetch(r).then((res) => { const copy = res.clone(); caches.open(V).then((c) => c.put(r, copy)); return res; }).catch(() => caches.match(r, { ignoreSearch: true }).then((m) => m || caches.match('app.html'))));
    return;
  }
  // scripts, styles, fonts, images: cache first (instant), saved on first use
  e.respondWith(caches.open(V).then((c) => c.match(r).then((hit) => hit || fetch(r).then((res) => { if (res.ok) c.put(r, res.clone()); return res; }))));
});
