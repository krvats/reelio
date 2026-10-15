"""The browser extension (tools/cookie-sync) and the worker must agree: what the extension encrypts and merges, the worker
opens and uses, and a refreshed export of the same browser replaces its own cookie slot and wakes it up."""
import os, sys, shutil, subprocess, tempfile, unittest, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reelio.store import Store
from reelio import cookiepool as cp

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        p = subprocess.run(["node", os.path.join(ROOT, "tools", "cookie-sync", "test", "sync.test.mjs"), cls.tmp], capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stdout + p.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def store(self):
        return Store(self.tmp, passphrase="test-passphrase")

    def test_worker_reads_what_the_extension_encrypted_and_other_logins_survive(self):
        s = self.store()
        self.assertEqual(s.secret("ig_1")["access_token"], "IGTOKEN")
        pool = cp.Pool(s, {"net_conn": "youtube-net"})
        self.assertEqual(len(pool.items), 2)
        self.assertEqual(sorted(pool.labels.values()), ["Spare 1", "Spare 2"])
        self.assertEqual(sorted(i[0] for i in pool.items), ["p-aaaa11", "p-bbbb22"])

    def test_refreshed_export_of_the_same_browser_wakes_its_rest_timer(self):
        s = self.store(); src = {"net_conn": "youtube-net"}
        pool = cp.Pool(s, src); pool.fail("p-aaaa11", "expired"); pool.fail("p-bbbb22", "blocked")
        self.assertEqual(len(cp.Pool(s, src).ready()), 0)
        # the extension sends a new export for browser A: new content, same slot
        sec = s.secret("youtube-net")["cookies"].replace("SA2", "SA3")
        s.save_secret("youtube-net", {"cookies": sec})
        ready = [c for c, _ in cp.Pool(s, src).ready()]
        self.assertEqual(ready, ["p-aaaa11"], "fresh cookie from A is tried again; B (unchanged) keeps resting")

    def test_exported_cookie_file_is_valid_netscape(self):
        body = [b for _, b in cp.Pool(self.store(), {"net_conn": "youtube-net"}).items][0]
        lines = [l for l in body.splitlines() if l and not l.startswith("#") or l.startswith("#HttpOnly_")]
        self.assertTrue(lines and all(len(l.split("\t")) == 7 for l in lines))


if __name__ == "__main__":
    unittest.main()
