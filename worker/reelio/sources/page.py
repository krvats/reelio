"""Page link as a source: give ONE link to a page (an Instagram profile, a YouTube channel, a playlist ...) and Reelio lists the
videos on it, turns each into its own video link, and the normal 'Video links' downloader does the rest. New videos that appear
on the page later are picked up by the next scan. Only for pages you own or have permission to reuse.

Instagram almost always needs a logged-in cookies.txt to list a profile from a cloud server (Accounts > YouTube downloads)."""
import os, re, json, subprocess, datetime
from ..errors import SourceProblem
from ..util import scrub, read_json, write_json
from . import links
from .links import link_id, _ytdlp


def _state_path(store, route):
    return store.p("pagestate", route["id"] + ".json")


def _fix(url, err=""):
    low = (err or "").lower()
    if "instagram.com" in (url or "") or any(w in low for w in ("login", "sign in", "cookies", "empty media", "rate-limit", "429")):
        return ("Instagram does not show a page's videos to cloud servers without a login. Open Accounts > YouTube downloads and paste a cookies.txt "
                "that includes instagram.com (use a spare login, not your main one), or paste the video links yourself with the Video links source.")
    return "The page could not be read from this cloud server. Check the link opens in a browser, or add cookies in Accounts > YouTube downloads."


def _video_url(d):
    u = d.get("url") or d.get("webpage_url") or ""
    if u.startswith("http"):
        return u
    return ""


def _wants_stats(route):
    r = route or {}
    f = r.get("filters") or {}
    return (r.get("order") in ("views_high", "views_low", "likes_high", "posted_new", "posted_old")
            or any(f.get(k) not in (None, "", 0) for k in ("min_views", "max_views", "min_likes", "date_from", "date_to", "within_days", "older_than_days")))


def _is_ig_profile(url):
    from .. import igarchive
    return "instagram.com" in url and not links._IG.search(url) and bool(igarchive.user_of(url))


def _ytdlp_rows(src, store, url, limit):
    sec = store.secret(src.get("net_conn", "youtube-net"))
    tmpd = os.path.join(store.root, ".tmp_page"); os.makedirs(tmpd, exist_ok=True)
    cmd = _ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", "--playlist-end", str(limit), url]
    try:
        if sec.get("cookies"):
            cf = os.path.join(tmpd, "cookies.txt")
            with open(cf, "w") as f:
                f.write(sec["cookies"])
            cmd += ["--cookies", cf]
        if sec.get("proxy"):
            cmd += ["--proxy", sec["proxy"]]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    finally:
        try:
            os.remove(os.path.join(tmpd, "cookies.txt")); os.rmdir(tmpd)
        except OSError:
            pass
    rows = []
    for line in p.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows, p.stderr


def list_items(src, store, route):
    from .. import igarchive
    from ..ig_common import to_int, to_iso
    url = (src.get("url") or "").strip()
    if not url.startswith("http"):
        raise SourceProblem("The page link is missing.", "Edit the flow and paste the page link.", cooldown_min=60, kind="config")
    limit = max(1, min(int(src.get("max_items") or 100), 500))
    rows, err, ig = [], "", _is_ig_profile(url)
    if ig and _wants_stats(route):                        # the other ways of listing know views and dates; yt-dlp does not
        try:
            rows = igarchive.list_profile_reels(store, url, limit)
        except Exception as e:
            err = scrub(e)
    if not rows:
        rows, err2 = _ytdlp_rows(src, store, url, limit)
        err = err or err2
    if not rows and ig:
        try:
            rows = igarchive.list_profile_reels(store, url, limit)
        except Exception as e:
            err = scrub(e)
    found = []
    for d in rows:
        vu = _video_url(d)
        if vu:
            found.append((vu, d))
    if not found:
        raise SourceProblem("Could not read the videos on that page.", _fix(url, err), cooldown_min=60, kind="blocked")
    # newest first in the listing; give older ones an earlier time so "oldest first" works when no real date is known
    n = len(found)
    base = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    out, seen_ids = [], set()
    for i, (vu, d) in enumerate(found):
        lid = link_id(vu)
        if lid in seen_ids:
            continue
        seen_ids.add(lid)
        meta = {"url": vu}
        cap = (d.get("description") or "").strip()
        if cap:
            meta["caption"] = cap
        title = (d.get("title") or "").strip()
        if title:
            meta["title"] = title
        author = d.get("user") or d.get("uploader") or d.get("channel")
        if author:
            meta["author"] = str(author)
        item = {"key": f"link:{lid}", "name": title[:60] or lid, "created": (base + datetime.timedelta(seconds=n - i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rank": n - i, "meta": meta}
        views = to_int(d.get("views", d.get("view_count")))
        likes = to_int(d.get("likes", d.get("like_count")))
        posted = to_iso(d.get("posted_at") or d.get("timestamp") or d.get("release_timestamp")) or (
            to_iso("%s-%s-%s" % (d["upload_date"][:4], d["upload_date"][4:6], d["upload_date"][6:8])) if re.fullmatch(r"\d{8}", str(d.get("upload_date") or "")) else None)
        for k, v in (("views", views), ("likes", likes), ("posted_at", posted)):
            if v is not None:
                item[k] = v
        out.append(item)
    if (src.get("backlog") or "all") == "new":      # "only videos posted from now on": remember what was already there
        sp = _state_path(store, route)
        st = read_json(sp, None)
        if st is None:
            write_json(sp, {"baseline": sorted(i["key"] for i in out)})
            return []
        base_keys = set(st.get("baseline", []))
        out = [i for i in out if i["key"] not in base_keys]
    out.sort(key=lambda i: i["created"])
    return out


def fetch(item, dest, store, route):
    return links.fetch(item, dest, store, route)
