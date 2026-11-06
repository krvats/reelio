# Setup Guide – Instagram Reels → Google Drive (GitHub Actions)

## 0. Install (zip is drop-in)

Unzip at the **root of your repo** (the folder containing `.github/`) and let it merge. It only *adds* files and overwrites nothing that already exists:

```
.github/workflows/instagram_scraper.yml     the workflow (must live here)
instagram_pipeline/
  orchestrator.py  cookieless_fallback.py  serverless_api_proxy.py  igcommon.py
  requirements.txt  targets.txt  .gitignore  SETUP_GUIDE.md
```
Then `git add -A && git commit -m "Add Instagram reels pipeline" && git push`, add the secrets below, and edit `instagram_pipeline/targets.txt`.

> Use a **private** repository. The Actions cache holds your Instagram session file, and anyone with read
> access to the repo could use a workflow to read it. (The uploaded *artifact* never contains session files.)

## 1. rclone.conf → Base64 secret `RCLONE_CONFIG_DATA`

1. On any machine with rclone: `rclone config` → **n** (new remote) → name it exactly **`gdrive`** → storage **drive** →
   scope **1 (full access)** (or 3 = `drive.file` if you only need files the app created) → finish the browser OAuth.
   *Tip:* create your own Google Cloud OAuth client ID and enter it when asked – the shared rclone client is heavily rate limited.
2. Find the file: `rclone config file`.
3. Encode it (single line, no wrapping):

   | OS | Command |
   |---|---|
   | Linux | `base64 -w0 ~/.config/rclone/rclone.conf` |
   | macOS | `base64 -i ~/.config/rclone/rclone.conf \| tr -d '\n'` |
   | Windows PowerShell | `[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:APPDATA\rclone\rclone.conf"))` |

4. Repo → **Settings → Secrets and variables → Actions → New repository secret** → name `RCLONE_CONFIG_DATA`, paste the string.
5. Keep only the `[gdrive]` section in the file you encode. The OAuth token inside refreshes itself; if Google
   revokes it (7-day expiry applies to OAuth apps left in *Testing* mode – set the consent screen to *In production*)
   re-run `rclone config reconnect gdrive:` and update the secret.

Verify locally before pasting: `RCLONE_CONFIG=<file> rclone lsd gdrive:`

## 2. Instagram session → `INSTAGRAM_SESSION_COOKIE` + `INSTAGRAM_USERNAME`

Use a **throw-away account**, not your main one – automation can get an account restricted.

Pick either way (the orchestrator auto-detects the format):

**A. Instaloader session file (recommended)**
```bash
pip install instaloader
instaloader --login YOUR_USER            # handles 2FA interactively
base64 -w0 ~/.config/instaloader/session-YOUR_USER     # macOS: base64 -i FILE | tr -d '\n'
```
**B. Browser cookies** – log in at instagram.com, copy cookie values and build a header string, then Base64 it:
```bash
printf 'sessionid=PASTE; csrftoken=PASTE; ds_user_id=PASTE' | base64 -w0
```
(a Netscape `cookies.txt` export or JSON cookie export, Base64-encoded, also works).

Secrets to create:

| Secret | Value |
|---|---|
| `INSTAGRAM_SESSION_COOKIE` | the Base64 string |
| `INSTAGRAM_USERNAME` | the login username that owns the session (needed by Instaloader) |

The one cookie is converted at runtime into: an Instaloader session file (Tier 1), a Netscape `cookies.txt`
(Tiers 2–3, deleted at the end of the run) and Playwright cookies (Tier 3 fallback harvest).

## 3. Tier 4b API keys (optional but recommended as last resort)

| Secret / variable | Purpose |
|---|---|
| `APIFY_TOKEN` (secret) | Apify actor `apify/instagram-reel-scraper` (override with env `APIFY_ACTOR`) |
| `RAPIDAPI_KEY` (secret) | RapidAPI Instagram scraper |
| `RAPIDAPI_HOST`, `RAPIDAPI_PATH` (repo *variables*, optional) | defaults `instagram-scraper-api2.p.rapidapi.com` and `/v1.2/reels`; change if you subscribe to a different API |

RapidAPI marketplaces differ in paths and response shape; the parser is tolerant but **test your chosen API once**
with `python serverless_api_proxy.py --user nasa --max-reels 3`. Both services bill per use – set a spending cap.

## 4. Run it

* **Manual:** Actions → *Instagram Reels Scraper* → *Run workflow*. Start with `dry_run = true` to validate the rclone secret and Drive access, then run with `instagram_username = nasa`, `max_reels = 3`.
* **Scheduled:** edit `cron` in the workflow (default every 12 h) and list accounts in `targets.txt`.
* **Webhook:**
  ```bash
  curl -X POST -H "Authorization: Bearer $GH_PAT" -H "Accept: application/vnd.github+json" \
    https://api.github.com/repos/OWNER/REPO/dispatches \
    -d '{"event_type":"instagram-scrape","client_payload":{"instagram_username":"nasa,natgeo","max_reels":10}}'
  ```
* `force_tier` lets you test one engine in isolation (`1`, `2`, `3`, `4`, `4a`, `4b`).

Files land in `Instagram_Reels/<username>/<shortcode>.mp4` in your Drive.

## 5. How state survives between runs

| What | Where | Notes |
|---|---|---|
| `archive.txt` (yt-dlp format), gallery-dl archive, Instaloader latest-stamps | `actions/cache` (primary) **and** `ig-archive-*` artifact (30 days, fallback) | A new cache entry is saved at the end of every run, even after failure/timeout |
| Instaloader session | `actions/cache` only | re-seeded from the secret every run |
| Run history | `run_state.json` (same places) | profiles are ordered least-recently-successful first |

Commits are **transactional per profile**: state is only kept after `rclone move` succeeded; otherwise it rolls back so nothing is ever recorded as archived without being in Drive.
If both cache *and* artifacts expire (GitHub evicts caches unused for 7 days; artifacts after 30), the next run re-downloads each profile's history – keep the schedule frequent or raise `retention-days`.

## 6. Behaviour you should know about

* **Time limit:** soft deadline 335 min; on timeout/cancel the orchestrator uploads what it has, saves state and exits; remaining profiles run first next time.
* **Rate limits / challenges:** detected from tool output; the tool is killed immediately and the next tier starts after a random 5–15 s pause. 3 consecutive blocks on a tier opens a circuit breaker for the rest of the run. Pauses between profiles are random 30–90 s.
* **Tier 1 URL correction:** the reels tab is `https://www.instagram.com/<username>/reels/` (the brief's URL was missing `www.` and the slash).
* **Tier 3:** `gallery-dl --get-urls` returns CDN media URLs, not `/reel/CODE/` links, so the harvest uses `gallery-dl --dump-json` and reads the shortcodes; Playwright is the backup harvester.
* **Realistic expectations:** Instagram blocks GitHub's Azure IP ranges aggressively. Expect Tier 1–3 to work sporadically (login challenges on a fresh datacenter IP are common) and mirrors (Tier 4a) to be frequently behind Cloudflare. Tier 4b is the most reliable but paid. The mirror selectors and API response shapes could not be tested against the live services in the sandbox this was written in – run each tier once with `force_tier` and adjust.
* **Tool flags:** the orchestrator checks each tool's `--help` and omits flags the installed version doesn't have (logged as a warning), so a renamed option degrades gracefully instead of failing the tier.
* **Terms of use:** scraping and re-hosting content may breach Instagram's terms and creators' copyright. Use it only for content you own or have permission to archive.
