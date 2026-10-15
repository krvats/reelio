# Roadmap (the source of truth for what is next; tick as you go)

## Done
- [x] v1.0 single-owner Reelio: worker, web app, GitHub Actions, migration seed, 36 tests
- [x] Project memory: CLAUDE.md, CONTEXT.md, ROADMAP, WORKLOG, `tools/handoff.py` (snapshot/diff/prompt/check)

## v1.1 (this chat)
- [x] Device-bound license service (`license/`), silent unlock, paywall, worker-side offline verification (16 node + 8 python tests; NOT live-tested with Stripe/Razorpay)
- [x] UI for many accounts: Pages overview + bulk actions, command palette, skeleton loading
- [x] Onboarding checklist on Home
- [ ] Still open from that list: week calendar (worker should emit `plan_week`), optimistic updates, count-up numbers, bulk actions on the Flows list
- [x] Screenshots generator `tools/screens.py` and `docs/screens/`

- [x] Add-on: Video links source (`docs/ADD_LINKS.md`); open: hosted-mode support, live test of Instagram downloads

## Owner situation (important)
No company/Stripe/Razorpay account. Payments run through manual UPI approval (done). Meta/Google reviews need a registered business, so the product runs in bring-your-own-keys mode until then.

## Next (in this order)
- [x] Phase A written: `docs/PHASE_A.md` (Cloudflare-first, cost model, approvals checklist). Still to do: clickable multi-account prototype review; start Meta/Google applications (owner)
- [x] Phase B part 1: `api/` (auth, per-tenant data, envelope-encrypted secrets, leases, exactly-once ledger; 10 tests)
- [x] Phase B part 2 (done in v1.4): Python worker `--api` mode (lease, fetch secrets, post, write ledger/queue via API); web app login + API data layer; plan link to license service; (still open: D1, R2, email magic link/passkeys)
- [~] Phase C (partly done: days of week, blackout dates, first comment, week plan, teams/roles/audit; open: intro/outro, trim, subtitles, CSV bulk import): per-video and per-account full control (days of week, blackout dates, first comment, intro/outro, trim, subtitles), bulk CSV import, teams and roles
- [~] Phase D (partly done: admin console, legal pages, welcome page, Hindi; open: live billing test, docs site): billing live (Stripe + Razorpay), admin console, marketing site (landing, pricing, docs), Hindi translation
- [ ] Phase E: hardening, load test, security review, launch checklist
- [ ] Verify live: Instagram publish via Cloudinary, Google OAuth redirect, yt-dlp on runner IPs, GitHub cron lag, Telegram CORS, Stripe/Razorpay webhooks
