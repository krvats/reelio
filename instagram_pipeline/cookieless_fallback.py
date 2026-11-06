#!/usr/bin/env python3
"""Tier 4a - cookie-less web-viewer scraper.

Uses headless Chromium (Playwright) to read *public Instagram mirror sites*
(Imginn, Picuki, ...) and extract direct ``.mp4`` CDN links, without any
Instagram login. Works as a library (``collect_reels``) and as a standalone CLI.

Honest caveats (also documented in SETUP_GUIDE.md):
  * Mirrors change markup, domains and anti-bot rules often. Every mirror is a
    small declarative ``Mirror`` entry, and extraction is deliberately generic
    (``<video>``/``<source>``/``og:video``/``<a download>``/regex over the HTML /
    sniffed network responses) so it survives most cosmetic changes.
  * Many mirrors sit behind Cloudflare and challenge data-center IPs. When that
    happens the module reports ``blocked=True`` instead of hanging, so the
    orchestrator can move on to the API tier.

CLI examples:
  python cookieless_fallback.py --user natgeo --max-reels 10 --json-out out.json
  python cookieless_fallback.py --user natgeo --download --out-dir /tmp/ig_staging/natgeo
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from igcommon import (
    DESKTOP_UA,
    DownloadError,
    SHORTCODE_RE,
    USERNAME_RE,
    download_mp4,
    get_logger,
    jitter_sleep,
    media_id_to_shortcode,
    unique,
)

log = get_logger("mirror")


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Mirror:
    """Declarative description of one public viewer site."""

    name: str
    base: str
    profile_urls: tuple[str, ...]          # templates containing {user}
    post_href_re: str                      # group(1) = shortcode OR numeric media id
    numeric_ids: bool = False              # True when group(1) is a numeric media id
    load_more_selectors: tuple[str, ...] = ()
    cf_titles: tuple[str, ...] = ("just a moment", "attention required", "access denied", "verify you are human")


MIRRORS: dict[str, Mirror] = {
    "imginn": Mirror(
        name="imginn",
        base="https://imginn.com",
        profile_urls=("https://imginn.com/{user}/reels/", "https://imginn.com/{user}/"),
        post_href_re=r"/p/([A-Za-z0-9_-]{5,24})/?",
        load_more_selectors=("button.load-more", "a.load-more", ".load-more"),
    ),
    "picuki": Mirror(
        name="picuki",
        base="https://www.picuki.com",
        profile_urls=("https://www.picuki.com/profile/{user}",),
        post_href_re=r"/media/(\d{8,})",
        numeric_ids=True,
        load_more_selectors=(".load-more-btn", "a.load-more", "button.load-more"),
    ),
}
DEFAULT_MIRROR_ORDER = ("imginn", "picuki")


@dataclass
class Reel:
    shortcode: str
    video_url: str
    source: str                     # mirror name or API provider
    referer: Optional[str] = None


@dataclass
class MirrorResult:
    reels: list[Reel] = field(default_factory=list)
    blocked: bool = False
    errors: list[str] = field(default_factory=list)
    mirrors_tried: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


class MirrorBlocked(RuntimeError):
    """Raised when a mirror serves a bot-challenge / captcha page."""


# --------------------------------------------------------------------------- #
# HTML parsing (BeautifulSoup) - pure functions, unit-testable offline
# --------------------------------------------------------------------------- #
_MP4_RE = re.compile(r"https?:(?:\\?/){2}(?:[^\s\"'<>\\]|\\/)+?\.mp4(?:[^\s\"'<>\\]|\\/|\\u0026)*", re.I)


def _clean_url(raw: str, base: str) -> Optional[str]:
    raw = html_lib.unescape(raw.replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "="))
    raw = raw.strip()
    if not raw or raw.startswith(("data:", "blob:", "javascript:")):
        return None
    url = urljoin(base, raw)
    return url if url.startswith("https://") else (("https://" + url[7:]) if url.startswith("http://") else None)


def extract_post_ids(html: str, pattern: str) -> list[str]:
    """Return ordered unique post identifiers found in anchor hrefs of ``html``."""
    soup = BeautifulSoup(html, "lxml")
    rx = re.compile(pattern)
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        m = rx.search(a["href"])
        if m:
            found.append(m.group(1))
    return unique(found)


def extract_video_urls(html: str, base_url: str) -> list[str]:
    """Return candidate direct video URLs from a post page, best candidates first."""
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []

    for meta in soup.find_all("meta"):
        if meta.get("property") in ("og:video", "og:video:url", "og:video:secure_url") and meta.get("content"):
            candidates.append(meta["content"])
    for tag in soup.find_all(["video", "source"]):
        for attr in ("src", "data-src"):
            if tag.get(attr):
                candidates.append(tag[attr])
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if a.has_attr("download") or ".mp4" in href.lower():
            candidates.append(href)
    candidates.extend(m.group(0) for m in _MP4_RE.finditer(html))

    cleaned = [u for u in (_clean_url(c, base_url) for c in candidates) if u]
    # keep only plausibly-video links, preserve order
    videoish = [u for u in cleaned if ".mp4" in u.lower() or "video" in u.lower() or "/v/" in u]
    return unique(videoish)


def looks_like_challenge(title: str, html: str, mirror: Mirror) -> bool:
    t = (title or "").lower()
    if any(s in t for s in mirror.cf_titles):
        return True
    head = html[:6000].lower()
    return "cf-chl" in head or "challenge-platform" in head or "g-recaptcha" in head or "cf-turnstile" in head


# --------------------------------------------------------------------------- #
# Browser session
# --------------------------------------------------------------------------- #
class _Browser:
    """Thin context manager around Playwright with network-sniffing of video responses."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self.context = None
        self.sniffed: list[str] = []

    def __enter__(self) -> "_Browser":
        from playwright.sync_api import sync_playwright  # imported lazily: optional dependency

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        self.context = self._browser.new_context(
            user_agent=DESKTOP_UA,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        # Skip heavy resources; video responses still flow so we can sniff them.
        self.context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in ("image", "font", "stylesheet") else route.continue_(),
        )
        self.context.on("response", self._on_response)
        return self

    def _on_response(self, resp) -> None:
        try:
            ctype = (resp.headers or {}).get("content-type", "").lower()
            url = resp.url
            if "video/mp4" in ctype or (".mp4" in url.lower().split("?")[0]):
                self.sniffed.append(url)
        except Exception:  # noqa: BLE001 - sniffing must never break scraping
            pass

    def new_page(self):
        page = self.context.new_page()
        page.set_default_timeout(30_000)
        return page

    def __exit__(self, *exc) -> None:
        for closer in (
            lambda: self.context and self.context.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


def _goto_with_challenge_check(page, url: str, mirror: Mirror, patience_s: float = 20.0) -> str:
    """Navigate, wait out a passive Cloudflare interstitial if it clears, else raise MirrorBlocked."""
    resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    if resp is not None and resp.status in (403, 429, 503):
        # 503/403 are typically the interstitial; give it a moment to auto-solve.
        pass
    deadline = time.monotonic() + patience_s
    while True:
        html = page.content()
        if not looks_like_challenge(page.title(), html, mirror):
            if resp is not None and resp.status in (404, 410):
                raise LookupError(f"{url} -> HTTP {resp.status}")
            return html
        if time.monotonic() >= deadline:
            raise MirrorBlocked(f"{mirror.name}: bot challenge not cleared at {url}")
        page.wait_for_timeout(2500)


# --------------------------------------------------------------------------- #
# Core collection logic
# --------------------------------------------------------------------------- #
def _shortcode_for(post_id: str, mirror: Mirror) -> Optional[str]:
    try:
        sc = media_id_to_shortcode(post_id) if mirror.numeric_ids else post_id
    except ValueError:
        return None
    return sc if SHORTCODE_RE.match(sc) else None


def _collect_from_mirror(
    mirror: Mirror,
    user: str,
    max_reels: int,
    skip: set[str],
    deadline: float,
    stop: Optional[threading.Event],
    delay: tuple[float, float],
) -> list[Reel]:
    reels: list[Reel] = []
    with _Browser() as br:
        page = br.new_page()

        # 1) Profile page(s) -> post ids
        post_ids: list[str] = []
        last_exc: Optional[Exception] = None
        for tmpl in mirror.profile_urls:
            url = tmpl.format(user=user)
            try:
                html = _goto_with_challenge_check(page, url, mirror)
            except LookupError as exc:
                last_exc = exc
                continue
            post_ids = extract_post_ids(html, mirror.post_href_re)
            # try "load more" a few times for longer histories
            for _ in range(6):
                if len(post_ids) >= max_reels * 2 or time.monotonic() > deadline or (stop and stop.is_set()):
                    break
                clicked = False
                for sel in mirror.load_more_selectors:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(int(random.uniform(1500, 3500)))
                        clicked = True
                        break
                if not clicked:
                    break
                post_ids = extract_post_ids(page.content(), mirror.post_href_re)
            if post_ids:
                break
        if not post_ids:
            if last_exc:
                raise last_exc
            raise LookupError(f"{mirror.name}: no posts found for @{user}")

        log.info("%s: found %d candidate posts for @%s", mirror.name, len(post_ids), user)

        # 2) Visit each unseen post, extract the video URL
        for pid in post_ids:
            if len(reels) >= max_reels or time.monotonic() > deadline or (stop and stop.is_set()):
                break
            sc = _shortcode_for(pid, mirror)
            if not sc or sc in skip:
                continue
            post_url = urljoin(mirror.base, f"/p/{pid}/" if not mirror.numeric_ids else f"/media/{pid}")
            br.sniffed.clear()
            try:
                post_html = _goto_with_challenge_check(page, post_url, mirror, patience_s=12.0)
            except LookupError:
                continue
            urls = extract_video_urls(post_html, post_url) or [u for u in br.sniffed if u.startswith("https://")]
            if urls:
                reels.append(Reel(shortcode=sc, video_url=urls[0], source=mirror.name, referer=mirror.base + "/"))
                log.info("%s: %s -> video link found (%d so far)", mirror.name, sc, len(reels))
            # else: image post, skip silently
            jitter_sleep(*delay, stop=stop)
    return reels


def collect_reels(
    user: str,
    *,
    max_reels: int = 30,
    mirrors: Iterable[str] = DEFAULT_MIRROR_ORDER,
    skip: Optional[set[str]] = None,
    time_budget_s: float = 600.0,
    stop: Optional[threading.Event] = None,
    delay: tuple[float, float] = (2.0, 6.0),
) -> MirrorResult:
    """Try each mirror in order; return the first mirror's reels that yields any."""
    if not USERNAME_RE.match(user):
        raise ValueError(f"invalid username: {user!r}")
    skip = skip or set()
    result = MirrorResult()
    deadline = time.monotonic() + time_budget_s
    blocked_count = 0

    for name in mirrors:
        mirror = MIRRORS.get(name)
        if mirror is None:
            result.errors.append(f"unknown mirror {name!r}")
            continue
        if time.monotonic() > deadline or (stop and stop.is_set()):
            break
        result.mirrors_tried.append(name)
        try:
            reels = _collect_from_mirror(mirror, user, max_reels, skip, deadline, stop, delay)
        except MirrorBlocked as exc:
            blocked_count += 1
            result.errors.append(str(exc))
            log.warning("%s", exc)
            continue
        except ImportError as exc:
            result.errors.append(f"playwright unavailable: {exc}")
            log.error("Playwright is not installed: %s", exc)
            break
        except Exception as exc:  # noqa: BLE001 - one broken mirror must not kill the tier
            result.errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:200]}")
            log.warning("%s failed: %s", name, exc)
            continue
        if reels:
            result.reels = reels
            return result
        result.errors.append(f"{name}: no video posts found")

    result.blocked = blocked_count > 0 and not result.reels and blocked_count == len(result.mirrors_tried)
    return result


def download_reels(
    reels: Iterable[Reel],
    out_dir: Path,
    *,
    stop: Optional[threading.Event] = None,
    delay: tuple[float, float] = (1.0, 4.0),
) -> tuple[list[Path], list[str]]:
    """Download each reel to ``out_dir/<shortcode>.mp4``. Returns (files, failures)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    files: list[Path] = []
    failures: list[str] = []
    for reel in reels:
        if stop is not None and stop.is_set():
            break
        dest = out_dir / f"{reel.shortcode}.mp4"
        try:
            files.append(download_mp4(reel.video_url, dest, session=session, referer=reel.referer, stop=stop, log=log))
            log.info("downloaded %s (%s)", dest.name, reel.source)
        except DownloadError as exc:
            failures.append(f"{reel.shortcode}: {exc}")
            log.warning("could not download %s: %s", reel.shortcode, exc)
        jitter_sleep(*delay, stop=stop)
    return files, failures


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Cookie-less Instagram Reels link harvester (public mirrors).")
    ap.add_argument("--user", required=True, help="Instagram username (no @)")
    ap.add_argument("--max-reels", type=int, default=20)
    ap.add_argument("--mirrors", default=",".join(DEFAULT_MIRROR_ORDER), help="comma-separated: " + ",".join(MIRRORS))
    ap.add_argument("--time-budget", type=float, default=600.0, help="seconds")
    ap.add_argument("--skip-archive", type=Path, help="yt-dlp style archive.txt; listed shortcodes are skipped")
    ap.add_argument("--json-out", type=Path, help="write result JSON here")
    ap.add_argument("--download", action="store_true", help="also download the .mp4 files")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/ig_staging"), help="download directory")
    args = ap.parse_args(argv)

    skip: set[str] = set()
    if args.skip_archive and args.skip_archive.exists():
        for line in args.skip_archive.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                skip.add(parts[1])

    result = collect_reels(
        args.user.lstrip("@").lower(),
        max_reels=args.max_reels,
        mirrors=[m.strip() for m in args.mirrors.split(",") if m.strip()],
        skip=skip,
        time_budget_s=args.time_budget,
    )
    if args.download and result.reels:
        files, failures = download_reels(result.reels, args.out_dir)
        log.info("downloaded %d file(s), %d failure(s)", len(files), len(failures))
        result.errors.extend(failures)
    if args.json_out:
        args.json_out.write_text(result.to_json())
    else:
        print(result.to_json())
    return 0 if result.reels else (3 if result.blocked else 1)


if __name__ == "__main__":
    sys.exit(_main())
