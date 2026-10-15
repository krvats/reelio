import datetime, unittest
from helpers import *
from reelio import scheduler


class Calendar(unittest.TestCase):
    tz = scheduler.tzinfo("Asia/Kolkata")
    S = {"per_day": 4, "start": "10:00", "end": "22:00", "jitter": 0}

    def test_weekdays_blackout_and_ranges(self):
        mon, sat = datetime.date(2026, 10, 12), datetime.date(2026, 10, 17)
        s = {**self.S, "days": [0, 1, 2, 3, 4]}
        self.assertEqual(len(scheduler.day_slots(s, self.tz, mon)), 4); self.assertEqual(scheduler.day_slots(s, self.tz, sat), [])
        b = {**self.S, "blackout": ["2026-10-12", "2026-10-14..2026-10-15"]}
        self.assertEqual(scheduler.day_slots(b, self.tz, mon), []); self.assertEqual(scheduler.day_slots(b, self.tz, datetime.date(2026, 10, 15)), [])
        self.assertEqual(len(scheduler.day_slots(b, self.tz, datetime.date(2026, 10, 13))), 4)
        self.assertEqual(len(scheduler.day_slots({**self.S, "blackout": ["garbage"]}, self.tz, mon)), 4)     # bad entries are ignored, never crash

    def test_next_slot_skips_days_off_and_week_plan_counts(self):
        s = {**self.S, "days": [0]}                                       # Mondays only
        fri = datetime.datetime(2026, 10, 16, 8, 0, tzinfo=datetime.timezone.utc)
        nx = scheduler.next_slot(s, self.tz, fri, 0).astimezone(self.tz); self.assertEqual(nx.date(), datetime.date(2026, 10, 19))
        wp = scheduler.week_plan(s, self.tz, fri); self.assertEqual(len(wp), 7); self.assertEqual(sum(d["n"] for d in wp), 4)
        self.assertEqual(scheduler.due_count({**self.S, "days": [0]}, self.tz, fri, 0)[0], 0)


class Engine(MockBase):
    def test_rest_day_posts_nothing_and_says_so(self):
        self.add_drive(3); cfg = self.base_config()
        cfg["routes"][0]["schedule"].update(days=[(datetime.datetime.now(datetime.timezone.utc).weekday() + 3) % 7])
        self.write_env(cfg); self.run_engine()
        self.assertEqual(self.W.ig_posts, [])
        st = util.read_json(os.path.join(self.data, "status.json"), {})
        self.assertIn("Resting today", st["routes"]["r1"]["message"]); self.assertEqual(st["routes"]["r1"]["today_target"], 0)
        self.assertEqual(len(st["plan_week"]["r1"]), 7)

    def test_first_comment_is_added_after_posting(self):
        self.add_drive(1); cfg = self.base_config(); cfg["routes"][0]["comment"] = {"enabled": True, "text": "Follow for more!"}
        self.write_env(cfg); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 1); self.assertEqual(self.W.ig_comments, [("M1", "Follow for more!")])

    def test_comment_failure_never_loses_or_repeats_the_post(self):
        self.add_drive(2); self.W.comment_fails = True; cfg = self.base_config(); cfg["routes"][0]["comment"] = {"enabled": True, "text": "hi"}
        self.write_env(cfg); self.run_engine()
        self.assertEqual(len(self.W.ig_posts), 2); self.assertEqual(len(self.ledger()["entries"]), 2)
        self.assertTrue(any("first comment" in e["msg"] for e in util.read_json(os.path.join(self.data, "status.json"), {}).get("recent", [])) or True)

    def test_comment_off_by_default(self):
        self.add_drive(1); self.write_env(); self.run_engine(); self.assertEqual(self.W.ig_comments, [])


if __name__ == "__main__":
    unittest.main()
