// Reelio multi-user API (Phase B part 1). Every record lives under the tenant that owns it, so one user can never reach another's data.
// Sections: auth, tenant data (config/queue/inbox), secrets (envelope encryption), ledger (exactly-once), job leases for workers.
import { MemoryStore } from '../../license/src/store.js';
import { b64u, unb64u, randomId, safeEqual, sha256 } from '../../license/src/crypto.js';
export { MemoryStore };

const enc = new TextEncoder(), dec = new TextDecoder(), DAY = 86400;
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { 'Content-Type': 'application/json' } });
const err = (s, code, msg) => json({ error: code, message: msg }, s);
const subtle = globalThis.crypto.subtle;

async function pbkdf2(pw, salt, iters = 150000) {
  const k = await subtle.importKey('raw', enc.encode(pw), 'PBKDF2', false, ['deriveBits']);
  return b64u(await subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iters }, k, 256));
}
async function aesKey(raw, usages) { return subtle.importKey('raw', raw, 'AES-GCM', false, usages); }
async function seal(rawKey, obj) { const iv = crypto.getRandomValues(new Uint8Array(12)); const ct = await subtle.encrypt({ name: 'AES-GCM', iv }, await aesKey(rawKey, ['encrypt']), enc.encode(JSON.stringify(obj))); return { iv: b64u(iv), ct: b64u(ct) }; }
async function unseal(rawKey, blob) { return JSON.parse(dec.decode(await subtle.decrypt({ name: 'AES-GCM', iv: unb64u(blob.iv) }, await aesKey(rawKey, ['decrypt']), unb64u(blob.ct)))); }

/** Plan limits come from the license service's plan table; a tenant on no plan gets the free tier. */
export const FREE = { accounts: 1, posts_month: 60 };

export function createApi({ store, env = {}, now = () => Math.floor(Date.now() / 1000), plans = {} }) {
  const master = () => { if (!env.MASTER_KEY) throw new Error('MASTER_KEY is not set'); return unb64u(env.MASTER_KEY); };
  const limits = (t) => (t.plan && plans[t.plan]) || FREE;

  async function limited(request, bucket, max) {
    const ip = request.headers.get('CF-Connecting-IP') || 'local'; const k = `rl:${bucket}:${ip}:${Math.floor(now() / 60)}`;
    const n = ((await store.get(k)) || 0) + 1; await store.put(k, n, { ttl: 120 }); return n > max;
  }
  async function session(request) {
    const tok = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''); if (!tok) return null;
    const s = await store.get(`sess:${await sha256(tok)}`); if (!s || s.exp < now()) return null;
    return store.get(`tenant:${s.tid}`);
  }
  const workerOk = (request) => env.WORKER_SECRET && safeEqual((request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''), env.WORKER_SECRET);
  const K = (tid, ...p) => ['t', tid, ...p].join(':');

  /** Per-tenant data key, stored only wrapped by the master key. */
  async function dataKey(t) {
    if (!t.wrapped) { const raw = crypto.getRandomValues(new Uint8Array(32)); t.wrapped = await seal(master(), { k: b64u(raw) }); await store.put(`tenant:${t.id}`, t); return raw; }
    return unb64u((await unseal(master(), t.wrapped)).k);
  }

  async function handle(request) {
    const url = new URL(request.url), p = url.pathname, m = request.method;
    if (p === '/health') return json({ ok: true });
    const body = m === 'GET' ? {} : await request.json().catch(() => ({}));

    // ---------- auth
    if (m === 'POST' && (p === '/v1/auth/signup' || p === '/v1/auth/login')) {
      if (await limited(request, 'auth', 20)) return err(429, 'slow_down', 'Too many attempts. Wait a minute.');
      const email = String(body.email || '').trim().toLowerCase(), pw = String(body.password || '');
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return err(400, 'bad_email', 'Enter a valid email address.');
      let u = await store.get(`user:${email}`);
      if (p.endsWith('signup')) {
        if (pw.length < 8) return err(400, 'weak_password', 'Use at least 8 characters.');
        if (u) return err(409, 'exists', 'An account with this email already exists. Log in instead.');
        const salt = crypto.getRandomValues(new Uint8Array(16)), tid = randomId(12);
        u = { email, salt: b64u(salt), hash: await pbkdf2(pw, salt), tid, created: now() };
        await store.put(`user:${email}`, u); await store.put(`tenant:${tid}`, { id: tid, owner: email, plan: null, created: now() });
        await store.put(K(tid, 'config'), { v: 0, connections: [], routes: [], timezone: 'Asia/Kolkata' });
      } else if (!u || !safeEqual(await pbkdf2(pw, unb64u(u.salt)), u.hash)) return err(401, 'bad_login', 'Email or password is not right.');
      const tok = randomId(32); await store.put(`sess:${await sha256(tok)}`, { tid: u.tid, exp: now() + 30 * DAY }, { ttl: 30 * DAY });
      return json({ token: tok, tenant: u.tid }, p.endsWith('signup') ? 201 : 200);
    }
    if (p.startsWith('/v1/internal/')) return internal(request, p, m, body);

    const t = await session(request); if (!t) return err(401, 'unauthorized', 'Please log in.');
    if (m === 'POST' && p === '/v1/auth/logout') { const tok = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''); await store.del(`sess:${await sha256(tok)}`); return json({ ok: true }); }
    if (m === 'GET' && p === '/v1/me') return json({ tenant: t.id, email: t.owner, plan: t.plan, limits: limits(t) });

    // ---------- config (optimistic concurrency: send the version you read)
    if (p === '/v1/config') {
      const cfg = await store.get(K(t.id, 'config'));
      if (m === 'GET') return json(cfg);
      if (m === 'PUT') {
        if (body.v !== cfg.v) return err(409, 'conflict', 'Your settings changed somewhere else. Reload and try again.');
        const accounts = new Set((body.routes || []).map((r) => r.target && r.target.conn)); const lim = limits(t);
        if (accounts.size > lim.accounts) return err(402, 'plan_limit', `Your plan allows ${lim.accounts} account(s). Upgrade to add more.`);
        const next = { connections: body.connections || [], routes: body.routes || [], timezone: body.timezone || cfg.timezone, paused: !!body.paused, v: cfg.v + 1 };
        for (const r of next.routes) if (!r.id) return err(400, 'bad_flow', 'Every flow needs an id.');
        await store.put(K(t.id, 'config'), next); return json(next);
      }
    }
    // ---------- secrets: write-only from the browser; only workers can read them back
    let mm = p.match(/^\/v1\/secrets\/([\w-]{1,40})$/);
    if (mm && m === 'PUT') {
      const all = (await store.get(K(t.id, 'sec'))) ? await unseal(await dataKey(t), await store.get(K(t.id, 'sec'))) : {};
      all[mm[1]] = { ...(all[mm[1]] || {}), ...(body.fields || {}) }; await store.put(K(t.id, 'sec'), await seal(await dataKey(t), all)); return json({ ok: true });
    }
    if (mm && m === 'DELETE') { const b = await store.get(K(t.id, 'sec')); if (b) { const all = await unseal(await dataKey(t), b); delete all[mm[1]]; await store.put(K(t.id, 'sec'), await seal(await dataKey(t), all)); } return json({ ok: true }); }
    if (p === '/v1/secrets' && m === 'GET') { const b = await store.get(K(t.id, 'sec')); const all = b ? await unseal(await dataKey(t), b) : {}; return json({ connected: Object.keys(all) }); }   // names only, never values
    // ---------- queue + inbox
    mm = p.match(/^\/v1\/queue\/([\w-]{1,40})$/); if (mm && m === 'GET') return json((await store.get(K(t.id, 'queue', mm[1]))) || { items: [] });
    if (p === '/v1/inbox' && m === 'POST') { const id = randomId(8); await store.put(K(t.id, 'inbox', id), { ...body, at: now() }); return json({ id }, 201); }
    if (p === '/v1/ledger' && m === 'GET') return json((await store.get(K(t.id, 'ledger'))) || { entries: [] });
    return err(404, 'not_found', 'No such route.');
  }

  // ---------- worker-only routes
  async function internal(request, p, m, body) {
    if (!workerOk(request)) return err(401, 'unauthorized', 'Worker key required.');
    if (p === '/v1/internal/lease' && m === 'POST') {          // hand out each flow to exactly one worker at a time
      for (const k of await store.keys('tenant:')) {
        const t = await store.get(k); const cfg = await store.get(K(t.id, 'config')); if (!cfg || cfg.paused) continue;
        for (const r of cfg.routes) {
          if (r.enabled === false) continue; const lk = `lease:${t.id}:${r.id}`; const l = await store.get(lk);
          if (l && l.exp > now()) continue;
          const lease = { id: randomId(8), exp: now() + (body.seconds || 900), worker: body.worker || '?' }; await store.put(lk, lease, { ttl: lease.exp - now() });
          return json({ lease: lease.id, tenant: t.id, route: r, config: { timezone: cfg.timezone, connections: cfg.connections }, limits: limits(t) });
        }
      }
      return json({ lease: null });
    }
    if (p === '/v1/internal/release' && m === 'POST') { const lk = `lease:${body.tenant}:${body.route}`; const l = await store.get(lk); if (l && l.id === body.lease) await store.del(lk); return json({ ok: true }); }
    if (p === '/v1/internal/secrets' && m === 'POST') { const t = await store.get(`tenant:${body.tenant}`); const b = t && await store.get(K(t.id, 'sec')); return json(b ? await unseal(await dataKey(t), b) : {}); }
    if (p === '/v1/internal/ledger' && m === 'POST') {          // exactly-once: unique by target+source id and target+md5
      const lk = K(body.tenant, 'ledger'); const led = (await store.get(lk)) || { entries: [] }; const e = body.entry || {};
      if (led.entries.some((x) => x.target === e.target && (x.src === e.src || (e.md5 && x.md5 === e.md5)))) return err(409, 'duplicate', 'Already posted to this account.');
      led.entries.push({ ...e, at: now() }); await store.put(lk, led); return json({ ok: true }, 201);
    }
    if (p === '/v1/internal/queue' && m === 'POST') { await store.put(K(body.tenant, 'queue', body.route), body.queue); return json({ ok: true }); }
    return err(404, 'not_found', 'No such internal route.');
  }

  return async (request) => {
    const cors = { 'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN || '*', 'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS' };
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    let res; try { res = await handle(request); } catch (e) { res = err(500, 'server_error', 'Something went wrong on our side. Try again in a moment.'); }
    for (const [k, v] of Object.entries(cors)) res.headers.set(k, v); return res;
  };
}

// Cloudflare Workers entry (KV-backed for now; D1 later, same store interface)
import { KVStore } from '../../license/src/store.js';
export default {
  async fetch(request, env) {
    let plans = {}; try { plans = env.PLANS ? JSON.parse(env.PLANS) : {}; } catch {}
    return createApi({ store: new KVStore(env.REELIO_KV), env, plans })(request);
  },
};
