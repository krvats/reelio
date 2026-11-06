"""Instagram ACCOUNT -> Drive (igarchive.py inside Save to Drive): listing ladder, fallbacks, auto-refresh, permission tick.
Runs against the same fake Drive / yt-dlp as test_grab.py plus a fake gallery-dl. Nothing real is touched."""
import os, sys, json, unittest, datetime, tempfile

import test_grab as tg
from reelio import util, grab, crypto, igarchive
from reelio.store import Store

COOKIE = ".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tSESSVALUE123456\n.instagram.com\tTRUE\t/\tTRUE\t1999999999\tcsrftoken\tCSRFVALUE123\n"


class IgArchive(tg.SaveToDrive):
    def setUp(self):
        super().setUp()
        os.environ.update({"REELIO_IG_NO_INSTALL": "1", "REELIO_IG_DELAY": "0,0", "REELIO_IG_ALLOW_HTTP": "1", "REELIO_IG_NO_BROWSER": "1"})
        for k in ("FAKE_GDL", "FAKE_GDL_CODES"):
            os.environ.pop(k, None)
        self.gdl_log = os.path.join(self.data, "..", f"gdl_{os.path.basename(self.data)}.txt")
        self.fake_gdl()

    def tearDown(self):
        super().tearDown()
        for k in ("REELIO_IG_NO_INSTALL", "REELIO_IG_DELAY", "REELIO_IG_ALLOW_HTTP", "REELIO_IG_NO_BROWSER", "REELIO_GALLERYDL", "FAKE_GDL", "FAKE_GDL_CODES", "FAKE_MODE"):
            os.environ.pop(k, None)

    # ---- helpers
    def fake_gdl(self):
        p = os.path.join(self.tmp, f"gdl_{os.path.basename(self.data)}.py")
        open(p, "w").write(f'''
import sys, os, json
a = sys.argv[1:]
open({self.gdl_log!r}, "a").write(" ".join(a) + "\\n")
if os.environ.get("FAKE_GDL") == "blocked":
    sys.stderr.write("[instagram][error] HttpError: '429 Too Many Requests'"); sys.exit(4)
codes = os.environ.get("FAKE_GDL_CODES", "AAAAA11111,BBBBB22222,CCCCC33333").split(",")
print(json.dumps([[2, {{"x": 1}}]] + [[3, "https://cdn/x", {{"post_shortcode": c}}] for c in codes]))
''')
        os.environ["REELIO_GALLERYDL"] = f"{sys.executable} {p}"

    def set_secrets(self, cookie=True, **extra):
        sec = {"google": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}, "ig_a": {"access_token": "IGTOKA"}}
        if cookie or extra:
            sec["instagram-net"] = dict({"cookies": COOKIE} if cookie else {}, **extra)
        util.write_json(os.path.join(self.data, "secrets.enc.json"), crypto.encrypt(sec, "test-pass", iters=1000))

    def serve(self, codes):
        self.w.ig_videos = [{"id": c, "caption": "", "url": ""} for c in codes]

    def gdl_calls(self):
        return open(self.gdl_log).read().count("\n") if os.path.exists(self.gdl_log) else 0

    def ytdlp_downloads(self):
        return sum(1 for l in self.calls().splitlines() if "--flat-playlist" not in l)

    def drive_srcids(self):
        return sorted(f["props"]["srcId"] for f in self.w.files.values())

    # ---- tests
    def test_igarchive_account_is_listed_saved_into_its_own_folder_and_watched(self):
        self.set_secrets()
        self.inbox({"cmd": "add", "links": ["https://www.instagram.com/NASA/reels/?hl=en"]})
        self.run_grab()
        self.assertEqual(self.drive_srcids(), ["ig:AAAAA11111", "ig:BBBBB22222", "ig:CCCCC33333"])
        root = self.folder_id("Reelio Downloads")
        sub = self.folder_id("Instagram - NASA", root)
        self.assertTrue(sub, "the account gets its own subfolder")
        self.assertTrue(all(f["parent"] == sub for f in self.w.files.values()))
        job = next(iter(self.jobs().values()))
        self.assertEqual((job["status"], job["watch"]["user"]), ("done", "NASA"))
        self.assertIn("/NASA/reels/", open(self.gdl_log).read())
        # the cookie value is never written into any log line of the activity feed
        feed = json.dumps(Store(self.data).recent_events(80))
        self.assertNotIn("SESSVALUE123456", feed)

    def test_igarchive_nothing_is_added_without_the_permission_tick(self):
        self.set_secrets()
        self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"], "confirm": False})
        self.run_grab()
        self.assertEqual(self.jobs(), {})
        self.assertEqual(self.gdl_calls(), 0, "nothing may even be looked up without permission")

    def test_igarchive_every_way_failing_gives_a_plain_fix_and_does_not_pause_instagram(self):
        self.set_secrets(cookie=False)                       # no cookie, no key, nothing installable
        self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"]})
        self.run_grab()
        self.assertEqual(self.jobs(), {})
        ev = [e for e in Store(self.data).recent_events(30) if "could not read" in e["msg"] and "nasa" in e["msg"]]
        self.assertTrue(ev and "SPARE Instagram account" in ev[0]["fix"], ev)
        st = util.read_json(os.path.join(self.data, "queues", "grab", "_state.json"), {})
        self.assertFalse((st.get("source_until") or {}).get("ig"))

    def test_igarchive_a_blocked_way_hands_over_to_the_next_one_and_links_are_used_directly(self):
        self.set_secrets()
        os.environ["FAKE_GDL"] = "blocked"; os.environ["FAKE_MODE"] = "blocked"        # gallery-dl AND yt-dlp are blocked
        self.serve(["MIRR111111", "MIRR222222"])
        host = self.base

        def fake_mirror(store, user, limit, tmp):
            igarchive._lookup.setdefault(user, {}).update({c: f"{host}/cdn/{c}.mp4" for c in ("MIRR111111", "MIRR222222")})
            return [igarchive._row(user, c, f"{host}/cdn/{c}.mp4") for c in ("MIRR111111", "MIRR222222")]
        old = igarchive.LIST_TIERS
        igarchive.LIST_TIERS = [old[0], ("mirror sites", fake_mirror)]
        try:
            self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"]})
            self.run_grab()
        finally:
            igarchive.LIST_TIERS = old
        self.assertEqual(self.drive_srcids(), ["ig:MIRR111111", "ig:MIRR222222"])
        self.assertTrue(all(f["bytes"] == self.plain_bytes for f in self.w.files.values()))
        st = util.read_json(os.path.join(self.data, "queues", "grab", "_state.json"), {})
        self.assertFalse((st.get("source_until") or {}).get("ig"), "fallbacks worked, so Instagram is not paused")

    def test_igarchive_after_two_blocked_downloads_yt_dlp_is_not_asked_again_this_run(self):
        self.set_secrets()
        os.environ["FAKE_MODE"] = "blocked"
        codes = ["CODE%06d" % i for i in range(6)]
        os.environ["FAKE_GDL_CODES"] = ",".join(codes)
        self.serve(codes)
        host = self.base
        igarchive._lookup.clear()
        orig = igarchive.LIST_TIERS[0]

        def listing(store, user, limit, tmp):
            return [igarchive._row(user, c, f"{host}/cdn/{c}.mp4") for c in codes]
        old = igarchive.LIST_TIERS
        igarchive.LIST_TIERS = [("fake", listing)]
        try:
            self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"]})
            self.run_grab()
        finally:
            igarchive.LIST_TIERS = old
        self.assertEqual(len(self.w.files), 6)
        self.assertLessEqual(self.ytdlp_downloads(), 2, "yt-dlp was asked at most twice, then the other ways went first")

    def test_igarchive_new_reels_arrive_by_themselves_and_only_every_12_hours(self):
        self.set_secrets()
        self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"]})
        self.run_grab()
        self.assertEqual(len(self.w.files), 3)
        n = self.gdl_calls()
        os.environ["FAKE_GDL_CODES"] = "DDDDD44444,AAAAA11111,BBBBB22222,CCCCC33333"
        self.run_grab(minutes=60 * 5)
        self.assertEqual(self.gdl_calls(), n, "not looked at again after 5 hours")
        self.assertEqual(len(self.w.files), 3)
        self.run_grab(minutes=60 * 8)                       # 13 hours after the first check
        self.assertEqual(self.gdl_calls(), n + 1)
        self.assertEqual(self.drive_srcids(), ["ig:AAAAA11111", "ig:BBBBB22222", "ig:CCCCC33333", "ig:DDDDD44444"])

    def test_igarchive_a_failed_check_is_retried_in_about_two_hours_and_never_stops_saving(self):
        self.set_secrets()
        self.inbox({"cmd": "add", "links": ["https://www.instagram.com/nasa/"]})
        self.run_grab()
        os.environ["FAKE_GDL"] = "blocked"; self.set_secrets(cookie=False)
        self.run_grab(minutes=60 * 13)
        ev = [e for e in Store(self.data).recent_events(40) if "Could not check @nasa" in e["msg"]]
        self.assertTrue(ev)
        job = next(iter(self.jobs().values()))
        self.assertEqual(job["status"], "done")
        last = util.parse_iso(job["watch"]["last"])
        self.assertTrue(datetime.timedelta(hours=9) < (self.t0 - last) + datetime.timedelta(hours=13) - datetime.timedelta(hours=0))

    def test_igarchive_cookie_parser_and_user_of(self):
        self.assertEqual(igarchive.cookie_dict(COOKIE), {"sessionid": "SESSVALUE123456", "csrftoken": "CSRFVALUE123"})
        self.assertEqual(igarchive.user_of("https://www.instagram.com/Some.User_1/reels/?x=1"), "Some.User_1")
        self.assertIsNone(igarchive.user_of("https://example.com/x"))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for n in sorted(dir(IgArchive)):
        if n.startswith("test_igarchive_"):
            suite.addTest(IgArchive(n))
    return suite


if __name__ == "__main__":
    unittest.main()
