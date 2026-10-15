# Reelio tutorial: from "what I have" to "a product people pay for"

Do the parts in order. Stop after any part: everything before it keeps working. Plain steps, no coding.

## Part 0: what is in the zip
`web/` the app people see · `worker/` the robot that posts · `license/` the payment/unlock service · `api/` the multi-user backend · `docs/` memory + plans · `tools/` helper scripts · `CLAUDE.md`, `CONTEXT.md` the project's own memory.
Tests passing when this zip was made: 56 worker, 16 license, 16 API, plus a browser smoke test of hosted mode. Not tested live: see Part 7.

## Part 1: update your live site safely (5 minutes)
1. Unzip `reelio-changed-files.zip` (small) or use the full zip.
2. Open github.com/krvats/reelio → Add file → Upload files → drag the unzipped folders in (keep folder names) → Commit.
3. Wait 1 minute, open krvats.github.io/reelio, press Ctrl+F5. Your flows, posts history and logins are in the other (private) repo, so they stay.
4. Check Home shows "Getting started" (if new) or your strip, and Accounts still says connected.
Nothing here turns on payment or multi-user mode. Your own use is unchanged.

## Part 2: turn on payments (paywall) (30 minutes, free)
1. Install Node from nodejs.org. Open a terminal in the `license` folder: `npm install -g wrangler`, then `wrangler login`.
2. `npm run keys` → copy the public key line it prints; keep the private line secret.
3. `wrangler kv namespace create LICENSE_KV` → paste the id into `wrangler.toml`.
4. `wrangler secret put SIGNING_KEY_JWK` (paste private key), then `wrangler secret put ADMIN_SECRET` (any long random text).
5. In Stripe (and/or Razorpay) create 3 monthly products (Starter, Pro, Agency). Put their price ids in the `PLANS` variable (see `license/README.md`). Add webhook URLs: `https://<your-worker>/v1/webhook/stripe` and `/razorpay`; then `wrangler secret put STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` (and the Razorpay ones).
6. `wrangler deploy`. Copy the worker address.
7. In your repo edit `web/app-config.js`: set `licenseUrl: 'https://<your-worker>'`. Commit. Now the app asks people to pick a plan and unlocks by itself after payment.
8. To use your own app free: call `POST /v1/admin/grant` with your device id (see license README) or temporarily leave `licenseUrl` empty.
Use Stripe/Razorpay TEST mode first and buy once with a test card.

## Part 3: hosted multi-user mode (1 hour)
1. In the `api` folder: `wrangler kv namespace create REELIO_KV`, paste the id into `wrangler.toml`.
2. Make two random secrets (any long random text): MASTER_KEY must be 32 random bytes in base64url (`node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`). Then `wrangler secret put MASTER_KEY`, `wrangler secret put WORKER_SECRET`, `wrangler secret put ADMIN_SECRET`, and `wrangler secret put LICENSE_PUBKEY` (the public key from Part 2, so paid plans raise limits).
3. `wrangler deploy`. Copy the address.
4. In your repo: Settings → Secrets and variables → Actions → add secrets `REELIO_API_URL` (the address) and `REELIO_WORKER_KEY` (the same WORKER_SECRET); add variable `HOSTED` = `1`. The workflow "Reelio hosted worker" now serves every user's flows every 5 minutes.
5. Edit `web/app-config.js`: set `apiUrl` to the address. Commit. The app now shows email sign-up/login instead of GitHub keys.
6. Keep a SECOND copy of the repo or a branch for your personal GitHub-mode setup if you still want it (hosted mode replaces the login for everyone on that site).
Back up MASTER_KEY somewhere safe: without it, stored user logins cannot be read.

## Part 4: legal and approvals (start today; they take weeks)
- Meta: developers.facebook.com → create app → Instagram API with Instagram Login → App Review for `instagram_business_content_publish`; Business Verification; use `privacy.html` and `terms.html` as starting points (have a lawyer check them).
- Google: Cloud console → OAuth consent screen → publish → verification for Drive and YouTube scopes (demo video needed); YouTube API compliance audit for more upload quota.
- Until approved: users bring their own app/project (the app already supports pasting their own Google client id and Instagram token).
Details: `docs/PHASE_A.md`.

## Part 5: running it day to day
- Admin screen: `admin.html` on your site (needs your ADMIN_SECRET): list users, suspend, set plan, stats.
- Users invite teammates in Settings → Team (editor/viewer).
- If something fails, the user sees a plain sentence and a Fix button; the Help page runs "Why is it failing?".

## Part 6: continuing in a new chat
Upload the zip. Say: "Continue Reelio. Read CLAUDE.md." If you edited files, also upload only those. The project knows what changed (`python tools/handoff.py diff`).

## Part 7: what to test live first (in this order)
1. Update site (Part 1), post one video from your own Drive.
2. Backup Drive folder with one blocked YouTube video.
3. Paywall with Stripe test card; then Razorpay test.
4. Hosted mode with two test emails; each connects its own Instagram test account.
5. Real Meta/Google approvals.
Known live-untested: Instagram publishing through Cloudinary from GitHub servers, yt-dlp on GitHub IPs, Google redirect from the Pages address, Telegram from the browser, Stripe/Razorpay real webhooks, deployed Cloudflare Workers, GitHub cron delay (5 to 15 minutes is normal).

## Part 8: honest limits
Anyone who copies the code and runs their own copy can remove the paywall; hosted mode (Part 3) is the real protection because posting runs on your side. GitHub Actions is fine for the first users; move the worker to a small VPS when you pass about 50 active accounts.
