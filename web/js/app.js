import { t } from './i18n.js';
import { licenseOn, entitlement } from './license.js';
import { $, h, LS, icon, toast, Data, ApiData, GhError, repoInfo, DEFAULT_CONFIG, encryptJson, decryptJson } from './core.js';

export const apiUrl = () => (window.REELIO_CONFIG || {}).apiUrl || '';
export const S = { ent: null, data: null, repo: repoInfo(), token: apiUrl() ? LS.get('apitoken', '') : LS.get('token', ''), pass: apiUrl() ? 'api' : LS.get('pass', ''), cfg: null, status: null, tz: 'UTC' };
export const app = { rerender: () => route() };

// ---------- shared data helpers
export async function loadCore(force) {
  if (!S.data) S.data = apiUrl() ? new ApiData(apiUrl(), S.token) : new Data(S.repo, S.token);
  const [cfg, st] = await Promise.all([S.data.read('config.json'), S.data.read('status.json')]);
  S.cfg = cfg ? { ...structuredClone(DEFAULT_CONFIG), ...cfg } : null;
  S.status = st || {};
  S.tz = (S.cfg && S.cfg.timezone) || 'UTC';
}
export async function saveCfg(fn, msg) {
  S.cfg = await S.data.update('config.json', (c) => { const n = { ...structuredClone(DEFAULT_CONFIG), ...c }; return fn(n) || n; }, msg || 'Reelio: settings', DEFAULT_CONFIG);
  S.tz = S.cfg.timezone || 'UTC'; return S.cfg;
}
export async function saveSecret(connId, fields) {
  if (apiUrl()) return S.data.putSecret(connId, fields);
  await S.data.update('secrets.enc.json', async (blob) => {
    let all = {};
    if (blob && blob.ct) all = await decryptJson(blob, S.pass);
    all[connId] = { ...(all[connId] || {}), ...fields };
    return encryptJson(all, S.pass);
  }, 'Reelio: saved login', {});
}
export async function deleteSecret(connId) {
  if (apiUrl()) return S.data.deleteSecret(connId);
  await S.data.update('secrets.enc.json', async (blob) => {
    let all = blob && blob.ct ? await decryptJson(blob, S.pass) : {}; delete all[connId]; return encryptJson(all, S.pass);
  }, 'Reelio: removed login', {});
}
export async function readSecret(connId) {
  if (apiUrl()) return {};      // hosted mode: logins are write-only for safety
  const blob = await S.data.read('secrets.enc.json'); if (!blob || !blob.ct) return {};
  return (await decryptJson(blob, S.pass))[connId] || {};
}
export const isConnected = (id) => !!(S.status.accounts && S.status.accounts[id] && S.status.accounts[id].connected);
export function runNow(action = 'run', routeId = '') {
  return S.data.dispatch(action, routeId).then(() => toast('Started. Results show up here in about a minute.')).catch((e) => toast(e.message, 6000));
}

// ---------- shell + router
const TABS = [['home', 'Home', 'home'], ['pages', 'Pages', 'pages'], ['flows', 'Flows', 'flows'], ['queue', 'Videos', 'queue']];
const MORE = [['accounts', 'Accounts', 'accounts'], ['schedule', 'Schedule', 'schedule'], ['analytics', 'Stats', 'chart'], ['logs', 'Activity', 'log'], ['settings', 'Settings', 'settings'], ['help', 'Help', 'help']];
const VIEWS = {
  more: () => import('./v_more.js'), home: () => import('./v_home.js'), queue: () => import('./v_queue.js'), flows: () => import('./v_flows.js'), accounts: () => import('./v_accounts.js'), pages: () => import('./v_pages.js'),
  schedule: () => import('./v_more.js'), analytics: () => import('./v_more.js'), logs: () => import('./v_more.js'), settings: () => import('./v_more.js'), help: () => import('./v_more.js'),
};
let timer = null;
/** Hand the signed token to the worker (through the private data repo) so posting also stops when the plan ends. */
async function pushLicense() {
  try { if (!S.ent || !S.ent.token || !S.data) return; if (LS.get('ent_pushed') === S.ent.token) return;
    if (apiUrl()) { await S.data.req('POST', '/v1/plan/sync', { token: S.ent.token }).catch(() => {}); LS.set('ent_pushed', S.ent.token); return; }
    await S.data.update('license.json', () => ({ token: S.ent.token, updated: new Date().toISOString() }), 'Reelio: plan updated', {}); LS.set('ent_pushed', S.ent.token); } catch {}
}

function shell(active, content) {
  const link = ([id, label, ic], cls = '') => h('a', { href: '#/' + id, class: cls, 'aria-current': id === active ? 'page' : null }, icon(ic), t(label));
  const mobileMore = h('a', { href: '#/more', 'aria-current': ['accounts', 'schedule', 'analytics', 'logs', 'settings', 'help', 'more'].includes(active) ? 'page' : null, class: 'less-only' }, icon('more'), t('More'));
  return h('div', { id: 'app' },
    h('nav', { class: 'tabs', 'aria-label': 'Main' },
      h('div', { class: 'brand' }, logo('logo'), 'Reelio'),
      TABS.map((t) => link(t)), MORE.map((t) => link(t, 'more-only')), mobileMore),
    h('main', { id: 'main' }, content));
}
export function logo(cls = 'logo') {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 64 64'); s.setAttribute('class', cls); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = '<rect width="64" height="64" rx="16" fill="#5a4bff"/><circle cx="32" cy="32" r="17" fill="none" stroke="#fff" stroke-width="4"/><circle cx="32" cy="32" r="4" fill="#fff"/><circle cx="32" cy="21" r="3.2" fill="#fff"/><circle cx="32" cy="43" r="3.2" fill="#fff"/><circle cx="21" cy="32" r="3.2" fill="#fff"/><circle cx="43" cy="32" r="3.2" fill="#fff"/>';
  return s;
}

export async function route() {
  clearTimeout(timer);
  const root = $('#root');
  const hash = location.hash.replace(/^#\/?/, '') || 'home';
  const [page, ...params] = hash.split('/');
  if (apiUrl() && !S.token) { const m = await import('./login.js'); root.replaceChildren(await m.render(S, app)); return; }
  if (!S.token || !S.pass || page === 'setup') {
    const m = await import('./setup.js'); root.replaceChildren(await m.render(S, app)); return;
  }
  if (licenseOn() && !(S.ent && S.ent.active)) {
    S.ent = await entitlement();
    if (!S.ent.active) { const pw = await import('./v_paywall.js'); root.replaceChildren(await pw.paywall(S.ent, (e) => { S.ent = e; route(); })); return; }
    pushLicense();
  }
  if (!$('#app')) root.replaceChildren(h('div', { class: 'skel', 'aria-label': 'Loading' }, h('i'), h('i'), h('i')));
  try {
    if (!S.cfg || page === 'home') await loadCore();
    else loadCore().then(() => {}, () => {});
  } catch (e) {
    root.replaceChildren(shell('home', h('div', { class: 'card' }, h('h2', null, 'Cannot open your data'), h('p', null, e.message),
      h('a', { class: 'btn primary', href: '#/setup' }, 'Open setup')))); return;
  }
  if (!S.cfg) { const m = await import('./setup.js'); root.replaceChildren(await m.render(S, app)); return; }
  document.documentElement.style.setProperty('--fs', (LS.get('fs', 17)) + 'px');
  const mod = await (VIEWS[page] || VIEWS.home)();
  const view = mod[page === 'more' ? 'more' : page] || mod.home;
  let node;
  try { node = await view(S, params, app); }
  catch (e) { node = h('div', { class: 'card' }, h('h2', null, 'Something went wrong'), h('p', null, e.message || String(e)), h('button', { class: 'btn', onclick: route }, 'Try again')); }
  root.replaceChildren(shell(VIEWS[page] ? page : 'home', node));
  window.scrollTo(0, 0);
  if (mod.refresh && page === 'home') timer = setTimeout(() => { if (!document.hidden) route(); else timer = setTimeout(route, 30000); }, mod.refresh);
}

function theme() { const t = LS.get('theme', 'auto'); if (t !== 'auto') document.documentElement.dataset.theme = t; }
theme();
window.addEventListener('hashchange', route);
import('./palette.js');
document.addEventListener('visibilitychange', () => { if (!document.hidden && /home|^$/.test(location.hash.replace('#/', ''))) route(); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
if (new URLSearchParams(location.search).get('code') || new URLSearchParams(location.search).get('error')) import('./v_accounts.js').then((m) => m.handleOAuth()).finally(route); else route();
