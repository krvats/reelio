import { store, syncNow } from './sync.js';

const v = document.getElementById('v');
const el = (t, p, ...k) => { const e = Object.assign(document.createElement(t), p || {}); e.append(...k.filter(Boolean)); return e; };
const rid = () => Math.random().toString(36).slice(2, 8);
const ago = (t) => { if (!t) return 'never'; const m = Math.round((Date.now() - t) / 60000); return m < 1 ? 'just now' : m < 90 ? m + ' min ago' : Math.round(m / 60) + ' h ago'; };

async function connect() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let info;
  try {
    [{ result: info }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => ({ token: localStorage.getItem('reelio.token'), pass: localStorage.getItem('reelio.pass'), repo: localStorage.getItem('reelio.repo'), host: location.hostname, path: location.pathname }) });
  } catch { return render('Open your Reelio app in this tab first (the page you use to manage flows), then click this icon again.'); }
  const parse = (s) => { try { return JSON.parse(s); } catch { return null; } };
  const token = parse(info.token), pass = parse(info.pass), repo = parse(info.repo) || {};
  if (!token || !pass) return render('This tab is not a signed-in Reelio app. Open your Reelio app, sign in, then click this icon again.');
  const m = (info.host || '').match(/^(.+)\.github\.io$/);
  const owner = repo.owner || (m && m[1]), data = repo.data || 'reelio-data';
  if (!owner) return render('Could not tell which GitHub account owns your Reelio data. Open the app from its normal address.');
  const old = await store.get();
  await store.set({ token, pass, owner, data, api: repo.api || 'https://api.github.com', profileId: old.profileId || rid(), label: old.label || 'This browser' });
  await sync(true);
}

async function sync(force) {
  render('Sending your cookies to Reelio...');
  const r = await syncNow({ force }).catch((e) => ({ ok: false, msg: e.message }));
  render(r.msg, r.ok);
}

async function render(note, ok) {
  const s = await store.get(); v.replaceChildren();
  if (note) v.append(el('p', { className: ok === true ? 'ok' : ok === false ? 'bad' : '' }, note));
  if (!s.token) {
    v.append(el('p', null, 'One click, once. First open your Reelio app in this tab, then press:'), el('button', { onclick: connect }, 'Connect to Reelio'));
    return;
  }
  v.append(el('p', { className: 'small' }, `Connected to ${s.owner}/${s.data}. Last sent: ${ago(s.lastPush)}. Last check: ${ago(s.lastRun)}.`),
    el('p', { className: 'small' }, 'It sends fresh cookies by itself every hour while this browser is open. Nothing else to do.'));
  const name = el('input', { value: s.label || '', placeholder: 'Name for this browser (e.g. Spare account 1)' });
  name.addEventListener('change', () => store.set({ label: name.value.trim() || 'This browser', lastHash: null }));
  v.append(name, el('button', { onclick: () => sync(true) }, 'Send now'),
    el('button', { className: 'alt', onclick: async () => { await store.clear(); render('Disconnected. Saved keys removed from this browser.', true); } }, 'Disconnect'));
}
render();
