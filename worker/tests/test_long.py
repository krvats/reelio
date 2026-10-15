import os, sys, json, glob, tempfile, datetime
from helpers import *
from reelio import longjob
from reelio.store import Store

VID = "LONGVIDEO01"


class LongVideos(MockBase):
    def setUp(self):
        super().setUp()
        self.calls_log = os.path.join(tempfile.mkdtemp(dir=self.tmp), "calls.txt")
        os.environ["REELIO_CHUNK"] = "20000"
        self.write_env()

    def tearDown(self):
        for k in ("REELIO_YTDLP", "REELIO_CHUNK"):
            os.environ.pop(k, None)
        super().tearDown()

    def fake(self, mode="ok", hours=9):
        d = tempfile.mkdtemp(dir=self.tmp); p = os.path.join(d, "fake_ytdlp.py")
        open(p, "w").write(f'''
import sys, json, shutil
a = sys.argv[1:]
open("{self.calls_log}", "a").write(" ".join(a) + "\\n")
if "--flat-playlist" in a:
    print(json.dumps({{"id": "{VID}", "title": "Big stream", "duration": {int(hours * 3600)}}}))
    sys.exit(0)
if "--dump-json" in a:
    if "{mode}" == "blocked":
        sys.stderr.write("ERROR: Sign in to confirm you're not a bot"); sys.exit(1)
    print(json.dumps({{"id": a[-1][-11:], "title": "Big stream", "duration": {int(hours * 3600)}, "upload_date": "20260101", "live_status": "was_live"}}))
    sys.exit(0)
if "{mode}" == "blocked":
    sys.stderr.write("ERROR: Sign in to confirm you're not a bot"); sys.exit(1)
out = a[a.index("-o") + 1].replace("%(ext)s", "mp4")
shutil.copy("{self.vid}", out)
''')
        os.environ["REELIO_YTDLP"] = f"{sys.executable} {p}"

    def add(self, hours=9, **settings):
        self.fake(hours=hours)
        cmd = {"cmd": "add", "links": [f"https://www.youtube.com/watch?v={VID}"], "settings": settings}
        os.makedirs(os.path.join(self.data, "long-inbox"), exist_ok=True)
        json.dump(cmd, open(os.path.join(self.data, "long-inbox", "1.json"), "w"))

    def store_(self):
        return Store(self.data)

    def job(self):
        return util.read_json(os.path.join(self.data, "queues", "long", f"{VID}.json"))

    def test_plan_and_titles(self):
        self.assertEqual([(p["start"], p["end"]) for p in longjob.plan_parts(5 * 3600, 4)], [(0, 9000), (9000, 18000)])
        self.assertEqual(len(longjob.plan_parts(24 * 3600, 4)), 6)
        self.assertEqual(len(longjob.plan_parts(1800, 4)), 1)
        job = {"id": "x", "title": "T" * 150, "url": "u", "parts": longjob.plan_parts(24 * 3600, 4), "settings": longjob._clean_settings({})}
        t = longjob.part_title(job, job["parts"][0])
        self.assertLessEqual(len(t), 100); self.assertTrue(t.endswith("(Part 1/6)"))

    def test_nine_hour_video_becomes_three_parts_each_downloaded_on_its_own(self):
        self.add(9, part_hours=4)
        self.W.yt_fail_chunk = True            # one upload chunk fails once: must resume, not restart or duplicate
        more = longjob.run(self.store_(), 320)
        self.assertFalse(more)
        job = self.job()
        self.assertEqual(job["status"], "done")
        self.assertEqual([p["status"] for p in job["parts"]], ["done"] * 3)
        self.assertEqual([u["meta"]["snippet"]["title"] for u in self.W.yt_uploads], [f"Big stream (Part {i}/3)" for i in (1, 2, 3)])
        self.assertTrue(all(u["meta"]["status"]["privacyStatus"] == "private" for u in self.W.yt_uploads))
        self.assertTrue(all(u["size"] == os.path.getsize(self.vid) for u in self.W.yt_uploads), "every byte arrived exactly once")
        calls = open(self.calls_log).read()
        for rng in ("*0-10800", "*10800-21600", "*21600-32400"):
            self.assertIn("--download-sections " + rng, calls)
        self.assertFalse(glob.glob(os.path.join(tempfile.gettempdir(), "long_*")), "temporary files are removed")

    def test_short_enough_video_is_one_part_with_no_section_cut(self):
        self.add(1, part_hours=4)
        longjob.run(self.store_(), 320)
        self.assertEqual([u["meta"]["snippet"]["title"] for u in self.W.yt_uploads], ["Big stream"])
        self.assertNotIn("--download-sections", open(self.calls_log).read().split("--dump-json")[-1].split("\n", 1)[-1])

    def test_a_24_hour_video_is_six_parts_and_continues_in_the_next_run_when_time_is_short(self):
        self.add(24, part_hours=4)
        self.assertTrue(longjob.run(self.store_(), 24), "less time than needed to start a part: ask for another run")
        self.assertEqual(len(self.W.yt_uploads), 0)
        self.assertEqual(len(self.job()["parts"]), 6)
        self.assertFalse(longjob.run(self.store_(), 320))
        self.assertEqual(len(self.W.yt_uploads), 6)
        self.assertEqual(self.job()["status"], "done")
        self.assertFalse(longjob.run(self.store_(), 320) and len(self.W.yt_uploads) > 6, "nothing is uploaded twice")
        self.assertEqual(len(self.W.yt_uploads), 6)

    def test_part_that_already_reached_youtube_before_a_crash_is_not_uploaded_again(self):
        self.add(9, part_hours=4)
        longjob.run(self.store_(), 24)                       # creates the job, uploads nothing
        job = self.job(); job["parts"][0].update(status="uploading", started_at="2020-01-01T00:00:00Z")
        util.write_json(os.path.join(self.data, "queues", "long", f"{VID}.json"), job)
        self.W.yt_recent = [("Big stream (Part 1/3)", "ALREADY1")]
        longjob.run(self.store_(), 320)
        j = self.job()
        self.assertEqual(j["parts"][0]["video_id"], "ALREADY1")
        self.assertEqual(len(self.W.yt_uploads), 2, "only parts 2 and 3 were uploaded")

    def test_upload_limit_pauses_only_this_channel_and_does_not_burn_parts(self):
        self.add(9, part_hours=4)
        self.W.yt_limit = True
        longjob.run(self.store_(), 320)
        j = self.job()
        self.assertEqual([p["status"] for p in j["parts"]], ["pending"] * 3)
        self.assertTrue(all(p.get("fails", 0) == 0 for p in j["parts"]))
        st = util.read_json(os.path.join(self.data, "queues", "long", "_state.json"))
        self.assertIn("google", st["conn_until"])
        before = len(self.W.calls)
        longjob.run(self.store_(), 320)                       # still cooling down: no new upload attempts
        self.assertFalse(any(c[1] == "/upload/youtube/v3/videos" for c in self.W.calls[before:]))

    def test_youtube_blocking_pauses_long_downloads_with_a_fix(self):
        self.add(9, part_hours=4)
        longjob.run(self.store_(), 24)
        self.fake("blocked", 9)
        longjob.run(self.store_(), 320)
        j = self.job()
        self.assertEqual([p["status"] for p in j["parts"]], ["pending"] * 3)
        st = util.read_json(os.path.join(self.data, "queues", "long", "_state.json"))
        self.assertTrue(st["source_until"])
        self.assertTrue(any("cookies" in (e.get("fix") or "") for e in Store(self.data).recent_events()))
        self.assertEqual(len(self.W.yt_uploads), 0)

    def test_unverified_channel_rejection_is_explained(self):
        self.add(1, part_hours=4)
        self.W.yt_status = "rejected"
        longjob.run(self.store_(), 320)
        err = self.job()["parts"][0]["last_error"]
        self.assertIn("verify", err["fix"].lower() + err["msg"].lower())

    def test_cancel_retry_remove(self):
        self.add(9, part_hours=4)
        longjob.run(self.store_(), 24)
        for cmd in ("cancel", "retry", "remove"):
            json.dump({"cmd": cmd, "id": VID}, open(os.path.join(self.data, "long-inbox", f"{cmd}.json"), "w"))
            longjob.intake(self.store_())
            if cmd == "cancel": self.assertEqual(self.job()["status"], "cancelled")
            if cmd == "retry": self.assertNotEqual(self.job()["status"], "cancelled")
        self.assertIsNone(self.job())

    def test_channel_scan_adds_only_long_finished_videos(self):
        self.fake(hours=6)
        os.makedirs(os.path.join(self.data, "long-inbox"), exist_ok=True)
        json.dump({"cmd": "add", "channel": {"handle": "@Mine", "tab": "streams", "min_minutes": 60, "max_videos": 2}, "settings": {}},
                  open(os.path.join(self.data, "long-inbox", "c.json"), "w"))
        longjob.intake(self.store_())
        self.assertEqual(len(self.job()["parts"]), 2)        # 6 h with 4 h parts
        self.assertEqual(self.job()["title"], "Big stream")

    def test_secrets_never_appear_in_job_files_or_logs(self):
        self.add(1)
        longjob.run(self.store_(), 320)
        blob = "".join(open(f).read() for f in glob.glob(os.path.join(self.data, "queues", "long", "*")) + glob.glob(os.path.join(self.data, "logs", "*")))
        for secret in ("RT", "IGTOKA", "test-pass"):
            self.assertNotIn(f'"{secret}"', blob)


if __name__ == "__main__":
    unittest.main()
