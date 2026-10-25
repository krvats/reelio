// Keeps the app shell available offline. Data always comes fresh from GitHub, never from this cache.
const V = 'reelio-v4';
const SHELL = ['./', 'index.html', 'style.css', 'icon.svg', 'js/app.js', 'js/core.js', 'js/setup.js', 'js/v_home.js', 'js/v_queue.js', 'js/links.js', 'js/v_flows.js', 'js/v_accounts.js', 'js/v_more.js', 'js/v_long.js', 'js/v_grab.js', 'js/cookies.js'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((x) => x !== V).map((x) => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); caches.open(V).then((c) => c.put(e.request, copy)); return r; }).catch(() => caches.match(e.request)));
});
