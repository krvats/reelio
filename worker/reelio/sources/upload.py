"""Videos you add straight from the app land in uploads/<flow>/ inside the data repo."""
import os, glob, json, shutil, hashlib, datetime
from ..errors import ItemProblem


def _dir(store, route):
    return store.p("uploads", route["id"])


def _sidecar(video_path):
    """Optional <video>.json next to a video: original caption, source link, time added."""
    try:
        d = json.load(open(os.path.splitext(video_path)[0] + ".json", encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def list_items(src, store, route):
    out = []
    for f in sorted(glob.glob(os.path.join(_dir(store, route), "*")), key=os.path.getmtime):
        if not f.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv")):
            continue
        size = os.path.getsize(f)
        md5 = hashlib.md5(open(f, "rb").read()).hexdigest() if size < 60_000_000 else None
        side = _sidecar(f)
        created = side.get("added_at") or datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append({"key": f"upload:{os.path.basename(f)}", "name": os.path.basename(f), "size": size, "md5": md5, "created": created,
                    "meta": {k: side[k] for k in ("caption", "title", "source_url") if side.get(k)}})
    return out


def fetch(item, dest, store, route):
    p = os.path.join(_dir(store, route), item["name"])
    if not os.path.isfile(p):
        raise ItemProblem("The uploaded file is gone.", "Upload it again.")
    shutil.copyfile(p, dest)


def cleanup(item, store, route):
    """After a successful post, free the space in the data repo."""
    p = os.path.join(_dir(store, route), item["name"])
    for f in (p, os.path.splitext(p)[0] + ".json"):
        if os.path.isfile(f):
            os.remove(f)
