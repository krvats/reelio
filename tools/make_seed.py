#!/usr/bin/env python3
"""Turns your old ig-pipeline / yt-pipeline folders into Reelio's starting data (settings + the never-repost ledger).
It copies ONLY non-secret facts (folder id, filter, caption, limits, which videos are already posted).
Tokens, API keys and client secrets are never read into the output.
Usage: python make_seed.py --ig path/to/ig-pipeline --yt path/to/yt-pipeline --out reelio-data-seed"""
import argparse, json, os, re, csv, datetime

ap = argparse.ArgumentParser()
ap.add_argument("--ig"); ap.add_argument("--yt"); ap.add_argument("--out", default="reelio-data-seed")
ap.add_argument("--per-day", type=int, default=50)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
J = lambda p: json.load(open(p, encoding="utf-8"))
cfg = {"version": 1, "paused": False, "timezone": "Asia/Kolkata",
       "notify": {"telegram": {"enabled": False, "conn": "telegram", "events": {"posted": False, "failed": True, "limit": True, "token": True, "daily": True}}},
       "connections": [{"id": "google", "kind": "google", "label": "Google (Drive + YouTube)"},
                       {"id": "cloudinary", "kind": "cloudinary", "label": "Cloudinary (video host)"},
                       {"id": "telegram", "kind": "telegram", "label": "Telegram alerts"},
                       {"id": "youtube-net", "kind": "ytnet", "label": "YouTube downloads (cookies)"}],
       "routes": []}
ledger = {"entries": [], "inflight": {}}
queues = {}
stamp = lambda s: datetime.datetime.fromisoformat(s).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if s else None

if a.ig:
    old = J(os.path.join(a.ig, "config.json"))
    state = J(os.path.join(a.ig, "state.json")) if os.path.exists(os.path.join(a.ig, "state.json")) else {}
    for job in old.get("jobs", [old]):
        name = job.get("name", "default"); cid = "ig_" + re.sub(r"\W", "", name)
        cfg["connections"].insert(0, {"id": cid, "kind": "instagram", "label": name, "ig_user_id": str(job.get("ig_user_id", ""))})
        src = job.get("source", {})
        folders = src.get("folders") or ([src["folder"]] if src.get("folder") else [])
        rid = re.sub(r"\W", "", name).lower() or "default"
        cfg["routes"].append({
            "id": rid, "name": f"Drive to {name}", "enabled": True,
            "source": {"type": "drive", "conn": "google", "folders": folders},
            "target": {"type": "instagram", "conn": cid}, "share_to_feed": job.get("share_to_feed", True),
            "schedule": {"per_day": a.per_day, "start": "08:00", "end": "23:00", "jitter": 0.25, "max_per_run": 10, "gap_seconds": max(int(job.get("gap_seconds", 90)), 90), "scan_every_min": 30},
            "caption": {"mode": "same", "text": job.get("default_title", ""), "template": job.get("caption_template", "{title}")},
            "edit": {"filter": job.get("filter", "none"), "strength": job.get("filter_strength", 1.0), "fit": "keep", "audio": {"mode": "keep"}},
            "order": "oldest"})
        for src_id, d in (state.get(name, {}).get("done", {})).items():
            ledger["entries"].append({"id": f"mig{len(ledger['entries']):04d}", "route": rid, "target": f"instagram:{cid}", "src": f"drive:{src_id}", "md5": None,
                                      "name": d.get("name"), "media_id": d.get("media_id"), "permalink": d.get("permalink", ""), "container_id": "",
                                      "title": "", "at": stamp(d.get("at")) or "2026-10-14T00:00:00Z", "status": "posted"})

if a.yt:
    ch = open(os.path.join(a.yt, "channel.txt")).read().strip() if os.path.exists(os.path.join(a.yt, "channel.txt")) else ""
    handle = ch.rstrip("/").split("/")[-1] if ch else ""
    st = J(os.path.join(a.yt, "state.json")) if os.path.exists(os.path.join(a.yt, "state.json")) else {}
    cfg["routes"].append({
        "id": "shorts-to-youtube", "name": f"{handle or 'YouTube'} Shorts to my YouTube channel", "enabled": True,
        "source": {"type": "youtube", "handle": handle, "include": "shorts", "conn": "google", "net_conn": "youtube-net"},
        "target": {"type": "youtube", "conn": "google"}, "youtube": {"privacy": "public", "shorts": True},
        "schedule": {"per_day": 6, "start": "08:00", "end": "22:00", "jitter": 0.25, "max_per_run": 3, "gap_seconds": 60, "scan_every_min": 60},
        "caption": {"mode": "original", "text": ""}, "edit": {"filter": "none", "fit": "keep", "audio": {"mode": "keep"}}, "order": "oldest"})
    uploaded = set()
    for name in st.get("done", []):
        m = re.match(r"^\d{8}_(.+)\.mp4$", name)
        if m:
            uploaded.add(m.group(1))
            ledger["entries"].append({"id": f"mig{len(ledger['entries']):04d}", "route": "shorts-to-youtube", "target": "youtube:google", "src": f"youtube:{m.group(1)}", "md5": None,
                                      "name": m.group(1), "media_id": None, "permalink": "", "container_id": "", "title": "", "at": "2026-10-13T00:00:00Z", "status": "unknown_id"})
    seen = []
    if os.path.exists(os.path.join(a.yt, "done.txt")):
        seen = [l.split()[1] for l in open(os.path.join(a.yt, "done.txt")) if len(l.split()) == 2]
    # videos the old tool downloaded but we cannot prove were uploaded: set aside, so nothing can be uploaded twice by accident
    queues["shorts-to-youtube"] = {"last_scan": None, "items": [
        {"key": f"youtube:{v}", "name": v, "status": "skipped", "fails": 0, "note": "Downloaded by the old tool but not confirmed as uploaded. Tap 'Use again' if you want it posted."}
        for v in seen if v not in uploaded]}

json.dump(cfg, open(os.path.join(a.out, "config.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
json.dump(ledger, open(os.path.join(a.out, "ledger.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
for rid, q in queues.items():
    os.makedirs(os.path.join(a.out, "queues"), exist_ok=True)
    json.dump(q, open(os.path.join(a.out, "queues", rid + ".json"), "w", encoding="utf-8"), indent=1)
print(f"seed written to {a.out}: {len(cfg['routes'])} flows, {len(ledger['entries'])} already-posted videos remembered")
