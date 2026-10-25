"""'Why is it failing?' - tests every connection and tells the owner the exact fix, in plain words. Publishes nothing."""
import os, subprocess, tempfile, shutil, shlex
from .util import iso, scrub
from .errors import Problem
from . import media, hosting


def run(store):
    checks = []

    def add(id, title, ok, detail="", fix=""):
        checks.append({"id": id, "title": title, "ok": bool(ok), "detail": scrub(detail), "fix": fix if not ok else ""})

    add("ffmpeg", "Video converter (ffmpeg)", shutil.which("ffmpeg") and shutil.which("ffprobe"), "found" if shutil.which("ffmpeg") else "missing",
        "Nothing for you to do: GitHub's server includes it. Re-run; if it persists tell the developer.")
    try:
        sec = store.secrets()
        add("unlock", "Secrets unlock with your passphrase", True, f"{len(sec)} saved")
    except ValueError as e:
        add("unlock", "Secrets unlock with your passphrase", False, str(e), "In GitHub: Settings > Secrets > REELIO_KEY must equal the passphrase you typed in the app.")
        return _save(store, checks)
    cfg = store.config()
    for c in cfg["connections"]:
        k, cid, label = c["kind"], c["id"], c.get("label", c["id"])
        s = store.secret(cid)
        if not s:
            add(cid, f"{label}", False, "no login saved", "Open Accounts and connect it.")
            continue
        try:
            if k == "instagram":
                from .targets.instagram import Instagram
                ig = Instagram(c, s); me = ig.me()
                bad = me.get("account_type") not in ("BUSINESS", "MEDIA_CREATOR")
                add(cid, f"{label} (Instagram)", not bad, f"@{me.get('username')} · {me.get('account_type')} · {me.get('media_count')} posts",
                    "Switch the Instagram account to a Professional (Creator or Business) account in the Instagram app settings.")
                try:
                    add(cid + "-quota", f"{label}: posts left in the last 24 hours", True, str(ig.quota_left()))
                except Problem as p:
                    add(cid + "-quota", f"{label}: posting allowance", False, p.msg, p.fix)
            elif k == "google":
                from .google import GoogleAuth
                GoogleAuth(s).headers()
                detail = "login works"
                try:
                    from .targets import youtube
                    detail += f" · YouTube channel: {youtube.whoami(store, cid)}"
                except Exception:
                    detail += " · no YouTube channel found (fine if you only use Drive)"
                add(cid, f"{label} (Google)", True, detail)
            elif k == "google_save":
                from .google import GoogleAuth
                GoogleAuth(s).headers()
                add(cid, f"{label} (Google Drive for Save to Drive)", True, "login works")
            elif k == "cloudinary":
                add(cid, f"{label} (video host)", *_cloudinary(s))
            elif k == "telegram":
                from .util import http
                from .notify import TG
                r = http("GET", f"{TG()}/bot{s.get('bot_token')}/getMe", retries=1, timeout=15)
                add(cid, f"{label} (Telegram)", r.status_code == 200, "bot reachable" if r.status_code == 200 else f"HTTP {r.status_code}",
                    "Re-paste the bot token from @BotFather in Accounts.")
            else:
                add(cid, label, True, "saved")
        except Problem as p:
            add(cid, label, False, p.msg, p.fix)
        except Exception as e:
            add(cid, label, False, str(e)[:200], "Open Accounts and reconnect it.")
    from .sources import get_source
    for r in cfg["routes"]:
        if not r.get("enabled", True):
            continue
        try:
            items = get_source(r["source"]["type"]).list_items(r["source"], store, r)
            add("src-" + r["id"], f"{r.get('name', r['id'])}: source", True, f"{len(items)} videos found")
        except Problem as p:
            add("src-" + r["id"], f"{r.get('name', r['id'])}: source", False, p.msg, p.fix)
        except Exception as e:
            add("src-" + r["id"], f"{r.get('name', r['id'])}: source", False, str(e)[:200], "Check the flow's source settings.")
    from .sources import drive as _drive
    for r in cfg["routes"]:
        bk = [f for f in (r["source"].get("backup_folders") or []) if str(f).strip()]
        if not r.get("enabled", True) or not bk:
            continue
        t = f"{r.get('name', r['id'])}: backup Drive folder"
        try:
            n = len(_drive.list_items({"conn": r["source"].get("backup_conn") or "google", "folders": bk}, store, r))
            add("bk-" + r["id"], t, True, f"{n} videos found")
        except Problem as p:
            add("bk-" + r["id"], t, False, p.msg, p.fix)
        except Exception as e:
            add("bk-" + r["id"], t, False, str(e)[:200], "Check the backup folder link and that it is shared with the connected Google account.")
    yt = [r for r in cfg["routes"] if r.get("enabled", True) and r["source"].get("type") == "youtube"]
    if yt:
        from .cookiepool import Pool
        src = yt[0]["source"]; n = Pool(store, src).summary(); where = src.get("net_conn", "youtube-net")
        t = "YouTube cookies (used when YouTube blocks downloads)"
        if not n["total"]:
            add("ytcookies", t, False, f"0 cookies found in '{where}'", "The worker sees no cookies. Open Accounts > YouTube downloads, add them again, then run Check again.")
        elif n["parked"] == n["total"]:
            add("ytcookies", t, False, f"{n['total']} saved, all logged out", "These logins ended. Export fresh cookies from a private window and add them.")
        else:
            add("ytcookies", t, n["ready"] > 0, f"{n['total']} saved: {n['ready']} ready, {n['resting']} resting, {n['parked']} logged out",
                "" if n["ready"] else "All are resting after YouTube refused them. YouTube blocks many cloud servers even with cookies; the reliable fix is the backup Drive folder.")
    return _save(store, checks)


def _cloudinary(sec):
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "t.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1", "-pix_fmt", "yuv420p", p], check=True)
        c = hosting.Cloudinary(sec)
        url, pid = c.upload(p)
        c.delete(pid)
        return True, "upload and delete test passed", ""
    except Problem as e:
        return False, e.msg, e.fix
    except Exception as e:
        return False, str(e)[:150], "Check the three Cloudinary values in Accounts."
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _save(store, checks):
    bad = [c for c in checks if not c["ok"]]
    out = {"at": iso(), "ok": not bad, "checks": checks,
           "verdict": "Everything is connected and working." if not bad else f"{len(bad)} thing(s) need attention. Start with: {bad[0]['title']}. {bad[0]['fix']}"}
    from .util import write_json
    write_json(store.p("diagnose.json"), out)
    return out
