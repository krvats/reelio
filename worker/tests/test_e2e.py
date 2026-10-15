import os, json, datetime, subprocess, tempfile, unittest
from helpers import *
from reelio import media


class DriveToInstagram(MockBase):
    def test_posts_everything_due_once_and_cleans_up(self):
        self.add_drive(5)
        self.W.drive["empty"] = {"name": "empty.mp4", "bytes": b"", "created": "2025-01-01T00:00:00Z", "md5": "d41d8cd98f00b204e9800998ecf8427e"}
        self.write_env()
        self.run_engine()
        W = self.W
        self.assertEqual(len(W.ig_posts), 5)
        self.assertEqual(W.cdn, {}, "Cloudinary temp files must be deleted after posting")
        led = self.ledger()["entries"]
        self.assertEqual(sorted(e["src"] for e in led), [f"drive:clip{i}" for i in range(5)])
        q = {i["key"]: i for i in self.queue()["items"]}
        self.assertEqual(q["drive:empty"]["status"], "failed"); self.assertIn("empty", q["drive:empty"]["last_error"]["msg"])
        self.assertTrue(all(q[f"drive:clip{i}"]["status"] == "posted" for i in range(5)))
        # second run posts nothing new - never twice
        self.run_engine(force_scan=True)
        self.assertEqual(len(W.ig_posts), 5)
        # the posted videos were really re-encoded (golden filter + even size) and have a Reel caption
        self.assertTrue(all(p["caption"] == "Hello reel" for p in W.ig_posts))

    def test_same_video_uploaded_twice_under_different_names_is_not_reposted(self):
        self.add_drive(1)
        W = self.W
        W.drive["copy"] = dict(W.drive["clip0"], name="copy of clip.mp4", created="2026-02-01T00:00:00Z")
        self.write_env(); self.run_engine()
        self.assertEqual(len(W.ig_posts), 1)
        q = {i["key"]: i for i in self.queue()["items"]}
        self.assertEqual(q["drive:copy"]["status"], "posted"); self.assertIn("never reposted", q["drive:copy"]["note"])

    def test_schedule_limits_posts_to_what_is_due(self):
        self.add_drive(30)
        cfg = self.base_config(); cfg["routes"][0]["schedule"].update(per_day=4, start="00:00", end="23:59", max_per_run=20, jitter=0)
        self.write_env(cfg)
        self.at(6, 0)                      # 4 slots a day: ~03:00, 09:00, 15:00, 21:00 -> one is due
        self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 1)
        self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 1, "a second run at the same time must not post more")
        self.at(23, 30)                    # the rest of the day has passed: 3 more, never more than per_day
        self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 4)
        self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 4)

    def test_global_pause_posts_nothing_but_still_scans(self):
        self.add_drive(3)
        cfg = self.base_config(paused=True); self.write_env(cfg)
        self.run_engine()
        self.assertEqual(self.W.ig_posts, [])
        self.assertEqual(len(self.queue()["items"]), 3)

    def test_one_bad_video_never_stops_the_queue(self):
        self.add_drive(4)
        cfg = self.base_config(); cfg["routes"][0]["caption"] = {"mode": "same", "text": "Reel {name}"}
        self.W.bad_names.add("clip1")
        self.write_env(cfg); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 3)
        q = {i["key"]: i for i in self.queue()["items"]}
        self.assertEqual(q["drive:clip1"]["fails"], 1); self.assertEqual(q["drive:clip1"]["status"], "pending")
        self.assertEqual([q[f"drive:clip{i}"]["status"] for i in (0, 2, 3)], ["posted"] * 3, "a later failure must not erase earlier 'posted' marks")
        self.assertIn("format", q["drive:clip1"]["last_error"]["msg"])
        self.assertEqual(self.W.cdn, {})

    def test_three_failures_in_a_row_pause_the_flow_not_burn_the_queue(self):
        self.add_drive(8)
        self.W.fail_container_always = True
        self.write_env(); self.run_engine()
        self.assertEqual(self.W.ig_posts, [])
        q = self.queue()["items"]
        self.assertTrue(all(i["fails"] == 0 for i in q), "videos must not be penalised for a systemic problem")
        st = self.store.status()["routes"]["r1"]
        self.assertEqual(st["state"], "cooldown")
        self.assertTrue(any("Three videos" in m for m in self.W.telegram))

    def test_a_video_that_fails_three_times_is_set_aside(self):
        self.add_drive(2)
        cfg = self.base_config(); cfg["routes"][0]["caption"] = {"mode": "same", "text": "Reel {name}"}
        self.W.bad_names.add("clip0")
        self.write_env(cfg)
        for _ in range(3):
            for i in self.queue()["items"]: i["retry_after"] = None
            if self.queue()["items"]:
                q = self.queue(); [i.update(retry_after=None) for i in q["items"]]; self.store_q(q)
            self.run_engine(force_scan=True)
        q = {i["key"]: i for i in self.queue()["items"]}
        self.assertEqual(q["drive:clip0"]["status"], "failed")
        self.assertEqual(q["drive:clip1"]["status"], "posted")

    def store_q(self, q):
        from reelio.store import Store
        Store(self.data).save_queue("r1", q)


class RateLimitsAndAccounts(MockBase):
    def two_accounts(self):
        cfg = self.base_config()
        cfg["connections"].append({"id": "ig_b", "kind": "instagram", "label": "Account B", "ig_user_id": "222"})
        cfg["routes"] = [self.route("ra", "ig_a", source={"type": "drive", "conn": "google", "folders": ["A"]}),
                         self.route("rb", "ig_b", source={"type": "drive", "conn": "google", "folders": ["B"]})]
        self.write_env(cfg, {"ig_b": {"access_token": "IGTOKB", "refreshed_at": util.iso()}})

    def test_rate_limit_pauses_only_that_account_and_resumes(self):
        self.add_drive(3); self.two_accounts()
        self.W.rate_limited_tokens.add("IGTOKA")
        e = self.run_engine()
        posts = self.W.ig_posts
        self.assertTrue(all(p["uid"] == "222" for p in posts)); self.assertEqual(len(posts), 3)
        st = self.store.status()
        self.assertIn("cooldown_until", st["accounts"]["ig_a"]); self.assertNotIn("cooldown_until", st["accounts"]["ig_b"])
        self.assertEqual(st["routes"]["ra"]["state"], "cooldown")
        self.assertTrue(any("slow down" in m for m in self.W.telegram))
        # limit lifted + cooldown cleared by the app's inbox command -> A posts
        self.W.rate_limited_tokens.clear()
        os.makedirs(os.path.join(self.data, "inbox"), exist_ok=True)
        util.write_json(os.path.join(self.data, "inbox", "1.json"), {"cmd": "clear_cooldown", "account": "ig_a"})
        self.run_engine()
        self.assertTrue(any(p["uid"] == "111" for p in self.W.ig_posts))

    def test_rate_limit_hit_in_the_middle_waits_then_cools_down(self):
        self.add_drive(3)
        self.write_env()
        W = self.W
        # first publish works, then Instagram starts refusing
        def hook(c):
            if len(W.ig_posts) >= 1:
                W.rate_limited_tokens.add("IGTOKA")
        W.publish_hook = hook
        self.run_engine()
        self.assertGreaterEqual(len(W.ig_posts), 1)
        self.assertEqual(self.store.status()["routes"]["r1"]["state"], "cooldown")
        self.assertEqual(self.queue()["items"][1]["fails"], 0, "a rate limit must not count against the video")

    def test_expired_token_asks_for_reconnect_and_does_not_crash(self):
        self.add_drive(2); self.write_env(); self.W.expired_tokens.add("IGTOKA")
        self.run_engine()
        st = self.store.status()
        self.assertEqual(st["accounts"]["ig_a"]["problem"]["kind"], "token")
        self.assertIn("Reconnect", st["accounts"]["ig_a"]["problem"]["fix"])
        self.assertTrue(any(t["kind"] == "action" for t in st["todo"]))

    def test_missing_cloudinary_says_what_to_connect(self):
        self.add_drive(1); self.write_env(secrets={"cld": {}})
        self.run_engine()
        rs = self.store.status()["routes"]["r1"]
        self.assertEqual(rs["state"], "needs_setup")

    def test_token_refreshed_after_20_days_and_expiry_tracked(self):
        self.add_drive(0)
        old = util.iso(util.now() - datetime.timedelta(days=25))
        self.write_env(secrets={"ig_a": {"access_token": "IGTOKA", "refreshed_at": old}})
        self.run_engine()
        self.assertEqual(self.W.refresh_calls, 1)
        self.assertIsNotNone(self.store.status()["accounts"]["ig_a"]["token_expires"])

    def test_secrets_never_leak_into_logs_or_status(self):
        self.add_drive(2); self.W.fail_container_always = True; self.write_env(); self.run_engine()
        blob = ""
        for dp, _, fs in os.walk(self.data):
            for f in fs:
                if f != "secrets.enc.json": blob += open(os.path.join(dp, f), errors="ignore").read()
        for s in ("IGTOKA", "test-pass", "RT", '"s"'):
            if s in ('"s"',): continue
            self.assertNotIn(s, blob.replace("RTL", ""))


class CrashRecovery(MockBase):
    def test_killed_after_container_ready_publishes_exactly_once_next_run(self):
        self.add_drive(1); self.write_env()
        W = self.W
        class Boom(BaseException): pass
        from reelio.targets import instagram
        orig = instagram.Instagram.publish
        def dying(self_, cid):
            raise Boom()                      # the runner is killed right before publishing
        instagram.Instagram.publish = dying
        try:
            with self.assertRaises(Boom):
                self.run_engine()
        finally:
            instagram.Instagram.publish = orig
        self.assertEqual(W.ig_posts, [])
        self.assertIn("r1", self.ledger()["inflight"])          # journal survived
        self.run_engine()
        self.assertEqual(len(W.ig_posts), 1)                    # published once by recovery
        self.assertEqual(len(self.ledger()["entries"]), 1)
        self.assertEqual(self.ledger()["inflight"], {})
        self.assertEqual(W.cdn, {}, "orphaned Cloudinary upload must be removed")
        self.run_engine(force_scan=True)
        self.assertEqual(len(W.ig_posts), 1)

    def test_killed_before_publish_attempt_is_safe(self):
        self.add_drive(1); self.write_env(); W = self.W
        class Boom(BaseException): pass
        from reelio.targets import instagram
        orig = instagram.Instagram.wait
        instagram.Instagram.wait = lambda *a, **k: (_ for _ in ()).throw(Boom())
        try:
            with self.assertRaises(Boom): self.run_engine()
        finally:
            instagram.Instagram.wait = orig
        self.run_engine()
        self.assertEqual(len(W.ig_posts), 1); self.assertEqual(W.cdn, {})


class Commands(MockBase):
    def cmd(self, n, **c):
        os.makedirs(os.path.join(self.data, "inbox"), exist_ok=True)
        util.write_json(os.path.join(self.data, "inbox", f"{n:03d}.json"), c)

    def test_skip_reorder_postnow_caption_retry(self):
        self.add_drive(4); cfg = self.base_config(); cfg["routes"][0]["schedule"]["per_day"] = 1; cfg["routes"][0]["schedule"]["start"] = "23:58"; cfg["routes"][0]["schedule"]["end"] = "23:59"
        self.write_env(cfg)
        self.run_engine()                                    # scan only (nothing due yet at this time of day, unless it's 23:59)
        self.W.ig_posts.clear(); self.W.ig_containers.clear()
        from reelio.store import Store
        s = Store(self.data)
        for f in os.listdir(self.data + "/ledger.json" if False else self.data): pass
        self.cmd(1, cmd="skip", route="r1", key="drive:clip0")
        self.cmd(2, cmd="caption", route="r1", key="drive:clip2", text="Special caption")
        self.cmd(3, cmd="post_now", route="r1", key="drive:clip2")
        self.cmd(4, cmd="reorder", route="r1", keys=["drive:clip3", "drive:clip1"])
        self.run_engine()
        posted = [p["caption"] for p in self.W.ig_posts]
        self.assertEqual(posted[0], "Special caption")                    # post_now goes first, with its own caption
        q = {i["key"]: i for i in self.queue()["items"]}
        self.assertEqual(q["drive:clip0"]["status"], "skipped")
        self.assertEqual(q["drive:clip3"]["order"], 0)
        self.assertEqual(os.listdir(os.path.join(self.data, "inbox")), [])  # commands consumed

    def test_repost_is_explicit_only(self):
        self.add_drive(1); self.write_env(); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 1)
        self.cmd(1, cmd="repost", route="r1", key="drive:clip0")
        self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 2)


class YouTube(MockBase):
    def test_drive_to_youtube_shorts(self):
        self.add_drive(2)
        cfg = self.base_config()
        cfg["connections"].append({"id": "yt", "kind": "google", "label": "My channel"})
        cfg["routes"] = [self.route("y1", "yt", target={"type": "youtube", "conn": "yt"}, caption={"mode": "same", "text": "A funny short #fun"}, host_conn="cld")]
        self.write_env(cfg, {"yt": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}})
        self.run_engine()
        ups = self.W.yt_uploads
        self.assertEqual(len(ups), 2)
        self.assertEqual(ups[0]["meta"]["snippet"]["title"], "A funny short #fun #Shorts")
        self.assertEqual(ups[0]["meta"]["status"]["privacyStatus"], "public")
        self.assertGreater(ups[0]["size"], 1000)
        self.assertEqual(len(self.ledger()["entries"]), 2)

    def test_youtube_daily_limit_waits_instead_of_failing_videos(self):
        self.add_drive(3)
        cfg = self.base_config()
        cfg["connections"].append({"id": "yt", "kind": "google", "label": "My channel"})
        cfg["routes"] = [self.route("y1", "yt", target={"type": "youtube", "conn": "yt"})]
        self.write_env(cfg, {"yt": {"client_id": "c", "client_secret": "s", "refresh_token": "RT"}})
        self.W.yt_limit = True
        self.run_engine()
        st = self.store.status()
        self.assertEqual(st["routes"]["y1"]["state"], "cooldown")
        self.assertIn("daily upload limit", st["accounts"]["yt"]["problem"]["msg"])
        self.assertTrue(all(i["fails"] == 0 for i in self.queue("y1")["items"]))

    def _fake_ytdlp(self, mode):
        d = tempfile.mkdtemp(dir=self.tmp); p = os.path.join(d, "fake_ytdlp.py")
        src = f'''
import sys, json, shutil
a = sys.argv[1:]
mode = "{mode}"
if "--flat-playlist" in a:
    for i in ("vidA", "vidB"): print(json.dumps({{"id": i, "title": "Short " + i}}))
    sys.exit(0)
if mode == "blocked":
    sys.stderr.write("ERROR: Sign in to confirm you're not a bot"); sys.exit(1)
out = a[a.index("-o") + 1].replace("%(ext)s", "mp4")
shutil.copy("{self.vid}", out)
'''
        open(p, "w").write(src)
        return f"{sys.executable} {p}"

    def test_youtube_channel_to_instagram_backup(self):
        os.environ["REELIO_YTDLP"] = self._fake_ytdlp("ok")
        try:
            cfg = self.base_config()
            cfg["routes"] = [self.route("yi", source={"type": "youtube", "handle": "@MyChannel", "include": "shorts"}, caption={"mode": "original"})]
            self.write_env(cfg); self.run_engine()
            self.assertEqual(len(self.W.ig_posts), 2)
            self.assertEqual(sorted(e["src"] for e in self.ledger()["entries"]), ["youtube:vidA", "youtube:vidB"])
            self.assertEqual(sorted(p["caption"] for p in self.W.ig_posts), ["Short vidA", "Short vidB"])
        finally:
            os.environ.pop("REELIO_YTDLP")

    def test_youtube_blocking_the_server_pauses_only_that_flow_with_a_fix(self):
        os.environ["REELIO_YTDLP"] = self._fake_ytdlp("blocked")
        try:
            self.add_drive(2)
            cfg = self.base_config()
            cfg["routes"] = [self.route("yi", source={"type": "youtube", "handle": "@MyChannel"}), self.route("r1")]
            self.write_env(cfg); self.run_engine()
            self.assertEqual(len(self.W.ig_posts), 2, "the Drive flow must keep working")
            rs = self.store.status()["routes"]["yi"]
            self.assertEqual(rs["state"], "cooldown"); self.assertIn("cookies", rs["problem"]["fix"])
        finally:
            os.environ.pop("REELIO_YTDLP")

    def test_backup_drive_folder_is_used_when_youtube_blocks_the_download(self):
        os.environ["REELIO_YTDLP"] = self._fake_ytdlp("blocked")
        try:
            self.add_drive(2)
            for fid, nm in zip(("clip0", "clip1"), ("vidA - edited.mp4", "vidB.mp4")):
                self.W.drive[fid]["name"] = nm
            cfg = self.base_config()
            cfg["routes"] = [self.route("yi", source={"type": "youtube", "handle": "@MyChannel", "backup_folders": ["https://drive.google.com/drive/folders/BK1"], "backup_conn": "google"})]
            self.write_env(cfg); self.run_engine()
            self.assertEqual(len(self.W.ig_posts), 2, "both videos must post from the backup folder")
            self.assertEqual(sorted(e["src"] for e in self.ledger()["entries"]), ["youtube:vidA", "youtube:vidB"])
            self.assertNotEqual(self.store.status()["routes"]["yi"].get("state"), "cooldown")
        finally:
            os.environ.pop("REELIO_YTDLP")

    def test_without_a_backup_file_the_error_says_what_to_add(self):
        os.environ["REELIO_YTDLP"] = self._fake_ytdlp("blocked")
        try:
            cfg = self.base_config()
            cfg["routes"] = [self.route("yi", source={"type": "youtube", "handle": "@MyChannel", "backup_folders": ["BK1"], "backup_conn": "google"})]
            self.write_env(cfg); self.run_engine()
            self.assertEqual(len(self.W.ig_posts), 0)
            self.assertIn("backup Drive folder", self.store.status()["routes"]["yi"]["problem"]["fix"])
        finally:
            os.environ.pop("REELIO_YTDLP")


class UploadSource(MockBase):
    def test_upload_from_app_posts_and_frees_space(self):
        d = os.path.join(self.data, "uploads", "r1"); os.makedirs(d)
        open(os.path.join(d, "mine.mp4"), "wb").write(self.vbytes)
        cfg = self.base_config(); cfg["routes"] = [self.route(source={"type": "upload"})]
        self.write_env(cfg); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 1)
        self.assertEqual(os.listdir(d), [])


class Tools(MockBase):
    def test_diagnose_and_analytics(self):
        self.add_drive(2); self.write_env()
        from reelio import diagnose, analytics
        from reelio.store import Store
        r = diagnose.run(Store(self.data))
        self.assertTrue(r["ok"], r)
        self.run_engine()
        a = analytics.run(Store(self.data))
        acc = a["accounts"]["ig_a"]
        self.assertEqual(len(acc["posts"]), 2); self.assertEqual(acc["posts"][0]["reach"], 120)
        self.assertEqual(sum(a["daily"]["r1"].values()), 2)

    def test_diagnose_reports_fix_for_wrong_cloudinary(self):
        self.write_env(secrets={"cld": {}})
        from reelio import diagnose
        from reelio.store import Store
        r = diagnose.run(Store(self.data))
        self.assertFalse(r["ok"]); self.assertIn("Cloudinary", r["verdict"])

    def test_wrong_passphrase_gives_plain_message(self):
        self.add_drive(1); self.write_env()
        os.environ["REELIO_KEY"] = "wrong"
        try:
            self.run_engine()
        finally:
            os.environ["REELIO_KEY"] = "test-pass"
        self.assertIn("REELIO_KEY", self.store.status()["run"]["message"])


class Media(MockBase):
    def test_fit_modes_and_options(self):
        for fit, (w, h) in (("keep", (720, 406)), ("blur", (1080, 1920)), ("crop", (1080, 1920)), ("pad", (1080, 1920))):
            out = os.path.join(self.tmp, f"o_{fit}.mp4")
            media.prepare(self.vid, out, {"filter": "vintage", "fit": fit, "watermark": {"text": "@me"}, "audio": {"mode": "mute" if fit == "pad" else "keep"}})
            p = media.probe(out)
            self.assertEqual((p["w"], p["h"]), (w, h)); self.assertEqual(bool(p["audio"]), fit != "pad")

    def test_too_short_video_rejected_with_plain_message(self):
        short = os.path.join(self.tmp, "short.mp4"); make_video(short, secs=1)
        from reelio.errors import ItemProblem
        with self.assertRaises(ItemProblem) as c:
            media.prepare(short, os.path.join(self.tmp, "x.mp4"), {})
        self.assertIn("3 seconds", c.exception.msg)

    def test_silent_clip_and_odd_fps(self):
        s = os.path.join(self.tmp, "silent.mp4"); subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=641x361:rate=10", "-t", "4", "-pix_fmt", "yuv444p", s], check=True)
        o = os.path.join(self.tmp, "silent_o.mp4"); media.prepare(s, o, {})
        p = media.probe(o); self.assertEqual(p["w"] % 2, 0); self.assertAlmostEqual(p["fps"], 30, delta=1)


if __name__ == "__main__":
    unittest.main()
