"""A pool of YouTube cookies. The owner pastes (or drops) as many cookie files as they like into ONE box; Reelio splits
them, tries them in turn, remembers which ones are resting and for how long, and never wastes a try on a cookie that
is known to be resting. Health is stored by a short fingerprint only (never the cookie itself).

Two kinds of failure, treated differently:
  blocked  YouTube refused this cookie for now (bot check, 429). It usually recovers after a rest: 30 min, 2 h, 6 h, 24 h.
  expired  The login behind the cookie ended (signed out, rotated). It does NOT come back: retried only after
           6 h, 24 h, 72 h and then parked until the owner adds a fresh one or taps "try again".
A video that is private or removed is NOT the cookie's fault and never counts against it."""
import os, re, hashlib, tempfile, shutil, datetime
from .util import read_json, write_json, iso, now

MARK = "# ---- next cookie ----"
_HEADER = re.compile(r"^\s*#\s*(Netscape\s+)?HTTP Cookie File", re.I)
BLOCKED_STEPS = (30, 120, 360, 1440)          # minutes
EXPIRED_STEPS = (360, 1440, 4320, 525600)     # last step = parked for a year
HEALTH_FILE = "cookie_health.json"


def _valid_line(line):
    if not line.strip() or (line.lstrip().startswith("#") and not line.lstrip().startswith("#HttpOnly_")):
        return False
    return len(line.rstrip("\r\n").split("\t")) >= 7


def split_pool(text):
    """One big pasted text (or several files joined together) -> a list of separate cookie files, de-duplicated."""
    chunks, cur = [], []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        if line.strip() == MARK or _HEADER.match(line):
            if cur:
                chunks.append(cur)
            cur = [] if line.strip() == MARK else [line]
        else:
            cur.append(line)
    if cur:
        chunks.append(cur)
    out, seen = [], set()
    for c in chunks:
        good = [l for l in c if _valid_line(l)]
        if not good:
            continue
        body = "# Netscape HTTP Cookie File\n" + "\n".join(l for l in c if l.strip() and (_valid_line(l) or l.lstrip().startswith("#"))
                                                              and not _HEADER.match(l)) + "\n"
        cid = meta(body)[0]
        if cid not in seen:
            seen.add(cid); out.append(body)
    return out


def fingerprint(body):
    return hashlib.sha256(body.encode()).hexdigest()[:10]


_PROFILE = re.compile(r"^\s*#\s*reelio-profile:\s*([A-Za-z0-9_-]+)[ \t]*(.*)$", re.M)


def meta(body):
    """(identity, label). The sync extension marks each browser profile with '# reelio-profile: <id> <label>', so a
    refreshed export of the SAME profile is the same cookie slot; anything else is identified by its content."""
    m = _PROFILE.search(body or "")
    return ("p-" + m.group(1), m.group(2).strip()) if m else (fingerprint(body), "")


def classify(stderr):
    """'expired' | 'blocked' | None (None = not the cookie's fault)."""
    low = (stderr or "").lower()
    if "cookies are no longer valid" in low or "no longer valid" in low or "have been rotated" in low:
        return "expired"
    if "confirm you" in low or "sign in" in low or "bot" in low or "429" in low or "too many requests" in low:
        return "blocked"
    return None


class Pool:
    def __init__(self, store, src=None):
        self.store = store
        sec = store.secret((src or {}).get("net_conn", "youtube-net"))
        self.items = [(meta(b)[0], b) for b in split_pool(sec.get("cookies") or "")]
        self.labels = {meta(b)[0]: meta(b)[1] for _, b in self.items}
        self.fp = {cid: fingerprint(b) for cid, b in self.items}
        self.path = store.p(HEALTH_FILE)
        self.h = (read_json(self.path, None) or {}).get("items", {})
        for cid in list(self.h):                       # a refreshed export is a fresh cookie: forget its old rest timer
            if cid in self.fp and self.h[cid].get("fp") and self.h[cid]["fp"] != self.fp[cid]:
                self.h.pop(cid)

    # ---- reading
    def _until(self, cid):
        u = (self.h.get(cid) or {}).get("until")
        try:
            return datetime.datetime.fromisoformat(u.replace("Z", "+00:00")) if u else None
        except Exception:
            return None

    def ready(self):
        """Cookies that may be tried now, least recently used first (spreads the load, so no one cookie is hammered)."""
        t = now()
        r = [(cid, b) for cid, b in self.items if not (self._until(cid) and self._until(cid) > t)]
        r.sort(key=lambda x: (self.h.get(x[0]) or {}).get("last_used") or "")
        return r

    def resting(self):
        t = now()
        return [(cid, self._until(cid)) for cid, _ in self.items if self._until(cid) and self._until(cid) > t]

    def minutes_until_next(self, default=180):
        """When should the flow look again? The soonest a resting cookie wakes up (15 min to 12 h). No cookies: default."""
        if not self.items:
            return default
        if self.ready():
            return 15
        waits = [(u - now()).total_seconds() / 60 for _, u in self.resting()]
        return int(min(720, max(15, min(waits)))) if waits else default

    def summary(self):
        """Plain counts for the app: how many cookies are ready, resting (will come back) or parked (logged out)."""
        t = now()
        items, nxt = [], None
        for cid, _ in self.items:
            u, kind = self._until(cid), (self.h.get(cid) or {}).get("kind")
            if u and u > t:
                parked = kind == "expired" and (u - t).days > 300
                items.append({"id": cid[:4], "label": self.labels.get(cid, ""), "state": "parked" if parked else "resting", "kind": kind, "until": None if parked else iso(u)})
                if not parked and (nxt is None or u < nxt):
                    nxt = u
            else:
                items.append({"id": cid[:4], "label": self.labels.get(cid, ""), "state": "ready", "kind": None, "until": None})
        c = lambda st: sum(1 for i in items if i["state"] == st)
        return {"total": len(items), "ready": c("ready"), "resting": c("resting"), "parked": c("parked"),
                "next_at": iso(nxt) if nxt else None, "items": items}

    # ---- writing
    def _save(self):
        keep = {cid: dict(v, fp=self.fp[cid]) for cid, v in self.h.items() if cid in self.fp}
        write_json(self.path, {"items": keep, "updated": iso()})

    def used(self, cid):
        self.h.setdefault(cid, {})["last_used"] = iso()

    def ok(self, cid):
        e = self.h.setdefault(cid, {})
        e.update({"fails": 0, "kind": None, "until": None, "last_ok": iso(), "last_used": iso()})
        self._save()

    def fail(self, cid, kind):
        e = self.h.setdefault(cid, {})
        n = int(e.get("fails", 0)) if e.get("kind") == kind else 0
        steps = EXPIRED_STEPS if kind == "expired" else BLOCKED_STEPS
        mins = steps[min(n, len(steps) - 1)]
        e.update({"fails": n + 1, "kind": kind, "last_fail": iso(), "last_used": iso(),
                  "until": iso(now() + datetime.timedelta(minutes=mins))})
        self._save()
        return mins

    def retry_all(self):
        """The owner tapped 'try again': wake everything up now."""
        for e in self.h.values():
            e["until"] = None
        self._save()


class _CookieFiles:
    """Writes each cookie to its own private temp file, removed afterwards."""
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="rk_")

    def path(self, cid, body):
        p = os.path.join(self.dir, cid + ".txt")
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o600)
        return p

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run_with_pool(store, src, attempt, ok, err):
    """Run attempt(cookie_args) with each ready cookie in turn, then once with no cookie at all.
    ok(result) says whether it worked; err(result) gives yt-dlp's error text.
    Stops early on an error that is not the cookie's fault (private video, no disk space...).
    Returns (result, notes) where notes lists what happened, in plain words, for the activity log."""
    pool = Pool(store, src)
    files, notes = _CookieFiles(), []
    try:
        for cid, body in pool.ready():
            res = attempt(["--cookies", files.path(cid, body)])
            pool.used(cid)
            if ok(res):
                pool.ok(cid)
                if notes:
                    notes.append(f"cookie {cid[:4]} worked")
                return res, notes
            kind = classify(err(res))
            if kind is None:
                return res, notes                      # the video's problem, not the cookie's: do not burn the others
            mins = pool.fail(cid, kind)
            notes.append(f"cookie {cid[:4]} {kind}, resting {mins} min")
        res = attempt([])                              # last easy path: no cookie at all
        if ok(res):
            if pool.items:
                notes.append("worked without a cookie")
            return res, notes
        return res, notes
    finally:
        files.close()
