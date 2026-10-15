# YouTube cookies in Reelio (v1.5)

**Does a failed cookie come back?** Depends why it failed.
- "Blocked" (YouTube's bot check or too many requests): usually YES after a rest. Reelio rests it 30 min, then 2 h, 6 h, 24 h, and uses it again by itself.
- "Logged out / rotated" (the login behind the cookie ended): NO, it will not recover. Reelio checks again after 6 h, 24 h, 72 h, then parks it. Add a fresh one.
Tip: export from a private window and close it right after; that keeps the cookie from being rotated early.

## One-time checklist
- [ ] Update the site files (upload the zip contents to github.com/krvats/reelio, Commit, Ctrl+F5)
- [ ] Open Accounts > YouTube cookies > Add cookies > choose ALL cookie files at once > Add
- [ ] (Optional) give YouTube flows a backup Drive folder: it is the last route if every cookie fails
- [ ] Old single-cookie setup keeps working; nothing to migrate

## What happens when a YouTube download is blocked
1. Each ready cookie is tried in turn (least recently used first). A failing cookie goes to rest with a timer.
2. One try with no cookie.
3. The flow's backup Drive folder (if set).
4. If still nothing: only that flow waits, until the soonest cookie wakes up (15 min to 12 h), and the app says how many cookies were tried and when it will look again. Other flows keep running.
A private or removed video is never blamed on the cookies.

## Cannot be tested live (no real YouTube here)
Real YouTube bot checks and the exact wording of its error messages (Reelio matches "sign in", "confirm you", "bot", "429", "no longer valid"); how fast real cookies get rotated; yt-dlp on GitHub runner IPs; the cookie dialog on a phone. Tested with a fake yt-dlp: splitting, switching, timers, reset after success, private videos, old single cookie, health file holds no cookie text. Browser: choosing two files at once saved 2 cookies in headless Chromium.
Honest note: Reelio cannot generate cookies; they must come from a signed-in browser. YouTube may limit accounts used this way, so use spare accounts.
