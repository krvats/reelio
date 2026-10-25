# Save to Drive: what to add to krvats/reelio

No new repos and no new secrets. Everything uses `krvats/reelio` and `krvats/reelio-data`.

## Copy these files into `krvats/reelio` (same paths)
NEW
- `.github/workflows/grab.yml`
- `worker/reelio/grab.py`
- `worker/reelio/driveup.py`
- `web/js/v_grab.js`
- `worker/tests/test_grab.py` (optional)
- `docs/GRAB.md` (optional)

CHANGED (small edits; replace if you have not edited them yourself, otherwise apply the same few lines)
- `worker/reelio/cli.py` (adds the `grab` action)
- `web/js/app.js`, `web/js/v_more.js`, `web/sw.js` (menu entry and cache list)
- `web/js/v_accounts.js` (Google login also asks for `drive.file`; remembers `drive_write`)

## Then do these 3 things
1. Google Cloud Console > OAuth consent screen > Data access > add scope `https://www.googleapis.com/auth/drive.file`. Keep the app "Published" (not Testing).
2. Reelio app > Accounts > Google > Reconnect (accept the new Drive permission). Your flows keep working.
3. More > Save to Drive > paste a link > Save to Drive.

Optional: for Instagram links that are not your own account, add a secret `instagram-net` with `cookies` (Netscape text) in the data repo's secrets. "My Instagram account" needs nothing.
