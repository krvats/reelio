"""YouTube upload through the official API (resumable, so a cut connection continues instead of duplicating)."""
import os, json
from ..google import GoogleAuth
from ..errors import youtube_error, ItemProblem, AccountProblem
from ..util import http, env_base, HttpFail
from ..captions import youtube_title

UPLOAD = lambda: env_base("YT_UPLOAD", "https://www.googleapis.com/upload/youtube/v3")


def post(ctx, item, path, caption):
    store, route, conn = ctx["store"], ctx["route"], ctx["conn"]
    auth = GoogleAuth(store.secret(conn["id"]))
    yt = route.get("youtube") or {}
    meta = item.get("meta") or {}
    desc = caption if route.get("caption", {}).get("mode") != "original" else (meta.get("description") or caption)
    body = {"snippet": {"title": youtube_title(caption if yt.get("title_from", "caption") == "caption" else meta.get("title", caption), yt.get("shorts", True)),
                        "description": desc[:4900], "tags": (meta.get("tags") or [])[:15], "categoryId": str(yt.get("category", "22"))},
            "status": {"privacyStatus": yt.get("privacy", "public"), "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(path)
    h = auth.headers()
    ctx["journal"]({"stage": "uploading", "src": item["key"]})
    try:
        r = http("POST", f"{UPLOAD()}/videos", params={"uploadType": "resumable", "part": "snippet,status"}, retries=2,
                 headers=dict(h, **{"X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size), "Content-Type": "application/json; charset=UTF-8"}),
                 data=json.dumps(body))
    except HttpFail as e:
        raise ItemProblem(f"Could not reach YouTube: {e}", "Usually temporary.")
    if r.status_code >= 400:
        raise youtube_error(r.status_code, _j(r))
    session = r.headers.get("Location")
    if not session:
        raise ItemProblem("YouTube did not start the upload.", "Retry later.")
    resp = None
    for attempt in range(4):
        try:
            with open(path, "rb") as f:
                resp = http("PUT", session, retries=1, timeout=(30, 900), data=f, headers={"Content-Length": str(size), "Content-Type": "video/mp4"})
            if resp.status_code in (200, 201):
                break
            if resp.status_code >= 400 and resp.status_code != 503:
                raise youtube_error(resp.status_code, _j(resp))
        except HttpFail:
            pass
        # ask YouTube how much arrived; 200/201 means it actually finished
        q = http("PUT", session, retries=1, headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
        if q.status_code in (200, 201):
            resp = q; break
    if resp is None or resp.status_code not in (200, 201):
        raise ItemProblem("The upload to YouTube did not finish.", "Reelio retries; nothing was published twice.")
    vid = _j(resp).get("id", "")
    return {"media_id": vid, "container_id": "", "permalink": f"https://youtube.com/shorts/{vid}" if vid else ""}


def _j(r):
    try:
        return r.json()
    except Exception:
        return {}


def whoami(store, conn_id):
    auth = GoogleAuth(store.secret(conn_id))
    r = http("GET", f"{env_base('YT_API', 'https://www.googleapis.com/youtube/v3')}/channels", headers=auth.headers(), params={"part": "snippet", "mine": "true"})
    items = _j(r).get("items") or []
    if not items:
        raise AccountProblem("This Google account has no YouTube channel.", "Create a channel at youtube.com, then reconnect.", kind="permission")
    return items[0]["snippet"]["title"]


def find_recent(store, conn_id, title, since):
    """After a crash mid-upload: did the video land anyway? Looks at the channel's newest uploads."""
    try:
        auth = GoogleAuth(store.secret(conn_id))
        base = env_base('YT_API', 'https://www.googleapis.com/youtube/v3')
        r = http("GET", f"{base}/channels", headers=auth.headers(), params={"part": "contentDetails", "mine": "true"})
        pl = _j(r)["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        r = http("GET", f"{base}/playlistItems", headers=auth.headers(), params={"part": "snippet", "playlistId": pl, "maxResults": 10})
        from ..util import parse_iso
        for i in _j(r).get("items", []):
            sn = i["snippet"]
            if sn.get("title", "") == title and (not since or (parse_iso(sn.get("publishedAt")) or since) >= since):
                return sn["resourceId"]["videoId"]
    except Exception:
        pass
    return None
