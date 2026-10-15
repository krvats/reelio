import argparse, os, sys
from .store import Store
from .util import say, scrub


def _maybe_analytics(store):
    """Refresh Reel stats about every 6 hours as part of normal runs."""
    from .util import read_json, parse_iso, now
    last = parse_iso((read_json(store.p("analytics.json"), {}) or {}).get("at"))
    if not last or (now() - last).total_seconds() > 6 * 3600:
        try:
            from . import analytics
            analytics.run(store); store.sync("reelio: analytics")
        except Exception as e:
            say("analytics skipped:", scrub(e))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reelio")
    ap.add_argument("action", choices=["run", "diagnose", "analytics", "scan", "long"], help="what to do")
    ap.add_argument("--data", default=os.environ.get("REELIO_DATA", "data"), help="folder with the data repo")
    ap.add_argument("--route", default=os.environ.get("REELIO_ROUTE") or None)
    ap.add_argument("--budget", type=int, default=int(os.environ.get("REELIO_BUDGET_MIN", "45")), help="max minutes for this run")
    a = ap.parse_args(argv)
    store = Store(a.data)
    try:
        if a.action in ("run", "scan"):
            from .engine import Engine
            eng = Engine(store, a.budget, a.route, force_scan=(a.action == "scan"))
            if a.action == "scan":
                eng.cfg["paused"] = True      # list sources and update queues, but post nothing
            eng.run()
            if a.action == "run":
                _maybe_analytics(store)
        elif a.action == "long":
            from . import longjob
            longjob.run(store, a.budget)
        elif a.action == "diagnose":
            from . import diagnose
            r = diagnose.run(store); say(r["verdict"])
            store.sync("reelio: diagnose")
        elif a.action == "analytics":
            from . import analytics
            analytics.run(store); say("analytics updated")
            store.sync("reelio: analytics")
    except Exception as e:      # last line of defence: never a red crash with a stack trace for the owner
        import traceback
        say("Reelio hit an unexpected problem and stopped safely:", scrub(e))
        print(scrub(traceback.format_exc()))
        try: store.flush_events(); store.sync("reelio: error")
        except Exception: pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
