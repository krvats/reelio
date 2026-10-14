import re
from ..google import GoogleAuth
from ..errors import SourceProblem, ItemProblem
from ..util import http, env_base, HttpFail
from . import download_url

BASE = lambda: env_base("DRIVE_BASE", "https://www.googleapis.com")


def _fid(s):
    m = re.search(r"/folders/([\w-]+)", s) or re.search(r"[?&]id=([\w-]+)", s)
    return m.group(1) if m else s.strip()


def _get(auth, url, params, **kw):
    h = auth.headers()
    p = dict(params)
    if not h and auth.api_key:
        p["key"] = auth.api_key
    r = http("GET", url, headers=h, params=p, **kw)
    if r.status_code in (401, 403, 404) and h and auth.api_key:        # login can't see it -> try the public link route
        r = http("GET", url, params=dict(params, key=auth.api_key), **kw)
    return r


def list_items(src, store, route):
    auth = GoogleAuth(store.secret(src.get("conn", "google")))
    stack = [_fid(f) for f in (src.get("folders") or []) if str(f).strip()]
    if not stack:
        raise SourceProblem("No Drive folder is set for this flow.", "Open the flow and paste a Drive folder link.", kind="setup")
    out, seen = [], set()
    while stack:
        fid = stack.pop()
        if fid in seen:
            continue
        seen.add(fid); tok = None
        while True:
            try:
                r = _get(auth, f"{BASE()}/drive/v3/files", {
                    "q": f"'{fid}' in parents and trashed=false", "pageSize": 1000, "pageToken": tok,
                    "fields": "nextPageToken,files(id,name,mimeType,createdTime,size,md5Checksum,videoMediaMetadata(durationMillis))",
                    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
            except HttpFail as e:
                raise SourceProblem(f"Could not reach Google Drive: {e}", "Usually temporary.", cooldown_min=10, kind="network")
            if r.status_code >= 400:
                raise SourceProblem(f"Google Drive refused to list the folder (HTTP {r.status_code}).",
                                    "Share the folder with the connected Google account, or set it to 'Anyone with the link: Viewer'.", cooldown_min=30, kind="access")
            j = r.json()
            for f in j.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    stack.append(f["id"])
                elif f["mimeType"].startswith("video/"):
                    out.append(f)
            tok = j.get("nextPageToken")
            if not tok:
                break
    out.sort(key=lambda f: f["createdTime"])
    items = []
    for f in out:
        size = int(f.get("size") or 0)
        it = {"key": f"drive:{f['id']}", "name": f["name"], "md5": f.get("md5Checksum"), "size": size, "created": f["createdTime"],
              "thumb": f"https://drive.google.com/thumbnail?id={f['id']}&sz=w240", "meta": {}}
        if size < 1024:
            it["empty"] = True
        items.append(it)
    return items


def fetch(item, dest, store, route):
    src = route["source"]
    auth = GoogleAuth(store.secret(src.get("conn", "google")))
    fid = item["key"].split(":", 1)[1]
    h = auth.headers(); p = {"alt": "media", "supportsAllDrives": "true"}
    if not h and auth.api_key:
        p["key"] = auth.api_key
    try:
        download_url(f"{BASE()}/drive/v3/files/{fid}", dest, headers=h, params=p)
    except ItemProblem:
        if h and auth.api_key:
            download_url(f"{BASE()}/drive/v3/files/{fid}", dest, params=dict(p, key=auth.api_key))
        else:
            raise
