# Phase A: multi-user architecture, cost model, approvals checklist

Written 2026-10-15. Prices and review times change: re-check before committing money. Nothing here was tested live.

## 1. Decision: Cloudflare-first (recommended)
| Piece | Choice | Why |
|---|---|---|
| Sign-in | Email magic link + Google login (own tiny auth on Workers, passkeys later) | Users must not need GitHub |
| Database | Cloudflare D1 (SQLite) for users/accounts/flows/queue/ledger; KV for license + rate limits | Free tier covers the first hundreds of users; one vendor |
| Secrets | Envelope encryption: per-tenant data key encrypted by a master key held as a Worker secret; never in logs | Same AES-256-GCM format family as v1 |
| Video storage | Cloudflare R2 (no egress fees, public URL for Instagram fetch, auto-delete after posting) | Cloudinary free tier will not carry many users |
| Job runner | Fly.io or Hetzner VPS running the existing Python worker as a per-account job queue (lease + idempotency key in D1). GitHub Actions stays for self-host mode | ffmpeg and yt-dlp need a real machine; this is where payment is truly enforced |
| Web app | Current vanilla app, talking to the Workers API instead of GitHub | Keeps the design and PWA |
| Billing | Existing license service (Stripe + Razorpay) merged into the same Worker | Already built and tested |
Alternative: Supabase (Postgres + auth + storage) is faster to start and has built-in auth, but costs more at scale and splits infra. Choose it only if you want less auth code to own.

## 2. Cost model (rough, per month)
- Free until about 50 active accounts: Workers/D1/KV free tiers, R2 10 GB free, one small VPS about $5 to 8.
- Per active account posting 10 videos/day (300/month, about 15 MB each, held minutes): compute about $0.05 to 0.15, storage and requests about $0.01, so under $0.25 per account.
- Fixed: VPS $5 to 20 (scale with accounts, one box handles dozens of accounts), domain about $12/year, email sending about $0 to 15.
- Payment fees: Stripe about 2.9% + fixed; Razorpay about 2% (India, plus GST handling).
- Break-even: Starter at ₹499 covers about 2,000 accounts worth of variable cost; fixed costs are covered by roughly 3 to 5 paying users.

## 3. Platform approvals (start now; they run in parallel and take weeks)
1. **Meta (Instagram publishing for other people's pages):** create a Meta app, add Instagram API with Instagram Login, request `instagram_business_basic` and `instagram_business_content_publish` through App Review (screencast of the flow, test credentials), complete Business Verification, publish privacy policy URL and a data-deletion callback/instructions page. Until approved: "bring your own app" mode (each user adds themselves as tester of their own app) or tester mode for up to a few accounts.
2. **Google OAuth:** Drive read scope and YouTube scopes are sensitive/restricted. Needs OAuth consent screen verification (domain, privacy policy, scope justification, demo video); restricted scopes can require a third-party security assessment. Until verified: "testing" mode allows 100 named users and tokens that expire in 7 days; "bring your own Google project" is the workaround.
3. **YouTube API:** new projects have small upload quotas (about 6 uploads/day); request the YouTube API Services compliance audit and a quota extension.
4. **Legal pages (templates to be reviewed by a lawyer):** Terms of Service, Privacy Policy (a `privacy.html` already exists in the app), DMCA/copyright policy with repeat-infringer rule, content-rights checkbox in onboarding, refund policy, GST/tax details for India.

## 4. Migration path from v1
1. Keep self-host mode as is. 2. Add the Workers API with the same data shapes (config, queue, ledger are already JSON documents, so they map to D1 rows or JSON columns). 3. Port the worker to read/write via the API instead of git. 4. Each flow becomes a job with a lease; ledger dedup becomes a unique index (target, source id) and (target, md5). 5. Import an existing user's data repo with one button.

## 5. Risks to be honest about
Instagram/Google can refuse or delay approval; automation terms of Meta must be followed (official publishing API only, no scraping); one shared server IP can be blocked by YouTube for downloads (use the user's own sources and the backup-Drive option); abuse and copyright claims need an admin kill switch per user (planned in Phase D).
