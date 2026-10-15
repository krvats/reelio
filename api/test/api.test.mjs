import test from 'node:test';
import assert from 'node:assert/strict';
import { createApi, MemoryStore } from '../src/index.js';

const master = Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url');
function setup(plans = { pro: { accounts: 3, posts_month: 600 } }) {
  let t = 1_800_000_000; const store = new MemoryStore();
  const api = createApi({ store, env: { MASTER_KEY: master, WORKER_SECRET: 'wk' }, now: () => t, plans });
  const call = (m, p, body, tok, extra = {}) => api(new Request('https://x.test' + p, { method: m, headers: { 'Content-Type': 'application/json', ...(tok ? { Authorization: 'Bearer ' + tok } : {}), ...extra }, body: body === undefined ? undefined : JSON.stringify(body) }));
  const user = async (email) => { const r = await call('POST', '/v1/auth/signup', { email, password: 'correct horse' }); const j = await r.json(); return { tok: j.token, tid: j.tenant }; };
  return { call, store, user, advance: (s) => { t += s; } };
}
const W = 'wk';
const route = (id, conn) => ({ id, name: id, enabled: true, target: { type: 'instagram', conn }, source: { type: 'drive' }, schedule: { per_day: 5 } });

test('signup, login, wrong password, duplicate, weak password', async () => {
  const s = setup(); const a = await s.user('a@x.com'); assert.ok(a.tok);
  assert.equal((await s.call('POST', '/v1/auth/signup', { email: 'a@x.com', password: 'whatever123' })).status, 409);
  assert.equal((await s.call('POST', '/v1/auth/signup', { email: 'b@x.com', password: 'short' })).status, 400);
  assert.equal((await s.call('POST', '/v1/auth/login', { email: 'a@x.com', password: 'nope nope nope' })).status, 401);
  const ok = await s.call('POST', '/v1/auth/login', { email: 'A@X.com', password: 'correct horse' }); assert.equal(ok.status, 200);
  assert.equal((await s.call('GET', '/v1/me')).status, 401);
  assert.equal((await (await s.call('GET', '/v1/me', undefined, a.tok)).json()).email, 'a@x.com');
});

test('sessions expire and logout kills them', async () => {
  const s = setup(); const a = await s.user('a@x.com');
  await s.call('POST', '/v1/auth/logout', {}, a.tok); assert.equal((await s.call('GET', '/v1/me', undefined, a.tok)).status, 401);
  const b = await s.user('b@x.com'); s.advance(31 * 86400); assert.equal((await s.call('GET', '/v1/me', undefined, b.tok)).status, 401);
});

test('login is rate limited', async () => {
  const s = setup(); let last = 0; for (let i = 0; i < 25; i++) last = (await s.call('POST', '/v1/auth/login', { email: 'z@x.com', password: 'x' })).status; assert.equal(last, 429);
});

test('config: optimistic concurrency and plan account limit', async () => {
  const s = setup(); const a = await s.user('a@x.com');
  let c = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  const put = (cfg, v) => s.call('PUT', '/v1/config', { ...cfg, v }, a.tok);
  assert.equal((await put({ routes: [route('r1', 'ig1')] }, c.v)).status, 200);
  assert.equal((await put({ routes: [route('r1', 'ig1')] }, c.v)).status, 409);                       // stale version
  c = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  assert.equal((await put({ routes: [route('r1', 'ig1'), route('r2', 'ig2')] }, c.v)).status, 402);   // free plan = 1 account
});

test('tenant isolation: B can never read or change A', async () => {
  const s = setup(); const a = await s.user('a@x.com'); const b = await s.user('b@x.com');
  const ca = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  await s.call('PUT', '/v1/config', { routes: [route('secretflow', 'ig1')], v: ca.v }, a.tok);
  await s.call('PUT', '/v1/secrets/ig1', { fields: { access_token: 'TOPSECRET' } }, a.tok);
  await s.call('POST', '/v1/inbox', { cmd: 'skip' }, a.tok);
  const cb = await (await s.call('GET', '/v1/config', undefined, b.tok)).json(); assert.deepEqual(cb.routes, []);
  assert.deepEqual((await (await s.call('GET', '/v1/secrets', undefined, b.tok)).json()).connected, []);
  assert.deepEqual((await (await s.call('GET', '/v1/queue/secretflow', undefined, b.tok)).json()).items, []);
  const dump = JSON.stringify([...s.store.m.entries()].filter(([k]) => k.startsWith(`t:${b.tid}:`)));
  assert.ok(!dump.includes('secretflow') && !dump.includes('TOPSECRET'));
});

test('secrets are encrypted at rest, never returned to the browser, readable by workers only', async () => {
  const s = setup(); const a = await s.user('a@x.com');
  await s.call('PUT', '/v1/secrets/ig1', { fields: { access_token: 'TOPSECRET123' } }, a.tok);
  await s.call('PUT', '/v1/secrets/ig1', { fields: { extra: 'v2' } }, a.tok);                          // merges
  const raw = JSON.stringify([...s.store.m.values()]); assert.ok(!raw.includes('TOPSECRET123'), 'plaintext must not be stored');
  const names = await (await s.call('GET', '/v1/secrets', undefined, a.tok)).json(); assert.deepEqual(names.connected, ['ig1']); assert.ok(!JSON.stringify(names).includes('TOPSECRET'));
  assert.equal((await s.call('POST', '/v1/internal/secrets', { tenant: a.tid })).status, 401);
  assert.equal((await s.call('POST', '/v1/internal/secrets', { tenant: a.tid }, a.tok)).status, 401);   // a user token is not a worker key
  const got = await (await s.call('POST', '/v1/internal/secrets', { tenant: a.tid }, W)).json(); assert.deepEqual(got.ig1, { access_token: 'TOPSECRET123', extra: 'v2' });
  await s.call('DELETE', '/v1/secrets/ig1', undefined, a.tok); assert.deepEqual(await (await s.call('POST', '/v1/internal/secrets', { tenant: a.tid }, W)).json(), {});
});

test('leases: a flow goes to one worker at a time, expires, and can be released', async () => {
  const s = setup(); const a = await s.user('a@x.com'); const c = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  await s.call('PUT', '/v1/config', { routes: [route('r1', 'ig1')], v: c.v }, a.tok);
  const l1 = await (await s.call('POST', '/v1/internal/lease', { worker: 'w1', seconds: 60 }, W)).json(); assert.equal(l1.route.id, 'r1'); assert.equal(l1.tenant, a.tid);
  assert.equal((await (await s.call('POST', '/v1/internal/lease', { worker: 'w2' }, W)).json()).lease, null);   // already leased
  s.advance(61); const l2 = await (await s.call('POST', '/v1/internal/lease', { worker: 'w2' }, W)).json(); assert.ok(l2.lease);   // crashed worker: lease expired
  await s.call('POST', '/v1/internal/release', { tenant: a.tid, route: 'r1', lease: l2.lease }, W);
  assert.ok((await (await s.call('POST', '/v1/internal/lease', { worker: 'w3' }, W)).json()).lease);
  const l4 = await (await s.call('POST', '/v1/internal/lease', { worker: 'w4', exclude: [[a.tid, 'r1']] }, W)).json(); assert.equal(l4.lease, null);   // excluded for this worker pass
});

test('paused tenants and disabled flows are never leased', async () => {
  const s = setup(); const a = await s.user('a@x.com'); const c = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  await s.call('PUT', '/v1/config', { routes: [{ ...route('r1', 'ig1'), enabled: false }], v: c.v }, a.tok);
  assert.equal((await (await s.call('POST', '/v1/internal/lease', {}, W)).json()).lease, null);
  const c2 = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  await s.call('PUT', '/v1/config', { routes: [route('r1', 'ig1')], paused: true, v: c2.v }, a.tok);
  assert.equal((await (await s.call('POST', '/v1/internal/lease', {}, W)).json()).lease, null);
});

test('ledger is exactly-once per target by source id and by content', async () => {
  const s = setup(); const a = await s.user('a@x.com'); const post = (entry) => s.call('POST', '/v1/internal/ledger', { tenant: a.tid, entry }, W);
  assert.equal((await post({ target: 'instagram:ig1', src: 'drive:1', md5: 'aa' })).status, 201);
  assert.equal((await post({ target: 'instagram:ig1', src: 'drive:1', md5: 'bb' })).status, 409);       // same source
  assert.equal((await post({ target: 'instagram:ig1', src: 'drive:2', md5: 'aa' })).status, 409);       // same content, new name
  assert.equal((await post({ target: 'instagram:ig2', src: 'drive:1', md5: 'aa' })).status, 201);       // other account may post it
  assert.equal((await (await s.call('GET', '/v1/ledger', undefined, a.tok)).json()).entries.length, 2);
});

test('missing master key fails safely without leaking', async () => {
  const store = new MemoryStore(); const api = createApi({ store, env: {} });
  const r = await api(new Request('https://x.test/v1/auth/signup', { method: 'POST', body: JSON.stringify({ email: 'a@x.com', password: 'longenough1' }) })); assert.equal(r.status, 201);
  const tok = (await r.json()).token;
  const r2 = await api(new Request('https://x.test/v1/secrets/x', { method: 'PUT', headers: { Authorization: 'Bearer ' + tok }, body: JSON.stringify({ fields: { a: 'b' } }) }));
  assert.equal(r2.status, 500); assert.ok(!(await r2.text()).includes('MASTER_KEY'));
});

test('state, inbox drain, status merge and plan change', async () => {
  const s = setup(); const a = await s.user('a@x.com'); const c = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  await s.call('PUT', '/v1/config', { routes: [route('r1', 'ig1')], v: c.v }, a.tok);
  await s.call('POST', '/v1/inbox', { cmd: 'skip', route: 'r1', key: 'drive:1' }, a.tok);
  const st = await (await s.call('POST', '/v1/internal/state', { tenant: a.tid, route: 'r1' }, W)).json(); assert.equal(st.inbox.length, 1);
  await s.call('POST', '/v1/internal/inbox-done', { tenant: a.tid, keys: st.inbox.map((x) => x._k) }, W);
  assert.equal((await (await s.call('POST', '/v1/internal/state', { tenant: a.tid, route: 'r1' }, W)).json()).inbox.length, 0);
  await s.call('POST', '/v1/internal/status', { tenant: a.tid, route: 'r1', status: { routes: { r1: { state: 'idle' }, other: { state: 'x' } }, recent: [{ at: 'a', msg: 'one' }] } }, W);
  await s.call('POST', '/v1/internal/status', { tenant: a.tid, route: 'r2', status: { routes: { r2: { state: 'ok' } }, recent: [{ at: 'b', msg: 'two' }] } }, W);
  const got = await (await s.call('GET', '/v1/status', undefined, a.tok)).json(); assert.deepEqual(Object.keys(got.routes).sort(), ['r1', 'r2']); assert.equal(got.recent.length, 2);
  await s.call('POST', '/v1/internal/plan', { tenant: a.tid, plan: 'pro' }, W);
  const c2 = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  assert.equal((await s.call('PUT', '/v1/config', { routes: [route('r1', 'a'), route('r2', 'b'), route('r3', 'c')], v: c2.v }, a.tok)).status, 200);   // pro = 3 accounts
});

test('release with a cooldown keeps a flow from running again right away', async () => {
  const s = setup(); const a = await s.user('a@x.com'); const c = await (await s.call('GET', '/v1/config', undefined, a.tok)).json();
  await s.call('PUT', '/v1/config', { routes: [route('r1', 'ig1')], v: c.v }, a.tok);
  const l = await (await s.call('POST', '/v1/internal/lease', { worker: 'w1' }, W)).json();
  await s.call('POST', '/v1/internal/release', { tenant: a.tid, route: 'r1', lease: l.lease, cooldown: 240 }, W);
  assert.equal((await (await s.call('POST', '/v1/internal/lease', { worker: 'w2' }, W)).json()).lease, null);
});
