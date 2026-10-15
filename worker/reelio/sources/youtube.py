"""YouTube channel as a source. Listing: YouTube API when Google is connected, otherwise yt-dlp's public listing.
Downloading ALWAYS goes through yt-dlp (the API only gives details, never the file) and into a temporary folder
on the server that is deleted after each video. YouTube sometimes blocks cloud servers; cookies/proxy fix it."""
import os, re, json, subprocess, tempfile, shutil
from ..google import GoogleAuth
from ..errors import SourceProblem, ItemProblem
from ..util import http, env_base, scrub, HttpFail

API = lambda: env_base("YT_API", "https://www.googleapis.com/youtube/v3")


def _iso_dur(s):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    return (int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)) if m else 0


def _ytdlp():
    cmd = os.environ.get("REELIO_YTDLP")
    return cmd.split() if cmd else (["yt-dlp"] if shutil.which("yt-dlp") else ["python3", "-m", "yt_dlp"])


def _channel_url(src):
    h = (src.get("handle") or src.get("channel") or "").strip()
    if h.startswith("http"):
        return h.rstrip("/")
    if h.startswith("UC") and len(h) > 20:
        return f"https://www.youtube.com/channel/{h}"
    return f"https://www.youtube.com/{h if h.startswith('@') else '@' + h}"


def _vid_id(x):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([A-Za-z0-9_-]{11})", x or "") or re.fullmatch(r"([A-Za-z0-9_-]{11})", (x or "").strip())
    return m.group(1) if m else None


def list_items(src, store, route):
    """include: shorts | long | all | selected. With clip.enabled, videos longer than max_seconds are cut into parts
    (each part is its own queue item, so each is posted once and never twice)."""
    include = src.get("include", "shorts")
    maxs = int(src.get("max_seconds", 180))
    gsec = store.secret(src.get("conn", "google")) if src.get("conn") else {}
    items = []
    if include == "selected":
        items = _list_selected(src, store, gsec, route)
    else:
        if gsec.get("refresh_token"):
            try:
                items = _list_api(src, gsec, include, maxs)
            except SourceProblem:
                raise
            except Exception as e:
                store.event("warn", f"YouTube API listing failed, trying the public list instead ({scrub(e)})", route["id"])
        if not items:
            items = _list_ytdlp(src, store, include)
    items = [i for i in items if not i.get("live")]
    items = _expand_clips(items, src, store, route, maxs)
    items.sort(key=lambda x: x.get("created") or "")
    return items


def _expand_clips(items, src, store, route, maxs):
    clip = src.get("clip") or {}
    out, warned = [], False
    is_ig = (route.get("target") or {}).get("type") == "instagram"
    for it in items:
        d = it.get("duration") or 0
        if clip.get("enabled") and d > maxs:
            out += _split(it, clip)
        elif is_ig and d > 900:          # Instagram Reels can only be about 15 minutes long
            if not warned:
                store.event("warn", "Some long videos were left out because Instagram Reels can't be longer than about 15 minutes. Turn on 'Cut long videos into clips' in the flow.", route["id"])
                warned = True
        else:
            out.append(it)
    return out


def _split(it, clip):
    sec = max(15, int(clip.get("seconds", 60) or 60))
    d = int(it["duration"])
    start, end = int(clip.get("skip_start", 0) or 0), d - int(clip.get("skip_end", 0) or 0)
    if end - start < 10:
        return []
    cuts = list(range(start, end, sec)) or [start]
    parts = [[c, min(c + sec, end)] for c in cuts]
    if len(parts) > 1 and parts[-1][1] - parts[-1][0] < max(10, sec // 4):    # tiny leftover joins the part before it
        parts[-2][1] = parts[-1][1]; parts.pop()
    cap = int(clip.get("max_per_video", 0) or 0)
    if cap > 0:
        parts = parts[:cap]
    n = len(parts)
    res = []
    for i, (a, b) in enumerate(parts, 1):
        title = (it.get("meta") or {}).get("title", "") or it["name"]
        meta = dict(it.get("meta") or {}); meta["title"] = f"{title} (part {i})"
        vid = it["key"].split(":", 1)[1]
        res.append({"key": f"youtube:{vid}@{a}-{b}", "name": f"{vid} part {i} of {n}", "created": f"{it.get('created') or ''}~{i:05d}",
                    "duration": b - a, "thumb": it.get("thumb"), "meta": meta})
    return res


def _list_selected(src, store, gsec, route):
    ids = []
    for line in re.split(r"[\s,]+", src.get("videos_text") or "\n".join(src.get("videos") or [])):
        v = _vid_id(line)
        if v and v not in ids:
            ids.append(v)
    if not ids:
        raise SourceProblem("No videos picked yet.", "Open the flow and paste the YouTube video links you want.", cooldown_min=60, kind="source")
    out = []
    for v in ids:
        p = subprocess.run(_ytdlp() + ["--dump-json", "--no-playlist", "--skip-download", "--no-warnings", f"https://www.youtube.com/watch?v={v}"] + _net_args(store, src) + _cookie_args(store, src),
                           capture_output=True, text=True, timeout=300)
        try:
            d = json.loads(p.stdout.splitlines()[0])
        except Exception:
            store.event("warn", f"Could not read video {v}: {_block_fix(p.stderr)}", route["id"]); continue
        up = d.get("upload_date") or ""
        out.append({"key": f"youtube:{v}", "name": v, "created": f"{up[:4]}-{up[4:6]}-{up[6:8]}T00:00:00Z" if len(up) == 8 else None,
                    "duration": d.get("duration"), "thumb": f"https://i.ytimg.com/vi/{v}/mqdefault.jpg",
                    "live": d.get("live_status") in ("is_live", "is_upcoming"), "meta": {"title": d.get("title") or ""}})
    if not out:
        raise SourceProblem("Could not read the picked videos.", _block_fix(""), cooldown_min=60, kind="blocked")
    # keep the order the user pasted them in
    for n, it in enumerate(out):
        it["created"] = f"2000-01-01T00:00:00Z~{n:05d}" if not it.get("created") else it["created"]
    return out


def _list_api(src, gsec, include, maxs):
    auth = GoogleAuth(gsec)
    h = auth.headers()
    if src.get("own", True) and not src.get("handle"):
        r = http("GET", f"{API()}/channels", headers=h, params={"part": "contentDetails", "mine": "true"})
    else:
        hd = src.get("handle", "")
        r = http("GET", f"{API()}/channels", headers=h, params={"part": "contentDetails", "forHandle": hd if hd.startswith("@") else "@" + hd})
    j = r.json()
    if r.status_code >= 400 or not j.get("items"):
        raise ItemProblem("Could not find that YouTube channel.", "Check the @handle in the flow.")
    pl = j["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = http("GET", f"{API()}/playlistItems", headers=h, params={"part": "contentDetails", "playlistId": pl, "maxResults": 50, "pageToken": tok})
        j = r.json()
        ids += [(i["contentDetails"]["videoId"], i["contentDetails"].get("videoPublishedAt")) for i in j.get("items", [])]
        tok = j.get("nextPageToken")
        if not tok:
            break
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = http("GET", f"{API()}/videos", headers=h, params={"part": "contentDetails,snippet,status", "id": ",".join(c[0] for c in chunk)})
        for v in r.json().get("items", []):
            d = _iso_dur(v["contentDetails"].get("duration"))
            if include == "shorts" and not (0 < d <= maxs):
                continue
            if include == "long" and d <= maxs:
                continue
            if v.get("snippet", {}).get("liveBroadcastContent") in ("live", "upcoming") or d == 0:
                continue
            if (v.get("status") or {}).get("privacyStatus") not in (None, "public"):
                continue
            sn = v["snippet"]
            out.append({"key": f"youtube:{v['id']}", "name": v["id"], "created": sn.get("publishedAt"), "duration": d,
                        "thumb": f"https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg",
                        "meta": {"title": sn.get("title", ""), "description": sn.get("description", ""), "tags": sn.get("tags", [])}})
    return out


def _list_ytdlp(src, store, include):
    base = _channel_url(src)
    tabs = src.get("tabs") or {"shorts": ["/shorts"], "long": ["/videos", "/streams"], "all": ["/shorts", "/videos", "/streams"]}.get(include, ["/shorts"])
    out, seen, err = [], set(), ""
    for tab in tabs:
        cmd = _ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", base + tab] + _net_args(store, src) + _cookie_args(store, src)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        err += p.stderr or ""
        for line in p.stdout.splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            vid = d.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            dur = d.get("duration")
            if include == "long" and dur and dur <= int(src.get("max_seconds", 180)):
                continue
            out.append({"key": f"youtube:{vid}", "name": vid, "created": None, "duration": int(dur) if dur else None,
                        "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", "live": d.get("live_status") in ("is_live", "is_upcoming"),
                        "meta": {"title": d.get("title") or ""}})
    if not out:
        raise SourceProblem("Could not read the YouTube channel's video list.", _block_fix(err), cooldown_min=60, kind="blocked")
    # yt-dlp lists newest first; give older ones a lower 'created' so 'oldest first' works
    n = len(out)
    for i, it in enumerate(out):
        it["created"] = f"2000-01-01T00:{(n - i) // 60 % 60:02d}:{(n - i) % 60:02d}Z"
        it["rank"] = n - i
    return out


def _net_args(store, src):
    args = []
    sec = store.secret(src.get("net_conn", "youtube-net"))
    if sec.get("proxy"):
        args += ["--proxy", sec["proxy"]]
    return args


def _cookie_args(store, src):
    sec = store.secret(src.get("net_conn", "youtube-net"))
    if not sec.get("cookies"):
        return []
    path = os.path.join(tempfile.gettempdir(), "reelio_cookies_list.txt")
    with open(path, "w") as f:
        f.write(sec["cookies"])
    os.chmod(path, 0o600)
    return ["--cookies", path]


def _block_fix(stderr):
    if "confirm you" in (stderr or "").lower() or "sign in" in (stderr or "").lower() or "bot" in (stderr or "").lower():
        return "YouTube is blocking this cloud server. Open Accounts > YouTube downloads and paste your browser cookies (guide inside), or put the original files in Google Drive instead."
    return "Usually temporary. If it keeps happening open Help > Why is it failing?"


# YouTube keeps changing how it serves video. "The page needs to be reloaded" and similar errors usually mean the
# default player client is being refused. We try several clients in turn and let yt-dlp use Node to solve YouTube's
# JavaScript challenge. Each attempt only runs if the previous one failed with one of these "try another way" errors.
_RETRY_WORDS = ("page needs to be reloaded", "requested format is not available", "only images are available",
                "nsig", "po token", "challenge", "signature", "http error 403", "unable to extract")
_CLIENT_TRIES = [None, "youtube:player_client=tv,web_safari", "youtube:player_client=android_vr,mweb", "youtube:player_client=ios"]


def _js_args():
    return ["--js-runtimes", "node", "--remote-components", "ejs:github"] if shutil.which("node") else []


def _run_download(cmd, tmpd, timeout=1800):
    last = None
    for client in _CLIENT_TRIES:
        for f in os.listdir(tmpd):
            if f.startswith("v."):
                try: os.remove(os.path.join(tmpd, f))
                except OSError: pass
        c = list(cmd)
        if client:
            c += ["--extractor-args", client]
        p = subprocess.run(c + _js_args(), capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0 and ("no such option" in (p.stderr or "").lower() or "unrecognized arguments" in (p.stderr or "").lower()):
            p = subprocess.run(c, capture_output=True, text=True, timeout=timeout)   # older yt-dlp without the JS options
        files = [f for f in os.listdir(tmpd) if f.startswith("v.") and not f.endswith((".part", ".ytdl"))]
        if p.returncode == 0 and files:
            return p, files
        last = (p, files)
        low = (p.stderr or "").lower()
        if not any(w in low for w in _RETRY_WORDS):
            break
    return last


def raise_for_failure(stderr):
    """Turn yt-dlp's error text into a plain-language problem (used by clip downloads and by long videos)."""
    err = scrub((stderr or "")[-400:])
    low = err.lower()
    if "confirm you" in low or "sign in" in low or "bot" in low or "429" in low:
        raise SourceProblem("YouTube blocked the download from this cloud server.", _block_fix(err), cooldown_min=180, kind="blocked")
    if "private" in low or "unavailable" in low or "removed" in low:
        raise ItemProblem("This video is private or removed on YouTube.", "Skip it.")
    if "no space left" in low:
        raise ItemProblem("The cloud runner ran out of disk space.", "Use shorter parts or a lower quality for this video.")
    raise ItemProblem("YouTube download failed: " + err[-200:], "Tap Retry later.")


def fetch(item, dest, store, route):
    src = route["source"]
    vid = item["key"].split(":", 1)[1]
    section = None
    if "@" in vid:                      # a clip of a long video: download ONLY that time range, never the whole video
        vid, rng = vid.split("@", 1)
        a, b = rng.split("-")
        section = f"*{a}-{b}"
    tmpd = tempfile.mkdtemp(prefix="yt_")
    cookie_file = None
    try:
        sec = store.secret(src.get("net_conn", "youtube-net"))
        cmd = _ytdlp() + ["-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "--no-playlist", "--no-warnings",
                          "-o", os.path.join(tmpd, "v.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
        if section:
            cmd += ["--download-sections", section, "--force-keyframes-at-cuts"]
        if sec.get("cookies"):
            cookie_file = os.path.join(tmpd, "cookies.txt")
            open(cookie_file, "w").write(sec["cookies"]); cmd += ["--cookies", cookie_file]
        if sec.get("proxy"):
            cmd += ["--proxy", sec["proxy"]]
        p, files = _run_download(cmd, tmpd)
        if p.returncode != 0 or not files:
            raise_for_failure(p.stderr)
        shutil.move(os.path.join(tmpd, files[0]), dest)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
