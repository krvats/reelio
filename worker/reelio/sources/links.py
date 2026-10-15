"""Links as a source: paste or send ANY video link (YouTube, Instagram, anything yt-dlp understands) and Reelio downloads it
from the cloud just before posting. Each link is one tiny file linkq/<flow>/<id>.json in the data repo (so the app, the browser
extension and the worker never edit the same file). Only use videos you own or have permission to reuse.

Honest limit: Instagram usually blocks downloads from cloud servers. For Instagram,
(save the file yourself and use "Upload here", or add cookies); links work best for sources that allow cloud downloads, like YouTube."""
import os, re, json, glob, hashlib, subprocess, tempfile, shutil, datetime
from ..errors import SourceProblem, ItemProblem
from ..util import scrub, now, iso, http, env_base, HttpFail

_IG = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]+)", re.I)
_YT = re.compile(r"(?:youtube\.com/(?:shorts/|watch\?(?:[^#]*&)?v=|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{6,})", re.I)


def link_id(url):
    """Same link always gives the same id, so adding it twice is harmless. The browser extension uses the identical rule."""
    url = (url or "").strip()
    m = _IG.search(url)
    if m:
        return "ig_" + m.group(1)
    m = _YT.search(url)
    if m:
        return "yt_" + m.group(1)
    u = re.sub(r"[?#].*$", "", url.lower()).rstrip("/")
    return "u_" + hashlib.sha1(u.encode()).hexdigest()[:12]


def _dir(store, route):
    return store.p("linkq", route["id"])


def _ytdlp():
    cmd = os.environ.get("REELIO_YTDLP")
    return cmd.split() if cmd else (["yt-dlp"] if shutil.which("yt-dlp") else ["python3", "-m", "yt_dlp"])


def list_items(src, store, route):
    out = []
    for f in glob.glob(os.path.join(_dir(store, route), "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        url = (d.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        lid = os.path.basename(f)[:-5]
        meta = {k: d[k] for k in ("caption", "title", "author", "source_url") if d.get(k)}
        meta["url"] = url
        item = {"key": f"link:{lid}", "name": d.get("title") or lid, "created": d.get("added_at") or iso(), "meta": meta}
        if d.get("post_first"):
            item["post_now"] = True
        out.append(item)
    out.sort(key=lambda i: i["created"])
    return out


def _block_fix(url):
    if _IG.search(url or ""):
        return "Instagram blocks cloud servers. Add a cookies.txt that includes instagram.com in Accounts > YouTube downloads (use a spare login), or save the video yourself and use Upload here."
    return "The site is blocking this cloud server. Add your browser cookies in Accounts > YouTube downloads, or put the file in Google Drive."


def _unjson(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace("\\u0026", "&").replace("\\/", "/")


def _instagram_public(url, dest):
    """Fallback for public Instagram posts when yt-dlp is refused: read the post's public embed page. Returns the caption (maybe '')."""
    m = _IG.search(url)
    if not m:
        return None
    base = env_base("IG_WEB", "https://www.instagram.com")
    try:
        r = http("GET", f"{base}/p/{m.group(1)}/embed/captioned/", retries=1, timeout=(15, 30), headers={"User-Agent": "Mozilla/5.0"})
        html = r.text if r.status_code < 400 else ""
    except HttpFail:
        return None
    v = re.search(r'"video_url\\?":\s*\\?"(.+?)\\?"', html) or re.search(r'<video[^>]+src="([^"]+)"', html)
    if not v:
        return None
    vurl = _unjson(v.group(1).replace("\\\\", "\\")).replace("&amp;", "&")
    from . import download_url
    download_url(vurl, dest)
    c = re.search(r'"edge_media_to_caption\\?":\{\\?"edges\\?":\[\{\\?"node\\?":\{\\?"text\\?":\s*\\?"(.*?)\\?"\}', html)
    return _unjson(c.group(1)) if c else ""


def fetch(item, dest, store, route):
    url = (item.get("meta") or {}).get("url")
    if not url:
        raise ItemProblem("The link is missing.", "Skip it and add it again.")
    src = route["source"]
    tmpd = tempfile.mkdtemp(prefix="lnk_")
    try:
        sec = store.secret(src.get("net_conn", "youtube-net"))
        cmd = _ytdlp() + ["-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "--no-playlist", "--no-warnings", "--write-info-json",
                          "-o", os.path.join(tmpd, "v.%(ext)s"), url]
        if sec.get("cookies"):
            cf = os.path.join(tmpd, "cookies.txt")
            open(cf, "w").write(sec["cookies"]); cmd += ["--cookies", cf]
        if sec.get("proxy"):
            cmd += ["--proxy", sec["proxy"]]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        files = [f for f in os.listdir(tmpd) if f.startswith("v.") and not f.endswith((".part", ".ytdl", ".json"))]
        if p.returncode == 0 and files:
            shutil.move(os.path.join(tmpd, files[0]), dest)
            try:                                  # the original caption, so caption mode "original" works for links too
                info = json.load(open(os.path.join(tmpd, "v.info.json"), encoding="utf-8"))
                cap = (info.get("description") or info.get("title") or "").strip()
                if cap:
                    item.setdefault("meta", {}).setdefault("caption", cap)
            except Exception:
                pass
            return
        err = scrub((p.stderr or "")[-400:]); low = err.lower()
        cap = _instagram_public(url, dest)       # second chance for public Instagram posts
        if cap is not None:
            if cap:
                item.setdefault("meta", {}).setdefault("caption", cap)
            return
        if any(w in low for w in ("login", "sign in", "confirm you", "bot", "429", "rate-limit", "rate limit", "cookies", "empty media")):
            raise SourceProblem("The site refused the download from this cloud server.", _block_fix(url), cooldown_min=180, kind="blocked")
        if any(w in low for w in ("private", "unavailable", "removed", "not found", "404", "no video")):
            raise ItemProblem("That link has no downloadable video (private, removed or not a video).", "Skip it.")
        raise ItemProblem("Download failed: " + err[-200:], "Tap Retry later.")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def cleanup(item, store, route):
    lid = item["key"].split(":", 1)[1]
    p = os.path.join(_dir(store, route), lid + ".json")
    if os.path.isfile(p):
        os.remove(p)
