# Add-on: Video links (paste a link, Reelio posts it)

Paste any video link (Instagram Reel/post, YouTube Short, or anything yt-dlp understands). Reelio downloads it in the cloud just before posting, then posts it to the flow's Instagram or YouTube account through the normal official posting path. No browser extension, no Instagram API for reading.

## Use it (2 minutes, after you upload these files and the site redeploys)
1. Flows > New flow (or edit one). "Where do the videos come from?" > **Video links**. Pick the target (Instagram Reels or YouTube Shorts), schedule, captions. Save.
2. Videos > pick that flow > **Add links**. Paste one link per line. Optional caption per link: `link | my caption`. Tick "Post these first" to jump the line. Tick the rights box. Add.
3. Done. The next worker run (max 5 min, or it starts one by itself) picks them up. Each link file is deleted after posting; a link is never posted twice, even pasted again with a different `?igsh=` tail.
- Caption mode "Original" uses the video's own caption (found during download). "Same for all"/table/hashtags work as usual.
- Same flow can mix Instagram and YouTube links.

## Page link (all videos of a page, automatically)
Flow source **Page link**: paste ONE link (an Instagram page like `https://www.instagram.com/yourpage/`, a YouTube channel, a playlist). Reelio lists the videos (up to 25-500, you choose), turns each into its own video link, and the Video links downloader posts them on your schedule. Every scan checks for new videos on the page. Choose "All videos on the page" or "Only videos added from now on" (the first scan just remembers what is already there). You must tick that the page is yours or you have permission. A video already posted (by a links flow or a page flow) is never posted again. Instagram pages almost always need the cookies.txt below; if refused, only that flow pauses and says so.

## Instagram links: honest limits
Instagram often refuses downloads from GitHub's servers. Reelio tries two ways: yt-dlp, then the post's public embed page (public posts only). If both fail, only that flow pauses 3 h and tells you the fix:
- Accounts > YouTube downloads > paste a cookies.txt that includes instagram.com (log in on your PC, export cookies with any "cookies.txt" tool). Cookies are encrypted like your other secrets. Using a login from a cloud IP can make Instagram ask you to verify; use a spare/secondary login for this, not your main account.
- Or save the file yourself and use **Upload here** (works 100%).
Only use videos you own or have permission to reuse; reposting other people's reels breaks Instagram's and copyright rules.

## New/changed files (all in this repo)
- NEW `worker/reelio/sources/page.py`, `worker/reelio/sources/links.py`, `web/js/links.js`, `worker/tests/test_links.py`, `docs/ADD_LINKS.md`
- CHANGED `worker/reelio/sources/__init__.py` (registers `links`), `worker/reelio/sources/upload.py` (optional `<video>.json` caption file, correct order), `worker/reelio/engine.py` (3 small hooks: cleanup, post-first, caption after download), `web/js/v_flows.js` (source option), `web/js/v_queue.js` (Add links button), `web/sw.js` (cache v3)
- Data repo gets `linkq/<flow>/<id>.json` files (one per link).

## Not tested live / not supported yet
Real Instagram/YouTube downloads from GitHub runners; the Add links dialog in a real browser (JS syntax-checked and the link-id rule is tested against the worker's, but not clicked through). Hosted (multi-user API) mode does not support links yet, same as Upload here.
