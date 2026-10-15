import { $, h, LS, icon, toast, Data, GhError, repoInfo, DEFAULT_CONFIG, encryptJson, decryptJson } from './core.js';

export const S = { data: null, repo: repoInfo(), token: LS.get('token', ''), pass: LS.get('pass', ''), cfg: null, status: null, tz: 'UTC' };
export const app = { rerender: () => route(true) };

// ---------- shared data helpers
export async function loadCore(force) {
  if (!S.data) S.data = new Data(S.repo, S.token);
  const [cfg, st] = await Promise.all([S.data.read('config.json'), S.data.read('status.json')]);
  S.cfg = cfg ? { ...structuredClone(DEFAULT_CONFIG), ...cfg } : null;
  S.status = st || {};
  S.tz = (S.cfg && S.cfg.timezone) || 'UTC'; S.loadedAt = Date.now();
}
export async function saveCfg(fn, msg) {
  S.cfg = await S.data.update('config.json', (c) => { const n = { ...structuredClone(DEFAULT_CONFIG), ...c }; return fn(n) || n; }, msg || 'Reelio: settings', DEFAULT_CONFIG);
  S.tz = S.cfg.timezone || 'UTC'; return S.cfg;
}
export async function saveSecret(connId, fields) {
  await S.data.update('secrets.enc.json', async (blob) => {
    let all = {};
    if (blob && blob.ct) all = await decryptJson(blob, S.pass);
    all[connId] = { ...(all[connId] || {}), ...fields };
    return encryptJson(all, S.pass);
  }, 'Reelio: saved login', {});
}
export async function deleteSecret(connId) {
  await S.data.update('secrets.enc.json', async (blob) => {
    let all = blob && blob.ct ? await decryptJson(blob, S.pass) : {}; delete all[connId]; return encryptJson(all, S.pass);
  }, 'Reelio: removed login', {});
}
export async function readSecret(connId) {
  const blob = await S.data.read('secrets.enc.json'); if (!blob || !blob.ct) return {};
  return (await decryptJson(blob, S.pass))[connId] || {};
}
export const isConnected = (id) => !!(S.status.accounts && S.status.accounts[id] && S.status.accounts[id].connected);
export function runNow(action = 'run', routeId = '') {
  return S.data.dispatch(action, routeId).then(() => toast('Started. Results show up here in about a minute.')).catch((e) => toast(e.message, 6000));
}

// ---------- shell + router
const TABS = [['home', 'Home', 'home'], ['queue', 'Videos', 'queue'], ['flows', 'Flows', 'flows'], ['accounts', 'Accounts', 'accounts']];
const MORE = [['schedule', 'Schedule', 'schedule'], ['analytics', 'Stats', 'chart'], ['long', 'Long videos', 'queue'], ['logs', 'Activity', 'log'], ['settings', 'Settings', 'settings'], ['help', 'Help', 'help']];
const VIEWS = {
  more: () => import('./v_more.js'), home: () => import('./v_home.js'), queue: () => import('./v_queue.js'), flows: () => import('./v_flows.js'), accounts: () => import('./v_accounts.js'),
  long: () => import('./v_long.js'), schedule: () => import('./v_more.js'), analytics: () => import('./v_more.js'), logs: () => import('./v_more.js'), settings: () => import('./v_more.js'), help: () => import('./v_more.js'),
};
let timer = null;

function shell(active, content, animate) {
  const link = ([id, label, ic], cls = '') => h('a', { href: '#/' + id, class: cls, 'aria-current': id === active ? 'page' : null }, icon(ic), label);
  const mobileMore = h('a', { href: '#/more', 'aria-current': ['schedule', 'analytics', 'long', 'logs', 'settings', 'help', 'more'].includes(active) ? 'page' : null, class: 'less-only' }, icon('more'), 'More');
  return h('div', { id: 'app' },
    h('nav', { class: 'tabs', 'aria-label': 'Main' },
      h('div', { class: 'brand' }, logo('logo'), 'Reelio'),
      TABS.map((t) => link(t)), MORE.map((t) => link(t, 'more-only')), mobileMore),
    h('main', { id: 'main', class: animate ? 'view-in' : null }, content));
}
export function logo(cls = 'logo') {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 64 64'); s.setAttribute('class', cls); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = '<rect width="64" height="64" rx="16" fill="#5a4bff"/><circle cx="32" cy="32" r="17" fill="none" stroke="#fff" stroke-width="4"/><circle cx="32" cy="32" r="4" fill="#fff"/><circle cx="32" cy="21" r="3.2" fill="#fff"/><circle cx="32" cy="43" r="3.2" fill="#fff"/><circle cx="21" cy="32" r="3.2" fill="#fff"/><circle cx="43" cy="32" r="3.2" fill="#fff"/>';
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
    if (!S.token || !S.pass || page === 'setup') { const m = await import('./setup.js'); if (!stale()) root.replaceChildren(await m.render(S, app)); return; }
    const fresh = S.cfg && !force && Date.now() - (S.loadedAt || 0) < 8000;
    try {
      if (!S.cfg || (page === 'home' && !fresh)) await loadCore();
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
// load every screen quietly in the background so switching tabs is instant
(window.requestIdleCallback || ((f) => setTimeout(f, 1500)))(() => Object.values(VIEWS).forEach((v) => v().catch(() => {})));
// tapping the tab you are already on used to do nothing (the address does not change); now it refreshes
document.addEventListener('click', (e) => { const a = e.target.closest && e.target.closest('a[href^="#/"]'); if (a && a.getAttribute('href') === location.hash) route(true); });

function accent() { const a = LS.get('accent', 'violet'); if (a === 'violet') delete document.documentElement.dataset.accent; else document.documentElement.dataset.accent = a; }
accent();
function theme() { const t = LS.get('theme', 'auto'); if (t !== 'auto') document.documentElement.dataset.theme = t; }
theme();
window.addEventListener('hashchange', () => route());
document.addEventListener('visibilitychange', () => { if (!document.hidden && /home|^$/.test(location.hash.replace('#/', ''))) route(true); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
if (new URLSearchParams(location.search).get('code') || new URLSearchParams(location.search).get('error')) import('./v_accounts.js').then((m) => m.handleOAuth()).finally(route); else route();
// Self-heal (added): starts a missed worker run when GitHub's schedule was late. Failure-proof, never blocks the app.
setTimeout(() => import('./heal.js').then((m) => m.startHeal(S)).catch(() => {}), 5000);
