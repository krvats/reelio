from ..errors import instagram_error, AccountProblem
from ..util import http, env_base
from . import download_url

GRAPH = lambda: env_base("IG_GRAPH", "https://graph.instagram.com")


def list_items(src, store, route):
    conn = store.conn(src["conn"]) or {}
    tok = store.secret(src["conn"]).get("access_token")
    if not tok:
        raise AccountProblem("The Instagram account used as a source is not connected.", "Open Accounts and connect it.", kind="setup")
    url = f"{GRAPH()}/v21.0/{conn.get('ig_user_id')}/media"
    params = {"fields": "id,media_type,media_url,caption,timestamp,thumbnail_url", "limit": 100, "access_token": tok}
    out = []
    while url:
        r = http("GET", url, params=params)
        j = r.json() if r.content else {}
        if r.status_code >= 400 or "error" in j:
            raise instagram_error(j.get("error", {}), r.status_code)
        for m in j.get("data", []):
            if m.get("media_type") == "VIDEO" and m.get("media_url"):
                out.append({"key": f"instagram:{m['id']}", "name": m["id"], "created": m["timestamp"], "thumb": m.get("thumbnail_url"),
                            "meta": {"caption": m.get("caption", ""), "url": m["media_url"]}})
        url = (j.get("paging") or {}).get("next"); params = None
    out.sort(key=lambda x: x["created"])
    return out


def fetch(item, dest, store, route):
    download_url(item["meta"]["url"], dest)
