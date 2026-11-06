#!/usr/bin/env python3
"""Tier 4b - serverless API proxy.

Asks a third-party scraping service (which handles proxy rotation / logins on its
side) for a profile's reels and returns direct ``.mp4`` links for the runner to
download. Two providers are supported; whichever has credentials is used:

  * Apify   (env APIFY_TOKEN)   actor ``apify/instagram-reel-scraper`` (override: APIFY_ACTOR)
  * RapidAPI (env RAPIDAPI_KEY) host/path/param are env-overridable because
    RapidAPI marketplace APIs differ: RAPIDAPI_HOST, RAPIDAPI_PATH, RAPIDAPI_USER_PARAM

Response parsing is tolerant: it walks the JSON for objects that carry a video URL
plus a shortcode (``code``/``shortCode``/``shortcode``/post ``url``), so minor schema
differences between actors/APIs do not break it.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from typing import Any, Iterator, Optional

import requests

from cookieless_fallback import Reel
from igcommon import SHORTCODE_RE, USERNAME_RE, get_logger, shortcode_from_url, unique

log = get_logger("api")


class ApiError(RuntimeError):
    """Generic provider failure."""


class ApiAuthError(ApiError):
    """Bad / missing credentials, or subscription not active. Retrying is pointless."""


class ApiQuotaError(ApiError):
    """Credits / rate quota exhausted (HTTP 402 / 429 after retries)."""


# --------------------------------------------------------------------------- #
# Tolerant JSON parsing
# --------------------------------------------------------------------------- #
def _walk(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _video_url_of(d: dict) -> Optional[str]:
    for key in ("videoUrl", "video_url", "videoURL", "video_url_hd", "playUrl"):
        v = d.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    versions = d.get("video_versions")
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        v = versions[0].get("url")
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


def _shortcode_of(d: dict) -> Optional[str]:
    for key in ("shortCode", "shortcode", "code"):
        v = d.get(key)
        if isinstance(v, str) and SHORTCODE_RE.match(v):
            return v
    for key in ("url", "permalink", "link", "postUrl"):
        v = d.get(key)
        if isinstance(v, str):
            sc = shortcode_from_url(v)
            if sc:
                return sc
    return None


def parse_reels(payload: Any, source: str) -> list[Reel]:
    """Extract unique (shortcode, https video url) pairs from any provider payload."""
    reels: list[Reel] = []
    seen: set[str] = set()
    for node in _walk(payload):
        url = _video_url_of(node)
        sc = _shortcode_of(node)
        if url and sc and sc not in seen and url.startswith("https://"):
            seen.add(sc)
            reels.append(Reel(shortcode=sc, video_url=url, source=source))
    return reels


# --------------------------------------------------------------------------- #
# HTTP helper with retry
# --------------------------------------------------------------------------- #
def _request(
    method: str,
    url: str,
    *,
    stop: Optional[threading.Event] = None,
    retries: int = 4,
    **kw: Any,
) -> requests.Response:
    kw.setdefault("timeout", (15, 90))
    last = "unknown"
    for attempt in range(1, retries + 1):
        if stop is not None and stop.is_set():
            raise ApiError("stopped")
        try:
            resp = requests.request(method, url, **kw)
        except requests.RequestException as exc:
            last = f"network: {str(exc)[:150]}"
        else:
            if resp.status_code in (401, 403):
                raise ApiAuthError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 402:
                raise ApiQuotaError(f"HTTP 402 (credits exhausted): {resp.text[:200]}")
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                if resp.status_code == 429 and attempt == retries:
                    raise ApiQuotaError("HTTP 429 (rate limited) after retries")
            elif resp.status_code >= 400:
                raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                return resp
        if attempt < retries:
            wait = min(90.0, 4 * (2 ** (attempt - 1)) + random.uniform(1, 5))
            log.warning("API call failed (%s); retry %d/%d in %.0fs", last, attempt, retries - 1, wait)
            (stop.wait(wait) if stop is not None else time.sleep(wait))
    raise ApiError(f"gave up after {retries} attempts: {last}")


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
def fetch_apify(user: str, max_reels: int, token: str, *, budget_s: float, stop: Optional[threading.Event]) -> list[Reel]:
    actor = os.environ.get("APIFY_ACTOR", "apify~instagram-reel-scraper").replace("/", "~")
    base = "https://api.apify.com/v2"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"username": [user], "resultsLimit": max_reels}

    run = _request("POST", f"{base}/acts/{actor}/runs", headers=headers, json=body, stop=stop).json()["data"]
    run_id, dataset_id = run["id"], run["defaultDatasetId"]
    log.info("Apify run %s started for @%s", run_id, user)

    deadline = time.monotonic() + budget_s
    status = run.get("status", "READY")
    while status in ("READY", "RUNNING", "ABORTING"):
        if time.monotonic() > deadline or (stop is not None and stop.is_set()):
            try:  # best effort: don't leave a billable run behind
                requests.post(f"{base}/actor-runs/{run_id}/abort", headers=headers, timeout=15)
            except requests.RequestException:
                pass
            raise ApiError("Apify run did not finish within the time budget")
        (stop.wait(8) if stop is not None else time.sleep(8))
        status = _request("GET", f"{base}/actor-runs/{run_id}", headers=headers, stop=stop).json()["data"]["status"]
    if status != "SUCCEEDED":
        raise ApiError(f"Apify run ended with status {status}")

    items = _request(
        "GET", f"{base}/datasets/{dataset_id}/items", headers=headers, params={"format": "json", "clean": "true"}, stop=stop
    ).json()
    return parse_reels(items, "apify")[:max_reels]


def fetch_rapidapi(user: str, max_reels: int, key: str, *, stop: Optional[threading.Event]) -> list[Reel]:
    host = os.environ.get("RAPIDAPI_HOST", "instagram-scraper-api2.p.rapidapi.com")
    path = os.environ.get("RAPIDAPI_PATH", "/v1.2/reels")
    param = os.environ.get("RAPIDAPI_USER_PARAM", "username_or_id_or_url")
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}

    reels: list[Reel] = []
    seen: set[str] = set()
    token: Optional[str] = None
    for _page in range(15):  # hard cap on pagination
        params = {param: user}
        if token:
            params["pagination_token"] = token
        payload = _request("GET", f"https://{host}{path}", headers=headers, params=params, stop=stop).json()
        for r in parse_reels(payload, "rapidapi"):
            if r.shortcode not in seen:
                seen.add(r.shortcode)
                reels.append(r)
        token = payload.get("pagination_token") if isinstance(payload, dict) else None
        if len(reels) >= max_reels or not token:
            break
        (stop.wait(random.uniform(1, 3)) if stop is not None else time.sleep(random.uniform(1, 3)))
    return reels[:max_reels]


def fetch_reels(
    user: str,
    *,
    max_reels: int = 30,
    rapidapi_key: Optional[str] = None,
    apify_token: Optional[str] = None,
    budget_s: float = 420.0,
    stop: Optional[threading.Event] = None,
) -> list[Reel]:
    """Query each configured provider until one returns reels. Raises ApiError if none work."""
    if not USERNAME_RE.match(user):
        raise ValueError(f"invalid username: {user!r}")
    providers: list[tuple[str, Any]] = []
    if apify_token:
        providers.append(("apify", lambda: fetch_apify(user, max_reels, apify_token, budget_s=budget_s, stop=stop)))
    if rapidapi_key:
        providers.append(("rapidapi", lambda: fetch_rapidapi(user, max_reels, rapidapi_key, stop=stop)))
    if not providers:
        raise ApiAuthError("no API credentials configured (set APIFY_TOKEN and/or RAPIDAPI_KEY)")

    errors: list[str] = []
    auth_failures = 0
    for name, fn in providers:
        try:
            reels = fn()
        except ApiAuthError as exc:
            auth_failures += 1
            errors.append(f"{name}: auth: {exc}")
        except ApiError as exc:
            errors.append(f"{name}: {exc}")
        except (KeyError, ValueError) as exc:  # malformed JSON / unexpected schema
            errors.append(f"{name}: unexpected response ({type(exc).__name__}: {exc})")
        else:
            if reels:
                log.info("%s returned %d reel link(s) for @%s", name, len(reels), user)
                return reels
            errors.append(f"{name}: returned no reels")
    if auth_failures == len(providers):
        raise ApiAuthError("; ".join(errors))
    raise ApiError("; ".join(errors))


def _main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch reel .mp4 links via third-party scraping APIs.")
    ap.add_argument("--user", required=True)
    ap.add_argument("--max-reels", type=int, default=20)
    args = ap.parse_args(argv)
    try:
        reels = fetch_reels(
            args.user.lstrip("@").lower(),
            max_reels=args.max_reels,
            rapidapi_key=os.environ.get("RAPIDAPI_KEY"),
            apify_token=os.environ.get("APIFY_TOKEN"),
        )
    except ApiError as exc:
        log.error("%s", exc)
        return 1
    print(json.dumps([r.__dict__ for r in reels], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
