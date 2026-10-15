# Reelio Cookie Sync (Chrome / Edge / Brave)

Keeps the YouTube cookies in Reelio fresh by itself, so you never export cookie files by hand.

## Install (once per browser profile, 2 minutes)
1. Unzip the file. 2. Open `chrome://extensions` (Edge: `edge://extensions`), turn on **Developer mode**, click **Load unpacked**, pick the folder.
3. In that browser sign in to YouTube once with a spare Google account.
4. Open your Reelio app tab, click the puzzle icon > Reelio Cookie Sync > **Connect to Reelio**.
Another Google account = another Chrome profile + the same steps. Each profile is its own cookie slot, so they never overwrite each other.

## What it does
- Every hour while the browser is open (and at browser start) it reads this browser's youtube.com / google.com cookies, merges them into the encrypted `secrets.enc.json` in your private data repo (only its own slot, other logins untouched) and updates the cookie count. It sends only when something changed.
- It never shows or logs cookie values. It keeps the Reelio GitHub key and passphrase in this extension's private storage (`chrome.storage.local`, not synced). "Disconnect" erases them.
- Works with the normal GitHub login (not hosted/email mode). Computer browsers only (phone Chrome has no extensions).

## Honest limits
- The browser must be opened now and then: it sends while it runs. The PC does not need to be on 24/7. Between sends the last cookie keeps working until YouTube retires it; Reelio's pool, rest timers and backup Drive folder cover the gaps.
- Use a dedicated spare profile and do not keep YouTube tabs open in it: a profile that is idle keeps its cookies longer than one you browse with.
- Google can still log a cookie out whenever it wants (new location, security check). Then that slot needs a fresh sign-in in the browser; the next send replaces it.
- Not tested live: a real Chrome install, a real GitHub repo, real YouTube. Tested: the sync code with a fake Chrome and fake GitHub, and that the Python worker opens what it writes.
