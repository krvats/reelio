import test from 'node:test';
import assert from 'node:assert/strict';
import { createApi, MemoryStore } from '../src/index.js';
import { importSigner, signToken } from '../../license/src/crypto.js';

const master = Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url');
async function setup() {
  const kp = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']); const priv = await crypto.subtle.exportKey('jwk', kp.privateKey);
  let t = 1_800_000_000; const store = new MemoryStore();
  const api = createApi({ store, env: { MASTER_KEY: master, WORKER_SECRET: 'wk', ADMIN_SECRET: 'adm', LICENSE_PUBKEY: priv.x }, now: () => t, plans: { pro: { accounts: 3, posts_month: 600 } } });
  const call = (m, p, body, tok, extra = {}) => api(new Request('https://x.test' + p, { method: m, headers: { 'Content-Type': 'application/json', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), ...extra }, body: body === undefined ? undefined : JSON.stringify(body) }));
  const user = async (email) => { const j = await (await call('POST', '/v1/auth/signup', { email, password: 'correct horse' })).json(); return { tok: j.token, tid: j.tenant, email }; };
  const mint = async (claims) => signToken(await importSigner(priv), 'k1', { iat: t, exp: t + 3600, ...claims });
  return { call, user, mint, store, now: () => t };
}

test('invite flow: editor can edit flows but not logins; viewer is read-only; remove works; audit records it', async () => {
  const s = await setup(); const owner = await s.user('o@x.com'), ed = await s.user('e@x.com'), vw = await s.user('v@x.com');
  const inv = async (email, role) => (await (await s.call('POST', '/v1/team/invite', { email, role }, owner.tok)).json()).code;
  assert.equal((await s.call('POST', '/v1/team/accept', { code: await inv('e@x.com', 'editor') }, ed.tok)).status, 200);
  assert.equal((await s.call('POST', '/v1/team/accept', { code: await inv('v@x.com', 'viewer') }, vw.tok)).status, 200);
  assert.equal((await s.call('POST', '/v1/team/accept', { code: await inv('someone@else.com', 'viewer') }, vw.tok)).status, 403);   // invite for another email
  const H = (u) => ({ 'X-Tenant': owner.tid });
  const cfg = await (await s.call('GET', '/v1/config', undefined, ed.tok, H())).json();
  const flow = { id: 'r1', target: { type: 'instagram', conn: 'ig1' } };
  assert.equal((await s.call('PUT', '/v1/config', { routes: [flow], v: cfg.v }, ed.tok, H())).status, 200);                  // editor edits
  assert.equal((await s.call('PUT', '/v1/secrets/ig1', { fields: { a: 'b' } }, ed.tok, H())).status, 403);                  // not logins
  assert.equal((await s.call('GET', '/v1/config', undefined, vw.tok, H())).status, 200);                                     // viewer reads
  assert.equal((await s.call('PUT', '/v1/config', { routes: [], v: 1 }, vw.tok, H())).status, 403);                          // viewer cannot write
  assert.equal((await s.call('GET', '/v1/team', undefined, ed.tok, H())).status, 403);
  assert.equal((await (await s.call('GET', '/v1/team', undefined, owner.tok)).json()).members.length, 2);
  await s.call('POST', '/v1/team/remove', { email: 'e@x.com' }, owner.tok);
  assert.equal((await s.call('GET', '/v1/config', undefined, ed.tok, H())).status, 401);                                     // access gone
  const log = await (await s.call('GET', '/v1/audit', undefined, owner.tok)).json(); assert.ok(log.some((x) => /removed/.test(x.what)) && log.some((x) => /saved settings/.test(x.what)));
  const stranger = await s.user('s@x.com'); assert.equal((await s.call('GET', '/v1/config', undefined, stranger.tok, H())).status, 401);   // not a member at all
});

test('plan sync accepts only a valid signed plan, and raises the account limit', async () => {
  const s = await setup(); const o = await s.user('o@x.com');
  assert.equal((await s.call('POST', '/v1/plan/sync', { token: 'garbage' }, o.tok)).status, 400);
  assert.equal((await s.call('POST', '/v1/plan/sync', { token: await s.mint({ plan: 'pro', exp: s.now() - 5 }) }, o.tok)).status, 400);   // expired
  assert.equal((await s.call('POST', '/v1/plan/sync', { token: await s.mint({ plan: 'pro' }) }, o.tok)).status, 200);
  const c = await (await s.call('GET', '/v1/config', undefined, o.tok)).json();
  const r = (id, conn) => ({ id, target: { conn } });
  assert.equal((await s.call('PUT', '/v1/config', { routes: [r('a', '1'), r('b', '2'), r('c', '3')], v: c.v }, o.tok)).status, 200);
});

test('admin: list, suspend (blocks login-use and leases), unsuspend, set plan, stats', async () => {
  const s = await setup(); const o = await s.user('o@x.com'); const A = { Authorization: 'Bearer adm' };
  assert.equal((await s.call('GET', '/v1/admin/tenants')).status, 401); assert.equal((await s.call('GET', '/v1/admin/tenants', undefined, 'nope')).status, 401);
  const c = await (await s.call('GET', '/v1/config', undefined, o.tok)).json(); await s.call('PUT', '/v1/config', { routes: [{ id: 'r1', target: { conn: 'ig' } }], v: c.v }, o.tok);
  assert.equal((await (await s.call('GET', '/v1/admin/tenants', undefined, 'adm')).json()).tenants[0].flows, 1);
  await s.call('POST', '/v1/admin/suspend', { tenant: o.tid }, 'adm');
  assert.equal((await s.call('GET', '/v1/config', undefined, o.tok)).status, 403);
  assert.equal((await (await s.call('POST', '/v1/internal/lease', {}, 'wk')).json()).lease, null);
  await s.call('POST', '/v1/admin/suspend', { tenant: o.tid, on: false }, 'adm'); assert.equal((await s.call('GET', '/v1/config', undefined, o.tok)).status, 200);
  await s.call('POST', '/v1/admin/plan', { tenant: o.tid, plan: 'pro' }, 'adm'); const st = await (await s.call('GET', '/v1/admin/stats', undefined, 'adm')).json(); assert.equal(st.paid, 1);
});

test('worker pull/push: gets config+secrets+queue+inbox, pushes back, acks inbox, dedups ledger', async () => {
  const s = await setup(); const o = await s.user('o@x.com'); const W = 'wk';
  const c = await (await s.call('GET', '/v1/config', undefined, o.tok)).json(); await s.call('PUT', '/v1/config', { routes: [{ id: 'r1', target: { conn: 'ig' } }], v: c.v }, o.tok);
  await s.call('PUT', '/v1/secrets/ig', { fields: { access_token: 'T' } }, o.tok); await s.call('POST', '/v1/inbox', { cmd: 'skip', key: 'k' }, o.tok);
  const pull = await (await s.call('POST', '/v1/internal/pull', { tenant: o.tid, route: 'r1' }, W)).json();
  assert.equal(pull.secrets.ig.access_token, 'T'); assert.equal(pull.inbox.length, 1); assert.equal(pull.config.routes[0].id, 'r1');
  const e1 = { id: 'x1', target: 'instagram:ig', src: 'd:1', md5: 'm' };
  let r = await (await s.call('POST', '/v1/internal/push', { tenant: o.tid, route: 'r1', queue: { items: [{ key: 'd:1', status: 'posted' }] }, status: { run: 1 }, ledger: [e1, { ...e1, id: 'x2' }], ack_inbox: [pull.inbox[0]._key] }, W)).json();
  assert.equal(r.duplicates, 1);
  assert.deepEqual((await (await s.call('GET', '/v1/status', undefined, o.tok)).json()), { run: 1 });
  assert.equal((await (await s.call('GET', '/v1/queue/r1', undefined, o.tok)).json()).items[0].status, 'posted');
  assert.equal((await (await s.call('POST', '/v1/internal/pull', { tenant: o.tid, route: 'r1' }, W)).json()).inbox.length, 0);
});
