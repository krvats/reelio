"""YouTube cookie pool: splitting, automatic switching, resting timers, and the final fallbacks."""
import os, sys, json, tempfile, shutil, unittest, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reelio.store import Store
from reelio import cookiepool as cp
from reelio.sources import youtube as yt
from reelio.errors import SourceProblem

LINE = ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\t{v}\n"


def cookie(tag):
    return "# Netscape HTTP Cookie File\n" + LINE.format(v=tag)


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "data"), passphrase="pw")
        self.src = {"net_conn": "youtube-net"}
        # fake yt-dlp: the cookie file's content decides what happens
        self.fake = os.path.join(self.tmp, "fake.py")
        open(self.fake, "w").write('''
import sys, shutil
a = sys.argv[1:]
ck = open(a[a.index("--cookies") + 1]).read() if "--cookies" in a else ""
if "GOOD" in ck or ("--cookies" not in a and "ANON_OK" in sys.argv[0]):
    out = a[a.index("-o") + 1].replace("%(ext)s", "mp4"); open(out, "wb").write(b"video"); sys.exit(0)
if "EXPIRED" in ck:
    sys.stderr.write("ERROR: The provided YouTube account cookies are no longer valid. They have likely been rotated"); sys.exit(1)
if "PRIVATE" in ck:
    sys.stderr.write("ERROR: Video unavailable. This video is private"); sys.exit(1)
sys.stderr.write("ERROR: Sign in to confirm you're not a bot"); sys.exit(1)
''')
        os.environ["REELIO_YTDLP"] = f"{sys.executable} {self.fake}"

    def tearDown(self):
        os.environ.pop("REELIO_YTDLP", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, *tags):
        self.store.save_secret("youtube-net", {"cookies": "\n".join(cookie(t) for t in tags)})

    def download(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        cmd = yt._ytdlp() + ["-o", os.path.join(d, "v.%(ext)s"), "https://www.youtube.com/watch?v=x"]
        (p, files), notes = yt.download_with_pool(self.store, self.src, cmd, d)
        return p, files, notes

    # ---- splitting
    def test_many_files_pasted_into_one_box_become_separate_cookies(self):
        text = cookie("A") + "\n" + cookie("B") + "\n" + cookie("A")          # the third is a duplicate
        self.assertEqual(len(cp.split_pool(text)), 2)

    def test_marker_line_and_headerless_files_are_split(self):
        raw = LINE.format(v="ONE") + cp.MARK + "\n" + LINE.format(v="TWO")
        self.assertEqual(len(cp.split_pool(raw)), 2)

    def test_junk_is_ignored_and_httponly_lines_count(self):
        self.assertEqual(cp.split_pool("hello\nnot a cookie\n"), [])
        self.assertEqual(len(cp.split_pool("# Netscape HTTP Cookie File\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tx\n")), 1)

    def test_classify_tells_cookie_trouble_from_video_trouble(self):
        self.assertEqual(cp.classify("Sign in to confirm you're not a bot"), "blocked")
        self.assertEqual(cp.classify("cookies are no longer valid"), "expired")
        self.assertIsNone(cp.classify("This video is private"))

    # ---- switching
    def test_skips_dead_cookies_and_uses_the_first_good_one(self):
        self.put("BLOCKED1", "EXPIRED1", "GOOD1")
        p, files, notes = self.download()
        self.assertEqual(p.returncode, 0); self.assertTrue(files)
        self.assertTrue(any("blocked" in n for n in notes) and any("expired" in n for n in notes))
        h = json.load(open(self.store.p("cookie_health.json")))["items"]
        self.assertEqual(sorted(v["kind"] or "ok" for v in h.values()), ["blocked", "expired", "ok"])

    def test_resting_cookie_is_not_tried_again_until_its_timer_ends(self):
        self.put("BLOCKED1", "GOOD1")
        self.download()                                                       # BLOCKED1 now rests
        pool = cp.Pool(self.store, self.src)
        self.assertEqual(len(pool.ready()), 1)
        self.assertEqual(pool.summary()["resting"], 1)
        _, _, notes = self.download()
        self.assertFalse(any("blocked" in n for n in notes), "a resting cookie must not be retried early")

    def test_blocked_cookie_wakes_up_after_its_rest_but_expired_one_rests_much_longer(self):
        self.put("BLOCKED1", "EXPIRED1")
        self.download()
        pool = cp.Pool(self.store, self.src)
        kinds = {cid: pool.h[cid]["kind"] for cid, _ in pool.items}
        for cid, k in kinds.items():
            mins = (pool._until(cid) - cp.now()).total_seconds() / 60
            self.assertTrue(25 < mins < 31 if k == "blocked" else 350 < mins < 361, (k, mins))
        # time passes: pretend the blocked cookie's rest is over
        bid = next(c for c, k in kinds.items() if k == "blocked")
        pool.h[bid]["until"] = cp.iso(cp.now() - datetime.timedelta(minutes=1)); pool._save()
        self.assertEqual([c for c, _ in cp.Pool(self.store, self.src).ready()], [bid])

    def test_repeated_failures_rest_longer_each_time(self):
        self.put("BLOCKED1")
        pool = cp.Pool(self.store, self.src); cid = pool.items[0][0]
        self.assertEqual([pool.fail(cid, "blocked") for _ in range(5)], [30, 120, 360, 1440, 1440])
        pool.ok(cid)
        self.assertEqual(pool.fail(cid, "blocked"), 30)                        # one success resets the ladder

    def test_a_private_video_is_not_blamed_on_the_cookies(self):
        self.put("PRIVATE1", "GOOD1")
        p, files, notes = self.download()
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(cp.Pool(self.store, self.src).summary()["resting"], 0)

    def test_nothing_works_gives_a_flow_timer_and_plain_fix(self):
        self.put("BLOCKED1", "EXPIRED1")
        p, files, _ = self.download()
        self.assertNotEqual(p.returncode, 0)
        with self.assertRaises(SourceProblem) as cm:
            yt.raise_for_failure(p.stderr, self.store, self.src)
        e = cm.exception
        self.assertTrue(15 <= e.cooldown_min <= 31, e.cooldown_min)             # wakes when the soonest cookie does
        self.assertIn("2 saved cookie", e.fix); self.assertIn("backup Drive folder", e.fix)

    def test_old_single_cookie_setup_still_works(self):
        self.store.save_secret("youtube-net", {"cookies": cookie("GOOD1")})
        p, files, _ = self.download()
        self.assertEqual(p.returncode, 0)

    def test_without_any_cookie_the_old_message_stays(self):
        with self.assertRaises(SourceProblem) as cm:
            yt.raise_for_failure("Sign in to confirm you're not a bot", self.store, self.src)
        self.assertIn("cookies", cm.exception.fix); self.assertEqual(cm.exception.cooldown_min, 180)

    def test_health_file_never_contains_the_cookie_itself(self):
        self.put("GOOD1", "BLOCKED1"); self.download()
        raw = open(self.store.p("cookie_health.json")).read()
        self.assertNotIn("GOOD1", raw); self.assertNotIn("SID", raw)

    def test_retry_all_wakes_everything(self):
        self.put("BLOCKED1", "EXPIRED1"); self.download()
        pool = cp.Pool(self.store, self.src); self.assertEqual(len(pool.ready()), 0)
        pool.retry_all()
        self.assertEqual(len(cp.Pool(self.store, self.src).ready()), 2)


if __name__ == "__main__":
    unittest.main()
