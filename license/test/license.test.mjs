import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../src/index.js';
import { MemoryStore } from '../src/store.js';
import { b64u, unb64u, hmacHex, verifyToken } from '../src/crypto.js';

const subtle = globalThis.crypto.subtle;
const enc = new TextEncoder();

async function signingJwk() {
  const kp = await subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
  return subtle.exportKey('jwk', kp.privateKey);
}

async function setup(extra = {}) {
  let t = 1_800_000_000;
  const env = {
    SIGNING_KEY_JWK: await signingJwk(), ADMIN_SECRET: 'adm', STRIPE_SECRET_KEY: 'sk', STRIPE_WEBHOOK_SECRET: 'whs',
    RAZORPAY_KEY_ID: 'rk', RAZORPAY_KEY_SECRET: 'rs', RAZORPAY_WEBHOOK_SECRET: 'rws', ...extra.env,
  };
  const plans = { starter: { name: 'S', accounts: 3, posts_month: 600, devices: 1, stripe_price: 'price_s', razorpay_plan: 'plan_s' }, pro: { name: 'P', accounts: 15, posts_month: 6000, devices: 3, stripe_price: 'price_p', razorpay_plan: 'plan_p' } };
  env.PLANS = plans;
  const calls = [];
  const fetchImpl = async (url, opt) => {
    calls.push({ url, opt });
    if (url.includes('checkout/sessions')) return new Response(JSON.stringify({ url: 'https://stripe.test/pay' }), { status: 200 });
    if (url.includes('billing_portal')) return new Response(JSON.stringify({ url: 'https://stripe.test/portal' }), { status: 200 });
    if (url.includes('razorpay')) return new Response(JSON.stringify({ short_url: 'https://rzp.test/pay' }), { status: 200 });
    return new Response('{}', { status: 404 });
  };
  const app = createApp({ store: new MemoryStore(), env, now: () => t, fetchImpl });
  const call = (method, path, body, headers = {}) => app(new Request('https://x.test' + path, { method, headers: { 'Content-Type': 'application/json', ...headers }, body: body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)) }));
  return { app, call, env, calls, advance: (s) => { t += s; }, now: () => t };
}

async function newDevice(call) {
  const kp = await subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const jwk = await subtle.exportKey('jwk', kp.publicKey);
  const pub = { kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y };
  const r = await call('POST', '/v1/device/register', { pub });
  const { deviceId } = await r.json();
  const sign = async (purpose, extra = {}) => {
    const c = await (await call('POST', '/v1/challenge', { deviceId })).json();
    const sig = b64u(await subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, kp.privateKey, enc.encode(`reelio:${purpose}:${c.nonce}:${deviceId}`)));
    return { deviceId, nonce: c.nonce, sig, ...extra };
  };
  return { deviceId, sign, kp };
}

const stripeEvent = async (call, env, now, ev) => {
  const raw = JSON.stringify(ev); const ts = now();
  const v1 = await hmacHex(env.STRIPE_WEBHOOK_SECRET, `${ts}.${raw}`);
  return call('POST', '/v1/webhook/stripe', raw, { 'Stripe-Signature': `t=${ts},v1=${v1}` });
};
const paidSession = (id, dev, cust = 'cus_1', plan = 'pro') => ({ id, type: 'checkout.session.completed', data: { object: { mode: 'subscription', client_reference_id: dev, customer: cust, subscription: 'sub_1', metadata: { deviceId: dev, plan } } } });

test('unpaid device gets 402, never a token', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  const r = await s.call('POST', '/v1/entitlement', await d.sign('entitlement'));
  assert.equal(r.status, 402); const j = await r.json(); assert.equal(j.active, false); assert.equal(j.token, undefined);
});

test('register is idempotent and deviceId is stable', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  const kp = d.kp; const jwk = await subtle.exportKey('jwk', kp.publicKey);
  const r = await (await s.call('POST', '/v1/device/register', { pub: { kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y } })).json();
  assert.equal(r.deviceId, d.deviceId);
  assert.equal((await s.call('POST', '/v1/device/register', { pub: { kty: 'EC' } })).status, 400);
});

test('payment webhook silently unlocks the device; token verifies offline and is bound to device', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  const w = await stripeEvent(s.call, s.env, s.now, paidSession('evt_1', d.deviceId)); assert.equal(w.status, 200);
  const r = await s.call('POST', '/v1/entitlement', await d.sign('entitlement')); assert.equal(r.status, 200);
  const j = await r.json(); assert.equal(j.state, 'active'); assert.equal(j.claims.cnf, d.deviceId); assert.equal(j.claims.lim.accounts, 15);
  const pubJwk = await (await s.call('GET', '/v1/keys')).json();
  const claims = await verifyToken(pubJwk.x, j.token, s.now()); assert.equal(claims.sub, d.deviceId);
  // tampered token fails
  const bad = j.token.slice(0, -4) + (j.token.endsWith('AAAA') ? 'BBBB' : 'AAAA');
  await assert.rejects(() => verifyToken(pubJwk.x, bad, s.now()));
  await assert.rejects(() => verifyToken(pubJwk.x, j.token, s.now() + 90000), /expired/);
});

test('nonce is one-time: replay is rejected', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  await stripeEvent(s.call, s.env, s.now, paidSession('evt_1', d.deviceId));
  const body = await d.sign('entitlement');
  assert.equal((await s.call('POST', '/v1/entitlement', body)).status, 200);
  assert.equal((await s.call('POST', '/v1/entitlement', body)).status, 401);
});

test('signature from another device or another purpose is rejected', async () => {
  const s = await setup(); const a = await newDevice(s.call); const b = await newDevice(s.call);
  const c = await (await s.call('POST', '/v1/challenge', { deviceId: a.deviceId })).json();
  const sig = b64u(await subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, b.kp.privateKey, enc.encode(`reelio:entitlement:${c.nonce}:${a.deviceId}`)));
  assert.equal((await s.call('POST', '/v1/entitlement', { deviceId: a.deviceId, nonce: c.nonce, sig })).status, 401);
  const body = await a.sign('checkout'); // signed for checkout, used for entitlement
  assert.equal((await s.call('POST', '/v1/entitlement', body)).status, 401);
});

test('stripe webhook: bad signature, stale, duplicate', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  const raw = JSON.stringify(paidSession('evt_9', d.deviceId));
  assert.equal((await s.call('POST', '/v1/webhook/stripe', raw, { 'Stripe-Signature': `t=${s.now()},v1=deadbeef` })).status, 400);
  const old = s.now() - 1000; const v1 = await hmacHex(s.env.STRIPE_WEBHOOK_SECRET, `${old}.${raw}`);
  assert.equal((await s.call('POST', '/v1/webhook/stripe', raw, { 'Stripe-Signature': `t=${old},v1=${v1}` })).status, 400);
  assert.equal((await stripeEvent(s.call, s.env, s.now, paidSession('evt_9', d.deviceId))).status, 200);
  const dup = await (await stripeEvent(s.call, s.env, s.now, paidSession('evt_9', d.deviceId))).json(); assert.equal(dup.duplicate, true);
});

test('payment failure gives grace, then locks; cancel locks at once; paid again unlocks', async () => {
  const s = await setup(); const d = await newDevice(s.call); const ent = async () => (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).status;
  await stripeEvent(s.call, s.env, s.now, paidSession('e1', d.deviceId));
  await stripeEvent(s.call, s.env, s.now, { id: 'e2', type: 'customer.subscription.updated', data: { object: { id: 'sub_1', customer: 'cus_1', status: 'past_due', current_period_end: s.now() } } });
  assert.equal(await ent(), 200);
  const j = await (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).json(); assert.equal(j.state, 'grace');
  s.advance(4 * 86400); assert.equal(await ent(), 402);
  await stripeEvent(s.call, s.env, s.now, { id: 'e3', type: 'invoice.paid', data: { object: { subscription: 'sub_1', customer: 'cus_1', lines: { data: [{ period: { end: s.now() + 2592000 } }] } } } });
  assert.equal(await ent(), 200);
  await stripeEvent(s.call, s.env, s.now, { id: 'e4', type: 'customer.subscription.deleted', data: { object: { id: 'sub_1', customer: 'cus_1', status: 'canceled' } } });
  assert.equal(await ent(), 402);
});

test('razorpay webhook verifies signature and unlocks by notes.deviceId', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  const ev = { event: 'subscription.activated', created_at: 1, payload: { subscription: { entity: { id: 'sub_r', customer_id: 'cust_r', current_end: s.now() + 999999, notes: { deviceId: d.deviceId, plan: 'starter' } } } } };
  const raw = JSON.stringify(ev);
  assert.equal((await s.call('POST', '/v1/webhook/razorpay', raw, { 'X-Razorpay-Signature': 'nope' })).status, 400);
  const sig = await hmacHex(s.env.RAZORPAY_WEBHOOK_SECRET, raw);
  assert.equal((await s.call('POST', '/v1/webhook/razorpay', raw, { 'X-Razorpay-Signature': sig })).status, 200);
  const j = await (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).json(); assert.equal(j.claims.plan, 'starter');
  const ev2 = { ...ev, event: 'subscription.cancelled', created_at: 2 }; const raw2 = JSON.stringify(ev2);
  await s.call('POST', '/v1/webhook/razorpay', raw2, { 'X-Razorpay-Signature': await hmacHex(s.env.RAZORPAY_WEBHOOK_SECRET, raw2) });
  assert.equal((await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).status, 402);
});

test('checkout passes deviceId to the provider so payment auto-binds', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  const r = await (await s.call('POST', '/v1/checkout', { ...(await d.sign('checkout')), plan: 'pro' })).json(); assert.equal(r.url, 'https://stripe.test/pay');
  assert.ok(String(s.calls.at(-1).opt.body).includes(encodeURIComponent(d.deviceId)) || String(s.calls.at(-1).opt.body).includes(d.deviceId));
  const r2 = await (await s.call('POST', '/v1/checkout', { ...(await d.sign('checkout')), plan: 'starter', provider: 'razorpay' })).json(); assert.equal(r2.provider, 'razorpay');
  assert.equal(JSON.parse(s.calls.at(-1).opt.body).notes.deviceId, d.deviceId);
  assert.equal((await s.call('POST', '/v1/checkout', { ...(await d.sign('checkout')), plan: 'zzz' })).status, 400);
});

test('admin: auth required; comp, revoke, stats', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  assert.equal((await s.call('POST', '/v1/admin/grant', { deviceId: d.deviceId })).status, 401);
  const H = { Authorization: 'Bearer adm' };
  assert.equal((await s.call('POST', '/v1/admin/grant', { deviceId: d.deviceId, days: 30 }, H)).status, 200);
  const j = await (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).json(); assert.equal(j.state, 'comped');
  const st = await (await s.call('POST', '/v1/admin/stats', {}, H)).json(); assert.equal(st.active, 1); assert.equal(st.devices, 1);
  assert.equal((await s.call('POST', '/v1/admin/revoke', { deviceId: d.deviceId }, H)).status, 200);
  assert.equal((await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).status, 402);
});

test('comp expires on its own', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  await s.call('POST', '/v1/admin/grant', { deviceId: d.deviceId, days: 1 }, { Authorization: 'Bearer adm' });
  s.advance(2 * 86400); assert.equal((await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).status, 402);
});

test('trial days unlock a new device only when configured', async () => {
  const s = await setup({ env: { TRIAL_DAYS: 2 } }); const d = await newDevice(s.call);
  const j = await (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).json(); assert.equal(j.state, 'trial');
  s.advance(3 * 86400); assert.equal((await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).status, 402);
});

test('link code adds a second device, respects seat limit, is one-time', async () => {
  const s = await setup(); const a = await newDevice(s.call); const b = await newDevice(s.call); const c = await newDevice(s.call);
  await stripeEvent(s.call, s.env, s.now, paidSession('e1', a.deviceId, 'cus_1', 'starter')); // 1 seat
  const code = (await (await s.call('POST', '/v1/link/create', await a.sign('link-create'))).json()).code; assert.ok(code);
  assert.equal((await s.call('POST', '/v1/link/redeem', { ...(await b.sign('link-redeem')), code })).status, 409);
  const s2 = await setup(); const a2 = await newDevice(s2.call); const b2 = await newDevice(s2.call);
  await stripeEvent(s2.call, s2.env, s2.now, paidSession('e1', a2.deviceId)); // pro: 3 seats
  const code2 = (await (await s2.call('POST', '/v1/link/create', await a2.sign('link-create'))).json()).code;
  assert.equal((await s2.call('POST', '/v1/link/redeem', { ...(await b2.sign('link-redeem')), code: code2 })).status, 200);
  assert.equal((await s2.call('POST', '/v1/entitlement', await b2.sign('entitlement'))).status, 200);
  assert.equal((await s2.call('POST', '/v1/link/redeem', { ...(await b2.sign('link-redeem')), code: code2 })).status, 404);
  assert.equal((await s2.call('POST', '/v1/link/create', await (await newDevice(s2.call)).sign('link-create'))).status, 402);
});

test('portal needs a stripe customer; rate limit and CORS work', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  assert.equal((await s.call('POST', '/v1/portal', await d.sign('portal'))).status, 404);
  await stripeEvent(s.call, s.env, s.now, paidSession('e1', d.deviceId));
  assert.equal((await (await s.call('POST', '/v1/portal', await d.sign('portal'))).json()).url, 'https://stripe.test/portal');
  const o = await s.app(new Request('https://x.test/v1/plans', { method: 'OPTIONS' })); assert.equal(o.status, 204);
  let last = 0; for (let i = 0; i < 35; i++) last = (await s.call('POST', '/v1/device/register', { pub: { kty: 'EC' } }, { 'CF-Connecting-IP': '9.9.9.9' })).status;
  assert.equal(last, 429);
});

test('token expiry is short and never outlives the paid period when not active-state', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  await s.call('POST', '/v1/admin/grant', { deviceId: d.deviceId, days: 1 }, { Authorization: 'Bearer adm' });
  const j = await (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).json();
  assert.ok(j.claims.exp - j.claims.iat <= 86400);
});

test('token carries worker-valid-until beyond the 24h exp, bounded by the paid period', async () => {
  const s = await setup(); const d = await newDevice(s.call);
  await stripeEvent(s.call, s.env, s.now, { id: 'e1', type: 'checkout.session.completed', data: { object: { mode: 'subscription', client_reference_id: d.deviceId, customer: 'c', subscription: 's', metadata: { deviceId: d.deviceId, plan: 'pro' } } } });
  await stripeEvent(s.call, s.env, s.now, { id: 'e2', type: 'customer.subscription.updated', data: { object: { id: 's', customer: 'c', status: 'active', current_period_end: s.now() + 10 * 86400 } } });
  const j = await (await s.call('POST', '/v1/entitlement', await d.sign('entitlement'))).json();
  assert.ok(j.claims.wv > j.claims.exp); assert.ok(j.claims.wv <= s.now() + 14 * 86400);
});
