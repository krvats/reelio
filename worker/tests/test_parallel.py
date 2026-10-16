import os, json, threading, types, unittest
from helpers import *
from reelio import engine as engine_mod, live as live_mod, util


class ParallelAndLive(MockBase):
    def accounts(self, n=2, per_route=None):
        cfg = self.base_config(); names = "abcdef"
        sec = {}
        for i in range(1, n):
            cid = f"ig_{names[i]}"; tok = f"IGTOK{names[i].upper()}"
            self.W.ig_accounts[tok] = str(222 + i * 111)
            cfg["connections"].append({"id": cid, "kind": "instagram", "label": f"Account {names[i].upper()}", "ig_user_id": self.W.ig_accounts[tok]})
            sec[cid] = {"access_token": tok, "refreshed_at": util.iso()}
        cfg["routes"] = [self.route(f"r{i}", "ig_a" if i == 0 else f"ig_{names[i]}", **(per_route or {})) for i in range(n)]
        self.write_env(cfg, sec)
        return cfg

    def test_accounts_post_in_parallel_lanes_and_nothing_is_lost(self):
        self.add_drive(4); self.accounts(4)
        seen, orig = set(), engine_mod.Engine.post_one
        def spy(self_, *a, **k):
            seen.add(threading.get_ident()); return orig(self_, *a, **k)
        engine_mod.Engine.post_one = spy
        try:
            self.run_engine()
        finally:
            engine_mod.Engine.post_one = orig
        self.assertGreaterEqual(len(seen), 2, "accounts must run in separate threads")
        self.assertEqual(len(self.W.ig_posts), 16)                      # 4 accounts x 4 videos
        led = self.ledger()["entries"]
        self.assertEqual(len(led), 16); self.assertEqual(len({e["id"] for e in led}), 16)
        for rid in ("r0", "r1", "r2", "r3"):
            self.assertEqual(len([e for e in led if e["route"] == rid]), 4)
        self.assertEqual(self.W.cdn, {})

    def test_one_failing_account_does_not_stop_the_others_in_parallel(self):
        self.add_drive(3); self.accounts(3)
        self.W.rate_limited_tokens.add("IGTOKA")
        self.run_engine()
        self.assertTrue(all(p["uid"] != "111" for p in self.W.ig_posts))
        self.assertEqual(len(self.W.ig_posts), 6)

    def test_live_pass_posts_one_per_account_then_respects_the_pause(self):
        self.add_drive(5); self.accounts(2)
        e = self.engine(live=True); e.run()
        self.assertEqual(len(self.W.ig_posts), 2)                        # one each
        e = self.engine(live=True); e.run()
        self.assertEqual(len(self.W.ig_posts), 2, "the pause between posts of one account is kept")
        t = util.now() + datetime.timedelta(seconds=70); util.set_clock(lambda: t)
        e = self.engine(live=True); e.run()
        self.assertEqual(len(self.W.ig_posts), 4)

    def test_post_now_goes_out_in_the_next_pass_even_inside_the_pause(self):
        self.add_drive(3); self.accounts(2)
        self.engine(live=True).run()
        self.assertEqual(len(self.W.ig_posts), 2)
        q = self.queue("r0"); key = next(i["key"] for i in q["items"] if i["status"] == "pending")
        os.makedirs(os.path.join(self.data, "inbox"), exist_ok=True)
        util.write_json(os.path.join(self.data, "inbox", "1.json"), {"cmd": "post_now", "route": "r0", "key": key})
        t = util.now() + datetime.timedelta(seconds=8); util.set_clock(lambda: t)
        self.engine(live=True).run()
        self.assertEqual(len(self.W.ig_posts), 3)
        self.assertEqual({i["key"]: i for i in self.queue("r0")["items"]}[key]["status"], "posted")

    def test_live_loop_keeps_going_and_never_double_posts(self):
        self.add_drive(6); self.accounts(2)
        clock = {"t": 1000.0}
        def tick():
            clock["t"] += 20; return clock["t"]
        fake = types.SimpleNamespace(time=tick, sleep=lambda s: None)
        orig = live_mod.time; live_mod.time = fake
        try:
            passes = live_mod.run(Store(self.data), 12, poll=0, sleeper=lambda s: None)
        finally:
            live_mod.time = orig
        self.assertGreaterEqual(passes, 2)
        self.assertEqual(len(self.W.ig_posts), 2)                        # fixed test clock: the 60 s pause holds, so one each, never twice
        keys = [(e["target"], e["src"]) for e in self.ledger()["entries"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_quiet_live_passes_do_not_rewrite_status_every_time(self):
        self.add_drive(0); self.accounts(2)
        st = Store(self.data)                       # the always-on loop keeps ONE store for all its passes
        engine_mod.Engine(st, 300, live=True).run()
        before = os.path.getmtime(os.path.join(self.data, "status.json"))
        import time; time.sleep(0.05)
        engine_mod.Engine(st, 300, live=True).run()
        self.assertEqual(before, os.path.getmtime(os.path.join(self.data, "status.json")))


if __name__ == "__main__":
    unittest.main()
