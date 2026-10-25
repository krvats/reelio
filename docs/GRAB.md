# Save to Drive (YouTube + Instagram videos into your Google Drive)

Paste a link in the app (More > Save to Drive). The cloud worker (`.github/workflows/grab.yml`) downloads it as an mp4 and puts it in your Drive. Your phone and computer can be off.

| You paste | Drive result |
|---|---|
| A YouTube video | `Main folder / Title.mp4` |
| A YouTube playlist | `Main folder / Playlist name / Title.mp4` (one file per video) |
| A YouTube channel | `Main folder / Channel - Videos / Title.mp4` |
| An Instagram post link | `Main folder / Title [id].mp4` (usually needs Instagram cookies) |
| "My Instagram account" | `Main folder / Instagram - <account> / Title [id].mp4` (official API) |

Title, description, uploader, date, thumbnail and chapters are written inside the mp4 (yt-dlp `--embed-metadata`). Instagram own-account files get the caption, date and link written inside by ffmpeg. English subtitles are an optional tick box.

## One-time setup (no new repos, no new secrets)
Everything lives in the repos you already have: `reelio` (app + worker) and `reelio-data` (private data).

1. Copy the new/changed files into `reelio` (list in `GRAB_README.md`). Commit. The Pages build updates the app by itself.
2. Google Cloud Console > your project > OAuth consent screen > Data access: add the scope `.../auth/drive.file` ("see and create only the files this app made"; it needs no Google review). Keep the app on "Publish app" (not Testing) or logins expire every 7 days.
3. In the Reelio app: Accounts > Add an account > **Google Drive for Save to Drive**. The client ID and secret are filled in from your existing Google login. Accept the permission.
4. More > Save to Drive > paste a link > Save to Drive.

Why a separate login: Google refuses to put `drive.file` and the YouTube permissions in one sign-in ("scopes that cannot be requested together"). So your existing Google login (Drive read + YouTube) is left exactly as it was, and Save to Drive gets its own login (`kind: google_save`) that has only `drive.file`.

## Why the main folder is made by Reelio
`drive.file` lets Reelio touch only files and folders it created itself. So Reelio creates "Reelio Downloads" in My Drive the first time. You may rename it or move it anywhere; Reelio keeps its access because it remembers the folder's ID. (Using an existing folder would need Google's full-Drive permission, which Google treats as restricted. The worker supports it through the `root_id` setting if you ever want it.)

## What it does when things go wrong
- One bad video never stops the rest (3 tries, then "Failed", with a Retry button).
- YouTube blocking the server pauses only YouTube items; Instagram trouble pauses only Instagram items. YouTube downloads use your cookie pool and proxy from Accounts > YouTube downloads, exactly like the other Reelio tools.
- Drive full / Google slow-down pauses that Google login and continues by itself.
- A run killed mid-upload is recovered by looking in Drive first (each file carries a hidden source tag), so nothing is saved twice. Adding the same playlist again only saves the new videos.
- Runs last up to 5h20m and start the next run by themselves. A check also runs hourly.

## Honest limits (not tested live)
Real YouTube/Instagram downloads from GitHub runner IPs, Google's real Drive consent and upload, and the page in a real browser. The worker logic is tested against fakes (13 tests in `worker/tests/test_grab.py`).
Rights: only save videos you own or may keep. Instagram links outside your own account need Instagram cookies and can get that account restricted; "My Instagram account" uses the official API and needs nothing extra.
