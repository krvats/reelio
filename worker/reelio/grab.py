"""Save to Drive ("grab"): a separate cloud job that copies videos INTO your own Google Drive as mp4 files.

  YouTube video link      -> Main folder / Title.mp4
  YouTube playlist link   -> Main folder / Playlist name / Title.mp4  (one file per video)
  YouTube channel link    -> Main folder / Channel name / Title.mp4
  Instagram link          -> Main folder / Title [id].mp4              (needs Instagram cookies for most posts)
  My Instagram account    -> Main folder / Instagram - <account> / Title [id].mp4   (official API, no login tricks)

Title, description, uploader, date, thumbnail and chapters are written INSIDE the mp4 (yt-dlp --embed-metadata),
so the file carries everything and no extra files are made.

It follows the same rules as the rest of Reelio (see longjob.py):
- one request = one job file in queues/grab/, with one entry per video; a bad video never stops the others
- a video is marked done only after Drive confirms it; a killed run is recovered by looking in Drive first (no duplicates)
- when the run is nearly out of time it stops cleanly and the workflow starts the next run by itself
- YouTube blocking the server pauses only YouTube items; Instagram trouble pauses only Instagram items;
  a Google problem pauses only that Google login
Nothing here touches flows, queues of flows, the ledger or the posting engine.
"""
import os, re, json, glob, hashlib, shutil, tempfile, subprocess, datetime
from .util import iso, now, parse_iso, read_json, write_json, scrub, say, http, HttpFail
from .errors import Problem, AccountProblem, ItemProblem, SourceProblem
from .google import GoogleAuth
from .sources import youtube as ysrc
from .sources import instagram as isrc, download_url
from . import driveup

MAX_TRIES = 3
MIN_TIME_LEFT_MIN = 12
MAX_ITEMS = 2000
GRAPH = lambda: os.environ.get("IG_GRAPH", "https://graph.instagram.com").rstrip("/")
DEFAULTS = {"conn": "google", "net_conn": "youtube-net", "quality": "1080", "root_name": "Reelio Downloads", "root_id": "",
            "subfolders": True, "subs": False, "ig_conn": ""}
MEDIA_EXT = (".mp4", ".mkv", ".webm", ".mov", ".m4v")
MIME = {".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm", ".mov": "video/quicktime", ".m4v": "video/x-m4v"}


# ------------------------------------------------------------------ files
def _dir(store):
    d = store.p("queues", "grab"); os.makedirs(d, exist_ok=True); return d


def load_jobs(store):
    out = []
    for f in sorted(glob.glob(os.path.join(_dir(store), "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        j = read_json(f, None)
        if isinstance(j, dict) and isinstance(j.get("items"), list):
            out.append(j)
    return out


def job_status(job):
    if job.get("cancelled"):
        return "cancelled"
    ss = [i["status"] for i in job["items"]]
    if not ss or all(s == "done" for s in ss):
        return "done"
    if any(s in ("pending", "downloading", "uploading") for s in ss):
        return "running" if any(s != "pending" for s in ss) else "queued"
    return "failed"


def save_job(store, job):
    job["status"] = job_status(job)
    job["done_count"] = sum(1 for i in job["items"] if i["status"] == "done")
    job["updated"] = iso()
    write_json(os.path.join(_dir(store), f"{job['id']}.json"), job)


def _state(store):
    return read_json(os.path.join(_dir(store), "_state.json"), None) or {}


def _save_state(store, st):
    st["updated"] = iso()
    write_json(os.path.join(_dir(store), "_state.json"), st)


def _checkpoint(store, st, msg):
    _save_state(store, st)
    store.flush_events()
    store.sync(msg)


# ------------------------------------------------------------------ settings and names
def _default_conn(store):
    """The Drive-saver login if there is one (kind google_save), else the plain 'google' login."""
    for c in (store.config().get("connections") or []):
        if c.get("kind") == "google_save":
            return c["id"]
    return "google"


def clean_settings(raw):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (raw or {}).items() if v not in (None, "")})
    s["quality"] = str(s["quality"]) if str(s["quality"]) in ("best", "1080", "720", "480") else "1080"
    s["root_name"] = safe_name(s["root_name"], 80) or DEFAULTS["root_name"]
    s["root_id"] = re.sub(r"[^\w-]", "", str(s.get("root_id") or ""))[:80]
    s["subfolders"] = bool(s.get("subfolders", True))
    s["subs"] = bool(s.get("subs", False))
    return s


def safe_name(t, limit=180):
    t = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", " ", str(t or ""))
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:limit].rstrip(" .")


def _kind(url):
    u = (url or "").lower()
    if "instagram.com" in u:
        return "ig_link"
    if "youtube.com" in u or "youtu.be" in u:
        return "yt"
    return None


def _jid(prefix, text):
    return f"{prefix}-{hashlib.sha1(text.encode()).hexdigest()[:10]}"


def _channel_tab(url):
    """A bare channel link means 'its videos' (yt-dlp would otherwise list the tabs themselves)."""
    m = re.match(r"^(https?://(?:www\.|m\.)?youtube\.com/(?:@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+))/?(?:[?#].*)?$", url)
    return m.group(1) + "/videos" if m else url


# ------------------------------------------------------------------ running yt-dlp for Instagram (no YouTube cookie pool)
def _ig_net(store, tmp):
    """Optional Instagram login cookies / proxy from the secret `instagram-net` (Accounts > Instagram downloads)."""
    sec = store.secret("instagram-net") or {}
    args = []
    if sec.get("cookies"):
        p = os.path.join(tmp, "ig_cookies.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(sec["cookies"])
        args += ["--cookies", p]
    if sec.get("proxy"):
        args += ["--proxy", sec["proxy"]]
    return args


def _run_plain(cmd, tmp, timeout):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    files = [f for f in os.listdir(tmp) if f.startswith("v.") and not f.endswith((".part", ".ytdl"))]
    return p, files


def _ig_failure(stderr):
    err = scrub((stderr or "")[-400:]); low = err.lower()
    if "login" in low or "log in" in low or "cookies" in low or "rate-limit" in low or "rate limit" in low or "429" in low or "empty media response" in low:
        raise SourceProblem("Instagram asked for a login before it would give this video.",
                            "Use 'My Instagram account' for your own reels (no login needed), or add Instagram cookies in Accounts > Instagram downloads. Use a spare account for cookies.",
                            cooldown_min=180, kind="blocked")
    if "private" in low or "not available" in low or "unavailable" in low or "removed" in low or "404" in low:
        raise ItemProblem("This Instagram post is private or removed.", "Skip it.")
    if "no space left" in low:
        raise ItemProblem("The cloud runner ran out of disk space.", "Tap Retry later.")
    raise ItemProblem("Instagram download failed: " + err[-200:], "Tap Retry later.")


# ------------------------------------------------------------------ adding
def _entries_yt(store, url, s):
    src = {"net_conn": s["net_conn"]}
    cmd = ysrc._ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", _channel_tab(url)] + ysrc._net_args(store, src)
    p, notes = ysrc._pool_run(store, src, cmd, timeout=900)
    ysrc._say(store, None, notes)
    rows = _json_lines(p.stdout)
    if not rows:
        ysrc.raise_for_failure(p.stderr or "could not read the link", store, src)
    return rows


def _entries_ig(store, url):
    tmp = tempfile.mkdtemp(prefix="grabl_")
    try:
        cmd = ysrc._ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", url] + _ig_net(store, tmp)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        rows = _json_lines(p.stdout)
        if not rows:
            _ig_failure(p.stderr or "could not read the link")
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _json_lines(text):
    out = []
    for line in (text or "").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _new_item(n, key, vid, url, title):
    return {"n": n, "key": key, "vid": vid, "url": url, "title": title or vid, "status": "pending", "fails": 0}


def _merge(job, new_items):
    """Add only videos the job does not already have. Returns how many were added (a re-added playlist picks up new videos)."""
    have = {i["key"] for i in job["items"]}
    added = 0
    for it in new_items:
        if it["key"] in have or len(job["items"]) >= MAX_ITEMS:
            continue
        it["n"] = len(job["items"]) + 1
        job["items"].append(it); have.add(it["key"]); added += 1
    if added:
        job["cancelled"] = False
    return added


def _add(store, c):
    s = clean_settings(dict(c.get("settings") or {}, conn=(c.get("settings") or {}).get("conn") or _default_conn(store)))
    links = c.get("links") or []
    if isinstance(links, str):
        links = re.split(r"[\s,]+", links)
    links = [l.strip() for l in links if l and l.strip()]
    if not links:
        store.event("warn", "Save to Drive: no link was given, so nothing was added.")
        return 0
    made = 0
    for url in dict.fromkeys(links):
        kind = _kind(url)
        if not kind:
            store.event("warn", f"Save to Drive: '{url[:80]}' is not a YouTube or Instagram link, so it was skipped.")
            continue
        try:
            vid1 = ysrc._vid_id(url) if kind == "yt" and "/playlist" not in url else None
            if vid1:       # one video: no need to ask YouTube anything now (so it still works while YouTube blocks the server)
                rows = [{"id": vid1, "title": "", "url": f"https://www.youtube.com/watch?v={vid1}"}]
            else:
                rows = _entries_yt(store, url, s) if kind == "yt" else _entries_ig(store, url)
        except Problem as p:
            store.event("warn", f"Save to Drive could not read {url[:80]}: {p.msg}", fix=p.fix); continue
        folder = ""
        items = []
        for r in rows:
            vid = str(r.get("id") or "")
            if not vid or r.get("live_status") in ("is_live", "is_upcoming"):
                continue
            if r.get("ie_key") == "YoutubeTab" or r.get("_type") == "playlist":      # a tab or playlist inside a channel list: not a video
                continue
            folder = folder or safe_name(r.get("playlist_title") or r.get("playlist") or "", 100)
            link = r.get("webpage_url") or r.get("url") or url
            if kind == "yt" and not str(link).startswith("http"):
                link = f"https://www.youtube.com/watch?v={vid}"
            items.append(_new_item(0, f"{'yt' if kind == 'yt' else 'ig'}:{vid}", vid, link, r.get("title")))
        if not items:
            store.event("warn", f"Save to Drive: no videos were found at {url[:80]}."); continue
        is_list = len(rows) > 1 or bool(folder)
        jid = _jid(kind, url)
        path = os.path.join(_dir(store), f"{jid}.json")
        job = read_json(path, None)
        if job and isinstance(job.get("items"), list):
            n = _merge(job, items)
            job["settings"] = s
            if not n:
                store.event("info", f"'{job['title']}' is already in the list. Nothing new was found, so nothing was added."); continue
            store.event("info", f"Save to Drive: {n} new video(s) added to '{job['title']}'.")
        else:
            title = folder or items[0]["title"]
            job = {"id": jid, "kind": kind, "url": url, "title": title, "folder": folder if is_list else "", "settings": s,
                   "created": iso(), "cancelled": False, "items": []}
            _merge(job, items)
            store.event("info", f"Save to Drive: '{title}' added ({len(job['items'])} video{'s' if len(job['items']) != 1 else ''}).")
        save_job(store, job); made += 1
    return made


def _add_ig_own(store, c):
    """Every video on one of YOUR connected Instagram accounts, through the official API."""
    s = clean_settings(dict(c.get("settings") or {}, conn=(c.get("settings") or {}).get("conn") or _default_conn(store)))
    conn_id = c.get("conn") or s.get("ig_conn")
    conn = store.conn(conn_id) if conn_id else None
    if not conn or conn.get("kind") != "instagram":
        store.event("warn", "Save to Drive: pick one of your connected Instagram accounts.", fix="Open Accounts and connect Instagram first."); return 0
    rows = isrc.list_items({"conn": conn_id}, store, None)
    label = safe_name(conn.get("label") or conn_id, 60)
    items = [_new_item(0, f"igown:{r['name']}", r["name"], "", (r.get("meta") or {}).get("caption", "")) for r in rows]
    for it, r in zip(items, rows):
        it["media_url"] = (r.get("meta") or {}).get("url", ""); it["created"] = r.get("created", "")
    if not items:
        store.event("warn", f"Save to Drive: no videos were found on {label}."); return 0
    jid = f"igown-{re.sub(r'[^A-Za-z0-9_-]', '', conn_id)[:30]}"
    path = os.path.join(_dir(store), f"{jid}.json")
    job = read_json(path, None)
    if job and isinstance(job.get("items"), list):
        n = _merge(job, items); job["settings"] = s
        if not n:
            store.event("info", f"Instagram {label} is already saved. Nothing new was found."); return 0
        store.event("info", f"Save to Drive: {n} new Instagram video(s) from {label}.")
    else:
        job = {"id": jid, "kind": "ig_own", "url": "", "conn_ig": conn_id, "title": f"Instagram - {label}", "folder": f"Instagram - {label}",
               "settings": s, "created": iso(), "cancelled": False, "items": []}
        _merge(job, items)
        store.event("info", f"Save to Drive: Instagram {label} added ({len(job['items'])} videos).")
    save_job(store, job)
    return 1


def intake(store):
    d = store.p("grab-inbox")
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        c = read_json(f, None)
        try:
            if isinstance(c, dict):
                cmd = c.get("cmd")
                if cmd == "add":
                    _add(store, c)
                elif cmd == "add_ig":
                    _add_ig_own(store, c)
                elif cmd in ("cancel", "retry", "remove"):
                    _control(store, cmd, c.get("id"))
        except Problem as p:
            store.event("error", f"Save to Drive: {p.msg}", fix=p.fix)
        except Exception as e:
            store.event("error", f"Save to Drive: could not read the request ({scrub(e)}).")
        finally:
            try: os.remove(f)
            except OSError: pass


def _control(store, cmd, jid):
    jid = re.sub(r"[^A-Za-z0-9_-]", "", str(jid or ""))
    path = os.path.join(_dir(store), f"{jid}.json")
    job = read_json(path, None)
    if not job:
        return
    if cmd == "remove":
        os.remove(path); return
    if cmd == "cancel":
        job["cancelled"] = True
    if cmd == "retry":
        job["cancelled"] = False
        for it in job["items"]:
            if it["status"] == "failed":
                it.update(status="pending", fails=0, retry_after=None, last_error=None, interrupted=0)
        st = _state(store); st["source_until"] = {}; st["conn_until"] = {}; _save_state(store, st)
    save_job(store, job)


# ------------------------------------------------------------------ one video
def _fmt(q):
    if q == "best":
        return "bv*+ba/b"
    return f"bv*[height<={q}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={q}]+ba/b[height<={q}]/b"


def _pick(tmp, files):
    media = sorted((f for f in files if f.lower().endswith(MEDIA_EXT)), key=lambda f: (not f.lower().endswith(".mp4"), f))
    return os.path.join(tmp, media[0]) if media else None


def _info(tmp):
    return read_json(os.path.join(tmp, "v.info.json"), {}) or {}


def _embed_flags(s):
    f = ["--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg", "--embed-chapters", "--write-info-json"]
    if s.get("subs"):
        f += ["--write-subs", "--sub-langs", "en.*,-live_chat", "--embed-subs"]
    return f


def _dl_yt(store, job, item, tmp, deadline):
    s = job["settings"]
    src = {"net_conn": s["net_conn"]}
    cmd = ysrc._ytdlp() + ["-f", _fmt(s["quality"]), "--merge-output-format", "mp4", "--no-playlist", "--no-warnings", "-N", "4",
                           "--retries", "10", "--fragment-retries", "10"] + _embed_flags(s) + ["-o", os.path.join(tmp, "v.%(ext)s"), item["url"]]
    cmd += ysrc._net_args(store, src)
    left = max(180, int((deadline - now()).total_seconds()))
    try:
        (p, files), notes = ysrc.download_with_pool(store, src, cmd, tmp, timeout=left)
        ysrc._say(store, None, notes)
    except subprocess.TimeoutExpired:
        raise ItemProblem("The download did not finish before this run ran out of time.", "Reelio tries again in the next run.")
    path = _pick(tmp, files)
    if p.returncode != 0 or not path:
        ysrc.raise_for_failure(p.stderr, store, src)
    return path


def _dl_ig_link(store, job, item, tmp, deadline):
    cmd = ysrc._ytdlp() + ["--no-playlist", "--no-warnings", "--merge-output-format", "mp4", "--retries", "5"] + _embed_flags({}) \
        + ["-o", os.path.join(tmp, "v.%(ext)s"), item["url"]] + _ig_net(store, tmp)
    left = max(180, int((deadline - now()).total_seconds()))
    try:
        p, files = _run_plain(cmd, tmp, left)
    except subprocess.TimeoutExpired:
        raise ItemProblem("The download did not finish before this run ran out of time.", "Reelio tries again in the next run.")
    path = _pick(tmp, files)
    if p.returncode != 0 or not path:
        _ig_failure(p.stderr)
    return path


def _ig_fresh(store, conn_id, media_id, fallback):
    """Instagram's file links expire, so ask for a fresh one right before downloading."""
    try:
        tok = store.secret(conn_id).get("access_token")
        r = http("GET", f"{GRAPH()}/v21.0/{media_id}", retries=2, params={"fields": "media_url,caption,timestamp,permalink,username,media_type", "access_token": tok})
        j = r.json() if r.content else {}
        if r.status_code < 400 and j.get("media_url"):
            return j
    except Exception:
        pass
    return {"media_url": fallback}


def _dl_ig_own(store, job, item, tmp, deadline):
    meta = _ig_fresh(store, job["conn_ig"], item["vid"], item.get("media_url", ""))
    url = meta.get("media_url") or item.get("media_url")
    if not url:
        raise ItemProblem("Instagram did not give a download link for this video.", "It may have been deleted. Tap Retry or skip it.")
    raw = os.path.join(tmp, "raw.mp4")
    download_url(url, raw)
    caption = (meta.get("caption") or "").strip()
    title = safe_name(caption.splitlines()[0], 100) if caption else ""
    out = os.path.join(tmp, "v.mp4")
    day = (meta.get("timestamp") or item.get("created") or "")[:10].replace("-", "")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-c", "copy", "-movflags", "+faststart",
           "-metadata", f"title={title or 'Instagram ' + item['vid']}", "-metadata", f"comment={caption}", "-metadata", f"description={caption}",
           "-metadata", f"date={day}", "-metadata", f"artist={meta.get('username') or job['title']}", "-metadata", f"purl={meta.get('permalink') or ''}", out]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(out):
        shutil.copy(raw, out)                      # details could not be written into the file: keep the video itself
    write_json(os.path.join(tmp, "v.info.json"), {"title": title or f"Instagram {item['vid']}", "id": item["vid"]})
    return out


def _folder_for(store, auth, job, st, checked):
    s = job["settings"]
    key = f"{s['conn']}|{s['root_id'] or s['root_name']}"

    def cached(k, make):
        fid = st.setdefault("folders", {}).get(k)
        if fid and k not in checked:
            if not driveup.folder_exists(auth, fid):
                fid = None
            checked.add(k)
        if not fid:
            fid = make(); st["folders"][k] = fid; checked.add(k)
        return fid
    root = s["root_id"] or cached(key, lambda: driveup.ensure_folder(auth, s["root_name"]))
    sub = job.get("folder") if (s["subfolders"] or job["kind"] == "ig_own") else ""
    if not sub:
        return root
    return cached(f"{key}|{sub}", lambda: driveup.ensure_folder(auth, sub, root))


def _link(fid):
    return f"https://drive.google.com/file/d/{fid}/view" if fid else ""


def _do_item(store, job, item, deadline, ctx, st, checked):
    s = job["settings"]
    auth = GoogleAuth(store.secret(s["conn"]))
    auth.headers()                                  # fail fast (before a long download) if Google is not connected
    parent = _folder_for(store, auth, job, st, checked)
    have = driveup.find_by_src(auth, parent, item["key"])
    if have:
        item.update(status="done", drive_id=have, url_drive=_link(have), at=iso(), last_error=None, fails=0)
        store.event("info", f"'{item['title']}' was already in Drive, so it was not saved again.")
        return
    tmp = tempfile.mkdtemp(prefix="grab_")
    try:
        item.update(status="downloading", started_at=iso())
        save_job(store, job); _checkpoint(store, st, "reelio: save to drive downloading")
        path = {"yt": _dl_yt, "ig_link": _dl_ig_link, "ig_own": _dl_ig_own}[job["kind"]](store, job, item, tmp, deadline)
        info = _info(tmp)
        title = safe_name(info.get("title") or item["title"] or item["vid"], 170) or item["vid"]
        item["title"] = title
        if len(job["items"]) == 1 and not job.get("folder"):
            job["title"] = title
        ext = os.path.splitext(path)[1].lower() or ".mp4"
        name = title + (f" [{item['vid']}]" if job["kind"] != "yt" else "") + ext
        item["status"] = "uploading"
        save_job(store, job); _checkpoint(store, st, "reelio: save to drive uploading")
        fid = driveup.upload(auth, path, name, parent, {"srcId": item["key"], "src": item.get("url", "")}, deadline, MIME.get(ext, "video/mp4"))
        if not fid:
            fid = driveup.find_by_src(auth, parent, item["key"])
        item.update(status="done", drive_id=fid, url_drive=_link(fid), size=os.path.getsize(path), at=iso(), last_error=None, fails=0)
        store.event("info", f"Saved to Drive: {name}")
    except Problem:
        item["status"] = "pending"
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _recover(store, job, st):
    """A killed run leaves a video half done. Look in Drive first so nothing is saved twice."""
    for item in job["items"]:
        if item["status"] not in ("downloading", "uploading"):
            continue
        found = ""
        if item["status"] == "uploading":
            try:
                s = job["settings"]
                auth = GoogleAuth(store.secret(s["conn"]))
                found = driveup.find_by_src(auth, _folder_for(store, auth, job, st, set()), item["key"])
            except Exception:
                found = ""
        if found:
            item.update(status="done", drive_id=found, url_drive=_link(found), at=iso())
            store.event("info", f"'{item['title']}' had reached Drive before the last run stopped; marked as done.")
            continue
        item["interrupted"] = item.get("interrupted", 0) + 1
        if item["interrupted"] >= MAX_TRIES:
            item.update(status="failed", last_error={"msg": "This video could not finish within one run.", "fix": "Try a lower quality, then tap Retry.", "at": iso()})
        else:
            item["status"] = "pending"
    save_job(store, job)


# ------------------------------------------------------------------ the run
def _until(st, group, key):
    return parse_iso(((st.get(group) or {}).get(key)))


def run(store, budget_min=320):
    from .notify import Notifier
    deadline = now() + datetime.timedelta(minutes=budget_min)
    cfg = store.config()
    try:
        nt = Notifier(store, cfg)
    except Exception:
        nt = None
    ctx = {"notify": lambda kind, text, key=None: nt.send(kind, text, key=key, ttl_hours=6 if key else 0) if nt else False}
    st = _state(store)
    if not isinstance(st.get("source_until"), dict):
        st["source_until"] = {}
    if not isinstance(st.get("conn_until"), dict):
        st["conn_until"] = {}
    intake(store)
    jobs = load_jobs(store)
    for j in jobs:
        _recover(store, j, st)
    more, checked = False, set()
    stopped = set()                                    # platforms paused during this run
    for job in sorted(jobs, key=lambda j: j.get("created") or ""):
        if job.get("cancelled") or job_status(job) in ("done", "failed"):
            continue
        conn = job["settings"]["conn"]
        plat = "ig" if job["kind"] in ("ig_link", "ig_own") else "yt"
        for item in job["items"]:
            if item["status"] != "pending" or item.get("fails", 0) >= MAX_TRIES:
                continue
            sw = _until(st, "source_until", plat)
            if plat in stopped or (sw and sw > now() and job["kind"] != "ig_own"):
                break
            cw = _until(st, "conn_until", conn)
            if cw and cw > now():
                break
            ra = parse_iso(item.get("retry_after"))
            if ra and ra > now():
                continue
            if (deadline - now()).total_seconds() < MIN_TIME_LEFT_MIN * 60:
                more = True; break
            try:
                _do_item(store, job, item, deadline, ctx, st, checked)
            except SourceProblem as p:
                st["source_until"][plat] = iso(now() + datetime.timedelta(minutes=p.cooldown_min or 180))
                stopped.add(plat)
                store.event("warn", f"Save to Drive paused for {'Instagram' if plat == 'ig' else 'YouTube'}: {p.msg}", fix=p.fix)
                ctx["notify"]("failed", f"Save to Drive paused. {p.msg} {p.fix}", "grab-source-" + plat)
                break
            except AccountProblem as p:
                st["conn_until"][conn] = iso(now() + datetime.timedelta(minutes=p.cooldown_min or 60))
                store.event("warn", f"Save to Drive paused for this Google login: {p.msg}", fix=p.fix)
                ctx["notify"]("limit" if p.kind == "quota" else "token", f"Save to Drive paused. {p.msg} {p.fix}", "grab-" + conn)
                break
            except ItemProblem as p:
                item["fails"] = item.get("fails", 0) + 1
                item["last_error"] = {"msg": p.msg, "fix": p.fix, "at": iso()}
                if item["fails"] >= MAX_TRIES:
                    item["status"] = "failed"
                    ctx["notify"]("failed", f"Save to Drive: '{item['title']}' failed. {p.msg} {p.fix}")
                else:
                    item["retry_after"] = iso(now() + datetime.timedelta(minutes=20 * item["fails"]))
                store.event("error", f"'{item['title']}': {p.msg}", fix=p.fix)
            except Exception as e:
                item["fails"] = item.get("fails", 0) + 1
                item["last_error"] = {"msg": f"Unexpected problem: {scrub(e)}", "fix": "Reelio will retry.", "at": iso()}
                if item["fails"] >= MAX_TRIES:
                    item["status"] = "failed"
                store.event("error", f"'{item['title']}': {scrub(e)}")
            save_job(store, job); _checkpoint(store, st, "reelio: save to drive progress")
        if job_status(job) == "done" and not job.get("notified"):
            job["notified"] = True
            ctx["notify"]("info", f"Saved to Drive: {job['title']} ({len(job['items'])} video{'s' if len(job['items']) != 1 else ''}).")
        elif job_status(job) in ("queued", "running") and not more:
            # waiting only because of a retry timer or a pause: ask the hourly check to look again later
            pass
    for j in jobs:
        save_job(store, j)
    _checkpoint(store, st, "reelio: save to drive")
    say("save to drive: " + ("more work waiting, the next run continues" if more else "nothing more to do right now"))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"more={'true' if more else 'false'}\n")
    return more
