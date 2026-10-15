import os, json, subprocess, time, unittest, urllib.request, shutil
from helpers import *
from reelio import apimode

API_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "api")


class ApiModeTests(MockBase):
    """The real Node API server + the real worker + fake Instagram/Drive/Cloudinary, end to end, with two separate users."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.port = 8790
        cls.node = subprocess.Popen(["node", os.path.join(API_DIR, "dev-server.mjs"), str(cls.port)], stdout=subprocess.PIPE, text=True)
        cls.node.stdout.readline()
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.node.terminate(); super().tearDownClass()

    def call(self, m, p, body=None, tok=None):
        req = urllib.request.Request(self.url + p, method=m, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

    def make_user(self, email, conn="ig_a", route_id="r1", flows=1):
        s, j = self.call("POST", "/v1/auth/signup", {"email": email, "password": "correct horse"}); self.assertEqual(s, 201)
        tok = j["token"]; _, cfg = self.call("GET", "/v1/config", tok=tok)
        base = self.base_config()
        s, _ = self.call("PUT", "/v1/config", {"v": cfg["v"], "connections": base["connections"], "routes": [self.route(route_id, conn)], "timezone": "UTC"}, tok); self.assertEqual(s, 200)
        sec = {"ig_a": {"access_token": "IGTOKA", "refreshed_at": util.iso()}, "cld": {"cloud_name": "demo", "api_key": "k", "api_secret": "s"}, "google": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}, "telegram": {"bot_token": "TG", "chat_id": "1"}}
        for k, v in sec.items(): self.call("PUT", "/v1/secrets/" + k, {"fields": v}, tok)
        return tok

    def test_full_cycle_posts_once_and_reports_back(self):
        self.add_drive(3)
        tok = self.make_user("a@x.com")
        n = apimode.serve(self.url, "wk", "test", budget_min=30)
        self.assertEqual(n, 1); self.assertEqual(len(self.W.ig_posts), 3)
        _, led = self.call("GET", "/v1/ledger", tok=tok); self.assertEqual(len(led["entries"]), 3)
        _, q = self.call("GET", "/v1/queue/r1", tok=tok); self.assertTrue(all(i["status"] == "posted" for i in q["items"]))
        _, st = self.call("GET", "/v1/status", tok=tok); self.assertIn("r1", st["routes"]); self.assertTrue(st["recent"])
        self.assertNotIn("IGTOKA", json.dumps(st))
        apimode.serve(self.url, "wk", "test", budget_min=30)          # again: nothing new, nothing twice
        self.assertEqual(len(self.W.ig_posts), 3)
        self.assertEqual(self.W.cdn, {})

    def test_inbox_command_from_the_app_is_applied(self):
        self.add_drive(2)
        tok = self.make_user("b@x.com", route_id="r9")
        cfg = self.call("GET", "/v1/config", tok=tok)[1]
        self.call("PUT", "/v1/config", {**cfg, "paused": True}, tok)       # paused: scan only, nothing posted
        apimode.serve(self.url, "wk", "test", 30)
        self.assertEqual(self.W.ig_posts, [])

    def test_two_users_are_separate(self):
        self.add_drive(2)
        a = self.make_user("c@x.com", route_id="ra"); b = self.make_user("d@x.com", route_id="rb")
        self.assertEqual(apimode.serve(self.url, "wk", "test", 30), 2)
        _, la = self.call("GET", "/v1/ledger", tok=a); _, lb = self.call("GET", "/v1/ledger", tok=b)
        self.assertEqual(len(la["entries"]), 2); self.assertEqual(len(lb["entries"]), 2)       # each user has own history (same account id, different users)
        self.assertEqual(self.call("GET", "/v1/queue/rb", tok=a)[1]["items"], [])

    def test_wrong_worker_key_does_nothing(self):
        with self.assertRaises(RuntimeError): apimode.Api(self.url, "nope").post("/v1/internal/lease", {})


if __name__ == "__main__":
    unittest.main()
