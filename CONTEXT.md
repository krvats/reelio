# CONTEXT: what Reelio is and why it is built this way (permanent; keep true)

## Owner and goal
K1NG (Krishna), Patna, India, GitHub `krvats` (never assume another domain; infer `<owner>.github.io` at runtime or ask). Windows PC, but nothing may depend on it being on.
Reelio replaces two old tools (Drive to Instagram Reels, YouTube Shorts uploader) with one cloud app, and is meant to become a public, paid product: many users, each managing many Instagram pages and YouTube channels with absolute per-account/per-video control. UI must work for ages 5 to 80. Owner prefs: short replies, minimal questions, finished zip every time, obvious decisions made without asking, say plainly what was not tested live. Security: never print/store secrets in logs/UI/zips; tell the owner to rotate any secret seen (old zips contained Instagram token, Google keys, Cloudinary secret, YouTube token.json: all must be rotated).

## Current state (v1.1)
Single-owner mode works (v1) plus the first product layers (v1.1):
- **Worker** (`worker/reelio`, Python 3.12): GitHub Actions cron every 5 min. `engine.py` brain, `scheduler.py` (N slots/day over a window, seeded jitter, cap 100/day), `store.py` (files + git sync with rebase/conflict recovery), `crypto.py` (AES-256-GCM, PBKDF2-SHA256 200k; byte-compatible with browser WebCrypto), `errors.py` (plain-language mapping), `media.py` (ffmpeg), `hosting.py` (Cloudinary temp host + sweep), `sources/` (drive, youtube, instagram, upload), `targets/` (instagram, youtube), `notify.py`, `diagnose.py`, `analytics.py`, `license.py` (v1.1).
- **Web app** (`web/`, vanilla ES modules, no build, GitHub Pages): Home (film-strip of today's slots), Pages & channels (v1.1: colour chips, progress, bulk select/pause/posts-a-day/time-window), Flows, Videos, Accounts, Schedule, Stats, Activity, Settings, Help, Setup. Ctrl/Cmd+K or "/" command palette (v1.1). Skeleton loading (v1.1). PWA. Light/dark, text size.
- **License service** (`license/`, Cloudflare Worker, free tier; v1.1): see Licensing below. `web/js/license.js`, `v_paywall.js`, `web/app-config.js`.
- **Data** lives in a private repo (`config.json`, `secrets.enc.json`, `ledger.json`, `queues/`, `status.json`, `license.json`, `inbox/*.json`, `logs/`). The UI uses a fine-grained PAT stored in the browser as login; no backend in single-owner mode.

## Data model (unchanged)
`connections[]` {id, kind instagram|google|cloudinary|telegram|ytnet, label, ig_user_id}. `routes[]` = "Flows": source {drive|youtube|instagram|upload}, target {instagram|youtube}, schedule {per_day<=100,start,end,jitter,max_per_run,gap_seconds>=60 for IG}, caption {mode,text,template,hashtag_sets,variants,table}, edit {filter,strength,fit keep|blur|crop|pad,audio,watermark,cover}, order, youtube opts. Ledger entry per post (dedup by source id AND md5 per target; only the "repost" command bypasses). Queue item statuses pending|posted|failed|skipped|missing. Inbox commands: skip, unskip, retry, retry_all, post_now, reorder, caption, repost, rescan, clear_cooldown.

## Hard behaviors (do not regress)
One bad video never stops a queue (3 tries then failed). 3 failures in a row pause a flow 60 min without penalising videos. Account problems (token, rate limit, quota) pause only that account with exponential backoff; mid-run rate limit sleeps 10 min once then retries. Source problems (YouTube blocking datacenter IPs) pause only that flow. Crash recovery via in-flight journal committed before publish; no double posts; Cloudinary files deleted after posting plus sweep. Instagram: graph.instagram.com v21.0, needs public video_url, 100 API posts/24h, token refresh every 20 days. YouTube API uploads about 6/day for new projects. Public repo means unlimited Actions minutes; keep-alive step re-enables the workflow (60-day idle disable).

## Licensing (v1.1)
Goal: no access until paid; each device silently proves itself; no "verify your subscription" step.
1. Browser makes an ECDSA P-256 key (non-extractable, IndexedDB). deviceId = SHA-256 thumbprint of the public key. Registered once.
2. For every call the server issues a one-time nonce (120 s); the device signs `reelio:<purpose>:<nonce>:<deviceId>`. Replays and cross-purpose signatures are rejected.
3. Server returns 402 if unpaid, else a 24 h Ed25519-signed entitlement (claims: st, plan, lim{accounts,posts_month,devices}, exp, wv, cnf=deviceId). `wv` = worker-valid-until (paid period + grace, max 35 days) so 24/7 posting continues while the owner is not opening the app.
4. Checkout (Stripe / Razorpay) carries deviceId in metadata/notes; the signed webhook binds the device to the subscription, so the app unlocks by itself (the paywall polls). States: active, grace (past_due, 3 days), trial (optional), comped (admin), none. Extra devices via one-time link codes with seat limits. Admin routes via Bearer ADMIN_SECRET (grant/revoke/stats).
5. The app pushes the token to `license.json` in the data repo; `worker/reelio/license.py` verifies it offline with `REELIO_LICENSE_PUBKEY` (or `license_pubkey` in config). No key configured = open mode (personal use). Inactive = nothing posts, scan still works, plain message shown. Limits: accounts (first N targets in config order), posts per calendar month.
**Honest limit:** code running on a user's own repo/machine can be patched; this stops casual sharing and makes paying the easy path. Real enforcement needs posting on infrastructure the owner controls (Phase B, multi-tenant).

## Multi-user backend (Phase B, in progress)
`api/` is a Cloudflare Worker (KV now, D1 later) with the tenant model: users, per-tenant config/queue/ledger, envelope-encrypted secrets, worker leases, exactly-once ledger. Design in `docs/PHASE_A.md`. Self-host mode (GitHub) still works unchanged.

## Tests
`cd worker && python -m unittest discover -s tests` (about 3 min; mock Instagram/Drive/Google/Cloudinary/YouTube/Telegram), `cd license && node --test test/*.test.mjs`, `cd api && npm test`. Python license tests mint tokens with the real Node code (cross-language). UI checked in headless Chromium via `tools/ui_demo.py` (`tools/screens.py` writes `docs/screens/`).

## Not verified live (always say so)
Instagram publish via Cloudinary from GitHub runners, Meta real rate limits, Google OAuth redirect from the Pages URL, yt-dlp on runner IPs, GitHub cron lag and re-enable call, Telegram CORS, Stripe and Razorpay real checkout/webhooks, deployed Cloudflare Worker, the paywall in a real browser against the deployed service.

## Project memory (how continuity works)
`CLAUDE.md` rules; this file; `docs/ROADMAP.md`; `docs/WORKLOG.md`; `docs/MANIFEST.json` (sha256 of every file) so `python tools/handoff.py diff` shows exactly what the owner edited since the last snapshot; `python tools/handoff.py prompt` rewrites `docs/NEXT_CHAT_PROMPT.md`; `docs/screens/` shows the UI. A new chat needs only the zip plus one line.

## Decisions made so far
Public app repo + private data repo; any source to any target; vanilla JS no build; stdlib unittest (no pip access in the build sandbox); Cloudflare Workers for the license service (free, KV); Stripe + Razorpay; Phase A decision still open: Supabase vs Cloudflare D1 for multi-tenant (see ROADMAP).
