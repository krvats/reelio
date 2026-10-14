#!/usr/bin/env python3
"""Developer tool: builds realistic demo data with the real worker against fake services, then serves a fake GitHub API
(+ the web app) so the UI can be tested and screenshotted without any real account.
usage: ui_demo.py [port]   -> prints the URL to open"""
import os, sys, json, base64, hashlib, threading, shutil, tempfile, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker", "tests"))
import helpers
from helpers import *

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
WEB = os.path.join(os.path.dirname(__file__), "..", "web")


class Demo(MockBase):
    def runTest(self): pass


def build():
    Demo.setUpClass(); d = Demo(); d.setUp()
    d.add_drive(14)
    cfg = d.base_config()
    cfg["connections"].append({"id": "yt", "kind": "google", "label": "My YouTube channel"})
    cfg["routes"][0]["name"] = "Drive to snowlves"; cfg["routes"][0]["schedule"].update(per_day=24, start="00:00", end="23:59", max_per_run=6, jitter=0.2)
    cfg["routes"].append(d.route("shorts", "yt", name="Shorts to my YouTube", source={"type": "drive", "conn": "google", "folders": ["B"]}, target={"type": "youtube", "conn": "yt"}, schedule={"per_day": 6, "start": "08:00", "end": "22:00", "jitter": .2, "max_per_run": 2, "gap_seconds": 60}))
    cfg["routes"][-1]["enabled"] = False
    d.write_env(cfg, {"yt": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}})
    helpers.Handler.W = d.W
    d.W.bad_names.add("clip5"); cfg["routes"][0]["caption"] = {"mode": "same", "text": "Reel {n}: {name} #fun"}; d.write_env(cfg, {"yt": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}})
    d.run_engine()
    from reelio import analytics, diagnose
    from reelio.store import Store
    s = Store(d.data); analytics.run(s); diagnose.run(s)
    return d


class Hub(BaseHTTPRequestHandler):
    root = None; log = []
    def log_message(self, *a): pass
    def _send(self, code, body=b"", ct="application/json", extra=None):
        if not isinstance(body, (bytes, bytearray)): body = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body))); self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Methods", "*")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self._send(204)
    def sha(self, p): return hashlib.sha1(open(p, "rb").read()).hexdigest()
    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/api/"): return self.api("GET", p[4:])
        f = os.path.join(WEB, p.lstrip("/") or "index.html")
        if os.path.isdir(f): f = os.path.join(f, "index.html")
        if os.path.isfile(f):
            ct = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml", "webmanifest": "application/manifest+json"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
            return self._send(200, open(f, "rb").read(), ct)
        self._send(404, b"nope", "text/plain")
    def do_PUT(self): self.api("PUT", self.path.split("?")[0][4:])
    def do_POST(self): self.api("POST", self.path.split("?")[0][4:])
    def do_DELETE(self): self.api("DELETE", self.path.split("?")[0][4:])
    def api(self, m, p):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if p == "/user": return self._send(200, {"login": "krvats"})
        if re.match(r"^/repos/[^/]+/[^/]+$", p): return self._send(200, {"name": "x"})
        if p.endswith("/actions/secrets"): return self._send(200, {"secrets": [{"name": "DATA_PAT"}]})
        if p.endswith("/dispatches"): Hub.log.append(("dispatch", body)); return self._send(204)
        if p.endswith("/runs"): return self._send(200, {"workflow_runs": [{"status": "completed", "conclusion": "success"}]})
        mm = re.match(r"^/repos/[^/]+/[^/]+/contents/(.*)$", p)
        if mm:
            rel = mm[1]; from urllib.parse import unquote; rel = unquote(rel); fp = os.path.join(Hub.root, rel)
            if m == "GET":
                if os.path.isdir(fp): return self._send(200, [{"name": x, "path": rel + "/" + x} for x in os.listdir(fp)])
                if not os.path.isfile(fp): return self._send(404, {"message": "Not Found"})
                if "raw" in (self.headers.get("Accept") or ""): return self._send(200, open(fp, "rb").read(), "text/plain")
                return self._send(200, {"sha": self.sha(fp), "content": base64.b64encode(open(fp, "rb").read()).decode()})
            if m == "PUT":
                if os.path.isfile(fp) and body.get("sha") != self.sha(fp): return self._send(409, {"message": "conflict"})
                os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "wb").write(base64.b64decode(body["content"])); Hub.log.append(("put", rel)); return self._send(200, {"content": {"sha": self.sha(fp)}})
            if m == "DELETE":
                if os.path.isfile(fp): os.remove(fp)
                return self._send(200, {})
        self._send(404, {"message": "mock has no " + p})


if __name__ == "__main__":
    d = build(); Hub.root = d.data
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Hub)
    print(f"READY http://127.0.0.1:{PORT}/?api=http://127.0.0.1:{PORT}/api&owner=krvats  data={d.data}", flush=True)
    srv.serve_forever()
