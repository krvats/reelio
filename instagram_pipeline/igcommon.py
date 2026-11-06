"""Shared helpers for the Instagram Reels pipeline.

Kept dependency-light (only ``requests``) so every other module can import it.
Provides: GitHub-Actions-aware logging, randomized sleeping, username /
shortcode validation, and a hardened MP4 downloader.
"""
from __future__ import annotations

import logging
import os
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

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
# Logging (GitHub Actions friendly)
# --------------------------------------------------------------------------- #
class _GHFormatter(logging.Formatter):
    """Plain timestamped lines; WARNING/ERROR also emit workflow annotations."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            if record.levelno >= logging.ERROR:
                return f"::error::{record.getMessage()}\n{msg}"
            if record.levelno == logging.WARNING:
                return f"::warning::{record.getMessage()}\n{msg}"
        return msg


def get_logger(name: str = "ig") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_GHFormatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("IG_LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    return logger


def gh_group(title: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        with _print_lock:
            print(f"::group::{title}", flush=True)
    else:
        with _print_lock:
            print(f"--- {title} ---", flush=True)


def gh_endgroup() -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        with _print_lock:
            print("::endgroup::", flush=True)


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
    log: Optional[logging.Logger] = None,
) -> Path:
    """Stream ``url`` into ``dest`` atomically and verify it is a real MP4.

    Retries transient failures (5xx, 429, network) with jittered exponential
    backoff; gives up immediately on 401/403/404/410 (expired or forbidden CDN
    links never recover by retrying).
    """
    log = log or get_logger("download")
    if not url.lower().startswith("https://"):
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
