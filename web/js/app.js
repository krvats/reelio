import { $, h, LS, icon, toast, Data, ApiData, GhError, repoInfo, DEFAULT_CONFIG, encryptJson, decryptJson } from './core.js';
import { t } from './i18n.js';

// Hosted (email login) mode is on only when app-config.js has an apiUrl. Demo mode: app.html?demo=1 (sample data, nothing is saved).
export const apiUrl = () => ((window.REELIO_CONFIG || {}).apiUrl || '').replace(/\/$/, '');
const qs = new URLSearchParams(location.search);
try { if (qs.has('demo')) sessionStorage.setItem('reelio.demo', '1'); if (qs.get('demo') === '0') sessionStorage.removeItem('reelio.demo'); } catch {}
export const DEMO = (() => { try { return sessionStorage.getItem('reelio.demo') === '1'; } catch { return qs.has('demo'); } })();

export const S = { data: null, repo: repoInfo(), token: DEMO ? 'demo' : (apiUrl() ? LS.get('apitoken', '') : LS.get('token', '')), pass: DEMO ? 'demo' : LS.get('pass', ''), cfg: null, status: null, tz: 'UTC' };
export const app = { rerender: () => route(true) };

// ---------- shared data helpers
async function ensureData() {
  if (S.data) return S.data;
  if (DEMO) S.data = (await import('./demo.js')).makeDemo();
  else if (apiUrl()) S.data = new ApiData(apiUrl(), S.token);
  else S.data = new Data(S.repo, S.token);
  return S.data;
}
// The last data we saw is kept on this device, so the app paints instantly and refreshes behind the scenes.
const CK = 'core_cache_v1';
const who = () => (DEMO ? 'demo' : (apiUrl() || S.repo.owner) + ':' + String(S.token).slice(-8));
function hydrate() {
  if (DEMO || !S.token) return false;
  const c = LS.get(CK, null);
  if (!c || c.who !== who() || !c.cfg) return false;
  S.cfg = { ...structuredClone(DEFAULT_CONFIG), ...c.cfg }; S.status = c.st || {}; S.tz = S.cfg.timezone || 'UTC'; S.loadedAt = 0; S.cached = true;
  return true;
}
export async function loadCore(force) {
  await ensureData();
  const [cfg, st] = await Promise.all([S.data.read('config.json'), S.data.read('status.json')]);
  S.cfg = cfg ? { ...structuredClone(DEFAULT_CONFIG), ...cfg } : null;
  S.status = st || {};
  S.tz = (S.cfg && S.cfg.timezone) || 'UTC'; S.loadedAt = Date.now(); S.cached = false;
  if (S.cfg && !DEMO) LS.set(CK, { who: who(), cfg, st: S.status, at: S.loadedAt });
}
export async function saveCfg(fn, msg) {
  S.cfg = await S.data.update('config.json', (c) => { const n = { ...structuredClone(DEFAULT_CONFIG), ...c }; return fn(n) || n; }, msg || 'Reelio: settings', DEFAULT_CONFIG);
  S.tz = S.cfg.timezone || 'UTC'; if (!DEMO) LS.set(CK, { who: who(), cfg: S.cfg, st: S.status, at: Date.now() }); return S.cfg;
}
export async function saveSecret(connId, fields) {
  if (S.data.putSecret) return S.data.putSecret(connId, fields);
  await S.data.update('secrets.enc.json', async (blob) => {
    let all = {};
    if (blob && blob.ct) all = await decryptJson(blob, S.pass);
    all[connId] = { ...(all[connId] || {}), ...fields };
    return encryptJson(all, S.pass);
  }, 'Reelio: saved login', {});
}
export async function deleteSecret(connId) {
  if (S.data.deleteSecret) return S.data.deleteSecret(connId);
  await S.data.update('secrets.enc.json', async (blob) => {
    let all = blob && blob.ct ? await decryptJson(blob, S.pass) : {}; delete all[connId]; return encryptJson(all, S.pass);
  }, 'Reelio: removed login', {});
}
export async function readSecret(connId) {
  if (S.data.putSecret) return {};   // hosted: logins never come back to the browser
  const blob = await S.data.read('secrets.enc.json'); if (!blob || !blob.ct) return {};
  return (await decryptJson(blob, S.pass))[connId] || {};
}
export const isConnected = (id) => !!(S.status.accounts && S.status.accounts[id] && S.status.accounts[id].connected);
export function runNow(action = 'run', routeId = '') {
  return S.data.dispatch(action, routeId).then(() => toast(DEMO ? 'Demo: in the real app this starts a check in the cloud.' : 'Started. Results show up here in about a minute.')).catch((e) => toast(e.message, 6000));
}

// ---------- shell + router
const TABS = [['home', 'Home', 'home'], ['pages', 'Pages', 'pages'], ['flows', 'Flows', 'flows'], ['queue', 'Videos', 'queue']];
const MORE = [['accounts', 'Accounts', 'accounts'], ['schedule', 'Schedule', 'schedule'], ['analytics', 'Stats', 'chart'], ['long', 'Long videos', 'queue'], ['grab', 'Save to Drive', 'queue'], ['logs', 'Activity', 'log'], ['settings', 'Settings', 'settings'], ['help', 'Help', 'help']];
const MORE_IDS = [...MORE.map((m) => m[0]), 'more'];
const VIEWS = {
  more: () => import('./v_more.js'), home: () => import('./v_home.js'), queue: () => import('./v_queue.js'), flows: () => import('./v_flows.js'), accounts: () => import('./v_accounts.js'), pages: () => import('./v_pages.js'),
  long: () => import('./v_long.js'), grab: () => import('./v_grab.js'), schedule: () => import('./v_more.js'), analytics: () => import('./v_more.js'), logs: () => import('./v_more.js'), settings: () => import('./v_more.js'), help: () => import('./v_more.js'),
};
let timer = null;

function demoBar() {
  const c = window.REELIO_CONFIG || {};
  return h('div', { class: 'demobar' }, h('span', null, 'Demo with sample data. Nothing here is saved or posted.'),
    h('a', { href: (c.contactUrl || './') + (c.contactUrl ? '' : '#access') }, 'Get access'), h('a', { href: './' }, 'Back to site'));
}
function shell(active, content, animate) {
  const link = ([id, label, ic], cls = '') => h('a', { href: '#/' + id, class: cls, 'aria-current': id === active ? 'page' : null }, icon(ic), t(label));
  const mobileMore = h('a', { href: '#/more', 'aria-current': MORE_IDS.includes(active) ? 'page' : null, class: 'less-only' }, icon('more'), t('More'));
  const el = h('div', { id: 'app' },
    h('nav', { class: 'tabs', 'aria-label': 'Main' },
      h('div', { class: 'brand' }, logo('logo'), 'Reelio'),
      TABS.map((x) => link(x)), MORE.map((x) => link(x, 'more-only')), mobileMore),
    h('main', { id: 'main', class: animate ? 'view-in' : null }, content));
  if (!DEMO) return el;
  const w = h('div', null, demoBar(), el); return w;
}
export function logo(cls = 'logo') {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 64 64'); s.setAttribute('class', cls); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = '<rect width="64" height="64" rx="14" fill="#0c2a33"/><circle cx="32" cy="32" r="17" fill="none" stroke="#fff" stroke-width="4"/><circle cx="32" cy="32" r="4" fill="#fff"/><circle cx="32" cy="21" r="3.2" fill="#fff"/><circle cx="32" cy="43" r="3.2" fill="#fff"/><circle cx="21" cy="32" r="3.2" fill="#fff"/><circle cx="43" cy="32" r="3.2" fill="#e5352b"/>';
  return s;
}

let navId = 0, lastPage = null;
function busy(on) { let b = document.getElementById('navbar'); if (!b) { b = h('div', { id: 'navbar' }); document.body.append(b); } b.className = on ? 'on' : ''; }
function updateCard() {
  return h('div', { class: 'card col' }, h('h2', null, 'Reelio just updated'), h('p', { class: 'muted' }, 'This page is running an older copy. One tap loads the new one.'),
    h('button', { class: 'btn primary', onclick: async () => { try { for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister(); for (const k of await caches.keys()) await caches.delete(k); } catch (e) {} location.reload(); } }, 'Load the new version'));
}

// force = refetch data from GitHub even if it was loaded a moment ago. Only the newest navigation may draw (older ones drop out), so a slow tab can never overwrite a newer one.
export async function route(force) {
  clearTimeout(timer);
  const my = ++navId, stale = () => my !== navId;
  const root = $('#root');
  const hash = location.hash.replace(/^#\/?/, '') || 'home';
  const [page, ...params] = hash.split('/');
  busy(true);
  try {
    const needLogin = apiUrl() ? !S.token : (!S.token || !S.pass);
    if (!DEMO && (needLogin || page === 'setup')) {
      const m = await import(apiUrl() ? './login.js' : './setup.js'); if (!stale()) root.replaceChildren(await m.render(S, app)); return;
    }
    if (!S.cfg) hydrate();
    await ensureData();
    const fresh = S.cfg && !force && Date.now() - (S.loadedAt || 0) < 8000;
    const wasCached = !!S.cached;
    try {
      if (!S.cfg) await loadCore();
      else if (wasCached) {
        // painted from the saved copy; fetch the real data now and redraw Home only if something changed
        const before = JSON.stringify([S.cfg, S.status]);
        loadCore().then(() => { if (!stale() && page === 'home' && JSON.stringify([S.cfg, S.status]) !== before) route(false); }, (e) => { if (e && e.status === 401) toast(e.message, 8000); });
      }
      else if (page === 'home' && !fresh) await loadCore();
      else if (!fresh) loadCore().then(() => {}, () => {});
    } catch (e) {
      if (stale()) return;
      root.replaceChildren(shell('home', h('div', { class: 'card' }, h('h2', null, 'Cannot open your data'), h('p', null, e.message), h('a', { class: 'btn primary', href: '#/setup' }, 'Open setup')))); return;
    }
    if (stale()) return;
    if (!S.cfg) { const m = await import('./setup.js'); if (!stale()) root.replaceChildren(await m.render(S, app)); return; }
    document.documentElement.style.setProperty('--fs', (LS.get('fs', 17)) + 'px');
    const known = !!VIEWS[page], animate = page !== lastPage;
    let mod;
    try { mod = await (VIEWS[page] || VIEWS.home)(); }
    catch (e) { if (!stale()) root.replaceChildren(shell(known ? page : 'home', updateCard(), true)); return; }
    if (stale()) return;
    const view = mod[page === 'more' ? 'more' : page] || mod.home;
    let node;
    try { node = await view(S, params, app); }
    catch (e) { node = h('div', { class: 'card' }, h('h2', null, 'Something went wrong'), h('p', null, e.message || String(e)), h('button', { class: 'btn', onclick: () => route(true) }, 'Try again')); }
    if (stale()) return;
    lastPage = page;
    root.replaceChildren(shell(known ? page : 'home', node, animate));
    if (animate) window.scrollTo(0, 0);
    if (mod.refresh && page === 'home') timer = setTimeout(() => { if (!document.hidden) route(true); else timer = setTimeout(() => route(true), 30000); }, mod.refresh);
  } finally { if (!stale()) busy(false); }
}
// load every screen quietly in the background so switching tabs is instant (skipped on data-saver and slow links)
const conn = navigator.connection || {};
if (!conn.saveData && !/2g/.test(conn.effectiveType || '')) (window.requestIdleCallback || ((f) => setTimeout(f, 2500)))(() => [...new Set(Object.values(VIEWS))].forEach((v) => v().catch(() => {})), { timeout: 4000 });
// tapping the tab you are already on used to do nothing (the address does not change); now it refreshes
document.addEventListener('click', (e) => { const a = e.target.closest && e.target.closest('a[href^="#/"]'); if (a && a.getAttribute('href') === location.hash) route(true); });

function accent() { const a = LS.get('accent', 'teal'); if (a === 'teal') delete document.documentElement.dataset.accent; else document.documentElement.dataset.accent = a; }
accent();
function theme() { const t = LS.get('theme', 'auto'); if (t !== 'auto') document.documentElement.dataset.theme = t; }
theme();
window.addEventListener('hashchange', () => route());
document.addEventListener('visibilitychange', () => { if (!document.hidden && /home|^$/.test(location.hash.replace('#/', ''))) route(true); });
if ('serviceWorker' in navigator && !DEMO) {
  const had = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register('sw.js').catch(() => {});
  let told = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!had || told) return; told = true;
    const bar = h('div', { class: 'toast', role: 'status', style: 'display:flex;gap:12px;align-items:center' }, 'Reelio has an update.', h('button', { class: 'btn small primary', onclick: () => location.reload() }, 'Reload'));
    document.body.append(bar);
  });
}
const done = () => { try { const sp = document.getElementById('splash'); if (sp) sp.remove(); } catch {} };
if (qs.get('code') || qs.get('error')) import('./v_accounts.js').then((m) => m.handleOAuth()).finally(() => route().finally(done)); else route().finally(done);
// Command palette (Ctrl/Cmd+K or "/") and self-heal start quietly after the first screen.
setTimeout(() => import('./palette.js').catch(() => {}), 1500);
if (!DEMO) setTimeout(() => import('./heal.js').then((m) => m.startHeal(S)).catch(() => {}), 5000);
