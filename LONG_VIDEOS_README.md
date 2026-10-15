# Long videos (any length) - what to add

Copy these files into your `krvats/reelio` repo at the same paths (they replace the old ones where they exist):

- `.github/workflows/long.yml`            (NEW: the long-video workflow)
- `worker/reelio/longjob.py`              (NEW)
- `worker/reelio/cli.py`                  (adds the `long` action)
- `worker/reelio/sources/youtube.py`      (small helpers the long workflow shares)
- `web/js/v_long.js`                      (NEW: the "Long videos" page)
- `web/js/app.js`, `web/js/v_more.js`, `web/sw.js`   (menu entry)
- `worker/tests/helpers.py`, `worker/tests/test_long.py`   (tests; optional)

No new secrets. It uses the same `DATA_PAT` and `REELIO_KEY`, and the same Google login as your other flows.
After pushing, open the app, then More, then Long videos.

## How it works
1. Paste video links (or let it look through a channel's long videos and past live streams).
2. Reelio makes one job per video and cuts it into equal parts no longer than "Longest part".
3. For each part: download only that time range, upload it to YouTube in resumable chunks, delete it, next part.
4. At about 5h20m the run stops cleanly and starts the next run by itself, until every part is up.
5. Once an hour it also checks for anything waiting (after YouTube's daily limit resets, etc).

A 24 hour video with 4 hour parts = 6 uploads named "Title (Part 1/6)" ... "(Part 6/6)".

## Limits you should know
- YouTube accepts videos over 15 minutes only from a phone-verified channel (youtube.com/verify).
- API uploads are limited by quota (about 6 a day for a new Google project), so 6 parts take about a day.
- Downloads from YouTube still need cookies or a proxy if YouTube blocks GitHub's servers (Accounts > YouTube downloads).
- Part boundaries are cut without re-encoding, so they can be off by a few seconds (fast, no quality loss).
- Disk on the runner is limited: 4 hour parts at 720p are fine, 8 hour parts at 1080p are too big (the app tells you).
- Only use videos you own or have permission to reuse.
