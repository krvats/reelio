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


def list_items(src, store, route):
    include = src.get("include", "shorts")
    maxs = int(src.get("max_seconds", 180))
    gsec = store.secret(src.get("conn", "google")) if src.get("conn") else {}
    items = []
    if gsec.get("refresh_token"):
        try:
            items = _list_api(src, gsec, include, maxs)
        except SourceProblem:
            raise
        except Exception as e:
            store.event("warn", f"YouTube API listing failed, trying the public list instead ({scrub(e)})", route["id"])
    if not items:
        items = _list_ytdlp(src, store, include)
    items.sort(key=lambda x: x.get("created") or "")
    return items


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
            if (v.get("status") or {}).get("privacyStatus") not in (None, "public"):
                continue
            sn = v["snippet"]
            out.append({"key": f"youtube:{v['id']}", "name": v["id"], "created": sn.get("publishedAt"), "duration": d,
                        "thumb": f"https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg",
                        "meta": {"title": sn.get("title", ""), "description": sn.get("description", ""), "tags": sn.get("tags", [])}})
    return out


def _list_ytdlp(src, store, include):
    url = _channel_url(src) + ("/shorts" if include == "shorts" else "/videos")
    cmd = _ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", url] + _net_args(store, src)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    out = []
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        vid = d.get("id")
        if not vid:
            continue
        out.append({"key": f"youtube:{vid}", "name": vid, "created": None, "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                    "meta": {"title": d.get("title") or ""}})
    if not out:
        raise SourceProblem("Could not read the YouTube channel's video list.", _block_fix(p.stderr), cooldown_min=60, kind="blocked")
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


def _block_fix(stderr):
    if "confirm you" in (stderr or "").lower() or "sign in" in (stderr or "").lower() or "bot" in (stderr or "").lower():
        return "YouTube is blocking this cloud server. Open Accounts > YouTube downloads and paste your browser cookies (guide inside), or put the original files in Google Drive instead."
    return "Usually temporary. If it keeps happening open Help > Why is it failing?"


def fetch(item, dest, store, route):
    src = route["source"]
    vid = item["key"].split(":", 1)[1]
    tmpd = tempfile.mkdtemp(prefix="yt_")
    cookie_file = None
    try:
        sec = store.secret(src.get("net_conn", "youtube-net"))
        cmd = _ytdlp() + ["-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "--no-playlist", "--no-warnings",
                          "-o", os.path.join(tmpd, "v.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
        if sec.get("cookies"):
            cookie_file = os.path.join(tmpd, "cookies.txt")
            open(cookie_file, "w").write(sec["cookies"]); cmd += ["--cookies", cookie_file]
        if sec.get("proxy"):
            cmd += ["--proxy", sec["proxy"]]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        files = [f for f in os.listdir(tmpd) if f.startswith("v.") and not f.endswith((".part", ".ytdl"))]
        if p.returncode != 0 or not files:
            err = scrub((p.stderr or "")[-400:])
            low = err.lower()
            if "confirm you" in low or "sign in" in low or "bot" in low or "429" in low:
                raise SourceProblem("YouTube blocked the download from this cloud server.", _block_fix(err), cooldown_min=180, kind="blocked")
            if "private" in low or "unavailable" in low or "removed" in low:
                raise ItemProblem("This video is private or removed on YouTube.", "Skip it.")
            raise ItemProblem("YouTube download failed: " + err[-200:], "Tap Retry later.")
        shutil.move(os.path.join(tmpd, files[0]), dest)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
