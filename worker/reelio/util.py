"""Small shared helpers: time, sleeping, safe JSON, logging with secret scrubbing, HTTP with retries."""
import os, json, time, re, datetime, tempfile, threading
import requests

UTC = datetime.timezone.utc
_SECRETS = set()          # every secret value seen this run; scrubbed from all logs / errors / UI text
_lock = threading.Lock()


def register_secret(v):
    if isinstance(v, str) and len(v) >= 6:
        _SECRETS.add(v)


def scrub(text):
    s = str(text)
    for v in sorted(_SECRETS, key=len, reverse=True):
        s = s.replace(v, "***")
    s = re.sub(r"(access_token|api_secret|client_secret|refresh_token|signature)=([^&\s\"']+)", r"\1=***", s)
    s = re.sub(r"\bIGA[A-Za-z0-9_-]{20,}", "IGA***", s)
    s = re.sub(r"\bEAA[A-Za-z0-9_-]{20,}", "EAA***", s)
    return s


_CLOCK = None          # tests can pin the time with set_clock(lambda: some_datetime)


def set_clock(fn):
    global _CLOCK
    _CLOCK = fn


def now():
    return _CLOCK() if _CLOCK else datetime.datetime.now(UTC)


def iso(dt=None):
    return (dt or now()).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def sleep(sec):
    """All waiting goes through here so tests can make it instant."""
    if sec > 0:
        time.sleep(sec)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:   # corrupt file: keep a copy, never crash the whole run
        try:
            os.replace(path, path + ".corrupt")
        except Exception:
            pass
        print(f"warning: {path} was not valid JSON ({e}); saved as .corrupt and using defaults")
        return default


def write_json(path, data):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def say(*a):
    print(scrub(" ".join(str(x) for x in a)), flush=True)


class HttpFail(Exception):
    """Network-level failure after retries (timeouts, DNS, 5xx)."""


def http(method, url, retries=3, timeout=(15, 90), **kw):
    """requests with timeout + backoff on network errors / 5xx / 429. Returns the Response (4xx returned as-is for callers to classify)."""
    last = None
    for i in range(retries):
        try:
            r = requests.request(method, url, timeout=timeout, **kw)
            if r.status_code >= 500 or r.status_code == 429:
                last = f"HTTP {r.status_code}"
                if i < retries - 1:
                    sleep(2 * (i + 1) ** 2)
                    continue
            return r
        except requests.RequestException as e:
            last = scrub(e)
            if i < retries - 1:
                sleep(2 * (i + 1) ** 2)
    raise HttpFail(f"network problem calling {scrub(url).split('?')[0]}: {last}")


def env_base(name, default):
    return os.environ.get(name, default).rstrip("/")
