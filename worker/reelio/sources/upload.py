"""Videos you add straight from the app land in uploads/<flow>/ inside the data repo."""
import os, glob, shutil, hashlib, datetime
from ..errors import ItemProblem


def _dir(store, route):
    return store.p("uploads", route["id"])


def list_items(src, store, route):
    out = []
    for f in sorted(glob.glob(os.path.join(_dir(store, route), "*")), key=os.path.getmtime):
        if not f.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv")):
            continue
        size = os.path.getsize(f)
        md5 = hashlib.md5(open(f, "rb").read()).hexdigest() if size < 60_000_000 else None
        out.append({"key": f"upload:{os.path.basename(f)}", "name": os.path.basename(f), "size": size, "md5": md5,
                    "created": datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "meta": {}})
    return out


def fetch(item, dest, store, route):
    p = os.path.join(_dir(store, route), item["name"])
    if not os.path.isfile(p):
        raise ItemProblem("The uploaded file is gone.", "Upload it again.")
    shutil.copyfile(p, dest)


def cleanup(item, store, route):
    """After a successful post, free the space in the data repo."""
    p = os.path.join(_dir(store, route), item["name"])
    if os.path.isfile(p):
        os.remove(p)
