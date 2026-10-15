"""The brain: one run = look at every flow, post what is due, remember everything, never crash."""
import os, time, uuid, hashlib, shutil, tempfile, traceback, datetime
from . import media, captions, scheduler
from .errors import Problem, ItemProblem, AccountProblem, SourceProblem, RunLimit
from .notify import Notifier
from .sources import get_source, download_url
from .targets import get_target
from . import util
from .util import now, iso, parse_iso, scrub, UTC
from . import hosting

MAX_FAILS = 3
STREAK_STOP = 3


class Engine:
    def __init__(self, store, budget_min=45, only_route=None, force_scan=False):
        self.store = store
        self.cfg = store.config()
        self.tz = scheduler.tzinfo(self.cfg.get("timezone"))
        self.t0 = time.time()
        self.deadline = self.t0 + budget_min * 60
        self.only = only_route
        self.force_scan = force_scan
        self.st = store.status()
        self.st.setdefault("accounts", {}); self.st.setdefault("routes", {}); self.st.setdefault("notified", {})
        try:
            self.notify = Notifier(store, self.cfg)
        except ValueError:
            self.cfg_no_notify = True
            self.notify = Notifier(store, {"notify": {}})      # secrets can't be unlocked: run() reports that clearly
        self.notify.state = self.st["notified"]
        self.posted_this_run = 0
        self.quota = {}          # account -> posts left today (cached per run)
        self.rate_slept = set()

    # ---------------------------------------------------------------- helpers
    def ev(self, level, msg, route=None, fix=None):
        self.store.event(level, msg, route, fix)

    def acct(self, cid):
        return self.st["accounts"].setdefault(cid, {})

    def time_left(self):
        return self.deadline - time.time()

    def conn_of(self, route):
        return self.store.conn(route["target"]["conn"])

    def target_key(self, route):
        t = route["target"]
        return f"{t['type']}:{t['conn']}"

    # ---------------------------------------------------------------- main
    def run(self):
        s = self.store
        started = iso()
        try:
            s.secrets()
        except ValueError as e:
            self.ev("error", str(e), fix="Set the REELIO_KEY secret to the passphrase you chose in the app.")
            self._finish(started, "needs_setup", str(e)); return False
        from . import license as lic
        self.lic = lic.check(s, self.cfg)
        self.st["license"] = {k: self.lic.get(k) for k in ("enforced", "active", "plan", "message")}
        self.ok_accounts = lic.allowed_accounts(self.cfg, self.lic["accounts"]) if self.lic["enforced"] and self.lic["active"] else None
        self.month_left = (self.lic["posts_month"] - lic.month_posts(s)) if self.lic["enforced"] else 10 ** 9
        if self.lic["enforced"] and not self.lic["active"]:
            self.cfg["paused"] = True
            self.ev("warn", self.lic["message"], fix="Open the Reelio app and choose a plan.")
        try:
            self.apply_inbox()
            self.recover()
            self.refresh_tokens()
            for route in self.cfg["routes"]:
                if self.only and route["id"] != self.only:
                    continue
                try:
                    self.run_route(route)
                except RunLimit:
                    self.ev("info", "Time budget reached; the next run continues from here.", route["id"]); break
                except Exception as e:     # a bug in one flow must never stop the others
                    self.ev("error", f"Unexpected problem in flow '{route.get('name')}': {scrub(e)}", route["id"], "Reelio will try again on the next run.")
                    print(scrub(traceback.format_exc()))
        finally:
            self.sweep()
            self.daily_summary()
            self._finish(started, "ok", "")
        return True

    def _finish(self, started, result, msg):
        self.build_status(started, result, msg)
        self.store.save_status(self.st)
        self.store.flush_events()
        self.store.sync("reelio: run summary")

    # ---------------------------------------------------------------- inbox commands from the app
    def apply_inbox(self):
        s = self.store
        for c in s.inbox():
            try:
                self._cmd(c)
            except Exception as e:
                self.ev("warn", f"Could not apply command {c.get('cmd')}: {scrub(e)}")
            s.inbox_done(c)

    def _cmd(self, c):
        s, cmd, rid, key = self.store, c.get("cmd"), c.get("route"), c.get("key")
        if cmd == "clear_cooldown":
            self.acct(c["account"]).pop("cooldown_until", None); self.acct(c["account"]).pop("problem", None); self.acct(c["account"])["rate_hits"] = 0
            return
        if not rid:
            return
        q = s.queue(rid)
        items = {i["key"]: i for i in q["items"]}
        if cmd == "rescan":
            q["last_scan"] = None
        elif cmd == "retry_all":
            for i in q["items"]:
                if i["status"] == "failed":
                    i.update(status="pending", fails=0, retry_after=None)
        elif key in items:
            it = items[key]
            if cmd == "skip": it["status"] = "skipped"
            elif cmd == "unskip": it["status"] = "pending"
            elif cmd == "retry": it.update(status="pending", fails=0, retry_after=None, last_error=None)
            elif cmd == "post_now": it.update(status="pending", post_now=True, fails=min(it.get("fails", 0), MAX_FAILS - 1), retry_after=None)
            elif cmd == "caption": it["caption_override"] = (c.get("text") or "").strip() or None
            elif cmd == "repost": it.update(status="pending", allow_repost=True, fails=0, retry_after=None)
        if cmd == "reorder":
            for n, k in enumerate(c.get("keys", [])):
                if k in items: items[k]["order"] = n
        s.save_queue(rid, q)

    # ---------------------------------------------------------------- crash recovery (never double-post, never leave orphans)
    def recover(self):
        led = self.store.ledger()
        for rid, j in list(led["inflight"].items()):
            route = next((r for r in self.cfg["routes"] if r["id"] == rid), None)
            try:
                if route:
                    self._recover_one(route, j)
            except Problem as p:
                self.ev("warn", f"Could not finish an interrupted post: {p.msg}", rid, p.fix)
                if isinstance(p, AccountProblem):
                    continue                      # keep the record, try again next run
            except Exception as e:
                self.ev("warn", f"Recovery problem: {scrub(e)}", rid)
            self.store.set_inflight(rid, None)

    def _recover_one(self, route, j):
        s = self.store
        t = route["target"]["type"]
        if j.get("pid"):
            try: hosting.Cloudinary(s.secret(s.host_conn(route))).delete(j["pid"])
            except Exception: pass
        if t == "instagram" and j.get("stage") == "ready":
            from .targets.instagram import Instagram
            ig = Instagram(self.conn_of(route), s.secret(route["target"]["conn"]))
            mid = link = None
            try:
                mid = ig.publish(j["cid"]); link = ig.permalink(mid)
            except ItemProblem:
                since = parse_iso(j.get("at")) or now()
                for m in ig.recent_media(10):
                    ts = parse_iso((m.get("timestamp") or "").replace("+0000", "+00:00"))
                    if ts and ts >= since - datetime.timedelta(minutes=3) and (m.get("caption") or "")[:40] == j.get("cap", "")[:40]:
                        mid, link = m["id"], m.get("permalink", ""); break
            if mid:
                self._ledger(route, {"key": j["src"], "name": j.get("name", j["src"]), "md5": j.get("md5")}, {"media_id": mid, "permalink": link, "container_id": j["cid"]}, j.get("title", ""))
                self._mark_posted(route, j["src"], mid, link)
                self.ev("ok", f"Finished a post that was interrupted last time: {j.get('name', j['src'])}", route["id"])
        elif t == "youtube" and j.get("stage") == "uploading":
            from .targets import youtube as yt
            found = yt.find_recent(s, route["target"]["conn"], j.get("title", ""), parse_iso(j.get("at")))
            if found:
                self._ledger(route, {"key": j["src"], "name": j.get("name", j["src"]), "md5": j.get("md5")}, {"media_id": found, "permalink": f"https://youtube.com/shorts/{found}", "container_id": ""}, j.get("title", ""))
                self._mark_posted(route, j["src"], found, "")

    def sweep(self):
        for c in self.cfg["connections"]:
            if c["kind"] == "cloudinary" and not self.store.ledger()["inflight"]:
                n = hosting.sweep(self.store.secret(c["id"]))
                if n: self.ev("info", f"Cleaned {n} leftover temporary file(s) from Cloudinary.")

    # ---------------------------------------------------------------- tokens
    def refresh_tokens(self):
        from .targets.instagram import Instagram
        for c in self.cfg["connections"]:
            if c["kind"] != "instagram":
                continue
            sec = self.store.secret(c["id"])
            a = self.acct(c["id"])
            if not sec.get("access_token"):
                continue
            last = parse_iso(sec.get("refreshed_at"))
            if not last or (now() - last).days >= 20:
                try:
                    r = Instagram(c, sec).refresh()
                except Problem:
                    r = None
                if r:
                    self.store.save_secret(c["id"], {"access_token": r[0], "refreshed_at": iso(), "expires_at": r[1]})
                    self.ev("info", f"Instagram login for {c.get('label', c['id'])} renewed for 60 days.")
                elif not last:
                    self.store.save_secret(c["id"], {"refreshed_at": iso()})   # try again in 20 days; token may be < 24h old
            exp = parse_iso(self.store.secret(c["id"]).get("expires_at"))
            a["token_expires"] = iso(exp) if exp else None
            if exp and (exp - now()).days < 7:
                self.notify.send("token", f"The Instagram login for {c.get('label', c['id'])} expires in {(exp - now()).days} days. Open Accounts and reconnect.", f"tok-{c['id']}", 24)

    # ---------------------------------------------------------------- one flow
    def run_route(self, route):
        s, rid = self.store, route["id"]
        rs = self.st["routes"].setdefault(rid, {})
        rs["name"] = route.get("name", rid)
        rs.pop("problem", None)
        if not route.get("enabled", True):
            rs["state"] = "disabled"; return
        conn = self.conn_of(route)
        if not conn or not self._has_secrets(route, conn):
            rs["state"] = "needs_setup"
            rs["message"] = "Connect the account(s) this flow uses."
            rs["problem"] = {"msg": "A required account is not connected yet.", "fix": "Open Accounts and finish connecting."}
            return
        if self.ok_accounts is not None and conn["id"] not in self.ok_accounts:
            rs["state"] = "needs_plan"; rs["message"] = "Your plan covers fewer accounts. Upgrade to turn this one on."
            rs["problem"] = {"msg": "This account is over your plan's limit.", "fix": "Open Settings, then Subscription, and upgrade."}
            return
        a = self.acct(conn["id"])
        cd = parse_iso(a.get("cooldown_until"))
        if cd and cd > now():
            rs["state"] = "cooldown"; rs["message"] = f"Waiting until {cd.astimezone(self.tz).strftime('%H:%M')} ({(a.get('problem') or {}).get('msg', '')})"
            rs["cooldown_until"] = iso(cd)
            self.scan(route, rs)       # scanning is harmless while waiting
            return
        rc = parse_iso(rs.get("route_cooldown"))
        if rc and rc > now():
            rs["state"] = "cooldown"; rs["message"] = f"Waiting until {rc.astimezone(self.tz).strftime('%H:%M')} ({(rs.get('problem') or {}).get('msg', '')})"
            return
        a.pop("cooldown_until", None)
        rs.pop("route_cooldown", None)
        q = self.scan(route, rs)
        if q is None:
            return
        paused = self.cfg.get("paused")
        sched = route.get("schedule") or {}
        today = now().astimezone(self.tz).date()
        done_today = s.posted_today(rid, self.tz, today)
        allowed, slots = scheduler.due_count(sched, self.tz, now(), done_today, rid)
        cap_day = min(int(sched.get("per_day", 10) or 10), scheduler.MAX_PER_DAY)
        rs["today_posted"], rs["today_target"] = done_today, cap_day
        rs["next_slot"] = iso(scheduler.next_slot(sched, self.tz, now(), done_today, rid))
        cands = self.candidates(route, q)
        rs["pending"] = sum(1 for i in q["items"] if i["status"] == "pending")
        rs["failed"] = sum(1 for i in q["items"] if i["status"] == "failed")
        rs["posted_total"] = sum(1 for i in q["items"] if i["status"] == "posted")
        want_now = [i for i in cands if i.get("post_now")]
        n = min(len(cands), max(allowed, len(want_now)), int(sched.get("max_per_run", 10) or 10))
        if paused:
            rs["state"] = "paused"; rs["message"] = (self.lic["message"] if self.lic["enforced"] and not self.lic["active"] else "Everything is paused."); return
        if self.month_left <= 0:
            rs["state"] = "needs_plan"; rs["message"] = "This month's posts for your plan are used up. Upgrade or wait for next month."; return
        n = min(n, max(self.month_left, 0)) if n else n
        if n <= 0:
            rs["state"] = "waiting" if cands else "idle"
            rs["message"] = "Next post at " + parse_iso(rs["next_slot"]).astimezone(self.tz).strftime("%H:%M") if cands else "Nothing waiting. Add videos to the source."
            return
        if route["target"]["type"] == "instagram":
            n = min(n, self.quota_left(route, conn))
            if n <= 0:
                rs["state"] = "cooldown"; rs["message"] = "Instagram's 24-hour limit is used up; resumes automatically."; return
        gap = max(int(sched.get("gap_seconds", 90) or 90), 60 if route["target"]["type"] == "instagram" else 10)
        streak, recent = 0, []
        posted = 0
        for it in cands[:n + 8]:        # a few extra in case some fail and we move on
            if posted >= n:
                break
            if self.time_left() < 360:
                raise RunLimit()
            if self.is_dup(route, it):
                it["status"] = "posted"; it["note"] = "Already posted earlier (never reposted)."
                s.save_queue(rid, q); continue
            res = self.post_one(route, conn, q, it, rs)
            if res == "ok":
                posted += 1; streak = 0; recent = []
                if posted < n:
                    self.wait_gap(gap)
            elif res == "item_fail":
                streak += 1; recent.append(it)
                if streak >= STREAK_STOP:
                    for x in recent:
                        x["fails"] = max(0, x.get("fails", 1) - 1)          # not the videos' fault
                    s.save_queue(rid, q)
                    p = rs.get("problem") or {"msg": "Three videos in a row failed.", "fix": "Open Help > Why is it failing?"}
                    rs["route_cooldown"] = iso(now() + datetime.timedelta(minutes=60)); rs["state"] = "cooldown"
                    rs["problem"] = {"msg": "Three videos in a row failed, which points to a setup problem, not the videos. " + p.get("msg", ""), "fix": p.get("fix", "")}
                    self.ev("error", rs["problem"]["msg"], rid, rs["problem"]["fix"])
                    self.notify.send("failed", f"{rs['name']}: Three videos in a row failed. {rs['problem']['fix']}", f"streak-{rid}", 3)
                    break
            else:                                                            # account/route level stop
                break
        self.refresh_counts(route, rs)
        if rs.get("state") not in ("cooldown",):
            rs["state"] = "ok"; rs["message"] = f"Posted {posted} now." if posted else "Nothing was due."

    def refresh_counts(self, route, rs):
        s = self.store
        q = s.queue(route["id"])
        today = now().astimezone(self.tz).date()
        done = s.posted_today(route["id"], self.tz, today)
        rs["today_posted"] = done
        rs["pending"] = sum(1 for i in q["items"] if i["status"] == "pending")
        rs["failed"] = sum(1 for i in q["items"] if i["status"] == "failed")
        rs["posted_total"] = sum(1 for i in q["items"] if i["status"] == "posted")
        rs["next_slot"] = iso(scheduler.next_slot(route.get("schedule") or {}, self.tz, now(), done, route["id"]))

    def is_dup(self, route, it):
        """Last-second duplicate guard: same source id or same file content already posted to this account."""
        if it.get("allow_repost"):
            return False
        posted = self.store.posted_keys(self.target_key(route))
        return it["key"] in posted or bool(it.get("md5") and "md5:" + it["md5"] in posted)

    def wait_gap(self, secs):
        waited = 0
        while waited < secs:
            if self.time_left() < 360:
                raise RunLimit()
            step = min(5, secs - waited)
            util.sleep(step); waited += step

    def _has_secrets(self, route, conn):
        s = self.store
        if not s.secret(conn["id"]):
            return False
        if route["target"]["type"] == "instagram" and not s.secret(s.host_conn(route)).get("api_secret"):
            return False
        return True

    def quota_left(self, route, conn):
        from .targets.instagram import Instagram
        cid = conn["id"]
        if cid not in self.quota:
            try:
                self.quota[cid] = Instagram(conn, self.store.secret(cid)).quota_left()
            except Problem as p:
                self.handle_account_problem(route, conn, p)
                self.quota[cid] = 0
        return self.quota[cid]

    # ---------------------------------------------------------------- scanning + queue
    def scan(self, route, rs):
        s, rid = self.store, route["id"]
        q = s.queue(rid)
        last = parse_iso(q.get("last_scan"))
        every = int((route.get("schedule") or {}).get("scan_every_min", 30))
        fresh = last and (now() - last).total_seconds() < every * 60
        if fresh and not self.force_scan:
            return q
        try:
            items = get_source(route["source"]["type"]).list_items(route["source"], s, route)
        except SourceProblem as p:
            self.route_problem(route, rs, p); return q if q["items"] else None
        except AccountProblem as p:
            self.route_problem(route, rs, p); return q if q["items"] else None
        except Problem as p:
            self.route_problem(route, rs, p); return q if q["items"] else None
        except Exception as e:
            self.ev("error", f"Could not read the source: {scrub(e)}", rid, "Reelio retries on the next run.")
            return q if q["items"] else None
        self.merge(route, q, items)
        q["last_scan"] = iso()
        s.save_queue(rid, q)
        return q

    def merge(self, route, q, items):
        s = self.store
        tk = self.target_key(route)
        posted = s.posted_keys(tk)
        by = {i["key"]: i for i in q["items"]}
        seen = set()
        for it in items:
            seen.add(it["key"])
            cur = by.get(it["key"])
            if not cur:
                cur = {"key": it["key"], "status": "pending", "fails": 0, "added_at": iso()}
                q["items"].append(cur); by[it["key"]] = cur
            for f in ("name", "md5", "size", "created", "thumb", "meta", "duration", "rank"):
                if it.get(f) is not None:
                    cur[f] = it[f]
            if it.get("md5"):
                s.backfill_md5(tk, it["key"], it["md5"])
                posted = s.posted_keys(tk)
            if cur["status"] == "missing":
                cur["status"] = "pending"
            if cur["status"] in ("pending", "failed") and not cur.get("allow_repost"):
                dup = it["key"] in posted or (it.get("md5") and "md5:" + it["md5"] in posted)
                if dup:
                    cur["status"] = "posted"; cur["note"] = "Already posted earlier (never reposted)."
            if it.get("empty") and cur["status"] == "pending":
                cur["status"] = "failed"
                cur["last_error"] = {"msg": "The file in the source is empty (0 bytes).", "fix": "Re-upload the original file.", "at": iso()}
        for cur in q["items"]:
            if cur["key"] not in seen and cur["status"] in ("pending", "failed"):
                cur["status"] = "missing"

    def candidates(self, route, q):
        order = (route.get("order") or "oldest")
        t = now()
        ok = []
        for i in q["items"]:
            if i["status"] != "pending" or i.get("fails", 0) >= MAX_FAILS:
                continue
            ra = parse_iso(i.get("retry_after"))
            if ra and ra > t and not i.get("post_now"):
                continue
            ok.append(i)

        def keyf(i):
            manual = i.get("order")
            base = {"oldest": i.get("created") or "", "newest": "", "random": hashlib.md5((route["id"] + i["key"]).encode()).hexdigest(),
                    "manual": ""}.get(order, i.get("created") or "")
            if order == "newest":
                return (0 if i.get("post_now") else 1, 0 if manual is not None else 1, manual if manual is not None else 0,
                        tuple(-ord(c) for c in (i.get("created") or "")))
            return (0 if i.get("post_now") else 1, 0 if manual is not None else 1, manual if manual is not None else 0, base)
        ok.sort(key=keyf)
        return ok

    # ---------------------------------------------------------------- backup Drive folder
    def _backup_items(self, route):
        """Videos sitting in the flow's backup Drive folder (listed once per run)."""
        cache = self.__dict__.setdefault("_bk_cache", {})
        rid = route["id"]
        if rid not in cache:
            src = route["source"]
            from .sources import drive
            try:
                cache[rid] = [i for i in drive.list_items({"conn": src.get("backup_conn") or "google", "folders": src.get("backup_folders") or []}, self.store, route) if not i.get("empty")]
            except Problem as p:
                self.ev("warn", f"Backup Drive folder could not be read: {p.msg}", rid, p.fix)
                cache[rid] = []
        return cache[rid]

    def _backup_match(self, route, it):
        """A backup file whose name contains the source video's id, or equals its name/title."""
        if "@" in it["key"]:        # a clip cut from a long video: a whole-file backup would not be the same clip
            return None
        vid = it["key"].split(":", 1)[-1].lower()
        names = {str(x).strip().lower() for x in (it.get("name"), (it.get("meta") or {}).get("title")) if x and len(str(x).strip()) >= 4}
        for f in self._backup_items(route):
            stem = os.path.splitext(f["name"])[0].strip().lower()
            if (len(vid) >= 4 and vid in stem) or stem in names:
                return f
        return None

    def fetch_with_backup(self, route, it, dest):
        s, src = self.store, route["source"]
        typ = src["type"]
        if not [f for f in (src.get("backup_folders") or []) if str(f).strip()] or typ in ("drive", "upload"):
            return get_source(typ).fetch(it, dest, s, route)
        hit = self._backup_match(route, it) if it.get("fails", 0) > 0 else None     # failed before: go straight to the backup copy
        if hit is None:
            try:
                return get_source(typ).fetch(it, dest, s, route)
            except Problem as e:
                if e.scope == "account":
                    raise
                hit = self._backup_match(route, it)
                if hit is None:
                    e.fix = (e.fix + " Or " if e.fix else "") + f"put the video in your backup Drive folder with its id '{it['key'].split(':', 1)[-1]}' in the file name, then tap Retry."
                    raise
        from .sources import drive
        drive.fetch({"key": hit["key"]}, dest, s, {"source": {"conn": src.get("backup_conn") or "google"}})
        self.ev("ok", f"Used the backup Drive copy for '{it.get('name')}'", route["id"])

    # ---------------------------------------------------------------- posting one video
    def post_one(self, route, conn, q, it, rs):
        s, rid = self.store, route["id"]
        tmp = tempfile.mkdtemp(prefix="reelio_")
        n = sum(1 for e in s.ledger()["entries"] if e.get("route") == rid) + 1
        cap, title = captions.build(route, it, n, now().astimezone(self.tz).strftime("%d %b %Y"))
        ctx = {"store": s, "route": route, "conn": conn, "deadline": self.deadline,
               "journal": lambda d, it=it, cap=cap, title=title: self._journal(route, it, cap, title, d)}
        try:
            src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out.mp4")
            self.fetch_with_backup(route, it, src)
            logo = music = None
            edit = route.get("edit") or {}
            wm = edit.get("watermark") or {}
            if wm.get("image"):
                logo = os.path.join(tmp, "logo"); download_url(wm["image"], logo)
            if (edit.get("audio") or {}).get("mode") == "music" and edit["audio"].get("music_url"):
                music = os.path.join(tmp, "music"); download_url(edit["audio"]["music_url"], music)
            media.prepare(src, out, edit, logo, music)
            os.remove(src)
            res = get_target(route["target"]["type"]).post(ctx, it, out, cap)
            self._ledger(route, it, res, title)
            self._mark_posted(route, it["key"], res["media_id"], res.get("permalink"), q)
            if route["source"]["type"] == "upload":
                from .sources import upload; upload.cleanup(it, s, route)
            s.set_inflight(rid, None)
            self.posted_this_run += 1
            self.acct(conn["id"])["rate_hits"] = 0
            if conn["id"] in self.quota: self.quota[conn["id"]] -= 1
            self.ev("ok", f"Posted '{it.get('name')}'", rid)
            self.notify.send("posted", f"Posted {it.get('name')} to {conn.get('label', conn['id'])}\n{res.get('permalink', '')}")
            s.sync(f"posted {it.get('name', '')[:40]}")
            return "ok"
        except RunLimit:
            s.set_inflight(rid, None); raise
        except AccountProblem as p:
            s.set_inflight(rid, None)
            if p.kind == "rate" and conn["id"] not in self.rate_slept and self.time_left() > 20 * 60:
                self.rate_slept.add(conn["id"])
                self.ev("warn", "Instagram asked us to slow down. Waiting 10 minutes, then trying again.", rid)
                util.sleep(600)
                return self.post_one(route, conn, q, it, rs)
            self.handle_account_problem(route, conn, p)
            return "account"
        except SourceProblem as p:
            s.set_inflight(rid, None); self.route_problem(route, rs, p); return "route"
        except ItemProblem as p:
            return self.item_failed(route, q, it, p.as_dict(), rs)
        except Exception as e:
            print(scrub(traceback.format_exc()))
            return self.item_failed(route, q, it, {"msg": f"Unexpected problem: {scrub(e)[:200]}", "fix": "Tap Retry. If it repeats, open Help > Why is it failing?"}, rs)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _journal(self, route, it, cap, title, d):
        j = dict(d, route=route["id"], name=it.get("name"), md5=it.get("md5"), cap=cap[:60], title=title)
        self.store.set_inflight(route["id"], j)
        if d.get("stage") == "ready":
            self.store.sync("journal: about to publish")

    def item_failed(self, route, q, it, err, rs):
        s = self.store
        it["fails"] = it.get("fails", 0) + 1
        it["last_error"] = dict(err, at=iso())
        it["retry_after"] = iso(now() + datetime.timedelta(minutes=20 * it["fails"]))
        if it["fails"] >= MAX_FAILS:
            it["status"] = "failed"
            self.notify.send("failed", f"{route.get('name')}: '{it.get('name')}' failed 3 times and was set aside.\n{err['msg']}\n{err.get('fix', '')}", f"fail-{it['key']}", 24)
        rs["problem"] = err
        s.set_inflight(route["id"], None)
        s.save_queue(route["id"], q)
        self.ev("warn", f"'{it.get('name')}' failed ({it['fails']}/{MAX_FAILS}): {err['msg']}", route["id"], err.get("fix"))
        return "item_fail"

    def handle_account_problem(self, route, conn, p):
        a = self.acct(conn["id"])
        a["problem"] = p.as_dict()
        rs = self.st["routes"].setdefault(route["id"], {})
        rs["state"] = "cooldown" if p.cooldown_min else "needs_setup"
        rs["problem"] = p.as_dict()
        if p.kind == "rate":
            a["rate_hits"] = a.get("rate_hits", 0) + 1
            mins = min(30 * 2 ** (a["rate_hits"] - 1), 360)
        else:
            mins = p.cooldown_min or 24 * 60            # needs the owner: wait a day, then re-check
        a["cooldown_until"] = iso(now() + datetime.timedelta(minutes=mins))
        self.ev("error", f"{conn.get('label', conn['id'])}: {p.msg}", route["id"], p.fix)
        kind = {"rate": "limit", "quota": "limit", "token": "token"}.get(p.kind, "failed")
        self.notify.send(kind, f"{conn.get('label', conn['id'])}: {p.msg}\n{p.fix}", f"acct-{conn['id']}-{p.kind}", 6)

    def route_problem(self, route, rs, p):
        rs["problem"] = p.as_dict()
        mins = p.cooldown_min or 60
        rs["route_cooldown"] = iso(now() + datetime.timedelta(minutes=mins)); rs["state"] = "cooldown"
        self.ev("error", f"{route.get('name')}: {p.msg}", route["id"], p.fix)
        self.notify.send("failed", f"{route.get('name')}: {p.msg}\n{p.fix}", f"route-{route['id']}-{p.kind}", 6)

    # ---------------------------------------------------------------- ledger
    def _ledger(self, route, it, res, title):
        s = self.store
        self.month_left -= 1
        s.add_ledger({"id": uuid.uuid4().hex[:12], "route": route["id"], "target": self.target_key(route), "src": it["key"], "md5": it.get("md5"),
                      "name": it.get("name"), "media_id": res.get("media_id"), "permalink": res.get("permalink", ""), "container_id": res.get("container_id", ""),
                      "title": title[:120], "at": iso(), "status": "posted" if res.get("media_id") else "unknown_id"})

    def _mark_posted(self, route, key, mid, link, q=None):
        q = q if q is not None else self.store.queue(route["id"])
        for i in q["items"]:
            if i["key"] == key:
                i.update(status="posted", media_id=mid, permalink=link, posted_at=iso(), last_error=None, post_now=False, allow_repost=False)
        self.store.save_queue(route["id"], q)

    # ---------------------------------------------------------------- summary
    def daily_summary(self):
        t = now().astimezone(self.tz)
        if t.hour < 22 or self.st.get("daily_sent") == t.date().isoformat():
            return
        total = sum(self.store.posted_today(r["id"], self.tz, t.date()) for r in self.cfg["routes"])
        if self.notify.send("daily", f"Today Reelio posted {total} video(s)."):
            self.st["daily_sent"] = t.date().isoformat()

    def build_status(self, started, result, msg):
        s = self.store
        st = self.st
        st["run"] = {"started": started, "finished": iso(), "seconds": int(time.time() - self.t0), "result": result, "posted": self.posted_this_run, "message": msg}
        st["paused"] = bool(self.cfg.get("paused"))
        st["version"] = 1
        for c in self.cfg["connections"]:
            a = self.acct(c["id"])
            a["label"] = c.get("label", c["id"]); a["kind"] = c["kind"]
            try:
                a["connected"] = bool(s.secret(c["id"]))
            except ValueError:
                a["connected"] = False
            cd = parse_iso(a.get("cooldown_until"))
            if cd and cd <= now():
                a.pop("cooldown_until", None)
                if a.get("problem", {}).get("kind") != "token":
                    a.pop("problem", None)
            a["ok"] = a["connected"] and not a.get("problem")
        todo, today = [], now().astimezone(self.tz).date()
        plan = {}
        for r in self.cfg["routes"]:
            rs = st["routes"].setdefault(r["id"], {})
            if r.get("enabled", True):
                slots = scheduler.day_slots(r.get("schedule") or {}, self.tz, today, r["id"])
                done = rs.get("today_posted", s.posted_today(r["id"], self.tz, today))
                plan[r["id"]] = [{"at": iso(x), "state": "done" if k < done else ("due" if x <= now() else "later")} for k, x in enumerate(slots)]
        st["plan"] = plan
        for rid in list(st["routes"]):
            if not any(r["id"] == rid for r in self.cfg["routes"]):
                st["routes"].pop(rid)
        for r in self.cfg["routes"]:
            rs = st["routes"][r["id"]]
            nm = r.get("name", r["id"])
            if rs.get("today_posted") is not None:
                todo.append({"kind": "done", "text": f"{nm}: {rs['today_posted']} of {rs.get('today_target')} posted today."})
            if rs.get("pending"):
                todo.append({"kind": "pending", "text": f"{nm}: {rs['pending']} videos are waiting in line."})
            if rs.get("problem") and rs.get("state") in ("needs_setup", "cooldown"):
                todo.append({"kind": "action", "text": f"{nm}: {rs['problem'].get('msg', '')} {rs['problem'].get('fix', '')}".strip()})
        for cid, a in st["accounts"].items():
            exp = parse_iso(a.get("token_expires"))
            if exp and (exp - now()).days < 10:
                todo.append({"kind": "action", "text": f"{a.get('label', cid)}: login expires in {(exp - now()).days} days. Reconnect it in Accounts."})
        if not self.cfg["routes"]:
            todo.append({"kind": "action", "text": "Create your first flow: pick where videos come from and where they go."})
        st["todo"] = todo
        st["recent"] = s.recent_events(25) + [e for e in s._events][-25:]
