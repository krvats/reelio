"""Worker in API mode: instead of reading/writing a git repo, take one flow at a time from the Reelio API (a lease), run the normal engine on a
temporary copy of that user's data, then send the results back. One bad flow or user never affects another: each lease is its own sandbox."""
import json, os, secrets, shutil, tempfile, time
from . import crypto
from .store import Store
from .util import http, read_json, write_json, say, scrub


class Api:
    def __init__(self, url, key):
        self.url, self.key = url.rstrip("/"), key

    def post(self, path, body):
        r = http("POST", self.url + path, headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}, data=json.dumps(body), timeout=(10, 60))
        if r.status_code == 409:
            return {"duplicate": True}
        if r.status_code >= 300:
            raise RuntimeError(f"API {path} answered {r.status_code}")
        return r.json()


def run_lease(api, lease, budget_min=45):
    from .engine import Engine
    tid, route = lease["tenant"], lease["route"]
    tmp = tempfile.mkdtemp(prefix="reelio_lease_")
    old_env = {k: os.environ.get(k) for k in ("REELIO_KEY", "REELIO_NO_GIT")}
    try:
        state = api.post("/v1/internal/state", {"tenant": tid, "route": route["id"]})
        pw = secrets.token_urlsafe(24)                                    # throw-away passphrase: secrets exist on disk only encrypted, only for this run
        write_json(os.path.join(tmp, "config.json"), {"connections": lease["config"]["connections"], "routes": [route], "timezone": lease["config"].get("timezone", "UTC")})
        write_json(os.path.join(tmp, "secrets.enc.json"), crypto.encrypt(api.post("/v1/internal/secrets", {"tenant": tid}), pw, iters=1000))
        write_json(os.path.join(tmp, "ledger.json"), state["ledger"])
        write_json(os.path.join(tmp, "queues", f"{route['id']}.json"), state["queue"])
        write_json(os.path.join(tmp, "status.json"), state.get("status") or {})
        for i, c in enumerate(state["inbox"]):
            c = {k: v for k, v in c.items() if k != "_k"}
            write_json(os.path.join(tmp, "inbox", f"{i:04d}.json"), c)
        os.environ["REELIO_KEY"], os.environ["REELIO_NO_GIT"] = pw, "1"
        before = {e["id"] for e in state["ledger"].get("entries", [])}
        Engine(Store(tmp), budget_min, route["id"]).run()
        led = read_json(os.path.join(tmp, "ledger.json"), {"entries": []})
        for e in led["entries"]:
            if e["id"] not in before:
                api.post("/v1/internal/ledger", {"tenant": tid, "entry": e})      # 409 = already there: fine
        api.post("/v1/internal/queue", {"tenant": tid, "route": route["id"], "queue": read_json(os.path.join(tmp, "queues", f"{route['id']}.json"), {"items": []})})
        st = read_json(os.path.join(tmp, "status.json"), {})
        st["recent"] = _recent(tmp)
        api.post("/v1/internal/status", {"tenant": tid, "route": route["id"], "status": st})
        api.post("/v1/internal/inbox-done", {"tenant": tid, "keys": [c["_k"] for c in state["inbox"]]})
        return True
    except Exception as e:
        say("Flow run failed safely:", scrub(e))
        return False
    finally:
        for k, v in old_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        try: api.post("/v1/internal/release", {"tenant": tid, "route": route["id"], "lease": lease["lease"], "cooldown": 240})
        except Exception: pass
        shutil.rmtree(tmp, ignore_errors=True)


def _recent(root):
    import glob
    out = []
    for f in sorted(glob.glob(os.path.join(root, "logs", "*.jsonl")))[-1:]:
        for line in open(f, encoding="utf-8").read().splitlines()[-40:]:
            try: out.append(json.loads(line))
            except Exception: pass
    return list(reversed(out))


def serve(url, key, worker="w1", budget_min=45, max_flows=10 ** 6):
    """Take leases until none are left or the time budget is used up."""
    api, t0, n, done = Api(url, key), time.time(), 0, []
    while n < max_flows and time.time() - t0 < budget_min * 60:
        lease = api.post("/v1/internal/lease", {"worker": worker, "seconds": max(300, budget_min * 60), "exclude": done})
        if not lease.get("lease"):
            break
        say(f"Running flow {lease['route'].get('name', lease['route']['id'])} for tenant {lease['tenant'][:6]}")
        done.append([lease["tenant"], lease["route"]["id"]])
        run_lease(api, lease, max(1, int(budget_min - (time.time() - t0) / 60)))
        n += 1
    return n
