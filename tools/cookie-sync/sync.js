import { encryptJson, decryptJson } from './crypto.js';
import { mergeProfile } from './pool.js';

const SIGNED_IN = ['SAPISID', '__Secure-3PAPISID', '__Secure-3PSID', 'SID'];
const utf8b64 = (s) => btoa(unescape(encodeURIComponent(s)));
const unb64utf8 = (s) => decodeURIComponent(escape(atob(s.replace(/\s/g, ''))));

export const store = {
  get: () => chrome.storage.local.get(null),
  set: (o) => chrome.storage.local.set(o),
  clear: () => chrome.storage.local.clear(),
};

/** This browser's YouTube/Google cookies as one Netscape cookie file, or null when nobody is signed in. */
export async function exportCookies(profileId, label) {
  const all = [...(await chrome.cookies.getAll({ domain: 'youtube.com' })), ...(await chrome.cookies.getAll({ domain: 'google.com' }))];
  const seen = new Set(), list = [];
  for (const c of all) { const k = c.domain + '|' + c.path + '|' + c.name; if (!seen.has(k)) { seen.add(k); list.push(c); } }
  if (!list.some((c) => SIGNED_IN.includes(c.name))) return null;
  const soon = Math.floor(Date.now() / 1000) + 30 * 86400;
  const lines = list.map((c) => `${c.httpOnly ? '#HttpOnly_' : ''}${c.domain}\t${c.domain.startsWith('.') ? 'TRUE' : 'FALSE'}\t${c.path}\t${c.secure ? 'TRUE' : 'FALSE'}\t${c.expirationDate ? Math.floor(c.expirationDate) : soon}\t${c.name}\t${c.value}`);
  return `# Netscape HTTP Cookie File\n# reelio-profile: ${profileId} ${String(label || '').replace(/[\r\n]/g, ' ').slice(0, 40)}\n${lines.join('\n')}\n`;
}

async function gh(cfg, path, opts = {}) {
  let res;
  try { res = await fetch(`${cfg.api}/repos/${cfg.owner}/${cfg.data}/contents/${path}`, { ...opts, cache: 'no-store', headers: { Authorization: 'Bearer ' + cfg.token, Accept: 'application/vnd.github+json', ...(opts.headers || {}) } }); }
  catch { throw new Error('Cannot reach GitHub. Check the internet connection.'); }
  if (res.status === 401) throw new Error('GitHub rejected the saved key. Open the Reelio app and press Connect again.');
  return res;
}

async function readFile(cfg, path) {
  const res = await gh(cfg, path);
  if (res.status === 404) return { sha: null, json: null };
  if (!res.ok) throw new Error(`Could not read ${path} (${res.status}).`);
  const j = await res.json();
  return { sha: j.sha, json: JSON.parse(unb64utf8(j.content)) };
}

async function writeFile(cfg, path, obj, sha, msg) {
  const res = await gh(cfg, path, { method: 'PUT', body: JSON.stringify({ message: msg, content: utf8b64(JSON.stringify(obj, null, 1)), ...(sha ? { sha } : {}) }) });
  if (res.status === 409 || res.status === 422) return false;            // somebody saved at the same moment: caller retries
  if (res.status === 404) throw new Error('Your Reelio data repository was not found, or the saved key cannot write to it.');
  if (!res.ok) throw new Error(`Could not save ${path} (${res.status}).`);
  return true;
}

/** Export, merge into the encrypted secrets, push. Returns {ok, msg}. Never logs cookie values. */
export async function syncNow({ force = false } = {}) {
  const st = await store.get();
  if (!st.token || !st.pass) return { ok: false, msg: 'Not connected yet. Open your Reelio app and press Connect.' };
  const cfg = { token: st.token, pass: st.pass, owner: st.owner, data: st.data, api: st.api || 'https://api.github.com' };
  const text = await exportCookies(st.profileId, st.label);
  if (!text) return await done({ ok: false, msg: 'Not signed in to YouTube in this browser. Sign in once, then press Sync.' });
  const digest = b64hash(text);
  if (!force && st.lastHash === digest) return await done({ ok: true, msg: 'Already up to date.', keep: true });
  let count = 0;
  for (let i = 0; i < 5; i++) {
    const { sha, json } = await readFile(cfg, 'secrets.enc.json');
    const all = json && json.ct ? await decryptJson(json, cfg.pass) : {};
    const yn = all['youtube-net'] || {};
    yn.cookies = mergeProfile(yn.cookies || '', text, st.profileId);
    all['youtube-net'] = yn;
    count = yn.cookies.split('# ---- next cookie ----').length;
    if (await writeFile(cfg, 'secrets.enc.json', await encryptJson(all, cfg.pass), sha, 'Reelio: cookie sync')) break;
    if (i === 4) return await done({ ok: false, msg: 'Saving kept colliding with a background run. It will try again next time.' });
    await new Promise((r) => setTimeout(r, 500 * (i + 1)));
  }
  try {                                                                   // keep the app's cookie counter true (not secret)
    for (let i = 0; i < 3; i++) {
      const { sha, json } = await readFile(cfg, 'config.json');
      if (!json) break;
      json.cookie_count = count;
      if (await writeFile(cfg, 'config.json', json, sha, 'Reelio: cookie count')) break;
    }
  } catch { /* the counter is only a nicety */ }
  return await done({ ok: true, msg: `Sent. Reelio now has ${count} cookie${count === 1 ? '' : 's'}.`, hash: digest });
}

async function done(r) {
  const patch = { lastRun: Date.now(), lastOk: r.ok, lastMsg: r.msg };
  if (r.ok && r.hash) { patch.lastHash = r.hash; patch.lastPush = Date.now(); }
  await store.set(patch);
  return r;
}

function b64hash(s) { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return String(h >>> 0) + ':' + s.length; }
