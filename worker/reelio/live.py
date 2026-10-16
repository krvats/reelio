"""Always-on mode. Instead of one quick pass every 5 minutes, one workflow run stays alive for ~50 minutes and keeps looking:
every pass starts each account in its own parallel lane and posts at most one video per account, then looks again right away.
Between passes it pulls the data repo every few seconds, so a "Post now" tap from the app is picked up within about 15 seconds,
even while other accounts are busy. The workflow starts the next run by itself, so there is no gap."""
import os, time
from .engine import Engine
from .util import say, scrub

POLL_SECONDS = 15
STOP_WHEN_LEFT_MIN = 8          # the engine needs time to finish and push; leave it to the next run


def run(store, budget_min=50, only_route=None, poll=POLL_SECONDS, sleeper=time.sleep):
    end = time.time() + budget_min * 60
    passes = 0
    while (end - time.time()) / 60 > STOP_WHEN_LEFT_MIN:
        busy = False
        try:
            eng = Engine(store, (end - time.time()) / 60, only_route, live=True)
            ok = eng.run()
            if ok is False:
                say("Reelio cannot continue until the setup problem above is fixed."); return passes
            busy = bool(eng.posted_this_run or eng.cmds_applied)
        except Exception as e:                       # one bad pass never ends the loop
            say("pass problem (continuing):", scrub(e))
        passes += 1
        if not busy:
            sleeper(poll)
            store.refresh()
        else:
            sleeper(1)
    say(f"live loop finished after {passes} passes")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:                                    # tells the workflow to start the next run right away
        with open(out, "a") as f:
            f.write("more=true\n")
    return passes
