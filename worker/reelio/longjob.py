"""Long videos: a separate workflow for videos of ANY length (20 minutes to 24+ hours), fully in the cloud.

One long video = one job (queues/long/<video id>.json). The job is cut into PARTS no longer than the part length
you choose. Each part is downloaded by itself (only its own time range, never the whole video) and uploaded to
YouTube, then deleted from the runner. So the disk never holds more than one part, a failure only repeats one part,
and a 24 hour video simply becomes six 4-hour videos named "Title (Part 1/6)" ...

Safety rules (same spirit as the rest of Reelio):
- Parts run one after another. A part is marked done only after YouTube confirms the upload.
- A run that is killed mid-part is recovered next time: the channel is checked first so nothing is uploaded twice.
- When the run's time is nearly over it stops cleanly and the workflow starts the next run by itself.
- YouTube blocking the server pauses all long downloads for 3 hours; an upload limit pauses only that channel.
"""
import os, re, json, math, glob, shutil, tempfile, subprocess, datetime
from .util import http, env_base, iso, now, parse_iso, read_json, write_json, scrub, say, sleep, HttpFail
from .errors import Problem, AccountProblem, ItemProblem, SourceProblem, youtube_error
from .google import GoogleAuth
from .sources import youtube as ysrc
from .targets import youtube as ytt

UPLOAD = lambda: env_base("YT_UPLOAD", "https://www.googleapis.com/upload/youtube/v3")
API = lambda: env_base("YT_API", "https://www.googleapis.com/youtube/v3")
MAX_TRIES = 3
MIN_TIME_LEFT_MIN = 25          # do not start a new part with less than this left in the run
GB_PER_HOUR = {"480": 0.6, "720": 1.1, "1080": 2.2, "1440": 5.0, "2160": 10.0}
DEFAULTS = {"conn": "google", "net_conn": "youtube-net", "part_hours": 4, "quality": "720", "privacy": "private", "category": "22",
            "title_template": "{title} (Part {n}/{total})", "description": "{title}\n\nPart {n} of {total}", "tags": []}


# ------------------------------------------------------------------ files
def _dir(store):
    d = store.p("queues", "long"); os.makedirs(d, exist_ok=True); return d


def load_jobs(store):
    out = []
    for f in sorted(glob.glob(os.path.join(_dir(store), "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        j = read_json(f, None)
        if isinstance(j, dict) and j.get("parts"):
            out.append(j)
    return out


def job_status(job):
    if job.get("cancelled"):
        return "cancelled"
    ps = [p["status"] for p in job["parts"]]
    if all(s == "done" for s in ps):
        return "done"
    if any(s in ("pending", "downloading", "uploading") for s in ps):
        return "running" if any(s != "pending" for s in ps) else "queued"
    return "failed"


def save_job(store, job):
    job["status"] = job_status(job)
    job["updated"] = iso()
    write_json(os.path.join(_dir(store), f"{job['id']}.json"), job)


def _state(store):
    return read_json(os.path.join(_dir(store), "_state.json"), None) or {}


def _save_state(store, st):
    st["updated"] = iso()
    write_json(os.path.join(_dir(store), "_state.json"), st)


def _checkpoint(store, msg):
    store.flush_events()
    store.sync(msg)


# ------------------------------------------------------------------ planning
def plan_parts(duration, part_hours):
    """Equal-sized parts, none longer than part_hours. A 5h video with 4h parts becomes 2 x 2.5h (no tiny leftover)."""
    dur = int(duration)
    cap = max(900, int(float(part_hours) * 3600))
    n = max(1, math.ceil(dur / cap))
    size = math.ceil(dur / n)
    parts = []
    for i in range(n):
        a, b = i * size, min((i + 1) * size, dur)
        if b > a:
            parts.append({"n": i + 1, "start": a, "end": b, "status": "pending", "fails": 0})
    return parts


def _clean_settings(raw):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (raw or {}).items() if v not in (None, "")})
    try:
        s["part_hours"] = min(8.0, max(0.5, float(s["part_hours"])))
    except Exception:
        s["part_hours"] = 4
    s["quality"] = str(s["quality"]) if str(s["quality"]) in GB_PER_HOUR else "720"
    if s["privacy"] not in ("private", "unlisted", "public"):
        s["privacy"] = "private"
    if isinstance(s["tags"], str):
        s["tags"] = [t.strip() for t in s["tags"].split(",") if t.strip()]
    s["tags"] = s["tags"][:15]
    return s


# ------------------------------------------------------------------ reading video info (no download)
def _resolve(store, src, vid):
    p, notes = ysrc._pool_run(store, src, ysrc._ytdlp() + ["--dump-json", "--no-playlist", "--skip-download", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"]
                              + ysrc._net_args(store, src))
    ysrc._say(store, None, notes)
    try:
        d = json.loads(p.stdout.splitlines()[0])
    except Exception:
        ysrc.raise_for_failure(p.stderr or "could not read the video", store, src)
    return {"id": vid, "title": d.get("title") or vid, "duration": int(d.get("duration") or 0), "upload_date": d.get("upload_date") or "",
            "live": d.get("live_status") in ("is_live", "is_upcoming")}


def _add(store, c):
    s = _clean_settings(c.get("settings"))
    src = {"net_conn": s["net_conn"], "conn": s["conn"]}
    ids = []
    for line in re.split(r"[\s,]+", "\n".join(c.get("links") or []) if isinstance(c.get("links"), list) else (c.get("links") or "")):
        v = ysrc._vid_id(line)
        if v and v not in ids:
            ids.append(v)
    ch = c.get("channel") or {}
    metas = {}
    if (ch.get("handle") or "").strip():
        min_s = int(float(ch.get("min_minutes", 20) or 20) * 60)
        want = max(1, min(int(ch.get("max_videos", 3) or 3), 50))
        tabs = {"videos": ["/videos"], "streams": ["/streams"]}.get(ch.get("tab"), ["/videos", "/streams"])
        found = []
        for tab in tabs:
            lst = ysrc._list_ytdlp({"handle": ch["handle"], "tabs": [tab], "net_conn": s["net_conn"], "max_seconds": min_s}, store, "long")
            found += [i["name"] for i in lst[:max(10, want * 3)]]
        for v in found[:80]:
            try:
                m = _resolve(store, src, v)
            except Problem as p:
                store.event("warn", f"Could not read video {v}: {p.msg}", fix=p.fix); continue
            if m["live"] or m["duration"] < min_s:
                continue
            metas[v] = m
        newest = sorted(metas.values(), key=lambda m: m["upload_date"], reverse=True)[:want]
        for m in newest:
            if m["id"] not in ids:
                ids.append(m["id"])
    made = 0
    for v in ids:
        path = os.path.join(_dir(store), f"{v}.json")
        old = read_json(path, None)
        if old and not old.get("cancelled"):
            store.event("info", f"Long video {v} is already in the list, so it was not added again."); continue
        try:
            m = metas.get(v) or _resolve(store, src, v)
        except Problem as p:
            store.event("warn", f"Could not read video {v}: {p.msg}", fix=p.fix); continue
        if m["live"]:
            store.event("warn", f"'{m['title']}' is live right now. Add it again after the stream has ended."); continue
        if m["duration"] < 60:
            store.event("warn", f"'{m['title']}' is shorter than a minute. Use a normal flow for Shorts."); continue
        job = {"id": v, "url": f"https://www.youtube.com/watch?v={v}", "title": m["title"], "duration": m["duration"], "created": iso(),
               "settings": s, "parts": plan_parts(m["duration"], s["part_hours"]), "cancelled": False}
        save_job(store, job); made += 1
        store.event("info", f"Long video added: '{m['title']}' ({_hms(m['duration'])}) in {len(job['parts'])} part(s).")
    if not made and not ids:
        store.event("warn", "No video links or channel were given, so nothing was added.")
    return made


def intake(store):
    d = store.p("long-inbox")
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        c = read_json(f, None)
        try:
            if isinstance(c, dict):
                cmd = c.get("cmd")
                if cmd == "add":
                    _add(store, c)
                elif cmd in ("cancel", "retry", "remove"):
                    _control(store, cmd, c.get("id"))
        except Problem as p:
            store.event("error", f"Long videos: {p.msg}", fix=p.fix)
        except Exception as e:
            store.event("error", f"Long videos: could not read the request ({scrub(e)}).")
        finally:
            try: os.remove(f)
            except OSError: pass


def _control(store, cmd, jid):
    path = os.path.join(_dir(store), f"{jid}.json")
    job = read_json(path, None)
    if not job:
        return
    if cmd == "remove":
        os.remove(path); return
    if cmd == "cancel":
        job["cancelled"] = True
    if cmd == "retry":
        job["cancelled"] = False
        for p in job["parts"]:
            if p["status"] == "failed":
                p.update(status="pending", fails=0, retry_after=None, last_error=None, interrupted=0)
        st = _state(store); st.get("conn_until", {}).pop(job["settings"]["conn"], None); st["source_until"] = None; _save_state(store, st)
    save_job(store, job)


# ------------------------------------------------------------------ one part
def _hms(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _fill(tpl, job, part, total):
    return (tpl.replace("{title}", job["title"]).replace("{n}", str(part["n"])).replace("{total}", str(total))
            .replace("{url}", job["url"]).replace("{id}", job["id"]))


def part_title(job, part):
    total, s = len(job["parts"]), job["settings"]
    clean = re.sub(r"[<>]", "", job["title"]).strip() or job["id"]
    tpl = s["title_template"] if total > 1 else "{title}"
    full = _fill(tpl, dict(job, title=clean), part, total)
    if len(full) > 100:                          # keep the "(Part n/N)" ending, shorten only the title
        over = len(full) - 100 + 1
        short = clean[:max(5, len(clean) - over)].rstrip() + "…"
        full = _fill(tpl, dict(job, title=short), part, total)
    return full[:100]


def _download(store, job, part, tmp, deadline):
    s = job["settings"]
    need = (part["end"] - part["start"]) / 3600 * GB_PER_HOUR[s["quality"]] * 2.2 * 1e9
    free = shutil.disk_usage(tmp).free
    if free < need:
        raise ItemProblem(f"Not enough disk space on the runner for this part (needs about {need / 1e9:.0f} GB, has {free / 1e9:.0f} GB).",
                          "Use shorter parts or a lower quality for this video, then tap Retry.")
    q = s["quality"]
    fmt = f"bv*[height<={q}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={q}]+ba/b[height<={q}]/b"
    src = {"net_conn": s["net_conn"]}
    cmd = ysrc._ytdlp() + ["-f", fmt, "--merge-output-format", "mp4/mkv", "--no-playlist", "--no-warnings", "-N", "4", "--retries", "10",
                           "--fragment-retries", "10", "-o", os.path.join(tmp, "v.%(ext)s"), job["url"]]
    if len(job["parts"]) > 1:
        cmd += ["--download-sections", f"*{part['start']}-{part['end']}"]
    cmd += ysrc._net_args(store, src)
    left = max(120, int((deadline - now()).total_seconds()))
    try:
        (p, files), notes = ysrc.download_with_pool(store, src, cmd, tmp, timeout=left)
        ysrc._say(store, None, notes)
    except subprocess.TimeoutExpired:
        raise ItemProblem("The download did not finish before this run ran out of time.", "Reelio tries again in the next run. Use shorter parts if it keeps happening.")
    if p.returncode != 0 or not files:
        ysrc.raise_for_failure(p.stderr, store, src)
    return os.path.join(tmp, files[0])


def _chunk_size():
    return int(os.environ.get("REELIO_CHUNK", 64 * 1024 * 1024))


def _upload(store, conn_id, path, body, deadline):
    """Resumable upload in chunks: after any hiccup we ask YouTube how much arrived and continue from there."""
    size = os.path.getsize(path)
    auth = GoogleAuth(store.secret(conn_id))
    try:
        r = http("POST", f"{UPLOAD()}/videos", params={"uploadType": "resumable", "part": "snippet,status"}, retries=3,
                 headers=dict(auth.headers(), **{"X-Upload-Content-Type": "video/*", "X-Upload-Content-Length": str(size),
                                                 "Content-Type": "application/json; charset=UTF-8"}), data=json.dumps(body))
    except HttpFail as e:
        raise ItemProblem(f"Could not reach YouTube: {e}", "Usually temporary. Reelio retries.")
    if r.status_code >= 400:
        raise youtube_error(r.status_code, _j(r))
    session = r.headers.get("Location")
    if not session:
        raise ItemProblem("YouTube did not start the upload.", "Retry later.")
    chunk, offset, bad = _chunk_size(), 0, 0
    with open(path, "rb") as f:
        while offset < size:
            if now() > deadline + datetime.timedelta(minutes=20):
                raise ItemProblem("The upload did not finish before this run ran out of time.", "Reelio tries this part again in the next run.")
            end = min(offset + chunk, size) - 1
            f.seek(offset)
            data = f.read(end - offset + 1)
            try:
                resp = http("PUT", session, retries=1, timeout=(30, 600), data=data,
                            headers={"Content-Length": str(len(data)), "Content-Range": f"bytes {offset}-{end}/{size}", "Content-Type": "video/*"})
            except HttpFail:
                resp = None
            if resp is not None and resp.status_code in (200, 201):
                return _j(resp).get("id", "")
            if resp is not None and resp.status_code == 308:
                new = _next_offset(resp, offset, end)
                bad = 0 if new > offset else bad + 1          # no progress at all counts as trouble
                offset = new
                if bad > 8:
                    raise ItemProblem("The upload to YouTube made no progress.", "Reelio tries this part again later. Nothing was published twice.")
                continue
            if resp is not None and 400 <= resp.status_code < 500 and resp.status_code != 404:
                raise youtube_error(resp.status_code, _j(resp))
            bad += 1                                  # network trouble, 5xx or a lost session: ask how much arrived
            if bad > 8:
                raise ItemProblem("The upload to YouTube kept failing.", "Reelio tries this part again later. Nothing was published twice.")
            sleep(min(60, 3 * bad * bad))
            try:
                q = http("PUT", session, retries=1, headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
            except HttpFail:
                continue
            if q.status_code in (200, 201):
                return _j(q).get("id", "")
            if q.status_code == 308:
                offset = _next_offset(q, offset, offset - 1)
    raise ItemProblem("YouTube did not confirm the upload.", "Reelio checks the channel before trying again, so nothing is posted twice.")


def _next_offset(resp, offset, sent_end):
    m = re.match(r"bytes=0-(\d+)", resp.headers.get("Range", "") or "")
    return int(m.group(1)) + 1 if m else (sent_end + 1 if sent_end >= offset else 0)


def _j(r):
    try:
        return r.json()
    except Exception:
        return {}


def _check_processing(store, conn_id, vid):
    """YouTube rejects over-15-minute uploads from channels that are not phone-verified, after the upload."""
    try:
        sleep(20)
        auth = GoogleAuth(store.secret(conn_id))
        r = http("GET", f"{API()}/videos", headers=auth.headers(), params={"part": "status", "id": vid}, retries=2)
        it = (_j(r).get("items") or [None])[0]
        st = (it or {}).get("status") or {}
        if st.get("uploadStatus") == "rejected" or st.get("failureReason"):
            why = st.get("rejectionReason") or st.get("failureReason") or "rejected"
            if why in ("uploadLimit", "uploadLimitExceeded", "length", "tooLong"):
                raise ItemProblem("YouTube rejected the video because it is longer than 15 minutes and this channel is not verified.",
                                  "Verify the channel with your phone number at youtube.com/verify, then tap Retry.")
            raise ItemProblem(f"YouTube rejected the video ({why}).", "Open YouTube Studio to see why, then tap Retry.")
    except ItemProblem:
        raise
    except Exception:
        pass


def _do_part(store, job, part, deadline, ctx):
    s = job["settings"]
    GoogleAuth(store.secret(s["conn"])).headers()      # fail fast (before hours of downloading) if Google is not connected
    tmp = tempfile.mkdtemp(prefix="long_")
    try:
        part.update(status="downloading", started_at=iso())
        save_job(store, job); _checkpoint(store, "reelio: long video downloading")
        path = _download(store, job, part, tmp, deadline)
        part["status"] = "uploading"
        save_job(store, job); _checkpoint(store, "reelio: long video uploading")
        total = len(job["parts"])
        title = part_title(job, part)
        body = {"snippet": {"title": title, "description": _fill(s["description"], job, part, total)[:4900], "tags": s["tags"], "categoryId": str(s["category"])},
                "status": {"privacyStatus": s["privacy"], "selfDeclaredMadeForKids": False}}
        vid = _upload(store, s["conn"], path, body, deadline)
        if not vid:
            vid = ytt.find_recent(store, s["conn"], title, parse_iso(part.get("started_at"))) or ""
        _check_processing(store, s["conn"], vid) if vid else None
        part.update(status="done", video_id=vid, url=f"https://youtu.be/{vid}" if vid else "", at=iso(), last_error=None, fails=0)
        store.event("info", f"Uploaded {title} ({_hms(part['end'] - part['start'])}).")
        ctx["notify"]("info", f"Long video: uploaded {title}", None)
    except Problem:
        part["status"] = "pending"
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _recover(store, job):
    """A run that was killed leaves a part half done. Check whether it actually reached YouTube before trying again."""
    for part in job["parts"]:
        if part["status"] not in ("downloading", "uploading"):
            continue
        found = ""
        if part["status"] == "uploading":
            try:
                found = ytt.find_recent(store, job["settings"]["conn"], part_title(job, part), parse_iso(part.get("started_at"))) or ""
            except Exception:
                found = ""
        if found:
            part.update(status="done", video_id=found, url=f"https://youtu.be/{found}", at=iso())
            store.event("info", f"Part {part['n']} of '{job['title']}' had reached YouTube before the last run stopped; marked as done.")
            continue
        part["interrupted"] = part.get("interrupted", 0) + 1
        if part["interrupted"] >= MAX_TRIES:
            part.update(status="failed", last_error={"msg": "This part could not finish within one run.", "fix": "Use shorter parts or a lower quality, then tap Retry.", "at": iso()})
        else:
            part["status"] = "pending"
    save_job(store, job)


# ------------------------------------------------------------------ the run
def run(store, budget_min=320):
    from .notify import Notifier
    deadline = now() + datetime.timedelta(minutes=budget_min)
    cfg = store.config()
    try:
        nt = Notifier(store, cfg)
    except Exception:
        nt = None
    ctx = {"notify": lambda kind, text, key=None: nt.send(kind, text, key=key, ttl_hours=6 if key else 0) if nt else False}
    intake(store)
    jobs = load_jobs(store)
    for j in jobs:
        _recover(store, j)
    st = _state(store)
    more = False
    t = now()
    src_wait = parse_iso(st.get("source_until"))
    stop_all = bool(src_wait and src_wait > t)
    for job in sorted(jobs, key=lambda j: j.get("created") or ""):
        if stop_all:
            break
        if job.get("cancelled") or job_status(job) in ("done", "failed"):
            continue
        conn = job["settings"]["conn"]
        cw = parse_iso((st.get("conn_until") or {}).get(conn))
        if cw and cw > now():
            continue
        for part in job["parts"]:
            if part["status"] != "pending" or part.get("fails", 0) >= MAX_TRIES:
                continue
            ra = parse_iso(part.get("retry_after"))
            if ra and ra > now():
                continue
            if (deadline - now()).total_seconds() < MIN_TIME_LEFT_MIN * 60:
                more = True; stop_all = True; break
            try:
                _do_part(store, job, part, deadline, ctx)
            except SourceProblem as p:
                st["source_until"] = iso(now() + datetime.timedelta(minutes=p.cooldown_min or 180))
                store.event("warn", f"Long videos paused: {p.msg}", fix=p.fix)
                ctx["notify"]("failed", f"Long videos paused. {p.msg} {p.fix}", "long-source")
                stop_all = True; break
            except AccountProblem as p:
                st.setdefault("conn_until", {})[conn] = iso(now() + datetime.timedelta(minutes=p.cooldown_min or 60))
                store.event("warn", f"Long videos for this channel paused: {p.msg}", fix=p.fix)
                ctx["notify"]("limit" if p.kind == "quota" else "token", f"Long videos paused. {p.msg} {p.fix}", "long-" + conn)
                break
            except ItemProblem as p:
                part["fails"] = part.get("fails", 0) + 1
                part["last_error"] = {"msg": p.msg, "fix": p.fix, "at": iso()}
                if part["fails"] >= MAX_TRIES:
                    part["status"] = "failed"
                    ctx["notify"]("failed", f"Long video part {part['n']} of '{job['title']}' failed: {p.msg} {p.fix}")
                else:
                    part["retry_after"] = iso(now() + datetime.timedelta(minutes=20 * part["fails"]))
                store.event("error", f"Part {part['n']} of '{job['title']}': {p.msg}", fix=p.fix)
            except Exception as e:
                part["fails"] = part.get("fails", 0) + 1
                part["last_error"] = {"msg": f"Unexpected problem: {scrub(e)}", "fix": "Reelio will retry.", "at": iso()}
                if part["fails"] >= MAX_TRIES:
                    part["status"] = "failed"
                store.event("error", f"Part {part['n']} of '{job['title']}': {scrub(e)}")
            save_job(store, job); _checkpoint(store, "reelio: long video progress")
        if job_status(job) == "done":
            ctx["notify"]("info", f"Long video finished: {job['title']} ({len(job['parts'])} part(s)).")
    _save_state(store, st)
    for j in jobs:
        save_job(store, j)
    _checkpoint(store, "reelio: long videos")
    say("long videos: " + ("more work waiting, the next run continues" if more else "nothing more to do right now"))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"more={'true' if more else 'false'}\n")
    return more
