"""Sources list videos and know how to fetch one into a local file. An item is:
   {key:'drive:<id>', name, md5?, size?, created?, thumb?, meta:{...}}"""
import os
from ..util import http, HttpFail
from ..errors import ItemProblem


def download_url(url, dest, headers=None, params=None, tries=3):
    last = None
    for i in range(tries):
        try:
            r = http("GET", url, retries=2, timeout=(30, 180), headers=headers or {}, params=params, stream=True)
            if r.status_code >= 400:
                raise ItemProblem(f"Could not download the video (HTTP {r.status_code}).", "Check the file still exists and is shared with the connected account.")
            with open(dest, "wb") as f:
                for ch in r.iter_content(1 << 20):
                    if ch:
                        f.write(ch)
            if os.path.getsize(dest) < 1024:
                raise ItemProblem("The video file is empty (under 1 KB).", "Re-upload the original file, or skip it.")
            return
        except ItemProblem:
            raise
        except (HttpFail, OSError) as e:
            last = e
    raise ItemProblem(f"Download kept failing: {last}", "Usually temporary. Reelio retries on the next run.")


def get_source(stype):
    from . import drive, youtube, instagram, upload, links
    return {"drive": drive, "youtube": youtube, "instagram": instagram, "upload": upload, "links": links}[stype]
