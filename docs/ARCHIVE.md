# Save an Instagram account's reels to Drive (accounts you have permission to use)

Works inside **Save to Drive**. Paste `instagram.com/name`, tick the permission box, tap the button. That is all.

## What happens by itself
1. Reelio finds the account's reels. Instagram does not give an official list, so it tries these ways in order and keeps the first that works:
   gallery-dl, Instaloader (both need the spare-account cookie), a headless browser, public mirror sites (no login), and an optional paid helper (Apify or RapidAPI).
2. Each reel is downloaded (yt-dlp first). If Instagram blocks that, Reelio switches to Instaloader, then to a direct video link found by the mirror sites or the paid helper. After two blocks in a row it stops knocking with yt-dlp for that run.
3. Each reel goes into Drive: `Reelio Downloads / Instagram - <name> / ...mp4`. Nothing is saved twice (a hidden tag on every Drive file, plus the job list).
4. Every 12 hours Reelio checks the account again and saves only the new reels. A failed check is retried in about 2 hours.
5. If everything is blocked, Reelio says so in plain words in the activity list and tries again later. Other accounts and YouTube are never affected.

## One-time steps (about 10 minutes)
1. **Update your code repo (`reelio`)**: upload the files from the update zip (see the top-level message). Keep the same folder names.
2. **Spare Instagram account**: make or pick an Instagram account you do not mind losing. Do NOT use your main one.
3. **Get its cookie**: log in to instagram.com with it in Chrome, install the free extension "Get cookies.txt LOCALLY", open instagram.com, click the extension, **Export** (Netscape format), open the file and copy everything.
4. **Paste it**: open Reelio, **Accounts > Instagram downloads**, paste, save.
5. **Add the account**: **Save to Drive**, paste `https://www.instagram.com/name/`, tick **I own these videos or have permission to save them**, tap the button.

## Optional: paid helper (most reliable when Instagram blocks GitHub)
Make an Apify account, copy the API token, and in your `reelio` repo go to Settings > Secrets and variables > Actions > New secret named `APIFY_TOKEN`. (RapidAPI works too: `RAPIDAPI_KEY`.) These cost money per use: set a spending limit.

## Honest limits
- Instagram blocks GitHub's servers a lot. Expect some days where the free ways fail; the cookie and the paid helper are what make it dependable.
- The mirror-site and paid-API parts could not be tested against the live services when this was written. Run it once on a small account and check the activity list.
- Only save content you own or have permission to keep. Scraping may break Instagram's terms; a spare account can be restricted.
