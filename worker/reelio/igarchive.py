"""Save the reels of an Instagram ACCOUNT (not just single links) into Google Drive, for accounts you have permission to use.

Why this file exists: Save to Drive already saved single Instagram links and your OWN connected account (official API).
This adds "paste instagram.com/name" for other accounts you are allowed to archive. Instagram does not give anyone an
official list for that, so it tries several ways in turn and uses the first that works. Nothing here ever posts anything.

LISTING ladder (what reels does the account have?)       DOWNLOAD ladder (one reel, after yt-dlp has been tried)
  1 gallery-dl  (needs the Instagram cookie)               1 Instaloader (needs the Instagram cookie)
  2 Instaloader (needs the Instagram cookie)               2 direct link found while listing (mirror / paid API)
  3 headless browser (cookie optional)                     3 look the reel up again on mirrors / paid API
  4 public mirror sites (no login at all)
  5 paid API: Apify or RapidAPI (optional keys)

Cookie: the same `instagram-net` secret Reelio already uses for single links (Accounts > Instagram downloads). Use a SPARE
Instagram account for it. Optional paid-API keys: GitHub secrets APIFY_TOKEN / RAPIDAPI_KEY, or fields `apify_token` /
`rapidapi_key` in the `instagram-net` secret.

Heavy tools (gallery-dl, Instaloader, BeautifulSoup, Playwright) are installed the first time they are needed, so the
hourly Save to Drive run stays fast when nobody uses this.
"""
import os, re, sys, json, random, shutil, subprocess, importlib
from . import util as _u
from .util import say, scrub, register_secret
from .ig_common import pick, to_int, to_iso
from .errors import ItemProblem

_USER = re.compile(r"instagram\.com/([A-Za-z0-9_.]{1,30})/?", re.I)
_CODES = re.compile(r'"(?:post_shortcode|shortcode)":\s*"([A-Za-z0-9_-]{5,24})"')
BLOCK = re.compile(r"(\b429\b|too many (?:requests|queries)|rate[- ]?limit|wait a few minutes|login[_ ]required|requires? (?:a )?login|"
                   r"checkpoint|challenge[_ ]required|\b401\b|unauthorized|redirected to login|please log ?in|not logged in|accounts/login|"
                   r"cookies? (?:are |is )?(?:invalid|expired)|use --cookies)", re.I)
DEFAULT_LIST_LIMIT = 500
_lookup = {}                  # user -> {shortcode: direct video url} found by mirrors / API during this run
_browser_ready = []


class Skip(Exception):
    """This way cannot be tried now (no cookie, no key, tool missing)."""


class Blocked(Exception):
    """Instagram (or the site) said no: rate limit, login wall, bot check."""


class Fail(Exception):
    """This way ran but found nothing / broke."""


# ------------------------------------------------------------------ small helpers
def user_of(url):
    m = _USER.search((url or "").split("?")[0])
    return m.group(1) if m else None


def polite_pause():
    """Random pause between Instagram requests (REELIO_IG_DELAY='min,max' seconds; tests set 0,0)."""
    try:
        lo, hi = (float(x) for x in os.environ.get("REELIO_IG_DELAY", "2,8").split(","))
    except ValueError:
        lo, hi = 2.0, 8.0
    _u.sleep(random.uniform(lo, hi))


def _net(store):
    sec = store.secret("instagram-net") or {}
    for k in ("cookies", "apify_token", "rapidapi_key"):
        register_secret(sec.get(k))
    return sec


def cookie_dict(text):
    """Netscape cookies.txt text -> {name: value} for instagram.com."""
    out = {}
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        line = line[len("#HttpOnly_"):] if line.startswith("#HttpOnly_") else line
        parts = line.split("\t")
        if len(parts) >= 7 and not line.startswith("#") and "instagram" in parts[0]:
            out[parts[5]] = parts[6].strip()
    return out


def _cookie_file(store, tmp):
    text = _net(store).get("cookies") or ""
    if not cookie_dict(text):
        return None, {}
    p = os.path.join(tmp, "ig_cookies.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text if text.startswith("#") else "# Netscape HTTP Cookie File\n" + text)
    os.chmod(p, 0o600)
    return p, cookie_dict(text)


def _ensure(module, pip_name=None):
    """Import a module, installing it first if this is the first time it is needed."""
    try:
        return importlib.import_module(module)
    except ImportError:
        if os.environ.get("REELIO_IG_NO_INSTALL"):
            raise Skip(f"{pip_name or module} is not installed")
    say(f"installing {pip_name or module} (first use) ...")
    p = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", pip_name or module],
                       capture_output=True, text=True, timeout=400)
    importlib.invalidate_caches()
    try:
        return importlib.import_module(module)
    except ImportError:
        raise Skip(f"could not install {pip_name or module}: {scrub(p.stderr[-160:])}")


def _ensure_browser():
    if os.environ.get("REELIO_IG_NO_BROWSER"):
        raise Skip("headless browser switched off")
    _ensure("playwright")
    if _browser_ready or os.environ.get("REELIO_IG_NO_INSTALL"):
        return
    p = subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        raise Skip("could not install the headless browser: " + scrub(p.stderr[-160:]))
    _browser_ready.append(1)


def _tool(env_name, module, pip_name):
    cmd = os.environ.get(env_name)
    if cmd:
        return cmd.split()
    _ensure(module, pip_name)
    return [sys.executable, "-m", module]


def _row(user, sc, media_url=None, views=None, likes=None, posted_at=None):
    r = {"id": sc, "title": "", "url": f"https://www.instagram.com/reel/{sc}/", "playlist_title": f"Instagram - {user}", "user": user}
    if media_url:
        r["media_url"] = media_url
    for k, v in (("views", views), ("likes", likes), ("posted_at", posted_at)):
        if v is not None:
            r[k] = v
    return r


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


# ------------------------------------------------------------------ LISTING tiers (each returns rows, or raises Skip / Blocked / Fail)
def _list_gallerydl(store, user, limit, tmp):
    cf, _ = _cookie_file(store, tmp)
    if not cf:
        raise Skip("no Instagram cookie saved")
    cmd = _tool("REELIO_GALLERYDL", "gallery_dl", "gallery-dl")
    cfg = os.path.join(tmp, "gdl.json")
    json.dump({"extractor": {"instagram": {"cookies": cf, "sleep-request": [2.0, 6.0]}}}, open(cfg, "w"))
    os.chmod(cfg, 0o600)
    cmd += ["--config", cfg, "-j"] + (["--range", f"1-{limit}"] if limit else []) + [f"https://www.instagram.com/{user}/reels/"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=700)
    stats = {}
    try:                                   # gallery-dl prints one JSON list; read the numbers when they are there
        for entry in json.loads(p.stdout or "[]"):
            m = entry[-1] if isinstance(entry, list) and entry and isinstance(entry[-1], dict) else None
            sc = pick(m, "post_shortcode", "shortcode")
            if sc and sc not in stats:
                stats[sc] = (to_int(pick(m, "video_view_count", "view_count", "play_count", "video_play_count", "views")), to_int(pick(m, "likes", "like_count")),
                             to_iso(pick(m, "post_date", "date")))
    except (ValueError, TypeError):
        pass
    codes = _uniq(list(stats) + _CODES.findall(p.stdout or ""))
    if codes:
        return [_row(user, c, None, *stats.get(c, (None, None, None))) for c in codes]
    raise (Blocked if BLOCK.search((p.stderr or "") + (p.stdout or "")) else Fail)((p.stderr or "no reels found")[-160:])


def _insta_ctx(store, tmp):
    il = _ensure("instaloader")
    _, ck = _cookie_file(store, tmp)
    if not ck.get("sessionid"):
        raise Skip("no Instagram cookie saved")
    L = il.Instaloader(quiet=True, download_pictures=False, download_videos=False, download_video_thumbnails=False, download_comments=False,
                       save_metadata=False, compress_json=False, post_metadata_txt_pattern="", max_connection_attempts=2, request_timeout=60)
    L.context.load_session("session", ck)
    return il, L


def _list_instaloader(store, user, limit, tmp):
    il, L = _insta_ctx(store, tmp)
    try:
        prof = il.Profile.from_username(L.context, user)
        posts = prof.get_reels() if hasattr(prof, "get_reels") else (p for p in prof.get_posts() if p.is_video)
        rows = []
        for post in posts:
            rows.append(_row(user, post.shortcode, getattr(post, "video_url", None), to_int(getattr(post, "video_view_count", None)),
                             to_int(getattr(post, "likes", None)), to_iso(getattr(post, "date_utc", None) and post.date_utc.isoformat())))
            if len(rows) >= (limit or DEFAULT_LIST_LIMIT):
                break
            polite_pause()
    except Exception as e:      # Instaloader raises many exception types; classify by text
        raise (Blocked if BLOCK.search(str(e)) else Fail)(scrub(e)[:160])
    if not rows:
        raise Fail("no reels found")
    return rows


def _list_browser(store, user, limit, tmp):
    _ensure_browser()
    from playwright.sync_api import sync_playwright
    _, ck = _cookie_file(store, tmp)
    codes, want = [], limit or DEFAULT_LIST_LIMIT
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = br.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
            if ck:
                ctx.add_cookies([{"name": k, "value": v, "domain": ".instagram.com", "path": "/", "secure": True} for k, v in ck.items()])
            page = ctx.new_page(); page.set_default_timeout(30000)
            page.goto(f"https://www.instagram.com/{user}/reels/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            if "/accounts/login" in page.url or page.query_selector('input[name="username"]'):
                raise Blocked("login wall")
            stale = 0
            while len(codes) < want and stale < 4:
                hrefs = page.eval_on_selector_all('a[href*="/reel/"], a[href*="/reels/"]', "e => e.map(a => a.getAttribute('href'))")
                before = len(codes)
                for h in hrefs:
                    m = re.search(r"/reels?/([A-Za-z0-9_-]{5,24})", h or "")
                    if m:
                        codes.append(m.group(1))
                codes = _uniq(codes)
                stale = stale + 1 if len(codes) == before else 0
                page.mouse.wheel(0, random.randint(1400, 2600)); page.wait_for_timeout(random.randint(1200, 3200))
        except Blocked:
            raise
        except Exception as e:
            raise (Blocked if BLOCK.search(str(e)) else Fail)(scrub(e)[:160])
        finally:
            br.close()
    if not codes:
        raise Fail("no reels found")
    return [_row(user, c) for c in codes[:want]]


def _list_mirror(store, user, limit, tmp):
    _ensure("bs4", "beautifulsoup4"); _ensure("lxml"); _ensure_browser()
    from . import ig_mirror
    res = ig_mirror.collect_reels(user, max_reels=limit or 30, time_budget_s=420)
    if res.reels:
        for r in res.reels:
            _lookup.setdefault(user, {})[r.shortcode] = r.video_url
        return [_row(user, r.shortcode, r.video_url, r.views, r.likes, r.posted_at) for r in res.reels]
    raise (Blocked if res.blocked else Fail)("; ".join(res.errors)[:160] or "no reels found")


def _api_keys(store):
    sec = _net(store)
    return (os.environ.get("RAPIDAPI_KEY") or sec.get("rapidapi_key") or "").strip(), (os.environ.get("APIFY_TOKEN") or sec.get("apify_token") or "").strip()


def _list_api(store, user, limit, tmp):
    rk, at = _api_keys(store)
    for v in (rk, at):
        register_secret(v)
    if not (rk or at):
        raise Skip("no paid-API key saved")
    from . import ig_api
    try:
        reels = ig_api.fetch_reels(user, max_reels=limit or 30, rapidapi_key=rk or None, apify_token=at or None, budget_s=420)
    except ig_api.ApiQuotaError as e:
        raise Blocked(scrub(e)[:160])
    except ig_api.ApiError as e:
        raise Fail(scrub(e)[:160])
    for r in reels:
        _lookup.setdefault(user, {})[r.shortcode] = r.video_url
    return [_row(user, r.shortcode, r.video_url, r.views, r.likes, r.posted_at) for r in reels]


LIST_TIERS = [("gallery-dl", _list_gallerydl), ("Instaloader", _list_instaloader), ("browser", _list_browser),
              ("mirror sites", _list_mirror), ("paid API", _list_api)]


def list_profile_reels(store, url_or_user, limit=0, tmp=None):
    """Rows for grab: [{id, title, url, playlist_title, user, media_url?}]. Tries every way in turn."""
    import tempfile
    user = user_of(url_or_user) or url_or_user
    own = tmp is None
    tmp = tmp or tempfile.mkdtemp(prefix="igarch_")
    tried = []
    try:
        for name, fn in LIST_TIERS:
            try:
                rows = fn(store, user, limit, tmp)
            except Skip as e:
                tried.append(f"{name}: skipped ({e})"); continue
            except Blocked as e:
                tried.append(f"{name}: blocked"); store.event("info", f"Instagram account @{user}: {name} was blocked, trying the next way.")
                polite_pause(); continue
            except Fail as e:
                tried.append(f"{name}: nothing found"); continue
            except subprocess.TimeoutExpired:
                tried.append(f"{name}: too slow"); continue
            except Exception as e:                                   # one broken way must never stop the others
                tried.append(f"{name}: error"); say("igarchive:", name, scrub(e)); continue
            store.event("info", f"Instagram account @{user}: found {len(rows)} reel(s) using {name}.")
            return rows[:limit] if limit else rows
    finally:
        if own:
            shutil.rmtree(tmp, ignore_errors=True)
    raise ItemProblem(f"Could not list the reels of @{user}. Instagram blocked every way we tried ({'; '.join(tried)[:240]}).",
                      "Add a login cookie from a SPARE Instagram account in Accounts > Instagram downloads, or add an Apify key (GitHub secret APIFY_TOKEN). "
                      "You can also paste single reel links instead. Reelio tries again by itself.")


# ------------------------------------------------------------------ DOWNLOAD fallbacks (after yt-dlp failed)
def _write_info(tmp, item, title=None):
    json.dump({"id": item.get("vid"), "title": title or item.get("title") or item.get("vid")}, open(os.path.join(tmp, "v.info.json"), "w"))


def _try_url(url, tmp, item, referer=None):
    from .ig_common import download_mp4, DownloadError
    dest = os.path.join(tmp, "v.mp4")
    try:
        download_mp4(url, __import__("pathlib").Path(dest), referer=referer)
    except DownloadError as e:
        say("igarchive: direct download failed:", scrub(e))
        return None
    _write_info(tmp, item)
    return dest


def _find_direct(store, user, sc):
    """A fresh direct video link for one reel, from mirrors or the paid API (each asked at most once per run and account)."""
    if user and sc not in _lookup.get(user, {}) and user not in _lookup.get("__asked__", {}):
        _lookup.setdefault("__asked__", {})[user] = True
        for name, fn in (("mirror sites", _list_mirror), ("paid API", _list_api)):
            try:
                fn(store, user, 30, "")
            except Exception as e:
                say("igarchive:", name, "lookup:", scrub(e)[:100])
            if sc in _lookup.get(user, {}):
                break
    return (_lookup.get(user) or {}).get(sc)


def fallback_download(store, item, user, tmp):
    """Fetch one reel when yt-dlp could not. Returns the file path, or None if every way failed."""
    sc = item.get("vid")
    try:                                                      # 1) Instaloader: asks Instagram for the reel's own video link
        il, L = _insta_ctx(store, tmp)
        post = il.Post.from_shortcode(L.context, sc)
        if post.video_url:
            p = _try_url(post.video_url, tmp, item)
            if p:
                return p
    except Skip:
        pass
    except Exception as e:
        say("igarchive: Instaloader could not fetch", sc, scrub(e)[:120])
    if item.get("media_url"):                                 # 2) link saved while listing
        p = _try_url(item["media_url"], tmp, item, "https://www.instagram.com/")
        if p:
            return p
    url = _find_direct(store, user or item.get("user"), sc)   # 3) ask mirrors / paid API again (links expire)
    if url:
        return _try_url(url, tmp, item, "https://www.instagram.com/")
    return None
