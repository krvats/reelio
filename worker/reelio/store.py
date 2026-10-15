"""Everything Reelio remembers lives in one folder (the private data repo): settings, secrets (encrypted),
the never-repost ledger, per-flow queues, status, logs. Only the worker writes queues/ledger/status;
only the app writes config and inbox commands, so the two never fight over a file."""
import os, glob, json, subprocess, time
from . import crypto
from .util import read_json, write_json, iso, now, register_secret, scrub, say

DEFAULT_CONFIG = {
    "version": 1, "paused": False, "timezone": "Asia/Kolkata",
    "notify": {"telegram": {"enabled": False, "conn": "telegram", "events": {"posted": False, "failed": True, "limit": True, "token": True, "daily": True}}},
    "connections": [], "routes": [],
}
WORKER_FILES = ("ledger.json", "status.json", "diagnose.json", "analytics.json", "cookie_health.json", "queues", "logs")


class Store:
    def __init__(self, root, passphrase=None):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.passphrase = passphrase if passphrase is not None else os.environ.get("REELIO_KEY", "")
        self._secrets = None
        self._events = []

    # ---- paths
    def p(self, *a):
        return os.path.join(self.root, *a)

    # ---- config (written by the app only)
    def config(self):
        c = read_json(self.p("config.json"), None) or {}
        out = json.loads(json.dumps(DEFAULT_CONFIG))
        out.update(c)
        return out

    def conn(self, cid):
        return next((c for c in self.config()["connections"] if c["id"] == cid), None)

    def host_conn(self, route):
        """Which saved connection holds the video host (Cloudinary) login for this flow."""
        if route.get("host_conn"):
            return route["host_conn"]
        return next((c["id"] for c in self.config()["connections"] if c["kind"] == "cloudinary"), "cloudinary")

    # ---- secrets
    def secrets(self):
        if self._secrets is None:
            blob = read_json(self.p("secrets.enc.json"), None)
            if not blob:
                self._secrets = {}
            else:
                if not self.passphrase:
                    raise ValueError("REELIO_KEY is not set. Add it under GitHub > Settings > Secrets (same passphrase you typed in the app).")
                self._secrets = crypto.decrypt(blob, self.passphrase)
            for s in self._secrets.values():
                for v in (s.values() if isinstance(s, dict) else []):
                    register_secret(v)
        return self._secrets

    def secret(self, cid):
        return self.secrets().get(cid) or {}

    def save_secret(self, cid, fields):
        s = self.secrets()
        s.setdefault(cid, {}).update(fields)
        for v in fields.values():
            register_secret(v)
        write_json(self.p("secrets.enc.json"), crypto.encrypt(s, self.passphrase))

    # ---- ledger (permanent: nothing is ever posted twice to the same account)
    def ledger(self):
        if not hasattr(self, "_ledger"):
            self._ledger = read_json(self.p("ledger.json"), None) or {"entries": [], "inflight": {}}
            self._ledger.setdefault("entries", []); self._ledger.setdefault("inflight", {})
            self._index = {}
            for e in self._ledger["entries"]:
                self._idx(e)
        return self._ledger

    def _idx(self, e):
        s = self._index.setdefault(e["target"], set())
        s.add(e["src"])
        if e.get("md5"):
            s.add("md5:" + e["md5"])

    def posted_keys(self, target):
        self.ledger()
        return self._index.get(target, set())

    def add_ledger(self, e):
        led = self.ledger()
        led["entries"].append(e); self._idx(e)
        write_json(self.p("ledger.json"), led)

    def backfill_md5(self, target, src, md5):
        for e in self.ledger()["entries"]:
            if e["target"] == target and e["src"] == src and not e.get("md5") and md5:
                e["md5"] = md5; self._idx(e); return True
        return False

    def save_ledger(self):
        write_json(self.p("ledger.json"), self.ledger())

    def set_inflight(self, route_id, data):
        led = self.ledger()
        if data is None:
            led["inflight"].pop(route_id, None)
        else:
            led["inflight"][route_id] = data
        self.save_ledger()

    def posted_today(self, route_id, tz, day):
        """number of posts by this flow on local calendar day `day` (date)"""
        n = 0
        for e in self.ledger()["entries"]:
            if e.get("route") == route_id and e.get("status", "posted") in ("posted", "unknown_id"):
                t = _parse(e.get("at"))
                if t and t.astimezone(tz).date() == day:
                    n += 1
        return n

    def posted_last_24h(self, target):
        cut = now().timestamp() - 86400
        return sum(1 for e in self.ledger()["entries"] if e["target"] == target and (_parse(e.get("at")) or now()).timestamp() > cut)

    # ---- queues
    def queue(self, route_id):
        q = read_json(self.p("queues", f"{route_id}.json"), None) or {"items": [], "last_scan": None}
        q.setdefault("items", [])
        return q

    def save_queue(self, route_id, q):
        write_json(self.p("queues", f"{route_id}.json"), q)

    # ---- status / events
    def status(self):
        return read_json(self.p("status.json"), None) or {}

    def save_status(self, st):
        st["updated"] = iso()
        write_json(self.p("status.json"), st)

    def event(self, level, msg, route=None, fix=None, **extra):
        ev = {"at": iso(), "level": level, "route": route, "msg": scrub(msg)}
        if fix:
            ev["fix"] = fix
        ev.update(extra)
        self._events.append(ev)
        say(f"[{level}]", f"({route})" if route else "", msg, ("-> " + fix) if fix else "")

    def flush_events(self):
        if not self._events:
            return
        month = now().strftime("%Y-%m")
        path = self.p("logs", f"{month}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for ev in self._events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._events = []
        lines = open(path, encoding="utf-8").read().splitlines()
        if len(lines) > 3000:
            open(path, "w", encoding="utf-8").write("\n".join(lines[-2000:]) + "\n")

    def recent_events(self, n=60):
        out = []
        for path in sorted(glob.glob(self.p("logs", "*.jsonl")))[-2:]:
            for line in open(path, encoding="utf-8").read().splitlines()[-n:]:
                try: out.append(json.loads(line))
                except Exception: pass
        return out[-n:]

    # ---- inbox: one tiny file per command from the app (never conflicts)
    def inbox(self):
        cmds = []
        for f in sorted(glob.glob(self.p("inbox", "*.json"))):
            c = read_json(f, None)
            if isinstance(c, dict):
                c["_file"] = f; cmds.append(c)
            else:
                os.remove(f)
        return cmds

    def inbox_done(self, cmd):
        try: os.remove(cmd["_file"])
        except Exception: pass

    # ---- git sync (data repo). Commit after every post so a killed run never loses the ledger.
    def sync(self, msg="reelio update"):
        if os.environ.get("REELIO_NO_GIT") or not os.path.isdir(self.p(".git")):
            return True
        g = lambda *a: subprocess.run(["git", "-C", self.root, *a], capture_output=True, text=True)
        g("config", "user.name", "reelio-bot"); g("config", "user.email", "reelio-bot@users.noreply.github.com")
        g("add", "-A")
        if g("diff", "--cached", "--quiet").returncode == 0 and not g("log", "origin/HEAD..HEAD", "--oneline").stdout.strip():
            return True
        g("commit", "-m", msg)
        for attempt in range(4):
            if g("pull", "--rebase", "--autostash").returncode != 0:
                g("rebase", "--abort")
                if not self._force_mine(g):
                    time.sleep(2 * (attempt + 1)); continue
            if g("push").returncode == 0:
                return True
            time.sleep(2 * (attempt + 1))
        say("warning: could not push data to GitHub (will retry next time)")
        return False

    def _force_mine(self, g):
        """Rebase conflict: keep the worker-owned files from this run, take everything else from the remote."""
        keep = {}
        for name in WORKER_FILES:
            path = self.p(name)
            if os.path.isfile(path):
                keep[name] = open(path, "rb").read()
            elif os.path.isdir(path):
                for dp, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(dp, f); keep[os.path.relpath(fp, self.root)] = open(fp, "rb").read()
        if g("fetch", "origin").returncode != 0:
            return False
        branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if g("reset", "--hard", f"origin/{branch}").returncode != 0:
            return False
        for rel, data in keep.items():
            fp = self.p(rel); os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "wb").write(data)
        g("add", "-A"); g("commit", "-m", "reelio update (merged)")
        return True


def _parse(s):
    from .util import parse_iso
    return parse_iso(s)
