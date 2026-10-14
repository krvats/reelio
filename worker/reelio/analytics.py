"""Pulls views/likes/reach for recent Reels (official API only, your own accounts) and works out the best posting hours."""
import datetime
from collections import defaultdict
from .util import iso, now, write_json, parse_iso
from .errors import Problem
from .scheduler import tzinfo


def run(store):
    cfg = store.config()
    tz = tzinfo(cfg.get("timezone"))
    out = {"at": iso(), "accounts": {}, "daily": {}}
    # posts per day per flow (last 45 days) from the ledger - works for every target
    cut = now() - datetime.timedelta(days=45)
    for e in store.ledger()["entries"]:
        t = parse_iso(e.get("at"))
        if t and t >= cut:
            out["daily"].setdefault(e["route"], {}).setdefault(t.astimezone(tz).date().isoformat(), 0)
            out["daily"][e["route"]][t.astimezone(tz).date().isoformat()] += 1
    from .targets.instagram import Instagram
    for c in cfg["connections"]:
        if c["kind"] != "instagram" or not store.secret(c["id"]).get("access_token"):
            continue
        try:
            ig = Instagram(c, store.secret(c["id"]))
            posts = []
            for m in ig.recent_media(30):
                ins = ig.insights(m["id"]) if m.get("media_type") in ("VIDEO", "REELS") else {}
                posts.append({"id": m["id"], "at": m.get("timestamp"), "permalink": m.get("permalink"), "caption": (m.get("caption") or "")[:80],
                              "likes": ins.get("likes", m.get("like_count", 0)), "comments": ins.get("comments", m.get("comments_count", 0)),
                              "reach": ins.get("reach", 0), "views": ins.get("views", ins.get("plays", 0)), "shares": ins.get("shares", 0), "saved": ins.get("saved", 0)})
            by = defaultdict(list)
            for p in posts:
                t = parse_iso((p["at"] or "").replace("+0000", "+00:00"))
                if t:
                    by[t.astimezone(tz).hour].append(p["reach"] or p["views"] or 0)
            best = sorted(((sum(v) / len(v), h) for h, v in by.items() if len(v) >= 1), reverse=True)[:3]
            out["accounts"][c["id"]] = {"label": c.get("label", c["id"]), "posts": posts, "best_hours": [h for _, h in best],
                                        "totals": {k: sum(p[k] for p in posts) for k in ("likes", "comments", "reach", "views", "shares", "saved")}}
        except Problem as p:
            out["accounts"][c["id"]] = {"label": c.get("label", c["id"]), "error": p.msg, "fix": p.fix}
    write_json(store.p("analytics.json"), out)
    return out
