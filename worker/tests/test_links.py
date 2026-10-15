"""Video links as a source (any link yt-dlp understands, plus a public-Instagram fallback) and caption sidecars for uploads."""
import os, sys, json, shutil, subprocess, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from helpers import *                      # noqa  (MockBase, util, Store ...)
from reelio.sources import links

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def put_link(data, rid, url, **extra):
    d = os.path.join(data, "linkq", rid); os.makedirs(d, exist_ok=True)
    lid = links.link_id(url)
    util.write_json(os.path.join(d, lid + ".json"), dict({"url": url, "added_at": util.iso()}, **extra))
    return lid


class LinksSource(MockBase):
    def _fake(self, mode="ok", desc="Original words #tag"):
        d = tempfile.mkdtemp(dir=self.tmp); p = os.path.join(d, "fake_ytdlp.py")
        open(p, "w").write(f'''
import sys, json, shutil
a = sys.argv[1:]
if "{mode}" == "blocked":
    sys.stderr.write("ERROR: Instagram sent an empty media response. Use --cookies, login required"); sys.exit(1)
out = a[a.index("-o") + 1]
shutil.copy("{self.vid}", out.replace("%(ext)s", "mp4"))
if "--write-info-json" in a:
    json.dump({{"description": "{desc}", "title": "T"}}, open(out.replace("%(ext)s", "info.json"), "w"))
''')
        return f"{sys.executable} {p}"

    def setUp(self):
        super().setUp()
        self.old = {k: os.environ.get(k) for k in ("REELIO_YTDLP", "IG_WEB")}

    def tearDown(self):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def cfg(self, **cap):
        c = self.base_config()
        c["routes"] = [self.route("lk", source={"type": "links", "net_conn": "youtube-net"}, caption=cap or {"mode": "original"})]
        return c

    def test_links_post_with_original_caption_and_are_freed(self):
        os.environ["REELIO_YTDLP"] = self._fake()
        put_link(self.data, "lk", "https://www.instagram.com/reel/ABC123/?igsh=zzz")
        put_link(self.data, "lk", "https://youtube.com/shorts/vid12345")
        self.write_env(self.cfg()); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 2)
        self.assertEqual({p["caption"] for p in self.W.ig_posts}, {"Original words #tag"})
        self.assertEqual(sorted(e["src"] for e in self.ledger()["entries"]), ["link:ig_ABC123", "link:yt_vid12345"])
        self.assertEqual(os.listdir(os.path.join(self.data, "linkq", "lk")), [])

    def test_same_link_added_again_is_never_reposted(self):
        os.environ["REELIO_YTDLP"] = self._fake()
        url = "https://www.instagram.com/reel/ABC123/"
        put_link(self.data, "lk", url)
        self.write_env(self.cfg()); self.run_engine()
        put_link(self.data, "lk", url + "?utm=x"); self.run_engine(force_scan=True)
        self.assertEqual(len(self.W.ig_posts), 1)

    def test_typed_caption_and_post_first(self):
        os.environ["REELIO_YTDLP"] = self._fake()
        put_link(self.data, "lk", "https://youtube.com/shorts/aaaaaa1", added_at="2026-01-01T00:00:00Z")
        put_link(self.data, "lk", "https://youtube.com/shorts/bbbbbb2", added_at="2026-01-02T00:00:00Z", post_first=True, caption="mine")
        c = self.cfg(mode="same", text="default"); c["routes"][0]["schedule"]["max_per_run"] = 1
        self.write_env(c); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 1)
        self.assertEqual(self.ledger()["entries"][0]["src"], "link:yt_bbbbbb2")

    def test_instagram_embed_fallback_when_ytdlp_is_refused(self):
        vid = self.vbytes
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(s):
                if s.path.startswith("/p/QQQ999/embed/captioned/"):
                    body = ('<script>{"video_url":"http://127.0.0.1:%d/v.mp4","owner":{"username":"x"},"edge_media_to_caption":{"edges":[{"node":{"text":"Embed caption"}}]}}</script>' % s.server.server_port).encode()
                elif s.path == "/v.mp4": body = vid
                else: s.send_response(404); s.end_headers(); return
                s.send_response(200); s.send_header("Content-Length", str(len(body))); s.end_headers(); s.wfile.write(body)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            os.environ["REELIO_YTDLP"] = self._fake("blocked"); os.environ["IG_WEB"] = f"http://127.0.0.1:{srv.server_port}"
            put_link(self.data, "lk", "https://www.instagram.com/reel/QQQ999/")
            self.write_env(self.cfg()); self.run_engine()
            self.assertEqual([p["caption"] for p in self.W.ig_posts], ["Embed caption"])
        finally:
            srv.shutdown()

    def test_blocked_link_pauses_only_that_flow_with_a_fix(self):
        os.environ["REELIO_YTDLP"] = self._fake("blocked"); os.environ["IG_WEB"] = "http://127.0.0.1:1"
        self.add_drive(2)
        put_link(self.data, "lk", "https://www.instagram.com/reel/NOPE001/")
        c = self.cfg(); c["routes"].append(self.route("r1"))
        self.write_env(c); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 2, "the Drive flow must keep working")
        rs = self.store.status()["routes"]["lk"]
        self.assertEqual(rs["state"], "cooldown"); self.assertIn("Instagram blocks", rs["problem"]["fix"])

    def test_upload_sidecar_gives_caption_and_is_cleaned(self):
        d = os.path.join(self.data, "uploads", "r1"); os.makedirs(d)
        open(os.path.join(d, "ig_x.mp4"), "wb").write(self.vbytes)
        util.write_json(os.path.join(d, "ig_x.json"), {"caption": "From sidecar", "added_at": "2026-01-01T00:00:00Z"})
        c = self.base_config(); c["routes"] = [self.route(source={"type": "upload"}, caption={"mode": "original"})]
        self.write_env(c); self.run_engine()
        self.assertEqual([p["caption"] for p in self.W.ig_posts], ["From sidecar"])
        self.assertEqual(os.listdir(d), [])


class LinkIdParity(unittest.TestCase):
    def test_web_and_worker_make_the_same_ids(self):
        urls = ["https://www.instagram.com/reel/ABC123/?igsh=1", "https://instagram.com/user.name/p/Zz_-9/", "https://youtu.be/abcDEF123?t=4",
                "https://www.youtube.com/watch?v=abcDEF123&x=1", "https://example.com/Clip/One/?a=1#b", "https://example.com/clip/one"]
        js = "import {linkId} from %r; for (const u of %s) console.log(await linkId(u));" % (
            os.path.abspath(os.path.join(ROOT, "web", "js", "links.js")), json.dumps(urls))
        out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split(), [links.link_id(u) for u in urls])
        self.assertEqual(links.link_id(urls[4]), links.link_id(urls[5]))


if __name__ == "__main__":
    unittest.main()
