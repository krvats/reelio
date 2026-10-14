import datetime, unittest
from helpers import *
from reelio import scheduler, captions, crypto
from reelio.errors import instagram_error, AccountProblem, ItemProblem


class Units(unittest.TestCase):
    def test_slots_spread_inside_window(self):
        tz = scheduler.tzinfo("Asia/Kolkata")
        s = {"per_day": 50, "start": "08:00", "end": "23:00", "jitter": 0.25}
        slots = scheduler.day_slots(s, tz, datetime.date(2026, 10, 14), "r")
        self.assertEqual(len(slots), 50)
        loc = [x.astimezone(tz) for x in slots]
        self.assertTrue(all(8 <= x.hour < 23 or (x.hour == 23 and x.minute == 0) for x in loc))
        self.assertEqual(slots, sorted(slots))
        self.assertEqual(slots, scheduler.day_slots(s, tz, datetime.date(2026, 10, 14), "r"))   # same every run
        self.assertNotEqual(slots, scheduler.day_slots(s, tz, datetime.date(2026, 10, 15), "r"))

    def test_due_count(self):
        tz = scheduler.tzinfo("UTC")
        s = {"per_day": 10, "start": "10:00", "end": "20:00", "jitter": 0}
        t = datetime.datetime(2026, 10, 14, 15, 0, tzinfo=datetime.timezone.utc)
        due, slots = scheduler.due_count(s, tz, t, 0)
        self.assertEqual(due, 5)
        self.assertEqual(scheduler.due_count(s, tz, t, 5)[0], 0)
        self.assertEqual(scheduler.due_count(s, tz, t, 9)[0], 0)
        late = datetime.datetime(2026, 10, 14, 23, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(scheduler.due_count(s, tz, late, 4)[0], 6)
        self.assertEqual(scheduler.due_count(s, tz, late, 10)[0], 0)      # never more than per_day

    def test_per_day_capped_at_100(self):
        self.assertEqual(len(scheduler.day_slots({"per_day": 500}, scheduler.tzinfo("UTC"), datetime.date(2026, 1, 1))), 100)

    def test_crypto_roundtrip_and_wrong_key(self):
        b = crypto.encrypt({"a": {"x": "🙂"}}, "pw", iters=1000)
        self.assertEqual(crypto.decrypt(b, "pw"), {"a": {"x": "🙂"}})
        with self.assertRaises(ValueError):
            crypto.decrypt(b, "nope")
        self.assertNotIn("🙂", str(b))

    def test_captions(self):
        r = {"caption": {"mode": "same", "text": "Hi {name}", "template": "{title} #{n}", "hashtag_sets": ["#a", "#b"]}}
        it = {"name": "my_clip-1.mp4"}
        self.assertEqual(captions.build(r, it, 1)[0], "Hi my clip 1 #1\n\n#a")
        self.assertTrue(captions.build(r, it, 2)[0].endswith("#b"))
        self.assertEqual(captions.build(r, dict(it, caption_override="Custom 🎉"), 1)[0].split("\n")[0], "Custom 🎉 #1")
        r2 = {"caption": {"table": {"my_clip-1.mp4": "From table"}}}
        self.assertEqual(captions.build(r2, it, 1)[0], "From table")
        r3 = {"caption": {"text": "x " + " ".join(f"#t{i}" for i in range(40))}}
        self.assertLessEqual(captions.build(r3, it, 1)[0].count("#"), 30)
        r4 = {"caption": {"mode": "same", "text": "{oops"}}
        self.assertTrue(captions.build(r4, it, 1)[0])                      # stray braces never crash
        self.assertEqual(captions.youtube_title("a" * 150)[-8:], " #Shorts")
        self.assertLessEqual(len(captions.youtube_title("a" * 150)), 100)

    def test_instagram_error_mapping(self):
        p = instagram_error({"code": 4, "error_subcode": 1349210, "message": "Application request limit reached"})
        self.assertIsInstance(p, AccountProblem); self.assertEqual(p.kind, "rate"); self.assertGreater(p.cooldown_min, 0)
        self.assertEqual(instagram_error({"code": 190, "message": "x"}).kind, "token")
        self.assertIsInstance(instagram_error({"error_subcode": 2207026, "message": "bad"}), ItemProblem)
        self.assertEqual(instagram_error({"error_subcode": 2207042, "message": "x"}).kind, "quota")

    def test_secrets_scrubbed(self):
        util.register_secret("SUPERSECRETVALUE")
        self.assertNotIn("SUPERSECRETVALUE", util.scrub("boom SUPERSECRETVALUE and access_token=abc123"))
        self.assertNotIn("abc123", util.scrub("url?access_token=abc123&x=1"))


if __name__ == "__main__":
    unittest.main()
