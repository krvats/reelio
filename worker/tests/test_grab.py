"""Save to Drive: YouTube video, playlist, channel, Instagram (own account), dedupe, resume, isolation of failures.
Everything runs against a fake Google Drive / Instagram / yt-dlp on localhost: nothing real is touched."""
import os, re, sys, json, shutil, tempfile, threading, unittest, datetime, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from helpers import make_video
from reelio import util, grab, crypto
from reelio.store import Store

PAD = os.urandom(600_000)


class W:
    def reset(self):
        self.files = {}          # id -> {name, parent, props, bytes}
        self.folders = {}        # id -> {name, parent}
        self.sessions = {}
        self.n = 0
        self.fail_chunk = False
        self.full = False
        self.noscope = False
        self.video = b""
        self.ig_videos = []      # [{"id","caption","url"}]
        self.calls = []


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    w = None

    def log_message(self, *a): pass

    def _send(self, code, body=b"", headers=None, ctype="application/json"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def _go(self, m):
        w = self.w; u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}; path = u.path
        n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n) if n else b""
        w.calls.append((m, path))
        if path == "/token":
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            return self._send(200, {"access_token": "gtok", "expires_in": 3600}) if form.get("refresh_token") == "RT" else self._send(400, {"error": "invalid_grant"})
        if path.startswith("/cdn/"):
            vid = path[5:].split(".")[0]
            return self._send(200, w.video, ctype="video/mp4") if any(v["id"] == vid for v in w.ig_videos) else self._send(404)
        if path.startswith("/v21.0/"):
            rest = path[len("/v21.0/"):]
            if rest == "111/media":
                return self._send(200, {"data": [{"id": v["id"], "media_type": "VIDEO", "media_url": f"http://{self.headers['Host']}/cdn/{v['id']}.mp4",
                                                  "caption": v["caption"], "timestamp": "2026-03-04T10:00:00+0000"} for v in w.ig_videos]})
            v = next((x for x in w.ig_videos if x["id"] == rest), None)
            if v:
                return self._send(200, {"media_url": f"http://{self.headers['Host']}/cdn/{v['id']}.mp4", "caption": v["caption"], "timestamp": "2026-03-04T10:00:00+0000",
                                        "permalink": f"https://instagram.com/reel/{v['id']}", "username": "mypage"})
            return self._send(404, {"error": {"message": "nope"}})
        # ---- Drive
        if w.noscope and path.startswith(("/drive/", "/upload/")):
            return self._send(403, {"error": {"message": "Request had insufficient authentication scopes.", "errors": [{"reason": "insufficientPermissions"}]}})
        if path == "/drive/v3/files" and m == "GET":
            qs = unquote(q.get("q", ""))
            res = []
            mm = re.search(r"name='((?:[^'\\]|\\.)*)' and '([^']+)' in parents", qs)
            if "mimeType='application/vnd.google-apps.folder'" in qs and mm:
                name = mm[1].replace("\\'", "'"); par = mm[2]
                res = [{"id": i, "name": f["name"]} for i, f in w.folders.items() if f["name"] == name and f["parent"] == par]
            mm = re.search(r"value='([^']+)' \} and '([^']+)' in parents", qs)
            if "appProperties" in qs and mm:
                res = [{"id": i, "name": f["name"]} for i, f in w.files.items() if f["props"].get("srcId") == mm[1] and f["parent"] == mm[2]]
            return self._send(200, {"files": res})
        if path == "/drive/v3/files" and m == "POST":
            body = json.loads(raw); w.n += 1; fid = f"F{w.n}"
            w.folders[fid] = {"name": body["name"], "parent": body["parents"][0]}
            return self._send(200, {"id": fid})
        mm = re.match(r"^/drive/v3/files/(\w+)$", path)
        if mm:
            return self._send(200, {"id": mm[1], "mimeType": "application/vnd.google-apps.folder", "trashed": False}) if mm[1] in w.folders else self._send(404, {"error": {"message": "not found"}})
        if path == "/upload/drive/v3/files" and m == "POST":
            if w.full:
                return self._send(403, {"error": {"message": "The user's Drive storage quota has been exceeded.", "errors": [{"reason": "storageQuotaExceeded"}]}})
            body = json.loads(raw); w.n += 1; sid = f"S{w.n}"
            w.sessions[sid] = {"name": body["name"], "parent": body["parents"][0], "props": body.get("appProperties", {}), "buf": b""}
            return self._send(200, b"", {"Location": f"http://{self.headers['Host']}/session/{sid}"})
        mm = re.match(r"^/session/(\w+)$", path)
        if mm and m == "PUT":
            s = w.sessions[mm[1]]; cr = self.headers.get("Content-Range", "")
            if cr.startswith("bytes */"):
                got = len(s["buf"]); return self._send(308, b"", {"Range": f"bytes=0-{got - 1}"} if got else {})
            a, b, total = (int(x) for x in re.match(r"bytes (\d+)-(\d+)/(\d+)", cr).groups())
            if w.fail_chunk and a > 0:
                w.fail_chunk = False
                return self._send(503)
            if a == len(s["buf"]):
                s["buf"] += raw
            if len(s["buf"]) >= total:
                w.n += 1; fid = f"D{w.n}"
                w.files[fid] = {"name": s["name"], "parent": s["parent"], "props": s["props"], "bytes": s["buf"]}
                return self._send(200, {"id": fid})
            return self._send(308, b"", {"Range": f"bytes=0-{len(s['buf']) - 1}"})
        self._send(404, {"error": {"message": f"fake has no {m} {path}"}})

    def do_GET(self): self._go("GET")
    def do_POST(self): self._go("POST")
    def do_PUT(self): self._go("PUT")


class SaveToDrive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = W(); cls.w.reset()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), type("HH", (H,), {"w": cls.w}))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.tmp = tempfile.mkdtemp(prefix="grab_test_")
        cls.plain = os.path.join(cls.tmp, "plain.mp4"); cls.plain_bytes = make_video(cls.plain)
        cls.big = os.path.join(cls.tmp, "big.mp4")
        with open(cls.big, "wb") as f:
            f.write(cls.plain_bytes + PAD)
        cls.saved_env = {k: os.environ.get(k) for k in ("DRIVE_API", "DRIVE_UPLOAD", "IG_GRAPH", "GOOGLE_TOKEN_URL", "REELIO_NO_GIT", "REELIO_KEY", "REELIO_YTDLP", "REELIO_DRIVE_CHUNK", "FAKE_BAD", "FAKE_MODE")}
        os.environ.update({"DRIVE_API": cls.base + "/drive/v3", "DRIVE_UPLOAD": cls.base + "/upload/drive/v3", "IG_GRAPH": cls.base,
                           "GOOGLE_TOKEN_URL": cls.base + "/token", "REELIO_NO_GIT": "1", "REELIO_KEY": "test-pass", "REELIO_DRIVE_CHUNK": "262144"})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)
        for k, v in cls.saved_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def setUp(self):
        self.w.reset(); self.w.video = self.plain_bytes
        self.t0 = datetime.datetime.now(datetime.timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        util.set_clock(lambda: self.t0)
        os.environ.pop("FAKE_BAD", None); os.environ.pop("FAKE_MODE", None); os.environ.pop("FAKE_EXTRA", None)
        self.data = tempfile.mkdtemp(prefix="data_", dir=self.tmp)
        self.log = os.path.join(self.data, "..", f"calls_{os.path.basename(self.data)}.txt")
        cfg = {"version": 1, "timezone": "UTC", "paused": False, "routes": [],
               "connections": [{"id": "google", "kind": "google", "label": "Google"}, {"id": "ig_a", "kind": "instagram", "label": "mypage", "ig_user_id": "111"}]}
        util.write_json(os.path.join(self.data, "config.json"), cfg)
        sec = {"google": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}, "ig_a": {"access_token": "IGTOKA"}}
        util.write_json(os.path.join(self.data, "secrets.enc.json"), crypto.encrypt(sec, "test-pass", iters=1000))
        self.fake_ytdlp()

    def tearDown(self):
        util.set_clock(None)

    # ---- fakes
    def fake_ytdlp(self, video=None):
        p = os.path.join(self.tmp, f"fake_{os.path.basename(self.data)}.py")
        open(p, "w").write(f'''
import sys, json, shutil, os
a = sys.argv[1:]
open({self.log!r}, "a").write(" ".join(a) + "\\n")
url = next((x for x in a if x.startswith("http")), "")
mode = os.environ.get("FAKE_MODE", "")
if "--flat-playlist" in a:
    if mode == "blocked":
        sys.stderr.write("ERROR: Sign in to confirm you're not a bot"); sys.exit(1)
    if mode == "igprofile" and "instagram.com" in url:
        sys.stderr.write("ERROR: [Instagram] someone: Unable to extract data; please report this issue"); sys.exit(1)
    rows = []
    if url.endswith("/shorts"):
        rows = [{{"id": "SHORT%06d" % i, "title": "Short %d" % i, "playlist_title": "Chan - Shorts", "url": "https://www.youtube.com/watch?v=SHORT%06d" % i}} for i in (1, 2)]
    elif "list=" in url or url.endswith("/videos"):
        rows = [{{"id": "VID%08d" % i, "title": "Clip %d" % i, "playlist_title": "My List", "url": "https://www.youtube.com/watch?v=VID%08d" % i}} for i in range(1, 4 + int(os.environ.get("FAKE_EXTRA", "0")))]
        rows.append({{"id": "LIVE0000001", "title": "Live", "playlist_title": "My List", "live_status": "is_upcoming"}})
    else:
        rows = [{{"id": "SINGLE00001", "title": "Single Title", "url": url}}]
    if "--playlist-end" in a:
        rows = rows[:int(a[a.index("--playlist-end") + 1])]
    for r in rows:
        print(json.dumps(r))
    sys.exit(0)
vid = url[-11:]
if mode == "blocked" or vid in os.environ.get("FAKE_BAD", ""):
    sys.stderr.write("ERROR: Sign in to confirm you're not a bot" if mode == "blocked" else "ERROR: Video unavailable. This video is private"); sys.exit(1)
out = a[a.index("-o") + 1]
d = os.path.dirname(out)
shutil.copy({video or self.big!r}, os.path.join(d, "v.mp4"))
json.dump({{"id": vid, "title": "Title of " + vid}}, open(os.path.join(d, "v.info.json"), "w"))
''')
        os.environ["REELIO_YTDLP"] = f"{sys.executable} {p}"

    def inbox(self, cmd, name="1.json"):
        if cmd.get("cmd") == "add":
            cmd = dict({"confirm": True}, **cmd)            # the app always sends the ownership tick; tests that leave it out say confirm=False
        os.makedirs(os.path.join(self.data, "grab-inbox"), exist_ok=True)
        json.dump(cmd, open(os.path.join(self.data, "grab-inbox", name), "w"))

    def run_grab(self, minutes=0):
        if minutes:
            self.t0 += datetime.timedelta(minutes=minutes)
        return grab.run(Store(self.data), 300)

    def jobs(self):
        return {j["id"]: j for j in grab.load_jobs(Store(self.data))}

    def calls(self):
        return open(self.log).read() if os.path.exists(self.log) else ""

    def folder_id(self, name, parent="root"):
        return next((i for i, f in self.w.folders.items() if f["name"] == name and f["parent"] == parent), None)

    # ---- tests
    def test_single_video_goes_to_main_folder_with_embedded_details(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"]})
        self.run_grab()
        root = self.folder_id("Reelio Downloads")
        self.assertTrue(root)
        self.assertEqual(len(self.w.files), 1)
        f = next(iter(self.w.files.values()))
        self.assertEqual((f["name"], f["parent"]), ("Title of SINGLE00001.mp4", root))
        self.assertEqual(f["props"]["srcId"], "yt:SINGLE00001")
        self.assertEqual(f["bytes"], self.plain_bytes + PAD)          # chunked upload arrived byte for byte
        c = self.calls()
        for flag in ("--embed-metadata", "--embed-thumbnail", "--embed-chapters", "--merge-output-format mp4"):
            self.assertIn(flag, c)
        job = next(iter(self.jobs().values()))
        self.assertEqual(job["status"], "done")
        self.assertTrue(job["items"][0]["url_drive"].startswith("https://drive.google.com/file/d/"))

    def test_playlist_makes_a_named_subfolder_and_skips_upcoming_lives(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]})
        self.run_grab()
        root = self.folder_id("Reelio Downloads"); sub = self.folder_id("My List", root)
        self.assertTrue(root and sub)
        self.assertEqual(sorted(f["name"] for f in self.w.files.values()), ["Title of VID00000001.mp4", "Title of VID00000002.mp4", "Title of VID00000003.mp4"])
        self.assertTrue(all(f["parent"] == sub for f in self.w.files.values()))
        # running again, or adding the same playlist again, never makes a second copy
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]})
        self.run_grab(minutes=70)
        self.assertEqual(len(self.w.files), 3)
        self.assertEqual(len([f for f in self.w.folders.values() if f["name"] == "My List"]), 1)

    def test_subfolders_can_be_turned_off(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"], "settings": {"subfolders": False, "root_name": "Vault"}})
        self.run_grab()
        root = self.folder_id("Vault")
        self.assertTrue(all(f["parent"] == root for f in self.w.files.values()))
        self.assertIsNone(self.folder_id("My List", root))

    def test_channel_link_lists_its_videos_tab(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/@somechannel"]})
        self.run_grab()
        self.assertIn("https://www.youtube.com/@somechannel/videos", self.calls())
        self.assertEqual(len(self.w.files), 3)

    def test_killed_upload_is_recovered_without_duplicates(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"]})
        self.run_grab()
        # pretend the run died right after the file reached Drive but before it was marked done
        path = os.path.join(self.data, "queues", "grab", next(iter(self.jobs())) + ".json")
        job = util.read_json(path); job["items"][0].update(status="uploading", drive_id="", url_drive=""); util.write_json(path, job)
        self.run_grab(minutes=70)
        self.assertEqual(len(self.w.files), 1)
        self.assertEqual(next(iter(self.jobs().values()))["status"], "done")

    def test_network_hiccup_mid_upload_resumes(self):
        self.w.fail_chunk = True
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"]})
        self.run_grab()
        self.assertEqual(len(self.w.files), 1)
        self.assertEqual(next(iter(self.w.files.values()))["bytes"], self.plain_bytes + PAD)

    def test_one_bad_video_never_stops_the_others(self):
        os.environ["FAKE_BAD"] = "VID00000002"
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]})
        self.run_grab()
        self.assertEqual(len(self.w.files), 2)
        job = next(iter(self.jobs().values()))
        bad = next(i for i in job["items"] if i["vid"] == "VID00000002")
        self.assertEqual((bad["status"], bad["fails"]), ("pending", 1))
        self.assertTrue(bad["last_error"]["fix"])
        for m in (30, 60, 120):                       # after 3 tries it is marked failed, and Retry brings it back
            self.run_grab(minutes=m)
        job = next(iter(self.jobs().values()))
        self.assertEqual(next(i for i in job["items"] if i["vid"] == "VID00000002")["status"], "failed")
        self.assertEqual(job["status"], "failed")
        os.environ.pop("FAKE_BAD")
        self.inbox({"cmd": "retry", "id": job["id"]})
        self.run_grab(minutes=5)
        self.assertEqual(len(self.w.files), 3)
        self.assertEqual(next(iter(self.jobs().values()))["status"], "done")

    def test_youtube_blocked_pauses_only_youtube_not_instagram(self):
        os.environ["FAKE_MODE"] = "blocked"
        self.w.ig_videos = [{"id": "9001", "caption": "My first reel\nline two", "url": ""}]
        self.w.video = self.plain_bytes
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"]}, "1.json")
        self.inbox({"cmd": "add_ig", "conn": "ig_a"}, "2.json")
        self.run_grab()
        st = util.read_json(os.path.join(self.data, "queues", "grab", "_state.json"))
        self.assertIn("yt", st["source_until"])
        self.assertNotIn("ig", st["source_until"])
        self.assertEqual(len(self.w.files), 1)                       # the Instagram video was saved
        ig = next(f for f in self.w.files.values())
        self.assertTrue(ig["name"].startswith("My first reel") and ig["name"].endswith("[9001].mp4"))
        yt_job = next(j for j in self.jobs().values() if j["kind"] == "yt")
        self.assertEqual(yt_job["items"][0]["status"], "pending")      # waiting, not failed
        self.assertEqual(yt_job["items"][0]["fails"], 0)

    def test_instagram_own_account_goes_to_its_own_subfolder_with_details_inside_the_file(self):
        self.w.ig_videos = [{"id": "9001", "caption": "Sunset vibes #golden", "url": ""}, {"id": "9002", "caption": "", "url": ""}]
        self.inbox({"cmd": "add_ig", "conn": "ig_a"})
        self.run_grab()
        root = self.folder_id("Reelio Downloads"); sub = self.folder_id("Instagram - mypage", root)
        self.assertTrue(sub)
        self.assertEqual(len(self.w.files), 2)
        self.assertTrue(all(f["parent"] == sub for f in self.w.files.values()))
        f = next(f for f in self.w.files.values() if f["props"]["srcId"] == "igown:9001")
        p = os.path.join(self.tmp, "check.mp4"); open(p, "wb").write(f["bytes"])
        tags = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", p], capture_output=True, text=True).stdout)["format"]["tags"]
        self.assertEqual(tags.get("title"), "Sunset vibes #golden")
        self.assertIn("Sunset vibes", tags.get("comment", ""))
        self.assertEqual(tags.get("date"), "20260304")

    def test_drive_full_pauses_that_login_and_loses_nothing(self):
        self.w.full = True
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]})
        self.run_grab()
        job = next(iter(self.jobs().values()))
        self.assertTrue(all(i["status"] == "pending" and i["fails"] == 0 for i in job["items"]))
        st = util.read_json(os.path.join(self.data, "queues", "grab", "_state.json"))
        self.assertIn("google", st["conn_until"])
        self.w.full = False
        self.run_grab(minutes=400)
        self.assertEqual(len(self.w.files), 3)

    def test_missing_drive_permission_gives_a_plain_fix(self):
        self.w.noscope = True
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"]})
        self.run_grab()
        ev = " ".join(e.get("fix", "") for e in Store(self.data).recent_events(20))
        self.assertIn("Reconnect", ev)
        self.assertEqual(len(self.w.files), 0)

    def test_the_separate_drive_login_is_used_when_the_app_does_not_name_one(self):
        cfg = util.read_json(os.path.join(self.data, "config.json"))
        cfg["connections"].append({"id": "gsave", "kind": "google_save", "label": "Drive saver", "drive_write": True}); util.write_json(os.path.join(self.data, "config.json"), cfg)
        sec = {"google": {"client_id": "c", "client_secret": "s", "refresh_token": "NOPE"}, "gsave": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}, "ig_a": {"access_token": "IGTOKA"}}
        util.write_json(os.path.join(self.data, "secrets.enc.json"), crypto.encrypt(sec, "test-pass", iters=1000))
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"]})
        self.run_grab()
        self.assertEqual(len(self.w.files), 1)
        self.assertEqual(next(iter(self.jobs().values()))["settings"]["conn"], "gsave")

    def test_links_that_are_not_youtube_or_instagram_are_skipped_with_a_message(self):
        self.inbox({"cmd": "add", "links": ["https://example.com/video.mp4"]})
        self.run_grab()
        self.assertEqual(self.jobs(), {})
        self.assertTrue(any("not a YouTube or Instagram link" in e["msg"] for e in Store(self.data).recent_events(20)))

    def test_cancel_and_remove(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]}, "1.json")
        os.environ["FAKE_MODE"] = "blocked"
        # reading the list needs yt-dlp too, so add while it works, then block downloads only
        os.environ.pop("FAKE_MODE")
        self.run_grab()
        jid = next(iter(self.jobs()))
        self.inbox({"cmd": "remove", "id": jid})
        self.run_grab(minutes=5)
        self.assertEqual(self.jobs(), {})
        self.assertEqual(len(self.w.files), 3)                          # removing the list never deletes what is already in Drive

    # ---- added in 1.9: ownership tick, newest N, Shorts tab, clean links, other people's Instagram accounts
    def test_nothing_is_added_without_the_ownership_tick(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/watch?v=SINGLE00001"], "confirm": False})
        self.run_grab()
        self.assertEqual(self.jobs(), {})
        self.assertEqual(len(self.w.files), 0)
        ev = Store(self.data).recent_events(20)
        self.assertTrue(any("not ticked" in e["msg"] and "tick the box" in (e.get("fix") or "") for e in ev))

    def test_newest_n_limits_a_channel_and_is_passed_to_yt_dlp(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/@somechannel"], "settings": {"max_items": 2}})
        self.run_grab()
        self.assertIn("--playlist-end 2", self.calls())
        self.assertEqual(len(self.w.files), 2)
        job = next(iter(self.jobs().values()))
        self.assertEqual(job["settings"]["max_items"], 2)

    def test_shorts_tab_and_both_tabs(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/@somechannel"], "settings": {"yt_tab": "shorts"}})
        self.run_grab()
        c = self.calls()
        self.assertIn("https://www.youtube.com/@somechannel/shorts", c)
        self.assertNotIn("@somechannel/videos", c)
        self.assertEqual(len(self.w.files), 2)
        self.w.reset(); self.w.video = self.plain_bytes
        self.data = tempfile.mkdtemp(prefix="data_", dir=self.tmp); self.setUp_data_again()
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/@somechannel"], "settings": {"yt_tab": "both"}})
        self.run_grab()
        self.assertEqual(len(self.w.files), 5, "2 Shorts + 3 videos, none twice")

    def setUp_data_again(self):
        cfg = {"version": 1, "timezone": "UTC", "paused": False, "routes": [],
               "connections": [{"id": "google", "kind": "google", "label": "Google"}, {"id": "ig_a", "kind": "instagram", "label": "mypage", "ig_user_id": "111"}]}
        util.write_json(os.path.join(self.data, "config.json"), cfg)
        sec = {"google": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}, "ig_a": {"access_token": "IGTOKA"}}
        util.write_json(os.path.join(self.data, "secrets.enc.json"), crypto.encrypt(sec, "test-pass", iters=1000))
        self.log = os.path.join(self.data, "..", f"calls_{os.path.basename(self.data)}.txt"); self.fake_ytdlp()

    def test_the_same_video_pasted_with_tracking_junk_is_one_list_and_one_file(self):
        self.inbox({"cmd": "add", "links": ["https://youtu.be/SINGLE00001?si=abc123", "https://www.youtube.com/watch?v=SINGLE00001&feature=share"]})
        self.run_grab()
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(len(self.w.files), 1)

    def test_link_cleaning(self):
        c = grab._clean_url
        self.assertEqual(c("https://www.instagram.com/reel/AbC_1-x/?igsh=zzz"), "https://www.instagram.com/reel/AbC_1-x/")
        self.assertEqual(c("instagram.com/someone/reel/QQQ/"), "https://www.instagram.com/reel/QQQ/")
        self.assertEqual(c("https://www.instagram.com/p/XYZ/?utm_source=ig_web_copy_link"), "https://www.instagram.com/p/XYZ/")
        self.assertEqual(c("https://www.instagram.com/Nasa/?hl=en"), "https://www.instagram.com/Nasa/")
        self.assertEqual(c("https://www.youtube.com/@chan/"), "https://www.youtube.com/@chan")
        self.assertEqual(c("https://www.youtube.com/playlist?list=PLabc&si=1"), "https://www.youtube.com/playlist?list=PLabc")
        self.assertTrue(grab._ig_is_profile("https://www.instagram.com/nasa/") and not grab._ig_is_profile("https://www.instagram.com/reel/AbC/"))

    def test_someone_elses_instagram_account_is_explained_and_does_not_pause_instagram(self):
        os.environ["FAKE_MODE"] = "igprofile"
        self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"]})
        self.run_grab()
        self.assertEqual(self.jobs(), {})
        ev = [e for e in Store(self.data).recent_events(20) if "someone else" in e["msg"]]
        self.assertTrue(ev and "Paste the links of the reels" in ev[0]["fix"] and "My Instagram account" in ev[0]["fix"])
        st = util.read_json(os.path.join(self.data, "queues", "grab", "_state.json"), {})
        self.assertFalse((st.get("source_until") or {}).get("ig"), "reading a profile must not pause single-reel downloads")

    def test_adding_the_same_playlist_again_saves_only_the_new_videos(self):
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]}, "1.json")
        self.run_grab()
        self.assertEqual(len(self.w.files), 3)
        os.environ["FAKE_EXTRA"] = "1"
        self.inbox({"cmd": "add", "links": ["https://www.youtube.com/playlist?list=PLabc"]}, "2.json")
        self.run_grab(minutes=5)
        self.assertEqual(len(self.w.files), 4)
        self.assertEqual(len(self.jobs()), 1)


if __name__ == "__main__":
    unittest.main()
