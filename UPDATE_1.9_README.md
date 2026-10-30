# Reelio 1.9: what is new and what to do

## What changed (plain words)
1. **New look**: the whole thing (app, website, privacy/terms pages, admin pages, icon) now looks like Jankari Patra: warm paper background, thick navy borders, hard shadows, orange / yellow / teal / red, big uppercase labels. Light and dark both work. More > Settings lets you pick the accent colour.
2. **Save to Drive** (your version) now also has: ownership tick, newest 10/25/50/100/All, YouTube Videos/Shorts/both, clean links, "Check for new videos", "Paste copied link". My separate "Extract to Drive" tab is gone; it is merged here.
3. **Easy for users**: Share a link from YouTube/Instagram straight into Reelio (after "Add to Home screen"), a "Save a video to Drive" box on Home, long-press shortcuts on the app icon, search (Ctrl+K) knows Save to Drive.
4. **Easy to advertise**: open `promote.html` on your site. It makes a tracked link, QR, English and Hindi captions and ad pictures. The "Message us" button now gives visitors a ready message with a code so you can see which ad worked. Details: `docs/ADS.md`.

## One-time checklist (about 10 minutes)
- [ ] Upload everything in this zip over your `krvats/reelio` repo (keep the folder layout). Commit. Wait for the Pages build (Actions tab, green tick).
- [ ] Nothing new for secrets. `grab.yml` and the Google "Drive for Save to Drive" login you already have keep working.
- [ ] Open your site, press Ctrl+F5 once (or close and reopen the installed app) so the new look loads.
- [ ] Phone: open the app in Chrome, menu > **Add to Home screen** (or Install). Then share a YouTube link and choose Reelio.
- [ ] Open `.../promote.html`, make your link, post your first ad.
- [ ] Optional: free counter at goatcounter.com, put the name in `web/app-config.js`.
- [ ] If the file `app-config.js` in your repo has your own settings, keep yours and just add the line `goatcounter: ''`.

## Tested here
Worker: 122 tests run; all pass except 2 old failures in `test_phase_c` (comments; they fail on your original zip too) and one start-up flake in `test_cookiesync` that passes when re-run. Save to Drive: 21 tests (7 new). Browser check (`python tools/ui_check.py`): every screen on phone and desktop, light and dark, no errors, no sideways scrolling; share link; ownership tick; Save to Drive demo; landing page; ads page and ref-code box.

## NOT tested live (needs your real accounts)
- Real YouTube/Instagram downloads from GitHub's servers, and real uploads to your Drive (tests use fake servers).
- Instagram: another person's whole account does not work from cloud servers (Instagram blocks it). Paste reel links instead, or use "My Instagram account" for yours.
- The phone **Share to Reelio** menu (needs the app installed from your real address; Android Chrome works, iPhone Safari does not support it).
- QR code and caption page need internet for the QR library (cdnjs).
- Font: I could not download Space Grotesk, so headings use the bundled Bricolage Grotesque. To change: put the font file in `web/fonts` and change the font-family name in `style.css` and `site.css`.
- Hindi ad pictures use the computer's Hindi font; regenerate with `python tools/make_ads.py yourname.github.io/reelio` if you want another address on them.
