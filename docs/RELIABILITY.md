# Permanent fix for missed schedules (do once, about 10 minutes)

**Cause:** GitHub's `schedule:` cron is not a promise. On busy hours it starts runs 15 to 60 minutes late or skips them, so posts wait and the app says "GitHub is running late".

**Fix:** something other than GitHub's cron starts the worker. Three layers are included; layer 1 is the one that makes it permanent.

## Layer 1: Cloudflare keep-alive (free, required)
1. GitHub > Settings > Developer settings > Fine-grained tokens > new token. Repository: only `krvats/reelio`. Permission: **Actions: Read and write**. Expiry: longest allowed. Copy it.
2. In the `keepalive` folder run:
   - `npm i -g wrangler` (once), `wrangler login`
   - `wrangler secret put GH_TOKEN` (paste the token)
   - `wrangler deploy`
3. Open the printed `*.workers.dev` address. You should see `"ok": true` and the last run.
4. Check: Cloudflare dashboard > Workers > reelio-keepalive > Logs. Every 5 minutes it says started or why it did not.
(No Cloudflare? Alternative with zero code: cron-job.org, every 5 min, POST `https://api.github.com/repos/krvats/reelio/actions/workflows/tick.yml/dispatches`, headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, body `{"ref":"main","inputs":{"action":"run","route":""}}`.)

## Layer 2: watchdog.yml (automatic)
Nothing to set up. Starts the worker if it was silent 12+ minutes.

## Layer 3: app self-heal (automatic)
When the app is open and the worker is 15+ minutes silent, it starts a run itself.

## Renew the token
When it expires, make a new one and run `wrangler secret put GH_TOKEN` again.
