# Reelio license service

Tiny service (Cloudflare Workers free tier, or any Node 20+) that answers one question: "may this device use Reelio?"

**How it feels to a user:** they open the app, pick a plan, pay. The app unlocks by itself. Nothing to type or verify.
**How it works:** each device makes a private key that never leaves it. Checkout carries the device id to Stripe/Razorpay; the payment webhook binds that device to the subscription. The device then proves itself with a one-time signed challenge and receives a 24 h signed entitlement (Ed25519). The app and the worker check it offline with the public key.

## Deploy (about 10 minutes, free)
1. `cd license && npm run keys` → prints a private key (secret) and the public key.
2. `npx wrangler kv namespace create LICENSE_KV` → paste id into `wrangler.toml`.
3. `npx wrangler secret put SIGNING_KEY_JWK` (paste the private key JSON), then `ADMIN_SECRET`, then the Stripe / Razorpay secrets you use.
4. Edit `PLANS` prices (set `stripe_price` / `razorpay_plan` ids) via the `PLANS` var, `npx wrangler deploy`.
5. In Stripe: webhook → `https://<worker>/v1/webhook/stripe` (events: checkout.session.completed, customer.subscription.*, invoice.paid, invoice.payment_failed). In Razorpay: `/v1/webhook/razorpay` (subscription.* events).
6. Put the worker address in `web/app-config.js` (`licenseUrl`) and the public key in `worker` setting `LICENSE_PUBKEY`.

## Admin (Bearer ADMIN_SECRET)
`POST /v1/admin/grant {deviceId|accountId, plan, days}` free access · `/revoke` · `/stats`.

## Test
`npm test` (15 tests; no network). Payments and webhooks were tested with signed fake events, not live Stripe/Razorpay.

## Honest limits
Anyone running code on their own machine can patch it. This service stops casual sharing and makes paying the easy path; hard enforcement needs posting to run on your servers (roadmap Phase B).
