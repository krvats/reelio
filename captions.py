"""Caption builder: one text for all, a per-video table, templates, rotating hashtag sets, variants."""
import os, re

MAX_CAPTION = 2200


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def build(route, item, n, today=""):
    cap = route.get("caption") or {}
    stem = os.path.splitext(item.get("name", ""))[0].replace("_", " ").replace("-", " ").strip()
    meta = item.get("meta") or {}
    orig = (meta.get("caption") or meta.get("description") or "").strip()
    table = cap.get("table") or {}
    title = ""
    if item.get("caption_override"):
        title = item["caption_override"]
    elif table.get(item.get("name")) or table.get(stem):
        title = table.get(item.get("name")) or table.get(stem)
    else:
        mode = cap.get("mode", "same")
        variants = [v for v in (cap.get("variants") or []) if str(v).strip()]
        if mode == "original":
            title = orig or meta.get("title") or stem
        elif mode == "filename":
            title = stem
        elif variants:
            title = variants[(n - 1) % len(variants)]
        else:
            title = cap.get("text") or meta.get("title") or stem
    tpl = cap.get("template") or "{title}"
    vars_ = _Safe(name=stem, n=n, orig=orig, date=today)
    if cap.get("mode", "same") in ("same",) and not item.get("caption_override"):
        try:
            title = title.format_map(vars_)          # {n}, {name}, {date} also work inside the main text
        except Exception:
            pass
    try:
        text = tpl.format_map(_Safe(title=title, **vars_))
    except Exception:
        text = title
    sets = [s for s in (cap.get("hashtag_sets") or []) if str(s).strip()]
    if sets:
        tags = sets[(n - 1) % len(sets)] if cap.get("rotate_hashtags", True) else sets[0]
        if tags.strip() and tags.strip() not in text:
            text = text.rstrip() + "\n\n" + tags.strip()
    # Instagram allows at most 30 hashtags
    tags_found = list(re.finditer(r"#\w+", text))
    if len(tags_found) > 30:
        text = text[: tags_found[30].start()].rstrip()
    return text[:MAX_CAPTION], title


def youtube_title(text, shorts=True):
    first = (text or "").strip().split("\n")[0]
    first = re.sub(r"\s+", " ", first)
    suffix = " #Shorts" if shorts and "#shorts" not in first.lower() else ""
    first = first[: 100 - len(suffix)].rstrip()
    return (first or "Video") + suffix
