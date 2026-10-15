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

## Next (in this order)
- [x] Phase A written: `docs/PHASE_A.md` (Cloudflare-first, cost model, approvals checklist). Still to do: clickable multi-account prototype review; start Meta/Google applications (owner)
- [ ] Phase B: multi-tenant backend (auth, database, per-tenant encrypted secrets, job queue, per-account isolation), worker refactored to per-account jobs, tests ported
- [ ] Phase C: per-video and per-account full control (days of week, blackout dates, first comment, intro/outro, trim, subtitles), bulk CSV import, teams and roles
- [ ] Phase D: billing live (Stripe + Razorpay), admin console, marketing site (landing, pricing, docs), Hindi translation
- [ ] Phase E: hardening, load test, security review, launch checklist
- [ ] Verify live: Instagram publish via Cloudinary, Google OAuth redirect, yt-dlp on runner IPs, GitHub cron lag, Telegram CORS, Stripe/Razorpay webhooks
