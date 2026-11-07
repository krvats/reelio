"""Shared helpers for saving Instagram profile reels (mirror viewers, API proxy, downloads).

Kept dependency-light (only ``requests``) so every other module can import it.
Provides: GitHub-Actions-aware logging, randomized sleeping, username /
shortcode validation, and a hardened MP4 downloader.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

from .util import say

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,24}$")
_REEL_URL_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9._]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]{5,24})")
_PROFILE_URL_RE = re.compile(r"instagram\.com/([A-Za-z0-9._]{1,30})/?")

DESKTOP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_B64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

_print_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Logging: everything goes through Reelio's say() so secrets are always scrubbed
# --------------------------------------------------------------------------- #
class _Log:
    def __init__(self, name):
        self.name = name

    def _p(self, lvl, msg, *a):
        try:
            msg = msg % a if a else msg
        except Exception:
            msg = f"{msg} {a}"
        say(f"[{self.name}] {lvl}", msg)

    def info(self, msg, *a): self._p("", msg, *a)
    def warning(self, msg, *a): self._p("warning:", msg, *a)
    def error(self, msg, *a): self._p("error:", msg, *a)
    def exception(self, msg, *a): self._p("error:", msg, *a)


def get_logger(name="ig"):
    return _Log(name)


def gh_group(title): say(f"--- {title} ---")
def gh_endgroup(): pass


# --------------------------------------------------------------------------- #
# Timing
# --------------------------------------------------------------------------- #
def jitter_sleep(low: float, high: float, stop: Optional[threading.Event] = None) -> float:
    """Sleep a random duration in [low, high] seconds. Returns seconds slept.

    Wakes early (and returns) if ``stop`` is set, so shutdown is never delayed.
    """
    if high < low:
        low, high = high, low
    delay = random.uniform(low, high)
    if delay <= 0:
        return 0.0
    started = time.monotonic()
    if stop is not None:
        stop.wait(delay)
    else:
        time.sleep(delay)
    return time.monotonic() - started


# --------------------------------------------------------------------------- #
# Identifier helpers
# --------------------------------------------------------------------------- #
def normalize_username(raw: str) -> Optional[str]:
    """Accept ``name``, ``@name`` or a profile URL; return a validated lowercase username."""
    raw = (raw or "").strip()
    if not raw:
        return None
    m = _PROFILE_URL_RE.search(raw) if "instagram.com" in raw else None
    candidate = m.group(1) if m else raw.lstrip("@")
    candidate = candidate.strip().strip("/")
    if candidate.lower() in {"p", "reel", "reels", "explore", "accounts", "stories", "tv"}:
        return None
    return candidate.lower() if USERNAME_RE.match(candidate) else None


def shortcode_from_url(url: str) -> Optional[str]:
    m = _REEL_URL_RE.search(url or "")
    return m.group(1) if m else None


def media_id_to_shortcode(media_id: int | str) -> str:
    """Convert a numeric Instagram media id to its URL shortcode (base-64 variant)."""
    n = int(str(media_id).split("_")[0])
    if n <= 0:
        raise ValueError("media id must be positive")
    out = ""
    while n:
        n, rem = divmod(n, 64)
        out = _B64_ALPHABET[rem] + out
    return out


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
class DownloadError(RuntimeError):
    """Raised when a media URL cannot be fetched after retries."""


def looks_like_mp4(path: Path) -> bool:
    """True when the file starts with an ISO-BMFF ``ftyp`` box (real MP4/MOV)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
        return len(head) >= 12 and head[4:8] == b"ftyp"
    except OSError:
        return False


def download_mp4(
    url: str,
    dest: Path,
    *,
    session: Optional[requests.Session] = None,
    referer: Optional[str] = None,
    retries: int = 4,
    min_bytes: int = 20_000,
    timeout: tuple[float, float] = (15.0, 120.0),
    stop: Optional[threading.Event] = None,
    log=None,
) -> Path:
    """Stream ``url`` into ``dest`` atomically and verify it is a real MP4.

    Retries transient failures (5xx, 429, network) with jittered exponential
    backoff; gives up immediately on 401/403/404/410 (expired or forbidden CDN
    links never recover by retrying).
    """
    log = log or get_logger("download")
    if not url.lower().startswith("https://") and not os.environ.get("REELIO_IG_ALLOW_HTTP"):   # (the env switch exists only for tests against localhost)
        raise DownloadError(f"refusing non-HTTPS media URL: {url[:80]}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    sess = session or requests.Session()
    headers = {"User-Agent": DESKTOP_UA, "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.5"}
    if referer:
        headers["Referer"] = referer

    last_err = "unknown"
    for attempt in range(1, retries + 1):
        if stop is not None and stop.is_set():
            raise DownloadError("stopped before download finished")
        try:
            with sess.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True) as resp:
                if resp.status_code in (401, 403, 404, 410):
                    raise DownloadError(f"HTTP {resp.status_code} (link expired or forbidden)")
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}"
                    raise requests.RequestException(last_err)
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "").lower()
                if "text/html" in ctype or "json" in ctype:
                    raise DownloadError(f"unexpected content-type {ctype!r} (probably a block page)")
                size = 0
                with open(part, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if stop is not None and stop.is_set():
                            raise DownloadError("stopped mid-download")
                        if chunk:
                            fh.write(chunk)
                            size += len(chunk)
            if size < min_bytes:
                raise DownloadError(f"file too small ({size} bytes)")
            if not looks_like_mp4(part):
                raise DownloadError("payload is not an MP4 container")
            os.replace(part, dest)
            return dest
        except DownloadError:
            part.unlink(missing_ok=True)
            raise
        except requests.RequestException as exc:
            last_err = str(exc)[:200]
            part.unlink(missing_ok=True)
            if attempt < retries:
                wait = min(60.0, (2 ** attempt) + random.uniform(0.5, 3.0))
                log.warning("download attempt %d/%d failed (%s); retrying in %.0fs", attempt, retries, last_err, wait)
                if stop is not None:
                    stop.wait(wait)
                else:
                    time.sleep(wait)
    raise DownloadError(f"gave up after {retries} attempts: {last_err}")


def unique(seq: Iterable[str]) -> list[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


ProgressFn = Callable[[str], None]


@dataclass
class Reel:
    shortcode: str
    video_url: str
    source: str                     # mirror name or API provider
    referer: Optional[str] = None
    views: Optional[int] = None     # best effort: only some ways of listing know these
    likes: Optional[int] = None
    posted_at: Optional[str] = None  # ISO 8601 UTC


def to_int(v):
    try:
        return int(float(str(v).replace(",", ""))) if v not in (None, "", False) else None
    except (TypeError, ValueError):
        return None


def to_iso(v):
    """Epoch seconds / milliseconds, 'YYYY-MM-DD HH:MM:SS' or ISO text -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC), or None."""
    import datetime as _dt
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)) or re.fullmatch(r"\d{9,13}(\.\d+)?", str(v)):
            x = float(v)
            x = x / 1000.0 if x > 1e11 else x
            return _dt.datetime.fromtimestamp(x, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        t = str(v).strip().replace(" ", "T").replace("+00:00", "Z")
        d = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def pick(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None
