// Device identity + silent entitlement. The private key is non-extractable and never leaves this browser.
import { LS } from './core.js';
const cfg = () => (window.REELIO_CONFIG || {});
export const licenseOn = () => !!cfg().licenseUrl;
const enc = new TextEncoder();
const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

function idb() {
  return new Promise((res, rej) => { const r = indexedDB.open('reelio-device', 1); r.onupgradeneeded = () => r.result.createObjectStore('k'); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
}
const idbGet = async (k) => { const d = await idb(); return new Promise((res, rej) => { const q = d.transaction('k').objectStore('k').get(k); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); }); };
const idbPut = async (k, v) => { const d = await idb(); return new Promise((res, rej) => { const t = d.transaction('k', 'readwrite'); t.objectStore('k').put(v, k); t.oncomplete = () => res(); t.onerror = () => rej(t.error); }); };

let keys = null;
async function deviceKeys() {
  if (keys) return keys;
  let rec = null; try { rec = await idbGet('device'); } catch {}
  if (!rec) {
    const kp = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']);
    const j = await crypto.subtle.exportKey('jwk', kp.publicKey);
    rec = { priv: kp.privateKey, pub: { kty: 'EC', crv: 'P-256', x: j.x, y: j.y } };
    try { await idbPut('device', rec); } catch {}
  }
  keys = rec; return rec;
}
async function api(path, body) {
  const r = await fetch(cfg().licenseUrl.replace(/\/$/, '') + path, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({})); return { status: r.status, ...j };
}
let deviceIdCache = null;
export async function deviceId() {
  if (deviceIdCache) return deviceIdCache;
  const k = await deviceKeys(); const r = await api('/v1/device/register', { pub: k.pub });
  if (!r.deviceId) throw new Error('Could not reach the Reelio account service. Check your internet and try again.');
  deviceIdCache = r.deviceId; return r.deviceId;
}
/** Ask the server for a one-time challenge and sign it. Everything happens silently. */
export async function signed(purpose, extra = {}) {
  const id = await deviceId(); const k = await deviceKeys();
  const c = await api('/v1/challenge', { deviceId: id });
  if (!c.nonce) throw new Error('Could not reach the Reelio account service.');
  const sig = b64u(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, k.priv, enc.encode(`reelio:${purpose}:${c.nonce}:${id}`)));
  return { deviceId: id, nonce: c.nonce, sig, ...extra };
}

/** Returns {active, state, token?, claims?, offline?}. Cached token is trusted until it expires so brief outages never lock people out. */
export async function entitlement() {
  if (!licenseOn()) return { active: true, state: 'open' };
  try {
    const r = await api('/v1/entitlement', await signed('entitlement'));
    if (r.active) { LS.set('ent', { token: r.token, claims: r.claims }); return r; }
    LS.del('ent'); return { active: false, state: r.state || 'none' };
  } catch (e) {
    const c = LS.get('ent', null);
    if (c && c.claims && c.claims.exp > Date.now() / 1000) return { active: true, state: c.claims.st, claims: c.claims, token: c.token, offline: true };
    return { active: false, state: 'offline', error: e.message };
  }
}
export const plans = () => api('/v1/plans');
export async function checkout(plan, provider) {
  const r = await api('/v1/checkout', await signed('checkout', { plan, provider, return_url: location.origin + location.pathname }));
  if (!r.url) throw new Error(r.message || 'Could not start checkout.'); return r.url;
}
export async function portal() { const r = await api('/v1/portal', await signed('portal', { return_url: location.href })); if (!r.url) throw new Error(r.message || 'No billing page yet.'); return r.url; }
export async function linkCreate() { const r = await api('/v1/link/create', await signed('link-create')); if (!r.code) throw new Error(r.message || 'Could not make a code.'); return r.code; }
export async function linkRedeem(code) { const r = await api('/v1/link/redeem', await signed('link-redeem', { code })); if (!r.ok) throw new Error(r.message || 'That code did not work.'); return true; }
