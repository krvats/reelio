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

## Part 2: get paid WITHOUT Stripe/Razorpay: UPI (no company needed to start)
You do not need Stripe or Razorpay. The license service has a manual UPI mode: people scan a QR (or tap a button), pay, paste the UPI reference number (UTR); you check it in your payment app and tap Approve; their app unlocks by itself and renewals stack. Nothing unlocks before you approve.
1. Install Node (nodejs.org). In the `license` folder: `npm install -g wrangler`, `wrangler login` (free Cloudflare account).
2. `npm run keys` and keep the private key secret. `wrangler kv namespace create LICENSE_KV` and paste the id into `wrangler.toml`.
3. `wrangler secret put SIGNING_KEY_JWK` (private key), `wrangler secret put ADMIN_SECRET` (long random text).
4. Set two plain variables in `wrangler.toml` under `[vars]`: `UPI_VPA = "yourname@bank"` and `UPI_NAME = "Your name"`. Set prices in the `PLANS` variable (see license README).
5. `wrangler deploy`; copy the address. In your repo edit `web/app-config.js`: `licenseUrl: 'https://<address>'`. Commit.
6. To approve payments open `upi-admin.html` on your site (or on your phone), paste the address and ADMIN_SECRET, press Load, check the UTR in your UPI app, press Approve.
7. Test with a Rs 1 payment from another phone before telling anyone.
To delay all payments: leave `licenseUrl` empty. The app stays open and free, exactly as now.
Use a normal bank UPI app for receiving money (FamPay is meant for teens; business-type payments there may break its rules). Money received is income: keep a record, and ask a local accountant about tax/GST thresholds. I am not a lawyer or tax advisor.

## Part 3: hosted multi-user mode (1 hour)
1. In the `api` folder: `wrangler kv namespace create REELIO_KV`, paste the id into `wrangler.toml`.
2. Make two random secrets (any long random text): MASTER_KEY must be 32 random bytes in base64url (`node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`). Then `wrangler secret put MASTER_KEY`, `wrangler secret put WORKER_SECRET`, `wrangler secret put ADMIN_SECRET`, and `wrangler secret put LICENSE_PUBKEY` (the public key from Part 2, so paid plans raise limits).
3. `wrangler deploy`. Copy the address.
4. In your repo: Settings → Secrets and variables → Actions → add secrets `REELIO_API_URL` (the address) and `REELIO_WORKER_KEY` (the same WORKER_SECRET); add variable `HOSTED` = `1`. The workflow "Reelio hosted worker" now serves every user's flows every 5 minutes.
5. Edit `web/app-config.js`: set `apiUrl` to the address. Commit. The app now shows email sign-up/login instead of GitHub keys.
6. Keep a SECOND copy of the repo or a branch for your personal GitHub-mode setup if you still want it (hosted mode replaces the login for everyone on that site).
Back up MASTER_KEY somewhere safe: without it, stored user logins cannot be read.

## Part 4: approvals, and what you can do without a company
Honest picture: for OTHER people's Instagram pages, Meta's App Review requires Business Verification (a registered business), and Google's verification for Drive/YouTube needs a domain and privacy policy. Without a business you cannot get these. Realistic options that need no approval:
- **Bring-your-own-keys (recommended now):** each user creates their own free Meta developer app (they are its admin, so no review is needed to post to their own accounts) and their own Google project (set to "In production" and accept the "unverified app" warning, or "Testing" with weekly re-login). Reelio already accepts their tokens/client ids. You sell the automation, scheduling and hosting, not Meta access. The Setup/Accounts screens guide them.
- **Setup service:** you or a helper sets this up for a client's accounts, then you charge monthly.
- **Later, when you have a business** (sole proprietorship with a current bank account is the usual first step in India, ask an accountant): do the Meta and Google reviews below.
Reference for later: Meta (developers.facebook.com, `instagram_business_content_publish`, Business Verification), Google (OAuth consent screen verification, YouTube API compliance audit). Use `privacy.html` / `terms.html` as starting points and have them checked. Details: `docs/PHASE_A.md`.
(The old list is kept in PHASE_A.)

## Cookies for YouTube downloads (only if YouTube blocks)
1. Open a private window, sign in to YouTube with a spare Google account, export with the extension "Get cookies.txt LOCALLY", close the private window. Repeat for each spare account.
2. In the app: Accounts > YouTube cookies > Add cookies > choose ALL the files at once > Add.
3. Nothing else: flows use them automatically, skip the ones that fail, and use them again when they recover.

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
