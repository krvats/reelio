# Changelog
## 1.1.0 (in progress)
- Added project memory tooling and rules (CLAUDE.md, ROADMAP, WORKLOG, handoff.py)
## 1.0.0
- First complete single-owner version: Drive/YouTube/Instagram/upload sources, Instagram/YouTube targets, scheduler, ledger, recovery, Telegram, diagnose, analytics, web app, setup guide, migration seed, 36 tests

## 1.1.0
- License service (device keys, signed entitlements, Stripe/Razorpay webhooks, link codes, admin) with 16 tests
- Paywall with silent unlock, Subscription card in Settings, worker-side offline verification with plan limits
- Pages & channels view with bulk actions, command palette, skeleton loading
- Project memory: handoff.py, CLAUDE.md, CONTEXT.md, ROADMAP, screenshots generator
- Merged owner's live edits from krvats/reelio (Oct 14, 2026): YouTube long videos/lives cut into clips, "selected videos" source, YouTube brand-channel Google login, newest yt-dlp + ffmpeg install in tick.yml, privacy.html
- Backup Drive folder for YouTube/Instagram sources (used when a download fails; clip-aware), diagnose check; Phase A document; onboarding checklist on Home
- api/: multi-user backend skeleton with 10 tests (Phase B part 1)
- v1.4: worker API mode (`serve`), hosted workflow, admin/teams/legal/Hindi/week plan (from parallel work), tutorial, fixes (translator shadowing in Home/Settings)
- UPI manual payments (QR/link + UTR claim + owner approval page), 2 new license tests; tutorial rewritten for no-company path
- YouTube cookie pool (v1.5): many cookies in one box (choose or drop many files, auto-split), automatic switching to the next good cookie, per-cookie rest timers (blocked 30m/2h/6h/24h; logged-out 6h/24h/72h then parked), flow waits until the soonest cookie wakes instead of a fixed time, backup Drive folder stays the last path; no fake "account" for cookies; 14 new worker tests
- Cookie Sync add-on (v1.6): Chrome/Edge extension in `tools/cookie-sync/` (also served as `web/downloads/reelio-cookie-sync.zip`): one-click Connect reads the app's login from the open Reelio tab, then every hour pushes this browser's YouTube cookies (own slot per browser profile, label, other logins untouched) into the encrypted secrets; worker treats a refreshed export of the same profile as a fresh cookie (rest timer reset); 3 cross-language tests
- Reliability (v1.7): Cloudflare keep-alive Worker (`keepalive/`) starts the posting worker every 5 min and long videos hourly, so GitHub's late or skipped cron no longer matters; second alarm `watchdog.yml`; in-app self-heal (`web/js/heal.js`); Long videos tab shows an instant "Adding..." card, live worker status, waiting requests, and the Start button no longer dies after an error (it used `e.currentTarget` after an await)
- Parallel + always-on (v1.8): every account posts in its own parallel lane (flows sharing an account stay in order); `REELIO_LIVE=1` keeps one workflow run alive ~50 min in a loop (`worker/reelio/live.py`): one post per account per pass, pause between an account's posts is checked not slept, data repo pulled every 15 s so Post now goes out within about 15 s, quiet passes do not spam commits, next run chained with no gap. Store methods are thread-locked. Stats page can switch between everything, one account, one flow, with an all-flows table. 6 new tests (`test_parallel.py`), fake Instagram container ids made thread-safe

## 1.2.0
- New website (`index.html`) with film-strip hero, day planner, Hindi toggle, screenshots; app moved to `app.html`
- Light-table theme for app, site and legal pages; self-hosted fonts (no Google Fonts)
- Speed: cached app shell (service worker rewrite, stamped per publish), instant paint from last data, lazy long lists, no fixed gradient layer
- Demo mode `app.html?demo=1` with sample data; screenshots now generated from it
- Re-connected Pages tab, command palette and hosted login in `app.js`; OAuth redirect stays the folder address
- LICENSE (PolyForm Noncommercial), docs/SELLING.md, README rewrite
