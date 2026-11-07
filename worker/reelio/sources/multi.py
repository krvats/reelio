"""Mix of sources: several pages (Instagram profiles, YouTube channels, playlists ...) plus the video links you pasted yourself,
all feeding ONE flow. Each page is read on its own, so one page that fails never stops the others. Items remember which page they
came from (meta.from, src_i) so 'Take turns between my pages' can rotate fairly.

    source: {type:'multi', rights:true, net_conn?, sources:[{type:'page', url, max_items, backlog}, ..., {type:'links'}]}
Only pages you own or have permission to reuse."""
import copy
from ..errors import SourceProblem, Problem
from ..util import scrub
from . import page, links

MAX_PAGES = 12


def _label(child, i):
    if child.get("type") == "links":
        return "my links"
    from .. import igarchive
    u = child.get("url") or ""
    return igarchive.user_of(u) or u.split("//")[-1].split("/")[0] or f"page {i + 1}"


def list_items(src, store, route):
    kids = [c for c in (src.get("sources") or []) if isinstance(c, dict)][:MAX_PAGES]
    if not kids:
        raise SourceProblem("No pages or links were added to this flow.", "Edit the flow and add at least one page link.", cooldown_min=60, kind="config")
    out, seen, errors, ok = [], set(), [], 0
    for i, child in enumerate(kids):
        typ = child.get("type") or "page"
        label = _label(child, i)
        try:
            if typ == "links":
                items = links.list_items({}, store, route)
            elif typ == "page":
                sub = copy.deepcopy(route)
                sub["id"] = f"{route['id']}~{i}"                      # each page keeps its own "already there" memory
                csrc = dict(child, net_conn=src.get("net_conn", "youtube-net"))
                items = page.list_items(csrc, store, sub)
            else:
                continue
        except Problem as p:
            errors.append(p); continue
        except Exception as e:
            errors.append(SourceProblem(f"Could not read {label}: {scrub(e)[:150]}", "Reelio retries on the next run.", cooldown_min=30, kind="blocked")); continue
        ok += 1
        for it in items:
            if it["key"] in seen:
                continue
            seen.add(it["key"])
            it["src_i"] = i
            it.setdefault("meta", {})["from"] = label
            out.append(it)
    if not ok and errors:
        raise errors[0]
    return out


def fetch(item, dest, store, route):
    return links.fetch(item, dest, store, route)


def cleanup(item, store, route):
    links.cleanup(item, store, route)
