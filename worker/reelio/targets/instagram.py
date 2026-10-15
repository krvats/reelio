"""Instagram API with Instagram Login (graph.instagram.com). Instagram only accepts a public video_url,
so the prepared file is parked on Cloudinary, Instagram fetches it, we publish, then delete it."""
import time
from ..errors import instagram_error, ItemProblem, AccountProblem, RunLimit
from ..hosting import Cloudinary
from .. import util
from ..util import scrub, http, env_base, HttpFail, iso, now, parse_iso

GRAPH = lambda: env_base("IG_GRAPH", "https://graph.instagram.com")
VER = "v21.0"


class Instagram:
    def __init__(self, conn, sec):
        self.uid = str(conn.get("ig_user_id", "")).strip()
        self.token = str(sec.get("access_token", "")).strip()
        util.register_secret(self.token)
        if not (self.uid and self.token):
            raise AccountProblem("This Instagram account is not connected.", "Open Accounts, tap the account and paste a token.", kind="setup")

    @property
    def api(self):
        return f"{GRAPH()}/{VER}"

    def _call(self, method, path, **kw):
        kw.setdefault("params" if method == "GET" else "data", {})
        kw["params" if method == "GET" else "data"]["access_token"] = self.token
        try:
            r = http(method, f"{self.api}/{path}", **kw)
        except HttpFail as e:
            raise ItemProblem(f"Could not reach Instagram: {e}", "Usually temporary. Reelio retries.")
        try:
            j = r.json()
        except Exception:
            j = {}
        if r.status_code >= 400 or (isinstance(j, dict) and "error" in j):
            raise instagram_error(j.get("error") if isinstance(j, dict) and "error" in j else {"message": r.text[:200]}, r.status_code)
        return j

    def me(self):
        return self._call("GET", "me", params={"fields": "user_id,username,account_type,media_count"})

    def quota_left(self):
        j = self._call("GET", f"{self.uid}/content_publishing_limit", params={"fields": "quota_usage,config"})
        d = (j.get("data") or [{}])[0]
        return int((d.get("config") or {}).get("quota_total", 100)) - int(d.get("quota_usage", 0))

    def refresh(self):
        """Long-lived tokens last 60 days; refresh gives 60 more. Returns (token, expires_at_iso) or None."""
        try:
            r = http("GET", f"{GRAPH()}/refresh_access_token", retries=2, params={"grant_type": "ig_refresh_token", "access_token": self.token})
            j = r.json()
        except Exception:
            return None
        if "access_token" in j:
            return j["access_token"], iso(now().replace(microsecond=0) + __import__("datetime").timedelta(seconds=int(j.get("expires_in", 5184000))))
        return None

    def create(self, video_url, caption, share_to_feed=True, cover_ms=None):
        d = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": str(bool(share_to_feed)).lower()}
        if cover_ms is not None:
            d["thumb_offset"] = int(cover_ms)
        return self._call("POST", f"{self.uid}/media", data=d, timeout=(15, 120))["id"]

    def status(self, cid):
        return self._call("GET", cid, params={"fields": "status_code,status"})

    def wait(self, cid, deadline):
        util.sleep(6)
        delay, waited = 8, 6
        while waited < 900:
            if deadline and time.time() > deadline:
                raise RunLimit()
            st = self.status(cid)
            if st.get("status_code") == "FINISHED":
                return
            if st.get("status_code") in ("ERROR", "EXPIRED"):
                detail = str(st.get("status") or "")
                import re
                m = re.search(r"(\d{7})", detail)
                err = {"message": detail or "processing failed", "error_subcode": int(m.group(1)) if m else None}
                p = instagram_error(err)
                if isinstance(p, ItemProblem) and not p.code:
                    p = ItemProblem("Instagram could not process this video (no reason given).",
                                    "Usually the video host was unreachable. Reelio retries; if all videos fail run Help > Why is it failing?")
                raise p
            util.sleep(delay); waited += delay; delay = min(delay + 4, 20)
        raise ItemProblem("Instagram took more than 15 minutes to process this video.", "Reelio retries later.")

    def publish(self, cid):
        return self._call("POST", f"{self.uid}/media_publish", data={"creation_id": cid}, timeout=(15, 120))["id"]

    def comment(self, mid, text):
        """First comment under the new Reel (needs the comments permission; a failure never loses the post)."""
        return self._call("POST", f"{mid}/comments", data={"message": text})

    def permalink(self, mid):
        try:
            return self._call("GET", mid, params={"fields": "permalink"}).get("permalink", "")
        except Exception:
            return ""

    def insights(self, mid):
        for metrics in ("reach,likes,comments,shares,saved,views", "reach,likes,comments,shares,saved,plays"):
            try:
                j = self._call("GET", f"{mid}/insights", params={"metric": metrics})
                return {m["name"]: (m.get("values") or [{}])[0].get("value", 0) for m in j.get("data", [])}
            except Exception:
                continue
        return {}

    def recent_media(self, limit=30):
        j = self._call("GET", f"{self.uid}/media", params={"fields": "id,caption,timestamp,permalink,media_type,like_count,comments_count", "limit": limit})
        return j.get("data", [])


def post(ctx, item, path, caption):
    """ctx: store, route, conn (target connection dict), deadline, journal(fn). Returns {media_id, permalink, container_id}."""
    store, route, conn = ctx["store"], ctx["route"], ctx["conn"]
    ig = Instagram(conn, store.secret(conn["id"]))
    cld = Cloudinary(store.secret(store.host_conn(route)))
    edit = route.get("edit") or {}
    pid = None
    try:
        url, pid = cld.upload(path)
        ctx["journal"]({"stage": "uploaded", "src": item["key"], "pid": pid, "at": iso()})
        cover = edit.get("cover_seconds")
        cid = ig.create(url, caption, route.get("share_to_feed", True), None if cover in (None, "") else float(cover) * 1000)
        ctx["journal"]({"stage": "container", "src": item["key"], "pid": pid, "cid": cid, "at": iso()})
        ig.wait(cid, ctx.get("deadline"))
        ctx["journal"]({"stage": "ready", "src": item["key"], "pid": pid, "cid": cid, "at": iso()})
        mid = ig.publish(cid)
        fc = ((route.get("comment") or {}).get("text") or "").strip() if (route.get("comment") or {}).get("enabled") else ""
        if fc:
            try:
                ig.comment(mid, fc)
            except Exception as e:
                store.event("warn", f"Posted, but the first comment could not be added ({scrub(e)})", route["id"], "Reconnect Instagram and allow comments, or turn the first comment off.")
        return {"media_id": mid, "container_id": cid, "permalink": ig.permalink(mid)}
    finally:
        if pid:
            cld.delete(pid)
