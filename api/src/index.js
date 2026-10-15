// Reelio multi-user API (Phase B part 1). Every record lives under the tenant that owns it, so one user can never reach another's data.
// Sections: auth, tenant data (config/queue/inbox), secrets (envelope encryption), ledger (exactly-once), job leases for workers.
import { MemoryStore } from '../../license/src/store.js';
import { b64u, unb64u, randomId, randomCode, safeEqual, sha256, verifyToken } from '../../license/src/crypto.js';
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
  /** Who is calling and in which workspace. A user may belong to several (agencies): pick one with the X-Tenant header. */
  async function session(request) {
    const tok = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''); if (!tok) return null;
    const s = await store.get(`sess:${await sha256(tok)}`); if (!s || s.exp < now()) return null;
    const want = request.headers.get('X-Tenant') || s.tid; let role = 'owner';
    if (want !== s.tid) { const ms = (await store.get(`member:${s.email}`)) || []; const hit = ms.find((x) => x.tid === want); if (!hit) return null; role = hit.role; }
    const t = await store.get(`tenant:${want}`); return t ? { t, role, email: s.email } : null;
  }
  const canWrite = (r) => ['owner', 'admin', 'editor'].includes(r), canAdmin = (r) => ['owner', 'admin'].includes(r);
  async function audit(tid, who, what) { const k = K(tid, 'audit'); const a = (await store.get(k)) || []; a.push({ at: now(), who, what }); await store.put(k, a.slice(-500)); }
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
      const tok = randomId(32); await store.put(`sess:${await sha256(tok)}`, { tid: u.tid, email, exp: now() + 30 * DAY }, { ttl: 30 * DAY });
      return json({ token: tok, tenant: u.tid }, p.endsWith('signup') ? 201 : 200);
    }
    if (p.startsWith('/v1/internal/')) return internal(request, p, m, body);

    if (p.startsWith('/v1/admin/')) return admin(request, p, m, body);
    const ses = await session(request); if (!ses) return err(401, 'unauthorized', 'Please log in.');
    const { t, role } = ses;
    if (t.suspended) return err(403, 'suspended', 'This workspace is paused. Contact support.');
    if (m !== 'GET' && p !== '/v1/auth/logout' && !canWrite(role) && p !== '/v1/team/accept') return err(403, 'read_only', 'Your role can look but not change things.');
    if (m === 'POST' && p === '/v1/auth/logout') { const tok = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''); await store.del(`sess:${await sha256(tok)}`); return json({ ok: true }); }
    if (m === 'GET' && p === '/v1/me') return json({ tenant: t.id, email: ses.email, role, plan: t.plan, limits: limits(t), workspaces: [{ tid: (await store.get(`user:${ses.email}`)).tid, role: 'owner' }, ...((await store.get(`member:${ses.email}`)) || [])] });
    if (m === 'POST' && p === '/v1/plan/sync') {       // the license service's signed entitlement upgrades this workspace
      if (!canAdmin(role)) return err(403, 'forbidden', 'Only an owner or admin can change the plan.');
      let c; try { c = await verifyToken(env.LICENSE_PUBKEY || '', body.token, now()); } catch { return err(400, 'bad_token', 'That plan proof is not valid or has expired.'); }
      t.plan = c.plan; t.plan_until = c.wv || c.exp; await store.put(`tenant:${t.id}`, t); await audit(t.id, ses.email, `plan ${c.plan}`); return json({ plan: t.plan });
    }
    if (p === '/v1/team/invite' && m === 'POST') {
      if (!canAdmin(role)) return err(403, 'forbidden', 'Only an owner or admin can invite people.');
      if (!['admin', 'editor', 'viewer'].includes(body.role)) return err(400, 'bad_role', 'Pick admin, editor or viewer.');
      const code = randomCode(); await store.put(`invite:${code}`, { tid: t.id, role: body.role, email: String(body.email || '').toLowerCase() }, { ttl: 7 * DAY }); await audit(t.id, ses.email, `invited ${body.email} as ${body.role}`); return json({ code, expires_in: 7 * DAY });
    }
    if (p === '/v1/team/accept' && m === 'POST') {
      const code = String(body.code || '').toUpperCase(), inv = await store.get(`invite:${code}`); if (!inv) return err(404, 'bad_code', 'That invite is wrong or has expired.');
      if (inv.email && inv.email !== ses.email) return err(403, 'wrong_user', 'This invite was made for another email.');
      const ms = (await store.get(`member:${ses.email}`)) || []; if (!ms.some((x) => x.tid === inv.tid)) ms.push({ tid: inv.tid, role: inv.role });
      await store.put(`member:${ses.email}`, ms); await store.del(`invite:${code}`); await audit(inv.tid, ses.email, `joined as ${inv.role}`); return json({ tid: inv.tid, role: inv.role });
    }
    if (p === '/v1/team' && m === 'GET') { if (!canAdmin(role)) return err(403, 'forbidden', 'Only an owner or admin can see the team.'); const out = []; for (const k of await store.keys('member:')) for (const x of (await store.get(k)) || []) if (x.tid === t.id) out.push({ email: k.slice(7), role: x.role }); return json({ owner: t.owner, members: out }); }
    if (p === '/v1/team/remove' && m === 'POST') { if (!canAdmin(role)) return err(403, 'forbidden', 'Only an owner or admin can remove people.'); const k = `member:${String(body.email || '').toLowerCase()}`; const ms = ((await store.get(k)) || []).filter((x) => x.tid !== t.id); await store.put(k, ms); await audit(t.id, ses.email, `removed ${body.email}`); return json({ ok: true }); }
    if (p === '/v1/audit' && m === 'GET') return json((canAdmin(role) && (await store.get(K(t.id, 'audit')))) || []);
    if (p === '/v1/status' && m === 'GET') return json((await store.get(K(t.id, 'status'))) || {});

    // ---------- config (optimistic concurrency: send the version you read)
    if (p === '/v1/config') {
      const cfg = await store.get(K(t.id, 'config'));
      if (m === 'GET') return json(cfg);
      if (m === 'PUT') {
        if (body.v !== cfg.v) return err(409, 'conflict', 'Your settings changed somewhere else. Reload and try again.');
        const accounts = new Set((body.routes || []).map((r) => r.target && r.target.conn)); const lim = limits(t);
        if (accounts.size > lim.accounts) return err(402, 'plan_limit', `Your plan allows ${lim.accounts} account(s). Upgrade to add more.`);
        const next = { ...body, connections: body.connections || [], routes: body.routes || [], timezone: body.timezone || cfg.timezone, paused: !!body.paused, v: cfg.v + 1 };
        for (const r of next.routes) if (!r.id) return err(400, 'bad_flow', 'Every flow needs an id.');
        await store.put(K(t.id, 'config'), next); await audit(t.id, ses.email, 'saved settings'); return json(next);
      }
    }
    // ---------- secrets: write-only from the browser; only workers can read them back
    let mm = p.match(/^\/v1\/secrets\/([\w-]{1,40})$/);
    if (mm && m !== 'GET' && !canAdmin(role)) return err(403, 'forbidden', 'Only an owner or admin can change logins.');
    if (mm && m === 'PUT') { await audit(t.id, ses.email, `saved login ${mm[1]}`);
      const all = (await store.get(K(t.id, 'sec'))) ? await unseal(await dataKey(t), await store.get(K(t.id, 'sec'))) : {};
      all[mm[1]] = { ...(all[mm[1]] || {}), ...(body.fields || {}) }; await store.put(K(t.id, 'sec'), await seal(await dataKey(t), all)); return json({ ok: true });
    }
    if (mm && m === 'DELETE') { const b = await store.get(K(t.id, 'sec')); if (b) { const all = await unseal(await dataKey(t), b); delete all[mm[1]]; await store.put(K(t.id, 'sec'), await seal(await dataKey(t), all)); } return json({ ok: true }); }
    if (p === '/v1/secrets' && m === 'GET') { const b = await store.get(K(t.id, 'sec')); const all = b ? await unseal(await dataKey(t), b) : {}; return json({ connected: Object.keys(all) }); }   // names only, never values
    // ---------- queue + inbox
    mm = p.match(/^\/v1\/queue\/([\w-]{1,40})$/); if (mm && m === 'GET') return json((await store.get(K(t.id, 'queue', mm[1]))) || { items: [] });
    if (p === '/v1/inbox' && m === 'POST') { const id = randomId(8); await store.put(K(t.id, 'inbox', id), { ...body, at: now() }); return json({ id }, 201); }
    if (p === '/v1/status' && m === 'GET') return json((await store.get(K(t.id, 'status'))) || {});
    if (p === '/v1/ledger' && m === 'GET') return json((await store.get(K(t.id, 'ledger'))) || { entries: [] });
    return err(404, 'not_found', 'No such route.');
  }

  // ---------- owner console (ADMIN_SECRET): users, usage, kill switch
  async function admin(request, p, m, body) {
    const tok = (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''); if (!env.ADMIN_SECRET || !safeEqual(tok, env.ADMIN_SECRET)) return err(401, 'unauthorized', 'Admin key required.');
    if (p === '/v1/admin/tenants') { const out = []; for (const k of await store.keys('tenant:')) { const t = await store.get(k); const cfg = (await store.get(K(t.id, 'config'))) || { routes: [] }; out.push({ id: t.id, owner: t.owner, plan: t.plan, suspended: !!t.suspended, flows: cfg.routes.length, accounts: new Set(cfg.routes.map((r) => r.target && r.target.conn)).size, created: t.created }); } return json({ tenants: out }); }
    if (p === '/v1/admin/stats') { const ts = await store.keys('tenant:'); let paid = 0, sus = 0; for (const k of ts) { const t = await store.get(k); if (t.plan) paid++; if (t.suspended) sus++; } return json({ tenants: ts.length, paid, suspended: sus }); }
    if (m === 'POST' && (p === '/v1/admin/suspend' || p === '/v1/admin/plan')) { const t = await store.get(`tenant:${body.tenant}`); if (!t) return err(404, 'not_found', 'No such workspace.'); if (p.endsWith('suspend')) t.suspended = body.on !== false; else t.plan = body.plan || null; await store.put(`tenant:${t.id}`, t); await audit(t.id, 'admin', p.endsWith('suspend') ? (t.suspended ? 'suspended' : 'unsuspended') : `plan set ${t.plan}`); return json({ ok: true }); }
    return err(404, 'not_found', 'Unknown admin route.');
  }

  // ---------- worker-only routes
  async function internal(request, p, m, body) {
    if (!workerOk(request)) return err(401, 'unauthorized', 'Worker key required.');
    if (p === '/v1/internal/lease' && m === 'POST') {          // hand out each flow to exactly one worker at a time
      for (const k of await store.keys('tenant:')) {
        const t = await store.get(k); if (t.suspended) continue; const cfg = await store.get(K(t.id, 'config')); if (!cfg || cfg.paused) continue;
        for (const r of cfg.routes) {
          if (r.enabled === false || (body.exclude || []).some((x) => x[0] === t.id && x[1] === r.id)) continue; const lk = `lease:${t.id}:${r.id}`; const l = await store.get(lk);
          if (l && l.exp > now()) continue;
          if (await store.get(`rest:${t.id}:${r.id}`)) continue;     // just served: wait for the next tick
          const lease = { id: randomId(8), exp: now() + (body.seconds || 900), worker: body.worker || '?' }; await store.put(lk, lease, { ttl: lease.exp - now() });
          return json({ lease: lease.id, tenant: t.id, route: r, config: { timezone: cfg.timezone, connections: cfg.connections }, limits: limits(t) });
        }
      }
      return json({ lease: null });
    }
    if (p === '/v1/internal/release' && m === 'POST') { const lk = `lease:${body.tenant}:${body.route}`; const l = await store.get(lk); if (l && l.id === body.lease) await store.del(lk); if (body.cooldown > 0) await store.put(`rest:${body.tenant}:${body.route}`, 1, { ttl: Math.max(60, body.cooldown) }); return json({ ok: true }); }
    if (p === '/v1/internal/secrets' && m === 'POST') { const t = await store.get(`tenant:${body.tenant}`); const b = t && await store.get(K(t.id, 'sec')); return json(b ? await unseal(await dataKey(t), b) : {}); }
    if (p === '/v1/internal/ledger' && m === 'POST') {          // exactly-once: unique by target+source id and target+md5
      const lk = K(body.tenant, 'ledger'); const led = (await store.get(lk)) || { entries: [] }; const e = body.entry || {};
      if (led.entries.some((x) => x.target === e.target && (x.src === e.src || (e.md5 && x.md5 === e.md5)))) return err(409, 'duplicate', 'Already posted to this account.');
      led.entries.push({ ...e, at: now() }); await store.put(lk, led); return json({ ok: true }, 201);
    }
    if (p === '/v1/internal/pull' && m === 'POST') {            // everything a worker needs for one flow, in one call
      const t = await store.get(`tenant:${body.tenant}`); if (!t || t.suspended) return err(404, 'no_tenant', 'Unknown or paused workspace.');
      const cfg = await store.get(K(t.id, 'config')), b = await store.get(K(t.id, 'sec')), inbox = [];
      for (const k of await store.keys(K(t.id, 'inbox', ''))) inbox.push({ ...(await store.get(k)), _key: k });
      return json({ config: cfg, secrets: b ? await unseal(await dataKey(t), b) : {}, queue: (await store.get(K(t.id, 'queue', body.route))) || { items: [] }, ledger: (await store.get(K(t.id, 'ledger'))) || { entries: [] }, status: (await store.get(K(t.id, 'status'))) || {}, inbox, limits: limits(t) });
    }
    if (p === '/v1/internal/push' && m === 'POST') {
      const tid = body.tenant; if (!(await store.get(`tenant:${tid}`))) return err(404, 'no_tenant', 'Unknown workspace.');
      let dups = 0;
      if (body.queue) await store.put(K(tid, 'queue', body.route), body.queue);
      if (body.status) await store.put(K(tid, 'status'), body.status);
      if (body.secrets) { const t = await store.get(`tenant:${tid}`); await store.put(K(tid, 'sec'), await seal(await dataKey(t), body.secrets)); }
      if (body.config_patch) { const cfg = await store.get(K(tid, 'config')); await store.put(K(tid, 'config'), { ...cfg, connections: body.config_patch.connections ?? cfg.connections }); }
      if (body.ledger && body.ledger.length) { const lk = K(tid, 'ledger'); const led = (await store.get(lk)) || { entries: [] };
        for (const e of body.ledger) { if (led.entries.some((x) => x.id === e.id || (x.target === e.target && (x.src === e.src || (e.md5 && x.md5 === e.md5))))) { dups++; continue; } led.entries.push(e); }
        await store.put(lk, led); }
      for (const k of body.ack_inbox || []) if (k.startsWith(K(tid, 'inbox', ''))) await store.del(k);
      return json({ ok: true, duplicates: dups });
    }
    if (p === '/v1/internal/state' && m === 'POST') {            // everything a worker needs to run one flow
      const tid = body.tenant; const inbox = []; for (const k of await store.keys(K(tid, 'inbox:'))) { const c = await store.get(k); if (c && (!c.route || c.route === body.route || c.account)) { inbox.push({ ...c, _k: k }); } }
      return json({ queue: (await store.get(K(tid, 'queue', body.route))) || { items: [], last_scan: null }, ledger: (await store.get(K(tid, 'ledger'))) || { entries: [] }, inbox, status: (await store.get(K(tid, 'status'))) || {} });
    }
    if (p === '/v1/internal/inbox-done' && m === 'POST') { for (const k of body.keys || []) if (String(k).startsWith(K(body.tenant, 'inbox:'))) await store.del(k); return json({ ok: true }); }
    if (p === '/v1/internal/status' && m === 'POST') {          // merge this flow's slice of status so parallel workers never overwrite each other
      const sk = K(body.tenant, 'status'); const cur = (await store.get(sk)) || { routes: {}, accounts: {}, plan: {}, recent: [] }; const st = body.status || {};
      cur.routes = { ...cur.routes, ...Object.fromEntries(Object.entries(st.routes || {}).filter(([k]) => k === body.route)) };
      cur.plan = { ...(cur.plan || {}), ...Object.fromEntries(Object.entries(st.plan || {}).filter(([k]) => k === body.route)) };
      cur.accounts = { ...cur.accounts, ...(st.accounts || {}) }; cur.run = st.run; cur.license = st.license; cur.updated = now();
      cur.recent = [...(st.recent || []), ...(cur.recent || [])].filter((e, i, a) => a.findIndex((x) => x.at === e.at && x.msg === e.msg) === i).slice(0, 60);
      await store.put(sk, cur); return json({ ok: true });
    }
    if (p === '/v1/internal/plan' && m === 'POST') { const t = await store.get(`tenant:${body.tenant}`); if (!t) return err(404, 'not_found', 'No such tenant.'); t.plan = body.plan || null; await store.put(`tenant:${t.id}`, t); return json({ ok: true }); }
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
