import os, json, subprocess, unittest
from helpers import *
from reelio import license as lic, util

LIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "license")


def mint(claims):
    """Token signed by the real Node license service code, so Python must agree with it byte for byte."""
    out = subprocess.run(["node", os.path.join(LIC_DIR, "scripts", "mint-token.mjs"), json.dumps(claims)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


class LicenseUnits(unittest.TestCase):
    def test_node_token_verifies_in_python_and_tamper_fails(self):
        m = mint({"st": "active", "plan": "pro"})
        self.assertEqual(lic.verify_token(m["x"], m["token"], 0)["plan"], "pro")
        h, b, s = m["token"].split(".")
        with self.assertRaises(ValueError): lic.verify_token(m["x"], f"{h}.{b}.{s[:-3]}AAA", 0)
        with self.assertRaises(ValueError): lic.verify_token(mint({})["x"], m["token"], 0)   # someone else's key

    def test_open_mode_when_no_key(self):
        os.environ.pop("REELIO_LICENSE_PUBKEY", None)
        r = lic.check(None, {})
        self.assertTrue(r["active"]); self.assertFalse(r["enforced"])


class LicenseEngine(MockBase):
    def setUp(self):
        super().setUp()
        self.add_drive(6); self.write_env()

    def tearDown(self):
        os.environ.pop("REELIO_LICENSE_PUBKEY", None)
        super().tearDown()

    def give(self, claims, tamper=False):
        m = mint(claims); os.environ["REELIO_LICENSE_PUBKEY"] = m["x"]
        t = m["token"] + ("x" if tamper else "")
        json.dump({"token": t}, open(os.path.join(self.data, "license.json"), "w"))

    def status(self): return util.read_json(os.path.join(self.data, "status.json"), {})

    def now_s(self): return int(util.now().timestamp())

    def test_no_token_means_nothing_posts_but_scan_works(self):
        os.environ["REELIO_LICENSE_PUBKEY"] = mint({})["x"]
        self.run_engine()
        self.assertEqual(self.W.ig_posts, [])
        self.assertEqual(len(self.queue()["items"]), 6)
        self.assertIn("plan", self.status()["license"]["message"].lower())

    def test_valid_token_posts(self):
        t = self.now_s(); self.give({"st": "active", "plan": "pro", "lim": {"accounts": 5, "posts_month": 100}, "exp": t + 3600})
        self.run_engine(); self.assertEqual(len(self.W.ig_posts), 6)

    def test_forged_or_expired_token_blocks(self):
        t = self.now_s(); self.give({"st": "active", "plan": "pro", "lim": {"accounts": 5, "posts_month": 100}, "exp": t + 3600}, tamper=True)
        self.run_engine(); self.assertEqual(self.W.ig_posts, [])
        self.give({"st": "active", "plan": "pro", "lim": {"accounts": 5, "posts_month": 100}, "exp": t - 10})
        self.run_engine(); self.assertEqual(self.W.ig_posts, [])

    def test_wv_keeps_posting_after_24h_expiry(self):
        t = self.now_s(); self.give({"st": "active", "plan": "pro", "lim": {"accounts": 5, "posts_month": 100}, "exp": t - 100, "wv": t + 86400 * 5})
        self.run_engine(); self.assertEqual(len(self.W.ig_posts), 6)

    def test_monthly_post_limit(self):
        t = self.now_s(); self.give({"st": "active", "plan": "starter", "lim": {"accounts": 5, "posts_month": 2}, "exp": t + 3600})
        self.run_engine(); self.assertEqual(len(self.W.ig_posts), 2)
        self.run_engine(force_scan=True); self.assertEqual(len(self.W.ig_posts), 2)

    def test_account_limit_zero_blocks_route(self):
        t = self.now_s(); self.give({"st": "active", "plan": "x", "lim": {"accounts": 0, "posts_month": 100}, "exp": t + 3600})
        self.run_engine(); self.assertEqual(self.W.ig_posts, [])
        self.assertEqual(list(self.status()["routes"].values())[0]["state"], "needs_plan")


if __name__ == "__main__":
    unittest.main()
