import re
from ..google import GoogleAuth
from ..errors import SourceProblem, ItemProblem
from ..util import http, env_base, HttpFail
from . import download_url

BASE = lambda: env_base("DRIVE_BASE", "https://www.googleapis.com")


def _fid(s):
    m = re.search(r"/folders/([\w-]+)", s) or re.search(r"[?&]id=([\w-]+)", s)
    return m.group(1) if m else s.strip()


VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".3gp", ".wmv")
FOLDER, SHORTCUT = "application/vnd.google-apps.folder", "application/vnd.google-apps.shortcut"
MAX_FOLDERS = 800           # safety stop for a huge Drive; far more than anyone needs


def _is_video(mime, name):
    """Real video types, plus files Drive labelled generically (phones and editors often upload .mp4 as 'octet-stream')."""
    mime = mime or ""
    return mime.startswith("video/") or (mime in ("", "application/octet-stream", "binary/octet-stream") and (name or "").lower().endswith(VIDEO_EXT))


FIELDS = "id,name,mimeType,createdTime,size,md5Checksum,videoMediaMetadata(durationMillis),shortcutDetails(targetId,targetMimeType)"


def _get(auth, url, params, **kw):
    h = auth.headers()
    p = dict(params)
    if not h and auth.api_key:
        p["key"] = auth.api_key
    r = http("GET", url, headers=h, params=p, **kw)
    if r.status_code in (401, 403, 404) and h and auth.api_key:        # login can't see it -> try the public link route
        r = http("GET", url, params=dict(params, key=auth.api_key), **kw)
    return r


def _meta(auth, fid):
    """One file's details (used for a pasted file link or a shortcut). None if it can't be read."""
    try:
        r = _get(auth, f"{BASE()}/drive/v3/files/{fid}", {"fields": FIELDS, "supportsAllDrives": "true"})
        return r.json() if r.status_code < 400 else None
    except HttpFail:
        return None


def list_items(src, store, route):
    """Every video under the pasted links. A link may be a folder (all its subfolders and shortcuts are scanned; anything that is not
    a video is ignored) or a single video file. One parent folder is enough; there is no need to paste each sub-folder."""
    auth = GoogleAuth(store.secret(src.get("conn", "google")))
    links = [str(f).strip() for f in (src.get("folders") or []) if str(f).strip()]
    if not links:
        raise SourceProblem("No Drive folder is set for this flow.", "Open the flow and paste a Drive folder link.", kind="setup")
    stack, out, seen, got = [], [], set(), set()

    def take(f):
        if f["id"] not in got and _is_video(f.get("mimeType"), f.get("name")):
            got.add(f["id"]); out.append(f)

    for ln in links:
        m = re.search(r"/file/d/([\w-]+)", ln)
        if m:                                                   # a link to one video
            f = _meta(auth, m.group(1))
            if f and f.get("mimeType") != FOLDER:
                take(f)
        else:
            stack.append(_fid(ln))
    while stack and len(seen) < MAX_FOLDERS:
        fid = stack.pop()
        if fid in seen:
            continue
        seen.add(fid); tok = None
        while True:
            try:
                r = _get(auth, f"{BASE()}/drive/v3/files", {
                    "q": f"'{fid}' in parents and trashed=false", "pageSize": 1000, "pageToken": tok,
                    "fields": f"nextPageToken,files({FIELDS})",
                    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
            except HttpFail as e:
                raise SourceProblem(f"Could not reach Google Drive: {e}", "Usually temporary.", cooldown_min=10, kind="network")
            if r.status_code >= 400:
                raise SourceProblem(f"Google Drive refused to list the folder (HTTP {r.status_code}).",
                                    "Share the folder with the connected Google account, or set it to 'Anyone with the link: Viewer'.", cooldown_min=30, kind="access")
            j = r.json()
            for f in j.get("files", []):
                mt = f.get("mimeType") or ""
                if mt == FOLDER:
                    stack.append(f["id"])
                elif mt == SHORTCUT:                            # a shortcut to a folder or a video somewhere else
                    d = f.get("shortcutDetails") or {}
                    tid, tmt = d.get("targetId"), d.get("targetMimeType") or ""
                    if tid and tmt == FOLDER:
                        stack.append(tid)
                    elif tid and tid not in got:
                        tf = _meta(auth, tid)
                        if tf:
                            take(tf)
                else:
                    take(f)
            tok = j.get("nextPageToken")
            if not tok:
                break
    out.sort(key=lambda f: f.get("createdTime") or "")
    items = []
    for f in out:
        size = int(f.get("size") or 0)
        it = {"key": f"drive:{f['id']}", "name": f["name"], "md5": f.get("md5Checksum"), "size": size, "created": f.get("createdTime"),
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
