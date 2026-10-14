"""A fake Instagram / Drive / Google / Cloudinary / YouTube / Telegram on localhost, so the whole worker can be tested
end to end without touching any real account."""
import os, re, json, sys, shutil, subprocess, tempfile, threading, unittest, datetime, hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reelio import util
from reelio.store import Store
from reelio import engine as engine_mod

util.sleep = lambda s: None          # tests never really wait


def make_video(path, secs=5, w=640, h=360, audio=True):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=25"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440"]
    cmd += ["-t", str(secs), "-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac"] if audio else []) + [path]
    subprocess.run(cmd, check=True)
    return open(path, "rb").read()


class World:
    """All fake-server state + knobs for failure injection."""
    def __init__(self):
        self.drive = {}            # file id -> {name, bytes, created, md5}
        self.cdn = {}              # cloudinary public_id -> bytes
        self.ig_posts = []         # published
        self.ig_containers = {}    # cid -> dict
        self.ig_accounts = {"IGTOKA": "111", "IGTOKB": "222"}
        self.rate_limited_tokens = set()
        self.expired_tokens = set()
        self.bad_names = set()     # captions/urls containing this id make container ERROR
        self.fail_container_always = False
        self.yt_uploads = []
        self.yt_limit = False
        self.telegram = []
        self.calls = []
        self.fetched_urls = []
        self.status_polls = {}
        self.refresh_calls = 0
        self.publish_hook = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    W = None

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def _params(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ct = self.headers.get("Content-Type", "")
        form = {}
        if "x-www-form-urlencoded" in ct: form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        elif "multipart" in ct: form = {"_raw": raw, "_ct": ct}
        return u.path, q, form, raw

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PUT(self): self.route("PUT")
    def do_DELETE(self): self.route("DELETE")

    def route(self, m):
        W = self.W; path, q, form, raw = self._params()
        W.calls.append((m, path))
        p = {**q, **{k: v for k, v in form.items() if not k.startswith("_")}}
        # ---------------- Instagram
        if re.match(r"^/v21\.0/", path) or path == "/refresh_access_token":
            return self.instagram(m, path, p)
        if path == "/refresh_access_token":
            return self.instagram(m, path, p)
        # ---------------- Cloudinary
        mm = re.match(r"^/v1_1/([\w-]+)/video/(upload|destroy)$", path)
        if mm:
            return self.cloudinary(m, mm[2], form, raw)
        if re.match(r"^/v1_1/[\w-]+/resources/video/upload$", path):
            return self._send(200, {"resources": [{"public_id": k, "created_at": "2020-01-01T00:00:00Z"} for k in W.cdn]})
        if path.startswith("/cdn/"):
            pid = path[5:].rsplit(".", 1)[0]
            W.fetched_urls.append(pid)
            data = W.cdn.get(pid)
            return self._send(200 if data else 404, data or b"", "video/mp4")
        # ---------------- Google / Drive
        if path == "/token":
            return self._send(200, {"access_token": "gtoken", "expires_in": 3600}) if p.get("refresh_token") == "RT" else self._send(400, {"error": "invalid_grant"})
        if path == "/drive/v3/files":
            files = [{"id": i, "name": f["name"], "mimeType": "video/mp4", "createdTime": f["created"], "size": str(len(f["bytes"])), "md5Checksum": f["md5"]} for i, f in W.drive.items()]
            return self._send(200, {"files": files})
        mm = re.match(r"^/drive/v3/files/([\w-]+)$", path)
        if mm and mm[1] in W.drive:
            return self._send(200, W.drive[mm[1]]["bytes"], "video/mp4")
        # ---------------- YouTube
        if path == "/upload/youtube/v3/videos" and m == "POST":
            if W.yt_limit:
                return self._send(403, {"error": {"message": "limit", "errors": [{"reason": "uploadLimitExceeded"}]}})
            W.yt_uploads.append({"meta": json.loads(raw)})
            return self._send(200, b"", headers={"Location": f"http://{self.headers['Host']}/yt-session/{len(W.yt_uploads) - 1}"})
        mm = re.match(r"^/yt-session/(\d+)$", path)
        if mm and m == "PUT":
            idx = int(mm[1])
            if self.headers.get("Content-Range"):
                return self._send(308)
            W.yt_uploads[idx]["size"] = len(raw); W.yt_uploads[idx]["id"] = f"YT{idx}"
            return self._send(200, {"id": f"YT{idx}"})
        if path == "/youtube/v3/channels":
            return self._send(200, {"items": [{"snippet": {"title": "Test Channel"}, "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}}]})
        if path == "/youtube/v3/playlistItems":
            return self._send(200, {"items": []})
        # ---------------- Telegram
        mm = re.match(r"^/bot([^/]+)/sendMessage$", path)
        if mm:
            W.telegram.append(p.get("text")); return self._send(200, {"ok": True})
        if re.match(r"^/bot[^/]+/getMe$", path):
            return self._send(200, {"ok": True})
        self._send(404, {"error": f"mock has no route {m} {path}"})

    def cloudinary(self, m, what, form, raw):
        W = self.W
        raw_form = raw
        if what == "upload":
            ct = form["_ct"]; boundary = ct.split("boundary=")[1].encode()
            fields, filedata = {}, b""
            for part in raw.split(b"--" + boundary):
                if b"Content-Disposition" not in part: continue
                head, _, body = part.partition(b"\r\n\r\n"); body = body.rsplit(b"\r\n", 1)[0]
                nm = re.search(rb'name="([^"]+)"', head)[1].decode()
                if b'filename="' in head: filedata = body
                else: fields[nm] = body.decode()
            pid = fields["public_id"]
            W.cdn[pid] = filedata
            return self._send(200, {"secure_url": f"http://{self.headers['Host']}/cdn/{pid}.mp4", "public_id": pid})
        d = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        W.cdn.pop(d.get("public_id"), None)
        return self._send(200, {"result": "ok"})

    def instagram(self, m, path, p):
        W = self.W
        tok = p.get("access_token", "")
        if tok in W.expired_tokens:
            return self._send(400, {"error": {"message": "Error validating access token: Session has expired", "code": 190}})
        uid = W.ig_accounts.get(tok)
        if not uid:
            return self._send(400, {"error": {"message": "Invalid OAuth access token", "code": 190}})
        if path == "/refresh_access_token":
            W.refresh_calls += 1
            return self._send(200, {"access_token": tok, "expires_in": 5184000})
        if tok in W.rate_limited_tokens and not path.endswith("/me"):
            return self._send(400, {"error": {"message": "Application request limit reached", "code": 4, "error_subcode": 1349210, "is_transient": True}})
        path = path[len("/v21.0"):]
        if path == "/me":
            return self._send(200, {"user_id": uid, "username": "acct" + uid, "account_type": "MEDIA_CREATOR", "media_count": 3})
        if path.endswith("/content_publishing_limit"):
            used = sum(1 for x in W.ig_posts if x["uid"] == uid)
            return self._send(200, {"data": [{"quota_usage": used, "config": {"quota_total": 100}}]})
        if path == f"/{uid}/media" and m == "POST":
            url = p.get("video_url", "")
            c = f"C{len(W.ig_containers) + 1}"
            data = None
            try:
                import requests
                r = requests.get(url, headers={"Range": "bytes=0-99"}, timeout=10)
                data = r.status_code in (200, 206) and len(r.content) > 0
            except Exception:
                data = False
            W.ig_containers[c] = {"uid": uid, "url": url, "caption": p.get("caption"), "ok": bool(data), "polls": 0, "published": False, "thumb_offset": p.get("thumb_offset")}
            return self._send(200, {"id": c})
        if path == f"/{uid}/media" and m == "GET":
            return self._send(200, {"data": [{"id": x["id"], "caption": x["caption"], "timestamp": x["at"], "permalink": x["link"], "media_type": "VIDEO", "like_count": 5, "comments_count": 1} for x in W.ig_posts if x["uid"] == uid]})
        if path == f"/{uid}/media_publish":
            c = W.ig_containers.get(p.get("creation_id"))
            if not c or c["published"]:
                return self._send(400, {"error": {"message": "Media ID is not available", "code": 9007, "error_subcode": 2207027}})
            if W.publish_hook: W.publish_hook(c)
            c["published"] = True
            mid = f"M{len(W.ig_posts) + 1}"
            W.ig_posts.append({"id": mid, "uid": uid, "caption": c["caption"], "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000"), "link": f"https://instagram.com/reel/{mid}", "url": c["url"]})
            return self._send(200, {"id": mid})
        mm = re.match(r"^/(C\d+)$", path)
        if mm:
            c = W.ig_containers[mm[1]]; c["polls"] += 1
            if W.fail_container_always or not c["ok"] or any(b in (c["caption"] or "") for b in W.bad_names):
                return self._send(200, {"status_code": "ERROR", "status": "Error: Media upload has failed with error code 2207026"})
            return self._send(200, {"status_code": "FINISHED" if c["polls"] >= 2 else "IN_PROGRESS"})
        mm = re.match(r"^/(M\d+)/insights$", path)
        if mm:
            return self._send(200, {"data": [{"name": n, "values": [{"value": v}]} for n, v in (("reach", 120), ("likes", 9), ("comments", 2), ("shares", 1), ("saved", 3), ("views", 400))]})
        mm = re.match(r"^/(M\d+)$", path)
        if mm:
            x = next(x for x in W.ig_posts if x["id"] == mm[1])
            return self._send(200, {"permalink": x["link"]})
        self._send(404, {"error": {"message": f"mock IG has no {path}"}})


class MockBase(unittest.TestCase):
    """Starts the fake services, builds a data folder, and offers helpers to add routes."""
    @classmethod
    def setUpClass(cls):
        cls.W = World(); H = type("H", (Handler,), {"W": cls.W})
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        os.environ.update({"IG_GRAPH": cls.base, "DRIVE_BASE": cls.base, "CLOUDINARY_BASE": cls.base, "GOOGLE_TOKEN_URL": cls.base + "/token",
                           "YT_API": cls.base + "/youtube/v3", "YT_UPLOAD": cls.base + "/upload/youtube/v3", "TELEGRAM_BASE": cls.base,
                           "REELIO_NO_GIT": "1", "REELIO_KEY": "test-pass"})
        cls.tmp = tempfile.mkdtemp(prefix="reelio_test_")
        cls.vid = os.path.join(cls.tmp, "v.mp4"); cls.vbytes = make_video(cls.vid)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def at(self, hh, mm=0):
        """pin the clock to today at hh:mm UTC (all code under test sees this time)"""
        t = datetime.datetime.now(datetime.timezone.utc).replace(hour=hh, minute=mm, second=0, microsecond=0)
        util.set_clock(lambda: t)

    def tearDown(self):
        util.set_clock(None)

    def setUp(self):
        self.at(23, 30)
        W = self.W
        W.__init__()
        self.data = tempfile.mkdtemp(prefix="data_", dir=self.tmp)
        self.store = None

    # ----- builders
    def add_drive(self, n, prefix="clip", dup_of=None):
        for i in range(n):
            b = self.vbytes + f"-{prefix}{i}".encode()      # distinct content -> distinct md5
            fid = f"{prefix}{i}"
            self.W.drive[fid] = {"name": f"{fid}.mp4", "bytes": b, "created": f"2026-01-{i + 1:02d}T00:00:00Z", "md5": hashlib.md5(b).hexdigest()}

    def base_config(self, **over):
        cfg = {"version": 1, "timezone": "UTC", "paused": False,
               "connections": [
                   {"id": "ig_a", "kind": "instagram", "label": "Account A", "ig_user_id": "111"},
                   {"id": "cld", "kind": "cloudinary", "label": "Cloudinary"},
                   {"id": "google", "kind": "google", "label": "Google"},
                   {"id": "telegram", "kind": "telegram", "label": "Telegram"}],
               "notify": {"telegram": {"enabled": True, "conn": "telegram", "events": {"posted": False, "failed": True, "limit": True, "token": True, "daily": False}}},
               "routes": [self.route()]}
        cfg.update(over)
        return cfg

    def route(self, id="r1", conn="ig_a", **kw):
        r = {"id": id, "name": "Drive to Instagram", "enabled": True,
             "source": {"type": "drive", "conn": "google", "folders": ["FOLDER1"]},
             "target": {"type": "instagram", "conn": conn},
             "schedule": {"per_day": 50, "start": "00:00", "end": "23:59", "jitter": 0, "max_per_run": 20, "gap_seconds": 60, "scan_every_min": 30},
             "caption": {"mode": "same", "text": "Hello reel"}, "edit": {"filter": "golden", "fit": "keep"}, "order": "oldest"}
        r.update(kw); return r

    def write_env(self, cfg=None, secrets=None):
        from reelio import crypto
        util.write_json(os.path.join(self.data, "config.json"), cfg or self.base_config())
        sec = {"ig_a": {"access_token": "IGTOKA", "refreshed_at": util.iso()}, "cld": {"cloud_name": "demo", "api_key": "k", "api_secret": "s"},
               "google": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}, "telegram": {"bot_token": "TG", "chat_id": "1"}}
        sec.update(secrets or {})
        util.write_json(os.path.join(self.data, "secrets.enc.json"), crypto.encrypt(sec, "test-pass", iters=1000))

    def engine(self, **kw):
        self.store = Store(self.data)
        kw.setdefault("budget_min", 300)
        return engine_mod.Engine(self.store, **kw)

    def run_engine(self, **kw):
        e = self.engine(**kw); e.run(); return e

    def queue(self, rid="r1"):
        return Store(self.data).queue(rid)

    def ledger(self):
        return util.read_json(os.path.join(self.data, "ledger.json"), {"entries": []})
