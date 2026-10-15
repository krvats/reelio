// Reelio license service. Every device silently proves who it is with a key that never leaves the device;
// the server answers with a short-lived signed entitlement. No codes to type, no "verify your subscription" step.
import { b64u, unb64u, utf8, randomId, randomCode, deviceIdFromJwk, verifyDeviceSig, importSigner, signToken, hmacHex, safeEqual } from './crypto.js';
import { MemoryStore, KVStore } from './store.js';

const DAY = 86400;
const json = (obj, status = 200, extra = {}) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json', ...extra } });
const err = (status, code, msg) => json({ error: code, message: msg }, status);

export const DEFAULT_PLANS = {
  starter: { name: 'Starter', price_inr: 499, price_usd: 6, interval: 'month', accounts: 3, posts_month: 600, devices: 2, stripe_price: '', razorpay_plan: '' },
  pro: { name: 'Pro', price_inr: 1499, price_usd: 18, interval: 'month', accounts: 15, posts_month: 6000, devices: 5, stripe_price: '', razorpay_plan: '' },
  agency: { name: 'Agency', price_inr: 4999, price_usd: 60, interval: 'month', accounts: 100, posts_month: 60000, devices: 15, stripe_price: '', razorpay_plan: '' },
};

export function createApp({ store, env = {}, now = () => Math.floor(Date.now() / 1000), fetchImpl = (...a) => fetch(...a) } = {}) {
  const cfg = {
    ttl: Number(env.TOKEN_TTL_HOURS || 24) * 3600, grace: Number(env.GRACE_DAYS || 3) * DAY, trialDays: Number(env.TRIAL_DAYS || 0),
    plans: env.PLANS ? (typeof env.PLANS === 'string' ? JSON.parse(env.PLANS) : env.PLANS) : DEFAULT_PLANS,
    origins: String(env.ALLOWED_ORIGINS || '*').split(',').map((s) => s.trim()), kid: env.KEY_ID || 'k1',
  };
  let signer = null, publicX = null;
  async function key() {
    if (!signer) {
      const jwk = typeof env.SIGNING_KEY_JWK === 'string' ? JSON.parse(env.SIGNING_KEY_JWK) : env.SIGNING_KEY_JWK;
      if (!jwk) throw new Error('SIGNING_KEY_JWK is not set');
      signer = await importSigner(jwk); publicX = jwk.x;
    }
    return signer;
  }

  // ---------- state
  const getDevice = (id) => store.get(`dev:${id}`);
  const getAccount = (id) => store.get(`acc:${id}`);
  async function accountOf(device) { return device && device.account ? getAccount(device.account) : null; }

  /** Decide access from stored facts only. Returns {active, state, plan, until}. */
  function access(device, account, t) {
    if (account && account.comp && (account.comp.until == null || account.comp.until > t)) return { active: true, state: 'comped', plan: account.comp.plan || 'pro', until: account.comp.until };
    const s = account && account.sub;
    if (s) {
      if (s.status === 'active') return { active: true, state: 'active', plan: s.plan, until: s.period_end || null };
      if (s.status === 'past_due' && (s.period_end || 0) + cfg.grace > t) return { active: true, state: 'grace', plan: s.plan, until: (s.period_end || t) + cfg.grace };
    }
    if (device && device.trial_until && device.trial_until > t) return { active: true, state: 'trial', plan: 'starter', until: device.trial_until };
    return { active: false, state: s ? s.status : 'none', plan: null };
  }

  async function limited(request, bucket, max) {
    const ip = request.headers.get('CF-Connecting-IP') || request.headers.get('X-Forwarded-For') || 'local';
    const k = `rl:${bucket}:${ip}:${Math.floor(now() / 60)}`;
    const n = ((await store.get(k)) || 0) + 1;
    await store.put(k, n, { ttl: 120 });
    return n > max;
  }

  /** A signed proof that this request comes from the device that owns the key. */
  async function proof(body, purpose) {
    const { deviceId, nonce, sig } = body || {};
    if (!deviceId || !nonce || !sig) return { error: err(400, 'bad_request', 'Missing deviceId, nonce or sig.') };
    const dev = await getDevice(deviceId);
    if (!dev) return { error: err(404, 'unknown_device', 'This device is not registered.') };
    const n = await store.get(`nonce:${nonce}`);
    if (!n || n.deviceId !== deviceId) return { error: err(401, 'bad_nonce', 'Challenge expired or already used.') };
    await store.del(`nonce:${nonce}`);                                    // one-time: a captured request cannot be replayed
    if (!(await verifyDeviceSig(dev.pub, `reelio:${purpose}:${nonce}:${deviceId}`, sig))) return { error: err(401, 'bad_signature', 'Signature does not match this device.') };
    return { dev };
  }

  async function issue(device, account, acc) {
    const plan = cfg.plans[acc.plan] || {};
    const lim = { accounts: plan.accounts || 3, posts_month: plan.posts_month || 600, devices: plan.devices || 1 };
    const t = now();
    const claims = { iss: 'reelio-license', sub: device.id, acct: device.account || null, st: acc.state, plan: acc.plan, lim, iat: t, wv: acc.state === 'trial' ? acc.until : (acc.until || t + 35 * DAY) + (acc.state === 'active' ? cfg.grace : 0), exp: Math.min(t + cfg.ttl, acc.until && acc.state !== 'active' ? acc.until : t + cfg.ttl), cnf: device.id };
    return { token: await signToken(await key(), cfg.kid, claims), claims };
  }

  // ---------- providers (injectable for tests)
  async function createCheckout(body, dev) {
    const plan = cfg.plans[body.plan]; if (!plan) return err(400, 'bad_plan', 'Unknown plan.');
    const returnUrl = body.return_url || env.RETURN_URL || '';
    if (body.provider === 'razorpay') {
      if (!plan.razorpay_plan || !env.RAZORPAY_KEY_ID) return err(501, 'provider_off', 'Razorpay is not configured.');
      const r = await fetchImpl('https://api.razorpay.com/v1/subscriptions', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Basic ' + btoa(`${env.RAZORPAY_KEY_ID}:${env.RAZORPAY_KEY_SECRET}`) },
        body: JSON.stringify({ plan_id: plan.razorpay_plan, total_count: 120, customer_notify: 1, notes: { deviceId: dev.id, plan: body.plan } }) });
      const j = await r.json(); if (!r.ok || !j.short_url) return err(502, 'provider_error', (j.error && j.error.description) || 'Razorpay refused.');
      return json({ url: j.short_url, provider: 'razorpay' });
    }
    if (!plan.stripe_price || !env.STRIPE_SECRET_KEY) return err(501, 'provider_off', 'Stripe is not configured.');
    const f = new URLSearchParams({ mode: 'subscription', 'line_items[0][price]': plan.stripe_price, 'line_items[0][quantity]': '1', client_reference_id: dev.id, 'metadata[deviceId]': dev.id, 'metadata[plan]': body.plan,
      'subscription_data[metadata][deviceId]': dev.id, 'subscription_data[metadata][plan]': body.plan, success_url: returnUrl || 'https://example.com/?paid=1', cancel_url: returnUrl || 'https://example.com/' });
    const r = await fetchImpl('https://api.stripe.com/v1/checkout/sessions', { method: 'POST', headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: f });
    const j = await r.json(); if (!r.ok || !j.url) return err(502, 'provider_error', (j.error && j.error.message) || 'Stripe refused.');
    return json({ url: j.url, provider: 'stripe' });
  }

  async function link(devId, accId) {
    const dev = await getDevice(devId); if (!dev) return;
    dev.account = accId; await store.put(`dev:${devId}`, dev);
    const acc = (await getAccount(accId)) || { id: accId, devices: [], created: now() };
    if (!acc.devices.includes(devId)) acc.devices.push(devId);
    await store.put(`acc:${accId}`, acc); return acc;
  }
  async function setSub(accId, patch) {
    const acc = (await getAccount(accId)) || { id: accId, devices: [], created: now() };
    acc.sub = { ...(acc.sub || {}), ...patch, updated: now() }; await store.put(`acc:${accId}`, acc); return acc;
  }

  // ---------- webhooks
  async function stripeWebhook(request) {
    const raw = await request.text(); const hdr = request.headers.get('Stripe-Signature') || '';
    const parts = Object.fromEntries(hdr.split(',').map((x) => x.split('=')));
    if (!env.STRIPE_WEBHOOK_SECRET || !parts.t || !parts.v1) return err(400, 'bad_signature', 'Missing signature.');
    if (Math.abs(now() - Number(parts.t)) > 300) return err(400, 'stale', 'Signature too old.');
    if (!safeEqual(await hmacHex(env.STRIPE_WEBHOOK_SECRET, `${parts.t}.${raw}`), parts.v1)) return err(400, 'bad_signature', 'Signature mismatch.');
    const ev = JSON.parse(raw); const o = ev.data && ev.data.object || {};
    if (await store.get(`evt:${ev.id}`)) return json({ ok: true, duplicate: true });
    await store.put(`evt:${ev.id}`, 1, { ttl: 7 * DAY });
    const map = { active: 'active', trialing: 'active', past_due: 'past_due', canceled: 'inactive', unpaid: 'inactive', incomplete_expired: 'inactive' };
    if (ev.type === 'checkout.session.completed' && o.mode === 'subscription') {
      const dev = o.client_reference_id || (o.metadata || {}).deviceId; const accId = `stripe:${o.customer}`;
      if (dev) { await link(dev, accId); }
      await setSub(accId, { provider: 'stripe', status: 'active', plan: (o.metadata || {}).plan || 'starter', sub_id: o.subscription, customer: o.customer });
      await store.put(`subidx:${o.subscription}`, accId);
    } else if (ev.type.startsWith('customer.subscription.')) {
      const accId = (await store.get(`subidx:${o.id}`)) || `stripe:${o.customer}`;
      const status = ev.type === 'customer.subscription.deleted' ? 'inactive' : (map[o.status] || 'inactive');
      const plan = (o.metadata || {}).plan; await setSub(accId, { status, ...(plan ? { plan } : {}), period_end: o.current_period_end, sub_id: o.id, customer: o.customer });
      await store.put(`subidx:${o.id}`, accId);
    } else if (ev.type === 'invoice.payment_failed') {
      const accId = (await store.get(`subidx:${o.subscription}`)) || `stripe:${o.customer}`; await setSub(accId, { status: 'past_due' });
    } else if (ev.type === 'invoice.paid') {
      const accId = (await store.get(`subidx:${o.subscription}`)) || `stripe:${o.customer}`; await setSub(accId, { status: 'active', ...(o.lines && o.lines.data && o.lines.data[0] ? { period_end: o.lines.data[0].period.end } : {}) });
    }
    return json({ ok: true });
  }

  async function razorpayWebhook(request) {
    const raw = await request.text();
    if (!env.RAZORPAY_WEBHOOK_SECRET || !safeEqual(await hmacHex(env.RAZORPAY_WEBHOOK_SECRET, raw), request.headers.get('X-Razorpay-Signature') || '')) return err(400, 'bad_signature', 'Signature mismatch.');
    const ev = JSON.parse(raw); const s = (((ev.payload || {}).subscription || {}).entity) || {};
    const evId = request.headers.get('X-Razorpay-Event-Id') || `${ev.event}:${s.id}:${ev.created_at}`;
    if (await store.get(`evt:${evId}`)) return json({ ok: true, duplicate: true });
    await store.put(`evt:${evId}`, 1, { ttl: 7 * DAY });
    const accId = `razorpay:${s.customer_id || s.id}`; const dev = (s.notes || {}).deviceId;
    const st = { 'subscription.activated': 'active', 'subscription.charged': 'active', 'subscription.resumed': 'active', 'subscription.pending': 'past_due', 'subscription.halted': 'inactive', 'subscription.cancelled': 'inactive', 'subscription.completed': 'inactive', 'subscription.paused': 'inactive' }[ev.event];
    if (st) {
      if (dev) await link(dev, accId);
      const known = (await store.get(`subidx:${s.id}`)) || accId; await store.put(`subidx:${s.id}`, known);
      await setSub(known, { provider: 'razorpay', status: st, plan: (s.notes || {}).plan, sub_id: s.id, period_end: s.current_end });
    }
    return json({ ok: true });
  }

  // ---------- routes
  const adminOk = (request) => env.ADMIN_SECRET && safeEqual((request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, ''), env.ADMIN_SECRET);

  async function handle(request) {
    const url = new URL(request.url); const p = url.pathname; const m = request.method;
    if (m === 'GET' && p === '/v1/keys') { await key(); return json({ kid: cfg.kid, alg: 'EdDSA', x: publicX }); }
    if (m === 'GET' && p === '/v1/plans') return json({ plans: cfg.plans, trial_days: cfg.trialDays });
    if (m === 'GET' && p === '/v1/upi/info') return json({ enabled: !!env.UPI_VPA, vpa: env.UPI_VPA || '', name: env.UPI_NAME || 'Reelio', plans: Object.fromEntries(Object.entries(cfg.plans).map(([k, v]) => [k, { name: v.name, price_inr: v.price_inr }])) });
    if (m === 'GET' && p === '/health') return json({ ok: true });
    if (m === 'POST' && p === '/v1/webhook/stripe') return stripeWebhook(request);
    if (m === 'POST' && p === '/v1/webhook/razorpay') return razorpayWebhook(request);
    if (p.startsWith('/v1/admin/')) {
      if (!adminOk(request)) return err(401, 'unauthorized', 'Admin key required.');
      const b = m === 'POST' ? await request.json().catch(() => ({})) : {};
      if (p === '/v1/admin/grant') {
        const dev = b.deviceId && await getDevice(b.deviceId); const accId = b.accountId || (dev && dev.account) || (b.deviceId && `comp:${b.deviceId}`);
        if (!accId) return err(400, 'bad_request', 'deviceId or accountId needed.');
        if (b.deviceId) await link(b.deviceId, accId);
        const acc = (await getAccount(accId)) || { id: accId, devices: [], created: now() };
        acc.comp = { plan: b.plan || 'pro', until: b.days ? now() + b.days * DAY : null, note: b.note || '' }; await store.put(`acc:${accId}`, acc); return json({ ok: true, accountId: accId });
      }
      if (p === '/v1/admin/revoke') {
        const accId = b.accountId || ((await getDevice(b.deviceId)) || {}).account; const acc = accId && await getAccount(accId);
        if (!acc) return err(404, 'not_found', 'No such account.');
        delete acc.comp; if (acc.sub) acc.sub.status = 'inactive'; await store.put(`acc:${accId}`, acc); return json({ ok: true });
      }
      if (p === '/v1/admin/stats') {
        const devs = await store.keys('dev:'), accs = await store.keys('acc:'); let active = 0;
        for (const k of accs) { const a = await store.get(k); if (access(null, a, now()).active) active++; }
        return json({ devices: devs.length, accounts: accs.length, active });
      }
      if (p === '/v1/admin/upi/pending') { const out = []; for (const k of await store.keys('upi:')) { const c = await store.get(k); if (c && c.status === 'pending') out.push(c); } return json({ pending: out.sort((a, b) => a.at - b.at) }); }
      if (p === '/v1/admin/upi/approve' || p === '/v1/admin/upi/reject') {
        const c = await store.get(`upi:${b.id}`); if (!c || c.status !== 'pending') return err(404, 'not_found', 'No such pending payment.');
        if (p.endsWith('reject')) { c.status = 'rejected'; await store.put(`upi:${c.id}`, c); return json({ ok: true }); }
        const accId = (await getDevice(c.deviceId) || {}).account || `upi:${c.deviceId}`; await link(c.deviceId, accId);
        const acc = (await getAccount(accId)) || { id: accId, devices: [], created: now() }; const base = acc.comp && acc.comp.until && acc.comp.until > now() ? acc.comp.until : now();
        acc.comp = { plan: c.plan, until: base + (b.days || 30) * DAY, note: `UPI ${c.utr}` }; await store.put(`acc:${accId}`, acc);   // renewals stack on top of the remaining time
        c.status = 'approved'; await store.put(`upi:${c.id}`, c); return json({ ok: true, until: acc.comp.until });
      }
      return err(404, 'not_found', 'Unknown admin route.');
    }
    if (m !== 'POST') return err(404, 'not_found', 'No such route.');
    const body = await request.json().catch(() => ({}));

    if (p === '/v1/device/register') {
      if (await limited(request, 'reg', 30)) return err(429, 'slow_down', 'Too many requests.');
      let id; try { id = await deviceIdFromJwk(body.pub); } catch { return err(400, 'bad_key', 'Invalid device key.'); }
      let dev = await getDevice(id);
      if (!dev) { dev = { id, pub: { kty: 'EC', crv: 'P-256', x: body.pub.x, y: body.pub.y }, created: now(), account: null }; if (cfg.trialDays) dev.trial_until = now() + cfg.trialDays * DAY; await store.put(`dev:${id}`, dev); }
      return json({ deviceId: id });
    }
    if (p === '/v1/challenge') {
      if (await limited(request, 'chal', 120)) return err(429, 'slow_down', 'Too many requests.');
      if (!body.deviceId || !(await getDevice(body.deviceId))) return err(404, 'unknown_device', 'This device is not registered.');
      const nonce = randomId(18); await store.put(`nonce:${nonce}`, { deviceId: body.deviceId }, { ttl: 120 }); return json({ nonce, exp: now() + 120 });
    }
    if (p === '/v1/entitlement') {
      const pr = await proof(body, 'entitlement'); if (pr.error) return pr.error;
      const account = await accountOf(pr.dev); const a = access(pr.dev, account, now());
      if (!a.active) return json({ state: a.state, active: false, message: 'No active subscription.' }, 402);
      const { token, claims } = await issue(pr.dev, account, a); return json({ active: true, state: a.state, token, claims });
    }
    if (p === '/v1/upi/claim') {
      if (!env.UPI_VPA) return err(501, 'provider_off', 'UPI payment is not turned on.');
      const pr = await proof(body, 'upi-claim'); if (pr.error) return pr.error;
      const utr = String(body.utr || '').trim().toUpperCase(); const plan = cfg.plans[body.plan];
      if (!plan) return err(400, 'bad_plan', 'Pick a plan.');
      if (!/^[A-Z0-9]{8,22}$/.test(utr)) return err(400, 'bad_utr', 'Enter the UPI reference number (UTR), 8 to 22 letters and digits, from your payment app.');
      if (await store.get(`utr:${utr}`)) return err(409, 'used', 'That reference number was already submitted.');
      const mine = (await store.keys('upi:')); let open = 0; for (const k of mine) { const c = await store.get(k); if (c && c.deviceId === pr.dev.id && c.status === 'pending') open++; }
      if (open >= 3) return err(429, 'slow_down', 'You already have payments waiting for approval.');
      const id = randomId(6); await store.put(`upi:${id}`, { id, deviceId: pr.dev.id, plan: body.plan, utr, amount: plan.price_inr, note: String(body.note || '').slice(0, 80), status: 'pending', at: now() }); await store.put(`utr:${utr}`, id);
      return json({ ok: true, id, message: 'Thanks! We will unlock your plan as soon as the payment is checked (usually within a few hours).' });
    }
    if (p === '/v1/checkout' || p === '/v1/portal' || p === '/v1/link/create' || p === '/v1/link/redeem') {
      const purpose = p.slice(4).replace('/', '-'); const pr = await proof(body, purpose); if (pr.error) return pr.error;
      if (p === '/v1/checkout') return createCheckout(body, pr.dev);
      const account = await accountOf(pr.dev);
      if (p === '/v1/portal') {
        const cust = account && account.sub && account.sub.customer; if (!cust || !env.STRIPE_SECRET_KEY) return err(404, 'no_portal', 'No billing portal for this account.');
        const r = await fetchImpl('https://api.stripe.com/v1/billing_portal/sessions', { method: 'POST', headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`, 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ customer: cust, return_url: body.return_url || env.RETURN_URL || 'https://example.com' }) });
        const j = await r.json(); return r.ok ? json({ url: j.url }) : err(502, 'provider_error', 'Stripe refused.');
      }
      if (p === '/v1/link/create') {
        if (!account || !access(pr.dev, account, now()).active) return err(402, 'inactive', 'Subscribe first.');
        const code = randomCode(); await store.put(`link:${code}`, { account: account.id }, { ttl: 600 }); return json({ code, expires_in: 600 });
      }
      const l = await store.get(`link:${String(body.code || '').toUpperCase()}`); if (!l) return err(404, 'bad_code', 'That code is wrong or has expired.');
      const acc = await getAccount(l.account); const plan = cfg.plans[(acc.sub && acc.sub.plan) || (acc.comp && acc.comp.plan)] || {};
      if (!acc.devices.includes(pr.dev.id) && acc.devices.length >= (plan.devices || 1)) return err(409, 'seat_limit', `This plan allows ${plan.devices || 1} device(s).`);
      await link(pr.dev.id, l.account); await store.del(`link:${String(body.code).toUpperCase()}`); return json({ ok: true });
    }
    return err(404, 'not_found', 'No such route.');
  }

  return async function fetchHandler(request) {
    const origin = request.headers.get('Origin') || '';
    const allow = cfg.origins.includes('*') ? '*' : (cfg.origins.includes(origin) ? origin : cfg.origins[0]);
    const cors = { 'Access-Control-Allow-Origin': allow, 'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Vary': 'Origin' };
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    let res; try { res = await handle(request); } catch (e) { res = err(500, 'server_error', 'Something went wrong on our side. Try again in a moment.'); }
    for (const [k, v] of Object.entries(cors)) res.headers.set(k, v);
    return res;
  };
}

// Cloudflare Workers entry
export default {
  async fetch(request, env, ctx) {
    const app = createApp({ store: new KVStore(env.LICENSE_KV), env });
    return app(request);
  },
};
