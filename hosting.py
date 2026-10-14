"""Instagram can only fetch a PUBLIC video URL, so each prepared file is parked on Cloudinary for a few
minutes and deleted right after posting (even if posting failed)."""
import os, re, hashlib, time
from .errors import AccountProblem, ItemProblem
from .util import http, env_base, HttpFail

BASE = lambda: env_base("CLOUDINARY_BASE", "https://api.cloudinary.com")


def _sign(params, secret):
    return hashlib.sha1(("&".join(f"{k}={params[k]}" for k in sorted(params)) + secret).encode()).hexdigest()


class Cloudinary:
    def __init__(self, sec):
        self.cloud, self.key, self.secret = sec.get("cloud_name"), sec.get("api_key"), sec.get("api_secret")
        if not (self.cloud and self.key and self.secret):
            raise AccountProblem("Cloudinary is not connected.", "Open Accounts, tap Cloudinary and paste the three values from your Cloudinary dashboard.", kind="setup")

    def upload(self, path):
        pid = "reelio_" + re.sub(r"[^A-Za-z0-9]", "", os.path.basename(path))[:24] + str(int(time.time()))
        ts = str(int(time.time()))
        p = {"public_id": pid, "timestamp": ts}
        try:
            with open(path, "rb") as f:
                r = http("POST", f"{BASE()}/v1_1/{self.cloud}/video/upload", timeout=(30, 600), retries=3,
                         data=dict(p, api_key=self.key, signature=_sign(p, self.secret)), files={"file": f})
        except HttpFail as e:
            raise ItemProblem(f"Could not reach Cloudinary: {e}", "Usually temporary. Reelio retries.")
        try:
            j = r.json()
        except Exception:
            j = {}
        if "secure_url" not in j:
            msg = (j.get("error") or {}).get("message", r.text[:120])
            if r.status_code in (401, 403) or "invalid" in msg.lower() and "key" in msg.lower() or "signature" in msg.lower():
                raise AccountProblem(f"Cloudinary rejected the login: {msg}", "Open Accounts, tap Cloudinary and re-paste the API key and secret.", kind="token")
            raise ItemProblem(f"Cloudinary refused the file: {msg}", "Check your Cloudinary storage is not full.")
        return j["secure_url"], pid

    def delete(self, pid):
        ts = str(int(time.time()))
        p = {"public_id": pid, "timestamp": ts, "invalidate": "true"}
        try:
            http("POST", f"{BASE()}/v1_1/{self.cloud}/video/destroy", retries=2, timeout=30,
                 data=dict(p, api_key=self.key, signature=_sign(p, self.secret)))
            return True
        except Exception:
            return False


def sweep(sec, older_than_min=30):
    """Delete leftovers from a run that died mid-post (anything named reelio_* on Cloudinary older than a bit)."""
    try:
        c = Cloudinary(sec)
        r = http("GET", f"{BASE()}/v1_1/{c.cloud}/resources/video/upload", retries=1, timeout=30,
                 params={"prefix": "reelio_", "max_results": 100}, auth=(c.key, c.secret))
        if r.status_code != 200:
            return 0
        n = 0
        import datetime
        from .util import parse_iso, now
        for res in r.json().get("resources", []):
            t = parse_iso(res.get("created_at"))
            if t and (now() - t).total_seconds() > older_than_min * 60:
                n += 1 if c.delete(res["public_id"]) else 0
        return n
    except Exception:
        return 0
