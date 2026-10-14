// Core helpers: DOM builder, storage, GitHub data access, encryption that matches the worker.
export const $ = (s, r = document) => r.querySelector(s);

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  const add = (k) => {
    if (k == null || k === false) return;
    if (Array.isArray(k)) return k.forEach(add);
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  };
  kids.forEach(add);
  return el;
}

export const LS = {
  get(k, d) { try { const v = localStorage.getItem('reelio.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('reelio.' + k, JSON.stringify(v)); } catch {} },
  del(k) { try { localStorage.removeItem('reelio.' + k); } catch {} },
};

export const ICONS = {
  home: 'M3 11l9-8 9 8M5 10v10h14V10',
  queue: 'M4 6h16M4 12h16M4 18h10',
  flows: 'M5 6a2 2 0 100-4 2 2 0 000 4zM19 22a2 2 0 100-4 2 2 0 000 4zM7 5h6a4 4 0 014 4v0a4 4 0 01-4 4H9a4 4 0 00-4 4v0a2 2 0 002 2h10',
  accounts: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 4-6 8-6s8 2 8 6',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  schedule: 'M4 5h16v15H4zM4 10h16M9 3v4M15 3v4',
  chart: 'M4 20V10M10 20V4M16 20v-8M22 20H2',
  log: 'M6 3h9l3 3v15H6zM9 11h6M9 15h6',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19 12l2-1-2-4-2 1-2-1-1-2h-4l-1 2-2 1-2-1-2 4 2 1v2l-2 1 2 4 2-1 2 1 1 2h4l1-2 2-1 2 1 2-4-2-1z',
  help: 'M12 21a9 9 0 100-18 9 9 0 000 18zM9.5 9.5a2.5 2.5 0 114 2c-1 .7-1.5 1.2-1.5 2.5M12 17h.01',
  pages: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  search: 'M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-5-5',
  play: 'M7 4l13 8-13 8z', pause: 'M7 4h3v16H7zM14 4h3v16h-3z', plus: 'M12 5v14M5 12h14',
  check: 'M5 13l4 4L19 7', refresh: 'M20 11a8 8 0 10-2 6M20 4v7h-7',
};
export function icon(name) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', ICONS[name] || '');
  s.append(p); return s;
}

export function toast(msg, ms = 3200) {
  const t = h('div', { class: 'toast', role: 'status' }, msg); document.body.append(t); setTimeout(() => t.remove(), ms);
}

export function fmtTime(iso, tz) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: tz || undefined }); } catch { return ''; }
}
export function fmtDay(iso, tz) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short', timeZone: tz || undefined }); } catch { return ''; }
}
export function ago(iso) {
  if (!iso) return 'never';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return 'just now'; if (s < 3600) return Math.round(s / 60) + ' minutes ago';
  if (s < 86400) return Math.round(s / 3600) + ' hours ago'; return Math.round(s / 86400) + ' days ago';
}
export const uid = () => Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4);
export const slug = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 30) || uid();

// ---------- encryption (AES-256-GCM, PBKDF2-SHA256) - same bytes the Python worker reads
const enc = new TextEncoder(), dec = new TextDecoder();
const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function deriveKey(pass, salt, iter) {
  const km = await crypto.subtle.importKey('raw', enc.encode(pass), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: iter, hash: 'SHA-256' }, km, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}
export async function encryptJson(obj, pass, iter = 200000) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await deriveKey(pass, salt, iter), enc.encode(JSON.stringify(obj)));
  return { v: 1, kdf: 'pbkdf2-sha256', iter, salt: b64(salt), iv: b64(iv), ct: b64(ct) };
}
export async function decryptJson(blob, pass) {
  try {
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(blob.iv) }, await deriveKey(pass, unb64(blob.salt), blob.iter || 200000), unb64(blob.ct));
    return JSON.parse(dec.decode(pt));
  } catch { throw new Error('That passphrase does not unlock your saved logins.'); }
}

// ---------- GitHub access
export class GhError extends Error { constructor(msg, status) { super(msg); this.status = status; } }

export function repoInfo() {
  const q = new URLSearchParams(location.search);
  const saved = LS.get('repo', {});
  const m = location.hostname.match(/^(.+)\.github\.io$/);
  const app = (location.pathname.split('/')[1] || '').replace(/\.html$/, '');
  return {
    api: q.get('api') || saved.api || 'https://api.github.com',
    owner: q.get('owner') || saved.owner || (m ? m[1] : ''),
    app: q.get('app') || saved.app || (m && app ? app : 'reelio'),
    data: q.get('data') || saved.data || 'reelio-data',
  };
}

export class Data {
  constructor(repo, token) { this.r = repo; this.token = token; }
  async gh(path, opts = {}) {
    let res;
    try {
      res = await fetch(this.r.api + path, { ...opts, headers: { Authorization: 'Bearer ' + this.token, Accept: 'application/vnd.github+json', ...(opts.headers || {}) } });
    } catch { throw new GhError('Cannot reach GitHub. Check your internet connection.', 0); }
    if (res.status === 401) throw new GhError('GitHub rejected your key. It may have expired. Create a new one in Settings.', 401);
    if (res.status === 403 && res.headers.get('x-ratelimit-remaining') === '0') throw new GhError('GitHub asked us to slow down. Try again in a few minutes.', 403);
    return res;
  }
  base() { return `/repos/${this.r.owner}/${this.r.data}/contents/`; }
  async readText(path) {
    const res = await this.gh(this.base() + encodeURI(path), { headers: { Accept: 'application/vnd.github.raw+json' }, cache: 'no-store' });
    if (res.status === 404) return null;
    if (!res.ok) throw new GhError(`Could not read ${path} (${res.status}).`, res.status);
    return res.text();
  }
  async read(path) { const t = await this.readText(path); if (t == null) return null; try { return JSON.parse(t); } catch { return null; } }
  async sha(path) {
    const res = await this.gh(this.base() + encodeURI(path), { cache: 'no-store' });
    if (res.status === 404) return null;
    return (await res.json()).sha;
  }
  async put(path, content, msg, sha, isBase64 = false) {
    const body = { message: msg || 'Reelio app', content: isBase64 ? content : btoa(unescape(encodeURIComponent(typeof content === 'string' ? content : JSON.stringify(content, null, 1)))) };
    if (sha) body.sha = sha;
    const res = await this.gh(this.base() + encodeURI(path), { method: 'PUT', body: JSON.stringify(body) });
    if (res.status === 409 || res.status === 422) throw new GhError('conflict', 409);
    if (res.status === 404) throw new GhError('Your data repository was not found, or your key cannot write to it. Check the setup page.', 404);
    if (!res.ok) throw new GhError(`Could not save ${path} (${res.status}).`, res.status);
    return res.json();
  }
  /** read-modify-write that survives the worker saving at the same moment */
  async update(path, fn, msg, fallback = {}) {
    for (let i = 0; i < 5; i++) {
      const sha = await this.sha(path);
      const cur = sha ? await this.read(path) : null;
      const next = await fn(cur ?? structuredClone(fallback));
      try { await this.put(path, next, msg, sha); return next; } catch (e) { if (e.status !== 409) throw e; await new Promise((r) => setTimeout(r, 400 * (i + 1))); }
    }
    throw new GhError('Saving kept colliding with a background run. Please try again.', 409);
  }
  async remove(path, msg) {
    const sha = await this.sha(path); if (!sha) return;
    await this.gh(this.base() + encodeURI(path), { method: 'DELETE', body: JSON.stringify({ message: msg || 'Reelio app', sha }) });
  }
  async command(cmd) { await this.put(`inbox/${Date.now()}-${uid()}.json`, cmd, 'Reelio command: ' + cmd.cmd); }
  async dispatch(action = 'run', route = '') {
    const res = await this.gh(`/repos/${this.r.owner}/${this.r.app}/actions/workflows/tick.yml/dispatches`, { method: 'POST', body: JSON.stringify({ ref: 'main', inputs: { action, route } }) });
    if (res.status === 404) throw new GhError('The Reelio worker was not found in your app repository. Check the setup page.', 404);
    if (res.status === 403 || res.status === 401) throw new GhError('Your GitHub key is not allowed to start runs. It needs the "Actions: read and write" permission.', 403);
    if (res.status === 422) throw new GhError('GitHub could not start the run. Is the workflow enabled in the Actions tab?', 422);
    if (!res.ok) throw new GhError(`GitHub could not start the run (${res.status}).`, res.status);
  }
  async latestRun() {
    const res = await this.gh(`/repos/${this.r.owner}/${this.r.app}/actions/workflows/tick.yml/runs?per_page=1`, { cache: 'no-store' });
    if (!res.ok) return null; const j = await res.json(); return (j.workflow_runs || [])[0] || null;
  }
  async listSecretNames() {
    const res = await this.gh(`/repos/${this.r.owner}/${this.r.app}/actions/secrets`);
    if (!res.ok) return null; return (await res.json()).secrets.map((s) => s.name);
  }
  async list(dir) {
    const res = await this.gh(this.base() + encodeURI(dir), { cache: 'no-store' });
    if (!res.ok) return []; const j = await res.json(); return Array.isArray(j) ? j : [];
  }
  async check() {
    const out = { token: false, dataRepo: false, appRepo: false, hasConfig: false };
    const me = await this.gh('/user'); out.token = me.ok;
    if (!me.ok) return out;
    out.login = (await me.json()).login;
    out.dataRepo = (await this.gh(`/repos/${this.r.owner}/${this.r.data}`)).ok;
    out.appRepo = (await this.gh(`/repos/${this.r.owner}/${this.r.app}`)).ok;
    if (out.dataRepo) out.hasConfig = (await this.sha('config.json')) != null;
    return out;
  }
}

export const DEFAULT_CONFIG = {
  version: 1, paused: false, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata',
  notify: { telegram: { enabled: false, conn: 'telegram', events: { posted: false, failed: true, limit: true, token: true, daily: true } } },
  connections: [], routes: [],
};

export const FILTERS = {
  none: ['No filter', 'none'], golden: ['Golden', 'sepia(.35) saturate(1.35) hue-rotate(-8deg) brightness(1.04)'],
  warm_yellow: ['Warm yellow', 'sepia(.25) saturate(1.2) hue-rotate(-5deg)'], soft_warm: ['Soft warm', 'sepia(.15) saturate(1.05) brightness(1.02)'],
  clean_pop: ['Clean pop', 'contrast(1.06) saturate(1.1)'], warm: ['Warm', 'sepia(.2) saturate(1.25)'], cool: ['Cool', 'hue-rotate(15deg) saturate(1.1) brightness(1.02)'],
  vintage: ['Vintage', 'sepia(.5) contrast(.95) saturate(.9)'], bw: ['Black and white', 'grayscale(1) contrast(1.1)'],
  vivid: ['Vivid', 'saturate(1.6) contrast(1.1)'], fade: ['Faded', 'contrast(.9) brightness(1.05) saturate(.8)'],
};

/** A stable colour + initials for each account, so a page is recognised at a glance everywhere in the app. */
export const hue = (id) => { let n = 0; for (const c of String(id)) n = (n * 31 + c.charCodeAt(0)) % 360; return n; };
export function chip(label, id) {
  const ini = String(label || '?').replace(/[^A-Za-z0-9 ]/g, '').trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase() || '?';
  return h('span', { class: 'chip', style: `--h:${hue(id)}`, 'aria-hidden': 'true' }, ini);
}
