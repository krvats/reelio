# Reelio

Your own videos, posted automatically to Instagram Reels and YouTube Shorts, from the cloud. Your PC can stay off.
You manage everything from a phone-friendly web app. No code, no config files.

## How it works (the short version)
- **This repo (public)** holds the app (`web/`, shown on GitHub Pages) and the worker (`worker/`, run by GitHub Actions every 5 minutes).
- **A second, private repo `reelio-data`** holds your settings, queue, the never-repost ledger and your logins (encrypted with your passphrase).
- The app edits the private repo through GitHub's API. The worker reads it, posts what is due, and saves the result.
- Instagram only accepts a public video address, so each video waits on Cloudinary for about a minute and is deleted right after posting.

Any source can feed any target, so you choose per "flow":
Google Drive, a YouTube channel, your own Instagram, or files uploaded from the app, going to Instagram Reels or YouTube Shorts.

## One-time setup (about 15 minutes)
Everything below is also shown, with buttons, inside the app's setup page.

1. **Create the public repo** `reelio` on GitHub and upload the contents of this folder (Add file, Upload files).
2. **Turn on the app page:** repo Settings, Pages, Source = **GitHub Actions**. The page appears at `https://YOURNAME.github.io/reelio/`.
3. **Create a private repo** `reelio-data` (empty is fine). If you are moving from the old tools, upload the files from `reelio-data-seed/` into it. That keeps your 7 posted Reels and 9 uploaded Shorts from ever being posted again.
4. **Make a GitHub key:** github.com/settings/personal-access-tokens/new. Only select repositories: `reelio` and `reelio-data`. Permissions: Contents = Read and write, Actions = Read and write.
5. **Add two secrets** in `reelio` > Settings > Secrets and variables > Actions: `DATA_PAT` = the key from step 4, `REELIO_KEY` = a passphrase you invent (write it down).
6. **Open the app page**, paste the key and the same passphrase. The setup page checks every step.
7. **Connect accounts** in the app: Instagram (token from the Meta developer dashboard), Cloudinary (free), Google (Drive and YouTube), and optionally Telegram for alerts.
8. **Create or review your flows**, press Check now, then Help > Why is it failing? to confirm everything is connected.

Rotate first: the access tokens, API keys and client secrets that were in your old zips and chats should be regenerated, then entered only in the app.

## Honest limits
- GitHub's schedule runs about every 5 minutes (sometimes late). Instagram and Meta limit how fast apps can post, so more is not faster. The default of 50 a day per account is the high end; if Meta shows "Application request limit reached" Reelio waits and resumes by itself.
- Instagram allows at most 100 API posts per 24 hours per account. YouTube's API allows only about 6 uploads a day for new projects.
- YouTube may block downloads from cloud servers. Reelio then switches to your next saved cookie, rests the ones that fail (a blocked one comes back after its timer; a logged-out one does not), and only pauses that flow if every way fails, then it tells you to add cookies (Accounts > YouTube cookies, many at once) or use a backup Drive folder.
- Only use videos you own or have permission to post.

## Developing
`cd worker && python -m unittest discover -s tests` runs 36 tests against fake Instagram, Drive, YouTube, Cloudinary and Telegram servers.
`python tools/ui_demo.py` serves the app with demo data and a fake GitHub for testing the interface.
