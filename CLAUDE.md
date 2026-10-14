# Rules for any AI (or person) continuing this project

Reelio is a cloud autopilot that posts a user's own videos to Instagram Reels and YouTube Shorts. This file is read first in every new chat.

1. **Read order:** `CLAUDE.md` (this), `CONTEXT.md` (product, architecture, decisions), `docs/ROADMAP.md` (done / next), end of `docs/WORKLOG.md`, then run `python tools/handoff.py diff` to see what changed since the last saved snapshot. Those changes are either the owner's own edits (treat as intentional) or unfinished work from the previous chat.
2. **Look at `docs/screens/`** to see the current UI before changing it.
3. **Never rely on a chat summary.** The project is the memory. After every meaningful work block run `python tools/handoff.py snapshot --note "what you did"`, tick items in `docs/ROADMAP.md`, add a line to `docs/CHANGELOG.md`, and keep `CONTEXT.md` true. If the chat may end suddenly, snapshot earlier rather than later.
4. **Before delivering:** run all tests (`cd worker && python -m unittest discover -s tests`; `cd license && node --test test/`), regenerate screenshots (`python tools/screens.py`), run `python tools/handoff.py snapshot --tests`, then `python tools/handoff.py prompt`, then zip the whole folder.
5. **Owner preferences:** short replies, minimal questions (one batch at most), a finished zip every time, obvious decisions made without asking, plain-language UI for ages 5 to 80, nothing hardcoded or secret in files or logs. Say exactly what could NOT be tested live.
6. **Hard rules:** official APIs only; only content the user owns or has permission to use; one bad video never stops a queue, one bad account never stops others; no double posts; every external call has a timeout, retry and a plain-language error with a fix; secrets never in logs, UI or zips (tell the owner to rotate any that appear).
7. **Honesty about enforcement:** code that runs on a user's own machine or repo can always be patched. Paid access is only truly enforced where the posting runs on infrastructure the owner controls and checks the license server-side.
