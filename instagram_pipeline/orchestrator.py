#!/usr/bin/env python3
"""Multi-tier Instagram Reels scraping orchestrator for GitHub Actions.

Per target profile the tiers run in order until one completes cleanly:

  1   Instaloader        incremental (--fast-update + persisted latest-stamps), session cookie
  2   gallery-dl         /reels/ tab, persisted download archive
  3   Hybrid             gallery-dl -j (or Playwright) harvests /reel/<code>/ links -> yt-dlp
  4a  Mirror viewers     Playwright over public mirrors, cookie-less        (cookieless_fallback.py)
  4b  API proxy          Apify / RapidAPI direct .mp4 links                  (serverless_api_proxy.py)

Guarantees
  * Transactional per profile: archive/stamp state is only committed after rclone
    successfully moved the files to Google Drive; otherwise it is rolled back so
    nothing is ever marked "done" without being stored.
  * Soft deadline (default 335 min) + SIGTERM/SIGINT handling: running children are
    stopped, what was downloaded is uploaded, state is saved, exit is clean.
  * Rate-limit / login-challenge text in tool output kills the tool at once and
    cycles to the next tier; repeated blocks trip a per-tier circuit breaker.
  * Secrets are redacted from all echoed output.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import builtins
import collections
import datetime as dt
import enum
import json
import os
import pickle
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from igcommon import (
    DESKTOP_UA,
    DownloadError,
    SHORTCODE_RE,
    download_mp4,
    get_logger,
    gh_endgroup,
    gh_group,
    jitter_sleep,
    looks_like_mp4,
    normalize_username,
    unique,
)

log = get_logger("orch")
_print_lock = threading.Lock()
ARCHIVE_KEY = "instagram"  # yt-dlp archive extractor key used for every tier


# =========================================================================== #
# Config / runtime
# =========================================================================== #
@dataclass
class Config:
    targets: list[str]
    force_tier: str = "auto"
    max_reels: int = 0                       # 0 = unlimited
    staging: Path = Path("/tmp/ig_staging")
    state_dir: Path = Path("state")
    artifact_dir: Path = Path("state_artifact")
    work_dir: Path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "ig_work"
    remote: str = "gdrive:Instagram_Reels"
    deadline_min: float = 335.0
    tier_timeout_min: float = 45.0
    upload_reserve_s: float = 600.0
    delay_profile: tuple[float, float] = (30.0, 90.0)
    delay_tier: tuple[float, float] = (5.0, 15.0)
    ytdlp_workers: int = 3
    breaker_threshold: int = 3
    dry_run: bool = False
    ig_username: str = ""
    session_secret: str = ""
    rapidapi_key: str = ""
    apify_token: str = ""


class Runtime:
    """Wall-clock budget + cooperative stop flag (set by SIGTERM/SIGINT)."""

    def __init__(self, deadline_s: float) -> None:
        self.t0 = time.monotonic()
        self.deadline_s = deadline_s
        self.stop = threading.Event()

    def left(self) -> float:
        return self.deadline_s - (time.monotonic() - self.t0)

    def should_stop(self) -> bool:
        return self.stop.is_set() or self.left() <= 0

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            log.warning("received signal %s - finishing current work and saving state", signal.Signals(signum).name)
            self.stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, handler)


# =========================================================================== #
# Secret redaction + subprocess runner
# =========================================================================== #
_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    if value and len(value) >= 6:
        _SECRETS.add(value)


def redact(text: str) -> str:
    for s in _SECRETS:
        if s in text:
            text = text.replace(s, "***")
    return text


@dataclass
class CmdResult:
    rc: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    stopped: bool = False
    aborted_on: Optional[str] = None     # abort-pattern that killed the process

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


_MAX_CAPTURE = 8_000_000


def run_cmd(
    cmd: list[str],
    *,
    timeout: float,
    rt: Runtime,
    tag: str,
    env: Optional[dict[str, str]] = None,
    echo_stdout: bool = True,
    abort_re: Optional[re.Pattern] = None,
) -> CmdResult:
    """Run ``cmd`` streaming its output live; enforce timeout, global stop and abort patterns."""
    full_env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})}
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", bufsize=1, env=full_env, start_new_session=True,
        )
    except FileNotFoundError as exc:
        return CmdResult(rc=127, stderr=f"command not found: {exc}")

    bufs: dict[str, list[str]] = {"out": [], "err": []}
    sizes = {"out": 0, "err": 0}
    abort_hit: list[str] = []
    lock = threading.Lock()

    def pump(stream, key: str, echo: bool) -> None:
        for line in stream:
            clean = redact(line.rstrip("\n"))
            if sizes[key] < _MAX_CAPTURE:
                bufs[key].append(clean)
                sizes[key] += len(clean) + 1
            if echo and clean.strip():
                with _print_lock:
                    print(f"[{tag}] {clean[:600]}", flush=True)
            if abort_re is not None and not abort_hit:
                m = abort_re.search(clean)
                if m:
                    with lock:
                        abort_hit.append(m.group(0))

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, "out", echo_stdout), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, "err", True), daemon=True),
    ]
    for t in threads:
        t.start()

    started = time.monotonic()
    timed_out = stopped = False
    while proc.poll() is None:
        if time.monotonic() - started > timeout:
            timed_out = True
        elif rt.stop.is_set():
            stopped = True
        elif abort_hit:
            pass
        else:
            time.sleep(0.4)
            continue
        _terminate(proc)
        break

    proc.wait()
    for t in threads:
        t.join(timeout=5)
    return CmdResult(
        rc=proc.returncode,
        stdout="\n".join(bufs["out"]),
        stderr="\n".join(bufs["err"]),
        timed_out=timed_out,
        stopped=stopped,
        aborted_on=abort_hit[0] if abort_hit else None,
    )


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# =========================================================================== #
# Failure classification
# =========================================================================== #
class Verdict(enum.Enum):
    OK = "ok"
    RATE_LIMIT = "rate-limit"
    AUTH = "login/challenge"
    UNAVAILABLE = "profile unavailable"
    ERROR = "error"


_RATE_RE = re.compile(
    r"(\b429\b|too many (?:requests|queries)|rate[- ]?limit|wait a few minutes|need to wait|"
    r"temporarily (?:blocked|banned)|try again later|please wait)", re.I)
_AUTH_RE = re.compile(
    r"(login[_ ]required|requires? (?:a )?login|checkpoint|challenge[_ ]required|\b401\b|unauthorized|"
    r"redirected to login|please log ?in|not logged in|session (?:file )?(?:is )?(?:expired|invalid)|"
    r"login error|cookies? (?:are |is )?(?:invalid|expired)|use --cookies|authentication ?(?:error|required|failed)|"
    r"EOFError|logged.?out|accounts/login)", re.I)
_UNAVAIL_RE = re.compile(
    r"(profile\s+\S+\s+does not exist|profile\s+\S+\s+is private|private profile|user\s+\S+\s+(?:not found|does not exist))", re.I)

# Patterns that mean "stop wasting time, switch tier now" (instaloader/gallery-dl otherwise sleep & retry).
ABORT_RE = re.compile(r"(too many (?:requests|queries)|\b429\b|wait a few minutes|need to wait|rate[- ]?limit)", re.I)


def classify(text: str) -> Verdict:
    if _UNAVAIL_RE.search(text) and not _AUTH_RE.search(text):
        return Verdict.UNAVAILABLE
    if _RATE_RE.search(text):
        return Verdict.RATE_LIMIT
    if _AUTH_RE.search(text):
        return Verdict.AUTH
    return Verdict.OK


class Status(enum.Enum):
    OK = "ok"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class TierOutcome:
    status: Status
    detail: str = ""


# =========================================================================== #
# Cookies / session handling
# =========================================================================== #
class _SafeUnpickler(pickle.Unpickler):
    """Only plain containers/scalars - an Instaloader session file is a dict of strings."""

    _ALLOWED = {"dict", "list", "str", "int", "float", "bool", "tuple", "set"}

    def find_class(self, module: str, name: str):
        if module == "builtins" and name in self._ALLOWED:
            return getattr(builtins, name)
        raise pickle.UnpicklingError(f"forbidden object in session data: {module}.{name}")


def _parse_cookie_blob(raw: bytes) -> dict[str, str]:
    """Accept: Instaloader pickle | Netscape cookies.txt | JSON (dict or list) | 'a=b; c=d' | bare sessionid."""
    if raw[:1] == b"\x80":
        import io
        data = _SafeUnpickler(io.BytesIO(raw)).load()
        if not isinstance(data, dict):
            raise ValueError("pickled session is not a dict")
        return {str(k): str(v) for k, v in data.items()}
    text = raw.decode("utf-8", errors="replace").strip()
    if text[:1] in "{[":
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return {c["name"]: c["value"] for c in data if "instagram" in str(c.get("domain", "instagram"))}
    if "\t" in text:
        out: dict[str, str] = {}
        for line in text.splitlines():
            line = line.removeprefix("#HttpOnly_")
            parts = line.split("\t")
            if len(parts) >= 7 and not line.startswith("#") and "instagram" in parts[0]:
                out[parts[5]] = parts[6]
        if out:
            return out
    if "=" in text:
        return {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in text.split(";")) if k.strip()}
    if len(text) >= 20 and " " not in text:
        return {"sessionid": text}
    raise ValueError("unrecognised cookie format")


@dataclass
class CookieBundle:
    cookies: dict[str, str] = field(default_factory=dict)
    netscape_path: Optional[Path] = None
    session_path: Optional[Path] = None

    @property
    def present(self) -> bool:
        return bool(self.cookies.get("sessionid"))


def build_cookie_bundle(cfg: Config) -> CookieBundle:
    """Decode INSTAGRAM_SESSION_COOKIE once; materialise every format the tools need."""
    session_file = cfg.state_dir / "session" / f"session-{cfg.ig_username or 'unknown'}"
    cookies: dict[str, str] = {}

    secret = cfg.session_secret.strip()
    if secret:
        try:
            try:
                raw = base64.b64decode(secret, validate=True)
            except (binascii.Error, ValueError):
                raw = secret.encode()
            cookies = _parse_cookie_blob(raw)
        except Exception as exc:  # noqa: BLE001
            log.error("INSTAGRAM_SESSION_COOKIE could not be decoded (%s: %s)", type(exc).__name__, exc)
    elif session_file.exists():
        try:
            cookies = _parse_cookie_blob(session_file.read_bytes())
            log.info("using cached session file (no INSTAGRAM_SESSION_COOKIE secret provided)")
        except Exception as exc:  # noqa: BLE001
            log.warning("cached session unreadable: %s", exc)

    bundle = CookieBundle(cookies=cookies)
    if not bundle.present:
        return bundle
    for v in cookies.values():
        register_secret(v)

    # Instaloader session file (pickled dict - exactly what Instaloader writes itself)
    session_file.parent.mkdir(parents=True, exist_ok=True)
    with open(session_file, "wb") as fh:
        pickle.dump(cookies, fh, protocol=4)
    os.chmod(session_file, 0o600)
    bundle.session_path = session_file

    # Netscape cookies.txt for gallery-dl / yt-dlp (kept OUT of the cached state dir)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    nets = cfg.work_dir / "cookies.txt"
    exp = int(time.time()) + 365 * 86400
    lines = ["# Netscape HTTP Cookie File"]
    for name, value in cookies.items():
        lines.append(f".instagram.com\tTRUE\t/\tTRUE\t{exp}\t{name}\t{value}")
    fd = os.open(nets, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    bundle.netscape_path = nets
    return bundle


# =========================================================================== #
# Persistent state (archive, stamps, run history) - transactional per profile
# =========================================================================== #
class StateStore:
    ARCHIVE_FILES = ("archive.txt", "gallery-dl-archive.sqlite3", "instaloader-latest-stamps.ini")

    def __init__(self, root: Path) -> None:
        self.root = root
        self.archive_dir = root / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        (root / "session").mkdir(parents=True, exist_ok=True)
        self.archive_txt = self.archive_dir / "archive.txt"
        self.gdl_archive = self.archive_dir / "gallery-dl-archive.sqlite3"
        self.stamps = self.archive_dir / "instaloader-latest-stamps.ini"
        self.run_state_path = root / "run_state.json"
        self.archive_txt.touch(exist_ok=True)
        self._snap: Optional[Path] = None

    # ---- archive.txt (yt-dlp format: "instagram <shortcode>") ---------------
    def archived(self) -> set[str]:
        out: set[str] = set()
        for line in self.archive_txt.read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == ARCHIVE_KEY:
                out.add(parts[1])
        return out

    def add(self, shortcodes: list[str]) -> None:
        new = [s for s in shortcodes if s not in self.archived()]
        if new:
            with open(self.archive_txt, "a") as fh:
                fh.writelines(f"{ARCHIVE_KEY} {s}\n" for s in new)

    def replace_archive_lines(self, lines: set[str]) -> None:
        tmp = self.archive_txt.with_suffix(".tmp")
        tmp.write_text("".join(f"{ln}\n" for ln in sorted(lines)))
        os.replace(tmp, self.archive_txt)

    # ---- transaction --------------------------------------------------------
    def begin(self) -> None:
        self._snap = self.root / ".snapshot"
        shutil.rmtree(self._snap, ignore_errors=True)
        shutil.copytree(self.archive_dir, self._snap)

    def rollback(self) -> None:
        if self._snap and self._snap.exists():
            shutil.rmtree(self.archive_dir, ignore_errors=True)
            shutil.copytree(self._snap, self.archive_dir)
            log.warning("state rolled back to the start of this profile")
        self._discard()

    def commit(self) -> None:
        self._discard()

    def _discard(self) -> None:
        if self._snap:
            shutil.rmtree(self._snap, ignore_errors=True)
        self._snap = None

    # ---- run history --------------------------------------------------------
    def load_run_state(self) -> dict:
        try:
            return json.loads(self.run_state_path.read_text())
        except (OSError, ValueError):
            return {"profiles": {}, "runs": []}

    def save_run_state(self, data: dict) -> None:
        tmp = self.run_state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.run_state_path)

    def restore_from(self, src: Path) -> int:
        """Seed missing state files from a downloaded artifact directory."""
        n = 0
        for name in self.ARCHIVE_FILES:
            dest = self.archive_dir / name
            found = next(iter(sorted(src.rglob(name))), None) if src.exists() else None
            if found and (not dest.exists() or dest.stat().st_size == 0):
                shutil.copy2(found, dest)
                n += 1
        found_rs = next(iter(sorted(src.rglob("run_state.json"))), None) if src.exists() else None
        if found_rs and not self.run_state_path.exists():
            shutil.copy2(found_rs, self.run_state_path)
            n += 1
        return n

    def export_artifact(self, out: Path) -> None:
        shutil.rmtree(out, ignore_errors=True)
        (out / "archive").mkdir(parents=True)
        for name in self.ARCHIVE_FILES:
            if (self.archive_dir / name).exists():
                shutil.copy2(self.archive_dir / name, out / "archive" / name)
        if self.run_state_path.exists():
            shutil.copy2(self.run_state_path, out / "run_state.json")


# =========================================================================== #
# Tool wrappers (flag probing keeps us compatible across tool versions)
# =========================================================================== #
def py_module(mod: str) -> list[str]:
    return [sys.executable, "-m", mod]


_help_cache: dict[tuple, str] = {}


def help_text(cmd: list[str]) -> str:
    key = tuple(cmd)
    if key not in _help_cache:
        try:
            r = subprocess.run(cmd + ["--help"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            _help_cache[key] = (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.SubprocessError):
            _help_cache[key] = ""
    return _help_cache[key]


def build_flags(base: list[str], wanted: list[tuple[str, Optional[str]]], tool: str) -> list[str]:
    """Return flag arguments, dropping flags this tool version does not advertise in --help."""
    help_ = help_text(base)
    out: list[str] = []
    for flag, value in wanted:
        if not help_ or re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_):
            out.append(flag)
            if value is not None:
                out.append(value)
        else:
            log.warning("%s: flag %s is not supported by the installed version - omitted", tool, flag)
    return out


# =========================================================================== #
# Per-profile context + tiers
# =========================================================================== #
@dataclass
class Ctx:
    cfg: Config
    rt: Runtime
    state: StateStore
    cookies: CookieBundle
    user: str
    staging: Path
    committed: set[str]                  # shortcodes already archived BEFORE this profile started

    def tier_timeout(self) -> float:
        return max(0.0, min(self.cfg.tier_timeout_min * 60, self.rt.left() - self.cfg.upload_reserve_s))

    def count_flag(self) -> Optional[str]:
        return str(self.cfg.max_reels) if self.cfg.max_reels > 0 else None


class Tier:
    id = ""
    label = ""
    needs_cookies = False

    def skip_reason(self, ctx: Ctx) -> Optional[str]:
        return None

    def run(self, ctx: Ctx) -> TierOutcome:  # pragma: no cover - interface
        raise NotImplementedError

    @staticmethod
    def judge(res: CmdResult, ok_rcs: tuple[int, ...] = (0,)) -> TierOutcome:
        """Translate a finished command into a TierOutcome."""
        if res.rc == 127:
            return TierOutcome(Status.FAILED, res.stderr.strip()[:200])
        verdict = classify(res.output if not res.aborted_on else res.output + " " + res.aborted_on)
        if res.stopped:
            return TierOutcome(Status.TIMEOUT, "stopped by signal/deadline")
        if res.aborted_on or verdict in (Verdict.RATE_LIMIT, Verdict.AUTH):
            v = Verdict.RATE_LIMIT if res.aborted_on else verdict
            return TierOutcome(Status.BLOCKED, v.value)
        if verdict is Verdict.UNAVAILABLE:
            return TierOutcome(Status.UNAVAILABLE, "profile does not exist or is private")
        if res.timed_out:
            return TierOutcome(Status.TIMEOUT, "tier timeout")
        if res.rc in ok_rcs:
            return TierOutcome(Status.OK)
        return TierOutcome(Status.FAILED, f"exit code {res.rc}")


class InstaloaderTier(Tier):
    id, label, needs_cookies = "1", "Instaloader (incremental)", True

    def skip_reason(self, ctx: Ctx) -> Optional[str]:
        if not ctx.cookies.session_path:
            return "no session cookie available"
        if not ctx.cfg.ig_username:
            return "INSTAGRAM_USERNAME secret not set (Instaloader needs the session owner's username)"
        return None

    def run(self, ctx: Ctx) -> TierOutcome:
        base = py_module("instaloader")
        wanted: list[tuple[str, Optional[str]]] = [
            ("--no-posts", None), ("--no-pictures", None), ("--no-captions", None),
            ("--no-metadata-json", None), ("--no-compress-json", None),
            ("--no-profile-pic", None), ("--no-video-thumbnails", None),
            ("--fast-update", None), ("--latest-stamps", str(ctx.state.stamps)),
            ("--request-timeout", "60"), ("--max-connection-attempts", "2"),
        ]
        if ctx.count_flag():
            wanted.append(("--count", ctx.count_flag()))
        cmd = base + [
            "--login", ctx.cfg.ig_username, "--sessionfile", str(ctx.cookies.session_path),
            "--dirname-pattern", str(ctx.staging), "--filename-pattern", "{shortcode}",
            "--reels",
        ] + build_flags(base, wanted, "instaloader") + [ctx.user]
        res = run_cmd(cmd, timeout=ctx.tier_timeout(), rt=ctx.rt, tag="instaloader", abort_re=ABORT_RE)
        return self.judge(res)


class GalleryDlTier(Tier):
    id, label, needs_cookies = "2", "gallery-dl (/reels/ tab)", True

    @staticmethod
    def write_config(ctx: Ctx) -> Path:
        cfgfile = ctx.cfg.work_dir / "gallery-dl.json"
        ig: dict = {"videos": True, "previews": False, "highlights": False, "retries": 2, "sleep-request": [2.0, 6.0]}
        if ctx.cookies.netscape_path:
            ig["cookies"] = str(ctx.cookies.netscape_path)
        cfgfile.parent.mkdir(parents=True, exist_ok=True)
        cfgfile.write_text(json.dumps({"extractor": {"instagram": ig}}, indent=2))
        os.chmod(cfgfile, 0o600)
        return cfgfile

    def run(self, ctx: Ctx) -> TierOutcome:
        base = py_module("gallery_dl")
        wanted: list[tuple[str, Optional[str]]] = [
            ("--download-archive", str(ctx.state.gdl_archive)),
            ("--filter", "extension == 'mp4'"),
        ]
        if ctx.cfg.max_reels > 0:
            wanted.append(("--range", f"1-{ctx.cfg.max_reels}"))
        cmd = base + [
            "--config", str(self.write_config(ctx)),
            "-D", str(ctx.staging), "-f", "{post_shortcode}.{extension}",
        ] + build_flags(base, wanted, "gallery-dl") + [f"https://www.instagram.com/{ctx.user}/reels/"]
        res = run_cmd(cmd, timeout=ctx.tier_timeout(), rt=ctx.rt, tag="gallery-dl", abort_re=ABORT_RE)
        # gallery-dl exits non-zero if *any* single file failed; block/auth/timeouts are judged first.
        return self.judge(res)


_REEL_LINK_RE = re.compile(r"/(?:[A-Za-z0-9._]+/)?reels?/([A-Za-z0-9_-]{5,24})")


def playwright_harvest(ctx: Ctx, budget_s: float) -> list[str]:
    """Scroll the logged-in /reels/ tab and collect shortcodes. Raises RuntimeError on login wall."""
    from playwright.sync_api import sync_playwright

    limit = ctx.cfg.max_reels or 200
    codes: list[str] = []
    deadline = time.monotonic() + budget_s
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            bctx = browser.new_context(user_agent=DESKTOP_UA, viewport={"width": 1280, "height": 900}, locale="en-US")
            if ctx.cookies.present:
                bctx.add_cookies([
                    {"name": k, "value": v, "domain": ".instagram.com", "path": "/", "secure": True}
                    for k, v in ctx.cookies.cookies.items()
                ])
            page = bctx.new_page()
            page.set_default_timeout(30_000)
            page.goto(f"https://www.instagram.com/{ctx.user}/reels/", wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(3000)
            if "/accounts/login" in page.url or page.query_selector('input[name="username"]'):
                raise RuntimeError("login wall (accounts/login)")
            stagnant = 0
            while len(codes) < limit and stagnant < 4 and time.monotonic() < deadline and not ctx.rt.should_stop():
                hrefs = page.eval_on_selector_all(
                    'a[href*="/reel/"], a[href*="/reels/"]', "els => els.map(e => e.getAttribute('href'))")
                before = len(codes)
                for h in hrefs:
                    m = _REEL_LINK_RE.search(h or "")
                    if m and SHORTCODE_RE.match(m.group(1)):
                        codes.append(m.group(1))
                codes = unique(codes)
                stagnant = stagnant + 1 if len(codes) == before else 0
                page.mouse.wheel(0, random.randint(1400, 2600))
                page.wait_for_timeout(random.randint(1200, 3200))
        finally:
            browser.close()
    return codes[:limit]


class HybridTier(Tier):
    id, label, needs_cookies = "3", "Hybrid harvest -> yt-dlp", True

    def harvest(self, ctx: Ctx) -> tuple[list[str], Optional[TierOutcome]]:
        """Return (shortcodes, failure). Method A: gallery-dl -j. Method B: Playwright."""
        base = py_module("gallery_dl")
        wanted: list[tuple[str, Optional[str]]] = [("--dump-json", None)]
        if ctx.cfg.max_reels > 0:
            wanted.append(("--range", f"1-{ctx.cfg.max_reels}"))
        cmd = base + ["--config", str(GalleryDlTier.write_config(ctx))] + build_flags(base, wanted, "gallery-dl") \
            + [f"https://www.instagram.com/{ctx.user}/reels/"]
        res = run_cmd(cmd, timeout=min(ctx.tier_timeout(), 600), rt=ctx.rt, tag="gdl-harvest",
                      echo_stdout=False, abort_re=ABORT_RE)
        codes = unique(re.findall(r'"(?:post_shortcode|shortcode)":\s*"([A-Za-z0-9_-]{5,24})"', res.stdout))
        if codes:
            log.info("gallery-dl harvested %d reel link(s)", len(codes))
            return codes, None
        a_outcome = self.judge(res)
        log.warning("gallery-dl harvest yielded nothing (%s %s) - trying Playwright", a_outcome.status.value, a_outcome.detail)
        if ctx.rt.should_stop():
            return [], TierOutcome(Status.TIMEOUT, "stopped")
        try:
            codes = playwright_harvest(ctx, budget_s=min(ctx.tier_timeout(), 420))
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {str(exc)[:160]}"
            blocked = "login wall" in msg or classify(msg) in (Verdict.AUTH, Verdict.RATE_LIMIT)
            return [], TierOutcome(Status.BLOCKED if blocked else Status.FAILED, f"playwright: {msg}")
        if codes:
            log.info("Playwright harvested %d reel link(s)", len(codes))
            return codes, None
        # Both methods empty: genuine empty profile only if gallery-dl exited cleanly.
        return [], (TierOutcome(Status.OK, "no reels found") if a_outcome.status is Status.OK
                    else TierOutcome(a_outcome.status if a_outcome.status is not Status.TIMEOUT else Status.TIMEOUT,
                                     a_outcome.detail or "harvest failed"))

    def run(self, ctx: Ctx) -> TierOutcome:
        codes, failure = self.harvest(ctx)
        if failure is not None:
            return failure
        archived = ctx.state.archived()
        todo = [c for c in codes if c not in archived]
        log.info("%d harvested, %d new", len(codes), len(todo))
        if not todo:
            return TierOutcome(Status.OK, "up to date")

        work = ctx.cfg.work_dir / "ytdlp"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        workers = max(1, min(ctx.cfg.ytdlp_workers, len(todo)))
        chunks = [todo[i::workers] for i in range(workers)]
        base = py_module("yt_dlp")
        flag_args = build_flags(base, [
            ("--no-playlist", None), ("--no-mtime", None), ("--ignore-errors", None), ("--no-overwrites", None),
            ("--retries", "3"), ("--fragment-retries", "3"), ("--extractor-retries", "2"),
            ("--concurrent-fragments", "4"), ("--sleep-interval", "3"), ("--max-sleep-interval", "9"),
            ("--sleep-requests", "1"), ("--merge-output-format", "mp4"), ("--newline", None),
        ], "yt-dlp")

        def job(i: int, chunk: list[str]) -> tuple[CmdResult, Path]:
            urls = work / f"urls_{i}.txt"
            urls.write_text("".join(f"https://www.instagram.com/reel/{c}/\n" for c in chunk))
            arch = work / f"archive_{i}.txt"
            shutil.copy2(ctx.state.archive_txt, arch)
            cmd = base + ["-a", str(urls), "--download-archive", str(arch),
                          "-o", str(ctx.staging / "%(id)s.%(ext)s")] + flag_args
            if ctx.cookies.netscape_path:
                cmd += ["--cookies", str(ctx.cookies.netscape_path)]
            if i:  # stagger workers so they don't hit Instagram in the same second
                jitter_sleep(2 * i, 6 * i, ctx.rt.stop)
            return run_cmd(cmd, timeout=ctx.tier_timeout(), rt=ctx.rt, tag=f"yt-dlp#{i}", abort_re=ABORT_RE), arch

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda a: job(*a), enumerate(chunks)))

        merged = ctx.state.archived()
        lines = {f"{ARCHIVE_KEY} {s}" for s in merged}
        for _res, arch in results:
            lines |= {ln.strip() for ln in arch.read_text(errors="replace").splitlines() if ln.strip()}
        ctx.state.replace_archive_lines(lines)

        got = {p.stem for p in ctx.staging.glob("*.mp4")}
        wanted_done = len(got & set(todo))
        blocked = [r for r, _ in results if r.aborted_on or classify(r.output) in (Verdict.RATE_LIMIT, Verdict.AUTH)]
        if any(r.stopped for r, _ in results):
            return TierOutcome(Status.TIMEOUT, f"{wanted_done}/{len(todo)} downloaded before stop")
        if blocked and wanted_done < len(todo):
            return TierOutcome(Status.BLOCKED, f"{wanted_done}/{len(todo)} downloaded before block")
        if any(r.timed_out for r, _ in results) and wanted_done < len(todo):
            return TierOutcome(Status.TIMEOUT, f"{wanted_done}/{len(todo)} downloaded before tier timeout")
        if wanted_done == 0:
            return TierOutcome(Status.FAILED, "yt-dlp downloaded nothing")
        if wanted_done < len(todo):
            log.warning("%d reel(s) could not be fetched (deleted/unavailable?) - not a block, continuing", len(todo) - wanted_done)
        return TierOutcome(Status.OK, f"{wanted_done}/{len(todo)} downloaded")


def _download_reel_list(ctx: Ctx, reels: list, referer_fallback: Optional[str] = None) -> tuple[int, list[str]]:
    import requests
    session = requests.Session()
    done, fails = 0, []
    for r in reels:
        if ctx.rt.should_stop():
            break
        try:
            download_mp4(r.video_url, ctx.staging / f"{r.shortcode}.mp4", session=session,
                         referer=r.referer or referer_fallback, stop=ctx.rt.stop, log=log)
            done += 1
        except DownloadError as exc:
            fails.append(f"{r.shortcode}: {exc}")
            log.warning("download failed for %s: %s", r.shortcode, exc)
        jitter_sleep(1.0, 4.0, ctx.rt.stop)
    return done, fails


class MirrorTier(Tier):
    id, label = "4a", "Cookie-less mirror viewers (Playwright)"

    def run(self, ctx: Ctx) -> TierOutcome:
        import cookieless_fallback as cf
        result = cf.collect_reels(
            ctx.user, max_reels=ctx.cfg.max_reels or 30, skip=ctx.state.archived(),
            time_budget_s=ctx.tier_timeout(), stop=ctx.rt.stop)
        if result.blocked:
            return TierOutcome(Status.BLOCKED, "; ".join(result.errors)[:300])
        if not result.reels:
            return TierOutcome(Status.FAILED, "; ".join(result.errors)[:300] or "no reels found")
        done, fails = _download_reel_list(ctx, result.reels)
        if done == 0:
            return TierOutcome(Status.FAILED, f"links found but 0 downloads ({fails[:1]})")
        return TierOutcome(Status.OK, f"{done}/{len(result.reels)} downloaded via {result.reels[0].source}")


class ApiTier(Tier):
    id, label = "4b", "Serverless API proxy (Apify/RapidAPI)"

    def skip_reason(self, ctx: Ctx) -> Optional[str]:
        if not (ctx.cfg.rapidapi_key or ctx.cfg.apify_token):
            return "no RAPIDAPI_KEY / APIFY_TOKEN configured"
        return None

    def run(self, ctx: Ctx) -> TierOutcome:
        import serverless_api_proxy as api
        try:
            reels = api.fetch_reels(
                ctx.user, max_reels=ctx.cfg.max_reels or 30, rapidapi_key=ctx.cfg.rapidapi_key or None,
                apify_token=ctx.cfg.apify_token or None, budget_s=ctx.tier_timeout(), stop=ctx.rt.stop)
        except api.ApiAuthError as exc:
            return TierOutcome(Status.FAILED, f"auth: {exc}"[:300])
        except api.ApiQuotaError as exc:
            return TierOutcome(Status.BLOCKED, f"quota: {exc}"[:300])
        except api.ApiError as exc:
            return TierOutcome(Status.FAILED, str(exc)[:300])
        archived = ctx.state.archived()
        todo = [r for r in reels if r.shortcode not in archived]
        if not todo:
            return TierOutcome(Status.OK, "up to date")
        done, fails = _download_reel_list(ctx, todo)
        if done == 0:
            return TierOutcome(Status.FAILED, f"0/{len(todo)} downloaded ({fails[:1]})")
        return TierOutcome(Status.OK, f"{done}/{len(todo)} downloaded via {todo[0].source}")


ALL_TIERS: dict[str, Tier] = {t.id: t for t in (InstaloaderTier(), GalleryDlTier(), HybridTier(), MirrorTier(), ApiTier())}
TIER_ORDER = ["1", "2", "3", "4a", "4b"]


# =========================================================================== #
# Staging reconciliation + upload
# =========================================================================== #
def reconcile(ctx: Ctx) -> list[str]:
    """Flatten staging, drop junk / corrupt / already-uploaded files, archive the rest.

    Returns shortcodes of valid files currently staged.
    """
    staged: list[str] = []
    for p in sorted(ctx.staging.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix.lower() != ".mp4":
            p.unlink(missing_ok=True)            # .part, .json.xz, thumbnails, captions ...
            continue
        if p.parent != ctx.staging:               # flatten
            target = ctx.staging / p.name
            os.replace(p, target)
            p = target
        if not looks_like_mp4(p) or p.stat().st_size < 10_000:
            log.warning("discarding invalid file %s", p.name)
            p.unlink(missing_ok=True)
            continue
        if p.stem in ctx.committed:
            log.info("dropping %s (already archived in an earlier run)", p.name)
            p.unlink(missing_ok=True)
            continue
        staged.append(p.stem)
    for d in sorted((x for x in ctx.staging.rglob("*") if x.is_dir()), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    ctx.state.add(staged)
    return staged


class UploadError(RuntimeError):
    pass


def upload_profile(cfg: Config, rt: Runtime, user: str, staging: Path) -> int:
    """rclone move staged mp4s to Drive. Returns number of files moved."""
    files = list(staging.glob("*.mp4"))
    if not files:
        return 0
    dest = f"{cfg.remote.rstrip('/')}/{user}"
    cmd = [
        "rclone", "move", str(staging), dest, "--include", "*.mp4", "--transfers", "4", "--checkers", "8",
        "--retries", "5", "--low-level-retries", "10", "--drive-chunk-size", "64M",
        "--drive-stop-on-upload-limit", "--delete-empty-src-dirs", "--stats", "20s", "--stats-one-line", "-v",
    ]
    last = ""
    for attempt in (1, 2):
        # Upload is allowed to use the reserved time even after the soft deadline passed.
        res = run_cmd(cmd, timeout=1800, rt=Runtime(3600), tag="rclone")
        if res.rc == 0 and not list(staging.glob("*.mp4")):
            log.info("uploaded %d file(s) to %s", len(files), dest)
            return len(files)
        last = res.output[-300:]
        log.warning("rclone attempt %d failed (rc=%s)", attempt, res.rc)
        if attempt == 1:
            jitter_sleep(10, 30)
    raise UploadError(f"rclone move failed: {last}")


# =========================================================================== #
# Orchestrator
# =========================================================================== #
@dataclass
class ProfileResult:
    user: str
    status: str = "pending"          # complete | partial | failed | unavailable | skipped
    new_reels: int = 0
    tiers: list[str] = field(default_factory=list)
    final_tier: str = ""
    note: str = ""


class Orchestrator:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.rt = Runtime(cfg.deadline_min * 60)
        self.state = StateStore(cfg.state_dir)
        self.cookies = CookieBundle()
        self.breaker: collections.Counter[str] = collections.Counter()
        self.results: list[ProfileResult] = []

    # ---- setup -------------------------------------------------------------
    def tier_plan(self) -> list[str]:
        f = self.cfg.force_tier
        if f in ("auto", ""):
            return list(TIER_ORDER)
        if f == "4":
            return ["4a", "4b"]
        if f in ALL_TIERS:
            return [f]
        raise SystemExit(f"invalid force_tier {f!r}")

    def preflight(self) -> None:
        gh_group("Preflight")
        try:
            self.cfg.staging.mkdir(parents=True, exist_ok=True)
            self.cfg.work_dir.mkdir(parents=True, exist_ok=True)
            for s in (self.cfg.rapidapi_key, self.cfg.apify_token):
                register_secret(s)
            register_secret(self.cfg.session_secret)
            self.cookies = build_cookie_bundle(self.cfg)
            log.info("targets: %d | tiers: %s | session cookie: %s | api keys: %s",
                     len(self.cfg.targets), ",".join(self.tier_plan()),
                     "yes" if self.cookies.present else "NO",
                     "yes" if (self.cfg.rapidapi_key or self.cfg.apify_token) else "no")
            for tool in ("rclone",):
                if not shutil.which(tool):
                    raise SystemExit(f"required tool missing: {tool}")
            res = run_cmd(["rclone", "mkdir", self.cfg.remote], timeout=120, rt=self.rt, tag="rclone-preflight")
            if res.rc != 0:
                log.error("cannot reach %s - check RCLONE_CONFIG_DATA / remote name / Drive auth", self.cfg.remote)
                raise SystemExit(2)
            log.info("Google Drive destination reachable: %s", self.cfg.remote)
        finally:
            gh_endgroup()

    def order_targets(self) -> list[str]:
        """Least-recently-successful first, so a deadline cut never starves the same profiles."""
        prof = self.state.load_run_state().get("profiles", {})
        return sorted(self.cfg.targets, key=lambda u: prof.get(u, {}).get("last_success") or "")

    # ---- main loop ---------------------------------------------------------
    def run(self) -> int:
        self.rt.install_signal_handlers()
        self.preflight()
        if self.cfg.dry_run:
            log.info("dry run: configuration valid, exiting before any scraping")
            return 0

        targets = self.order_targets()
        for idx, user in enumerate(targets):
            if self.rt.should_stop() or self.rt.left() < self.cfg.upload_reserve_s + 120:
                for rest in targets[idx:]:
                    self.results.append(ProfileResult(rest, "skipped", note="deadline reached - will run next time"))
                log.warning("time budget exhausted; %d profile(s) deferred to the next run", len(targets) - idx)
                break
            self.results.append(self.process_profile(user))
            if idx < len(targets) - 1 and not self.rt.should_stop():
                pause = jitter_sleep(*self.cfg.delay_profile, self.rt.stop)
                log.info("randomised cool-down between profiles: %.0fs", pause)
        return self.finish()

    def process_profile(self, user: str) -> ProfileResult:
        pr = ProfileResult(user)
        gh_group(f"@{user}")
        staging = self.cfg.staging / user
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        self.state.begin()
        ctx = Ctx(self.cfg, self.rt, self.state, self.cookies, user, staging, committed=self.state.archived())
        completed = unavailable = False

        try:
            for tid in self.tier_plan():
                tier = ALL_TIERS[tid]
                if self.rt.should_stop():
                    pr.note = "stopped before all tiers ran"
                    break
                reason = tier.skip_reason(ctx)
                if reason is None and self.breaker[tid] >= self.cfg.breaker_threshold:
                    reason = f"circuit breaker open ({self.breaker[tid]} consecutive blocks)"
                if reason is None and ctx.tier_timeout() < 60:
                    reason = "not enough time left"
                if reason:
                    log.info("tier %s skipped: %s", tid, reason)
                    pr.tiers.append(f"{tid}:skipped")
                    continue

                log.info("=== tier %s: %s ===", tid, tier.label)
                try:
                    outcome = tier.run(ctx)
                except Exception as exc:  # noqa: BLE001 - a tier crash must never stop the cascade
                    log.exception("tier %s crashed", tid)
                    outcome = TierOutcome(Status.FAILED, f"{type(exc).__name__}: {exc}"[:200])
                staged = reconcile(ctx)
                log.info("tier %s -> %s %s | staged files: %d", tid, outcome.status.value, outcome.detail, len(staged))
                pr.tiers.append(f"{tid}:{outcome.status.value}")

                if outcome.status is Status.BLOCKED:
                    self.breaker[tid] += 1
                elif outcome.status is Status.OK:
                    self.breaker[tid] = 0

                if outcome.status is Status.OK:
                    completed, pr.final_tier = True, tid
                    break
                if outcome.status is Status.UNAVAILABLE:
                    unavailable, pr.note = True, outcome.detail
                    break
                if outcome.status is Status.TIMEOUT and self.rt.should_stop():
                    break
                pr.note = f"tier {tid}: {outcome.detail}"
                if not self.rt.should_stop():
                    jitter_sleep(*self.cfg.delay_tier, self.rt.stop)
        finally:
            reconcile(ctx)

        # ---- upload & commit/rollback ---------------------------------------
        try:
            moved = upload_profile(self.cfg, self.rt, user, staging)
            self.state.commit()
            pr.new_reels = moved
            if unavailable:
                pr.status = "unavailable"
            elif completed:
                pr.status = "complete"
            else:
                pr.status = "partial" if moved else ("skipped" if self.rt.should_stop() else "failed")
        except UploadError as exc:
            log.error("%s", exc)
            self.state.rollback()
            pr.status, pr.note, pr.new_reels = "failed", f"upload failed - state rolled back ({exc})"[:300], 0
        finally:
            shutil.rmtree(staging, ignore_errors=True)    # runner disk wiped clean
            self.update_run_state(pr)
            gh_endgroup()
        log.info("@%s => %s, %d new reel(s) uploaded", user, pr.status, pr.new_reels)
        return pr

    # ---- bookkeeping ---------------------------------------------------------
    def update_run_state(self, pr: ProfileResult) -> None:
        data = self.state.load_run_state()
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        p = data.setdefault("profiles", {}).setdefault(pr.user, {"total_reels": 0})
        p.update(last_attempt=now, last_status=pr.status, last_tiers=pr.tiers)
        if pr.status == "complete":
            p["last_success"] = now
            p["last_tier"] = pr.final_tier
        p["total_reels"] = p.get("total_reels", 0) + pr.new_reels
        self.state.save_run_state(data)

    def finish(self) -> int:
        data = self.state.load_run_state()
        total = sum(r.new_reels for r in self.results)
        failed = [r for r in self.results if r.status == "failed"]
        incomplete = any(r.status in ("skipped", "partial") for r in self.results)
        data.setdefault("runs", []).append({
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "profiles": len(self.results), "new_reels": total, "failed": len(failed),
            "elapsed_min": round((time.monotonic() - self.rt.t0) / 60, 1),
        })
        data["runs"] = data["runs"][-30:]
        self.state.save_run_state(data)
        self.state.export_artifact(self.cfg.artifact_dir)
        self.write_summary(total)
        self.write_outputs(total, len(failed), incomplete)
        self.cleanup_sensitive()
        log.info("DONE: %d profile(s), %d new reel(s), %d failed, %.1f min", len(self.results), total, len(failed),
                 (time.monotonic() - self.rt.t0) / 60)
        return 1 if failed else 0

    def write_summary(self, total: int) -> None:
        rows = ["| Profile | Status | New reels | Tiers tried | Note |", "|---|---|---:|---|---|"]
        for r in self.results:
            rows.append(f"| @{r.user} | {r.status} | {r.new_reels} | {' → '.join(r.tiers) or '-'} | {r.note.replace('|', '/')[:120]} |")
        md = f"## Instagram Reels run\n\n**{total}** new reel(s) uploaded to `{self.cfg.remote}`.\n\n" + "\n".join(rows) + "\n"
        (self.cfg.artifact_dir / "run_summary.md").write_text(md)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a") as fh:
                fh.write(md)

    def write_outputs(self, total: int, failed: int, incomplete: bool) -> None:
        path = os.environ.get("GITHUB_OUTPUT")
        if path:
            with open(path, "a") as fh:
                fh.write(f"new_reels={total}\nfailed={failed}\nincomplete={str(incomplete).lower()}\n")

    def cleanup_sensitive(self) -> None:
        shutil.rmtree(self.cfg.staging, ignore_errors=True)
        if self.cookies.netscape_path:
            self.cookies.netscape_path.unlink(missing_ok=True)
        (self.cfg.work_dir / "gallery-dl.json").unlink(missing_ok=True)


# =========================================================================== #
# CLI
# =========================================================================== #
def load_targets(inline: str, file: Optional[Path]) -> list[str]:
    raw: list[str] = []
    if inline.strip():
        raw = re.split(r"[,\s]+", inline.strip())
    elif file and file.exists():
        for line in file.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                raw.append(line)
    out, seen = [], set()
    for item in raw:
        user = normalize_username(item)
        if not user:
            log.warning("ignoring invalid target %r", item[:40])
        elif user not in seen:
            seen.add(user)
            out.append(user)
    return out


def parse_args(argv: Optional[list[str]] = None) -> Config:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", default=os.environ.get("INPUT_USERNAMES", ""), help="comma/space separated usernames (overrides file)")
    ap.add_argument("--targets-file", type=Path, default=Path("targets.txt"))
    ap.add_argument("--force-tier", default=os.environ.get("INPUT_FORCE_TIER", "auto") or "auto",
                    choices=["auto", "1", "2", "3", "4", "4a", "4b"])
    ap.add_argument("--max-reels", type=int, default=int(os.environ.get("INPUT_MAX_REELS", "0") or 0))
    ap.add_argument("--staging", type=Path, default=Path("/tmp/ig_staging"))
    ap.add_argument("--state-dir", type=Path, default=Path("state"))
    ap.add_argument("--artifact-dir", type=Path, default=Path("state_artifact"))
    ap.add_argument("--remote", default=os.environ.get("RCLONE_REMOTE_PATH", "gdrive:Instagram_Reels"))
    ap.add_argument("--deadline-min", type=float, default=335.0, help="soft deadline for the whole run")
    ap.add_argument("--tier-timeout-min", type=float, default=45.0)
    ap.add_argument("--delay-profile", default="30,90", help="min,max seconds between profiles")
    ap.add_argument("--delay-tier", default="5,15", help="min,max seconds between tiers")
    ap.add_argument("--ytdlp-workers", type=int, default=3)
    ap.add_argument("--restore-from", type=Path, help="directory of a downloaded artifact to seed missing state from")
    ap.add_argument("--dry-run", action="store_true", default=os.environ.get("INPUT_DRY_RUN", "").lower() == "true")
    a = ap.parse_args(argv)

    def pair(s: str) -> tuple[float, float]:
        lo, hi = (float(x) for x in s.split(","))
        return lo, hi

    cfg = Config(
        targets=load_targets(a.targets, a.targets_file),
        force_tier=a.force_tier, max_reels=max(0, a.max_reels), staging=a.staging, state_dir=a.state_dir,
        artifact_dir=a.artifact_dir, remote=a.remote, deadline_min=a.deadline_min, tier_timeout_min=a.tier_timeout_min,
        delay_profile=pair(a.delay_profile), delay_tier=pair(a.delay_tier), ytdlp_workers=a.ytdlp_workers,
        dry_run=a.dry_run,
        ig_username=os.environ.get("INSTAGRAM_USERNAME", "").strip().lstrip("@"),
        session_secret=os.environ.get("INSTAGRAM_SESSION_COOKIE", ""),
        rapidapi_key=os.environ.get("RAPIDAPI_KEY", "").strip(),
        apify_token=os.environ.get("APIFY_TOKEN", "").strip(),
    )
    if a.restore_from:
        n = StateStore(cfg.state_dir).restore_from(a.restore_from)
        log.info("restored %d state file(s) from %s", n, a.restore_from)
    return cfg


def main(argv: Optional[list[str]] = None) -> int:
    cfg = parse_args(argv)
    if not cfg.targets:
        log.error("no valid targets: pass instagram_username input or fill targets.txt")
        return 2
    try:
        return Orchestrator(cfg).run()
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2


if __name__ == "__main__":
    sys.exit(main())
