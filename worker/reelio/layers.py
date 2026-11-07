"""Overlay layers for a flow's look. The reel is always the bottom layer; everything in `edit.layers` is stacked on top, in order.

    edit = {
      "canvas": {"bg": "#000000"},                       # colour behind the reel when it does not fill the screen
      "reel_box": {"x": 50, "y": 52, "w": 86, "h": 62, "fit": "cover"},   # optional: put the reel inside a window (centre x,y and size, in %)
      "layers": [
        {"id": "a", "type": "frame", "color": "#ffffff", "opacity": 1, "radius": 36, "window": {"x": 50, "y": 52, "w": 86, "h": 62}},
        {"id": "b", "type": "image", "src": "asset:frame.png", "full": true, "opacity": 1},                    # a PNG with transparent parts
        {"id": "c", "type": "image", "src": "https://.../logo.png", "x": 85, "y": 8, "w": 18, "rotate": 0, "opacity": 0.9},
        {"id": "d", "type": "box", "x": 50, "y": 90, "w": 90, "h": 8, "color": "#000000", "opacity": 0.5},
        {"id": "e", "type": "text", "text": "{title}", "font": "sans-bold", "size": 64, "color": "#111111", "x": 50, "y": 52, "clip_to": "a"}
      ]}

All positions are the CENTRE of the thing, in percent of a 1080x1920 screen. `clip_to` = id of a frame / full-screen picture layer: the
layer then shows ONLY where that layer is transparent (the "window"). Text can use {title} {n} {date} {author} {views} {likes}.
Nothing here ever raises on bad input: unknown or broken layers are dropped, numbers are clamped.
"""
import os, re, shutil, subprocess
from .errors import ItemProblem

W, H = 1080, 1920
MAX_LAYERS = 12
TYPES = ("frame", "image", "box", "text")

FONTS = {   # key -> (label, candidate files). The first one that exists is used; DejaVu is the guaranteed fallback.
    "sans-bold": ("Sans bold", ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"]),
    "sans": ("Sans", ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]),
    "serif-bold": ("Serif bold", ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf"]),
    "mono-bold": ("Typewriter", ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf"]),
    "clean-bold": ("Clean bold", ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]),
    "clean-serif": ("Book", ["/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf"]),
    "narrow-bold": ("Narrow bold", ["/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSansNarrow-Bold.ttf"]),
    "rounded-bold": ("Rounded bold", ["/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]),
    "hindi": ("Hindi (Devanagari)", ["/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
                                    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"]),
}
_HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONTS["sleek-light"] = ("Sleek light", [os.path.join(_HERE, "Poppins-Light.ttf"), "/usr/share/fonts/truetype/google-fonts/Poppins-Light.ttf",
                                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"])
FONTS["sleek"] = ("Sleek", [os.path.join(_HERE, "Poppins-Medium.ttf"), "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
                            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"])
DEFAULT_FONT = "sans-bold"


def font_path(key, custom=None):
    if custom and os.path.exists(custom):
        return custom
    for k in (key, DEFAULT_FONT):
        for p in FONTS.get(k, FONTS[DEFAULT_FONT])[1]:
            if os.path.exists(p):
                return p
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------------ cleaning input
def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def _hex(v, default="#ffffff"):
    v = str(v or "").strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
        return "0x" + v.lstrip("#").upper()
    if re.fullmatch(r"#?[0-9a-fA-F]{3}", v):
        c = v.lstrip("#"); return "0x" + "".join(ch * 2 for ch in c).upper()
    return "0x" + default.lstrip("#").upper()


def normalize(layers):
    """Return a cleaned list of layer dicts (unknown / empty ones dropped, numbers clamped, ids unique)."""
    out, ids = [], set()
    for i, l in enumerate((layers or [])[:MAX_LAYERS]):
        if not isinstance(l, dict) or l.get("type") not in TYPES or l.get("hidden"):
            continue
        t = l["type"]
        lid = re.sub(r"[^A-Za-z0-9_-]", "", str(l.get("id") or f"l{i}"))[:20] or f"l{i}"
        while lid in ids:
            lid += "x"
        ids.add(lid)
        c = {"id": lid, "type": t, "opacity": _num(l.get("opacity", 1), 0, 1, 1), "start": _num(l.get("start", 0), 0, 3600, 0),
             "end": _num(l.get("end", 0), 0, 3600, 0)}
        if t == "frame":
            w = l.get("window") or {}
            c.update(color=_hex(l.get("color"), "#ffffff"), radius=_num(l.get("radius", 0), 0, 400, 0),
                     window={"x": _num(w.get("x", 50), 0, 100, 50), "y": _num(w.get("y", 50), 0, 100, 50), "w": _num(w.get("w", 80), 1, 100, 80), "h": _num(w.get("h", 50), 1, 100, 50)})
        elif t == "image":
            if not str(l.get("src") or "").strip():
                continue
            c.update(src=str(l["src"]).strip(), full=bool(l.get("full")), x=_num(l.get("x", 50), -50, 150, 50), y=_num(l.get("y", 50), -50, 150, 50),
                     w=_num(l.get("w", 30), 1, 200, 30), rotate=_num(l.get("rotate", 0), -360, 360, 0))
        elif t == "box":
            c.update(color=_hex(l.get("color"), "#000000"), x=_num(l.get("x", 50), -50, 150, 50), y=_num(l.get("y", 50), -50, 150, 50),
                     w=_num(l.get("w", 50), 1, 200, 50), h=_num(l.get("h", 10), 1, 200, 10))
        else:  # text
            txt = str(l.get("text") or "")[:400]
            if not txt.strip():
                continue
            st, sh, bx = l.get("stroke") or {}, l.get("shadow") or {}, l.get("box") or {}
            c.update(text=txt, font=l.get("font") if l.get("font") in FONTS or l.get("font") == "custom" else DEFAULT_FONT, font_src=str(l.get("font_src") or "").strip(),
                     size=_num(l.get("size", 64), 12, 400, 64), color=_hex(l.get("color"), "#ffffff"), x=_num(l.get("x", 50), -50, 150, 50),
                     y=_num(l.get("y", 50), -50, 150, 50), wrap=_num(l.get("wrap", 80), 10, 100, 80), align=l.get("align") if l.get("align") in ("left", "center", "right") else "center",
                     spacing=_num(l.get("spacing", 8), -20, 100, 8), fade_in=_num(l.get("fade_in", 0), 0, 30, 0), fade_out=_num(l.get("fade_out", 0), 0, 30, 0),
                     stroke={"w": _num(st.get("w", 0), 0, 30, 0), "color": _hex(st.get("color"), "#000000")},
                     shadow={"x": _num(sh.get("x", 0), -30, 30, 0), "y": _num(sh.get("y", 0), -30, 30, 0), "color": _hex(sh.get("color"), "#000000"), "opacity": _num(sh.get("opacity", 0.6), 0, 1, 0.6)},
                     box={"on": bool(bx.get("on")), "color": _hex(bx.get("color"), "#000000"), "opacity": _num(bx.get("opacity", 0.5), 0, 1, 0.5), "pad": _num(bx.get("pad", 16), 0, 100, 16)},
                     clip_to=re.sub(r"[^A-Za-z0-9_-]", "", str(l.get("clip_to") or ""))[:20])
        out.append(c)
    return out


def reel_box(edit):
    b = (edit or {}).get("reel_box")
    if not isinstance(b, dict):
        return None
    w, h = _num(b.get("w", 100), 5, 100, 100), _num(b.get("h", 100), 5, 100, 100)
    return {"x": _num(b.get("x", 50), 0, 100, 50), "y": _num(b.get("y", 50), 0, 100, 50), "w": w, "h": h, "fit": "contain" if b.get("fit") == "contain" else "cover"}


def wants_layers(edit):
    return bool(normalize((edit or {}).get("layers")) or reel_box(edit))


def canvas_bg(edit):
    return _hex(((edit or {}).get("canvas") or {}).get("bg"), "#000000")


# ------------------------------------------------------------------ assets
def asset_refs(edit):
    """[(layer_id, src)] of pictures and [(layer_id, font_src)] of custom fonts that must be fetched before rendering."""
    out = []
    for l in normalize((edit or {}).get("layers")):
        if l["type"] == "image":
            out.append((l["id"], l["src"]))
        if l["type"] == "text" and l["font"] == "custom" and l["font_src"]:
            out.append(("font:" + l["id"], l["font_src"]))
    return out


def resolve_assets(edit, store, tmp, download):
    """Fetch every picture / custom font into `tmp`. `asset:name` reads the data repo's assets/ folder, http(s) is downloaded. -> {id: path}"""
    paths = {}
    for lid, src in asset_refs(edit):
        dest = os.path.join(tmp, "asset_" + re.sub(r"[^A-Za-z0-9_-]", "", lid))
        if src.startswith("asset:"):
            name = os.path.basename(src[6:])
            p = store.p("assets", name)
            if not os.path.isfile(p):
                raise ItemProblem(f"The overlay picture '{name}' is missing.", "Open the flow, Look and sound, and upload the picture again.")
            shutil.copyfile(p, dest)
        elif src.startswith("https://"):
            try:
                download(src, dest)
            except ItemProblem:
                raise ItemProblem("An overlay picture or font link could not be downloaded.", "Check the link opens in a browser, or upload the picture in the flow instead.")
        else:
            raise ItemProblem("An overlay picture link must start with https:// or be uploaded in the app.", "Edit the flow's overlays.")
        paths[lid] = dest
    return paths


# ------------------------------------------------------------------ text helpers
class _Vars(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def fill(text, variables):
    try:
        return str(text).format_map(_Vars({k: ("" if v is None else v) for k, v in (variables or {}).items()}))
    except (ValueError, IndexError, KeyError, AttributeError):
        return str(text)


def wrap_text(text, size, wrap_pct):
    """ffmpeg's drawtext never wraps, so wrap by an estimated glyph width (about 0.56 x size for bold sans)."""
    per = max(4, int((W * wrap_pct / 100.0) / (size * 0.56)))
    lines = []
    for para in str(text).replace("\r", "").split("\n"):
        cur = ""
        for word in para.split(" "):
            if cur and len(cur) + 1 + len(word) > per:
                lines.append(cur); cur = word
            else:
                cur = (cur + " " + word).strip() if cur else word
        lines.append(cur)
    return "\n".join(lines)


def _fesc(p):
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _enable(l):
    s, e = l["start"], l["end"]
    if s <= 0 and e <= 0:
        return ""
    return f":enable='between(t\\,{s:g}\\,{e:g})'" if e > 0 else f":enable='gte(t\\,{s:g})'"


_DT_ALIGN = []


def _has_text_align():
    if not _DT_ALIGN:
        try:
            p = subprocess.run(["ffmpeg", "-hide_banner", "-h", "filter=drawtext"], capture_output=True, text=True, timeout=20)
            _DT_ALIGN.append("text_align" in (p.stdout or ""))
        except Exception:
            _DT_ALIGN.append(False)
    return _DT_ALIGN[0]


def make_frame_png(path, color, opacity, radius, win):
    """One transparent-window frame as a 1080x1920 PNG (rounded corners smooth)."""
    cx, cy, ww, hh = W * win["x"] / 100, H * win["y"] / 100, W * win["w"] / 100, H * win["h"] / 100
    x0, x1, y0, y1 = cx - ww / 2, cx + ww / 2, cy - hh / 2, cy + hh / 2
    r = max(0.5, min(radius, ww / 2, hh / 2))
    rgb = color[2:]
    rr, gg, bb = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    dx = f"max(max({x0 + r}-X,X-({x1 - r})),0)"
    dy = f"max(max({y0 + r}-Y,Y-({y1 - r})),0)"
    inside = f"gte(X,{x0})*lte(X,{x1})*gte(Y,{y0})*lte(Y,{y1})"
    hole = f"({inside})*(1-clip(hypot({dx},{dy})-{r}+0.5,0,1))"
    expr = f"255*{opacity:.3f}*(1-{hole})"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=1,format=rgba,"
           f"geq=r={rr}:g={gg}:b={bb}:a='{expr}'", "-frames:v", "1", path]
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    if p.returncode != 0 or not os.path.exists(path):
        raise ItemProblem("The overlay frame could not be drawn: " + p.stderr.decode(errors="ignore")[-200:], "Check the frame settings in the flow's overlays.")


def _drawtext(l, textfile, fontfile, alpha_expr):
    parts = [f"drawtext=fontfile='{_fesc(fontfile)}'", f"textfile='{_fesc(textfile)}'", "expansion=none", f"fontsize={l['size']:g}",
             f"fontcolor={l['color']}", f"x=({W * l['x'] / 100:.1f})-text_w/2", f"y=({H * l['y'] / 100:.1f})-text_h/2", f"line_spacing={l['spacing']:g}"]
    if _has_text_align():
        parts.append("text_align=" + {"left": "L", "center": "C", "right": "R"}[l["align"]])
    if alpha_expr:
        parts.append(f"alpha='{alpha_expr}'")
    if l["stroke"]["w"] > 0:
        parts += [f"borderw={l['stroke']['w']:g}", f"bordercolor={l['stroke']['color']}"]
    sh = l["shadow"]
    if sh["x"] or sh["y"]:
        parts += [f"shadowx={sh['x']:g}", f"shadowy={sh['y']:g}", f"shadowcolor={sh['color']}@{sh['opacity']:.2f}"]
    if l["box"]["on"]:
        parts += ["box=1", f"boxcolor={l['box']['color']}@{l['box']['opacity']:.2f}", f"boxborderw={l['box']['pad']:g}"]
    return ":".join(parts)


def _alpha(l):
    """drawtext alpha expression (opacity x fade in / out), or '' when it is simply 1."""
    op, s, e, fi, fo = l["opacity"], l["start"], l["end"], l["fade_in"], l["fade_out"]
    if fi <= 0 and fo <= 0:
        return f"{op:.3f}" if op < 1 else ""
    expr = f"{op:.3f}"
    if fi > 0:
        expr = f"min({expr}\\,{op:.3f}*max(0\\,min(1\\,(t-{s:g})/{fi:g})))"
    if fo > 0 and e > 0:
        expr = f"min({expr}\\,{op:.3f}*max(0\\,min(1\\,({e:g}-t)/{fo:g})))"
    return expr


# ------------------------------------------------------------------ the compositor
def build(layers, start_label, first_input, files, tmp, duration, rate, variables):
    """Stack `layers` on the filter stream `[start_label]`.
    Returns (extra_ffmpeg_input_args, filter_complex_parts, final_label). `files` = {layer_id: path} from resolve_assets()."""
    args, fc = [], []
    cur, n_in = start_label, first_input
    D = max(1.0, float(duration or 60))
    by_id = {l["id"]: l for l in layers}
    uses = {}
    for l in layers:
        if l["type"] == "text" and l["clip_to"] in by_id and by_id[l["clip_to"]]["type"] in ("frame", "image"):
            uses[l["clip_to"]] = uses.get(l["clip_to"], 0) + 1
    hole = {}      # layer id -> list of labels of its "window" mask (white where the layer is transparent), one per text that uses it
    k = 0

    def nxt():
        nonlocal k
        k += 1
        return f"s{k}"

    for l in layers:
        lid = l["id"]
        if l["type"] in ("frame", "image"):
            if l["type"] == "frame":
                png = os.path.join(tmp, f"frame_{lid}.png")
                make_frame_png(png, l["color"], l["opacity"], l["radius"], l["window"])
                src_path, full, op = png, True, 1.0
            else:
                src_path, full, op = files.get(lid), l["full"], l["opacity"]
                if not src_path:
                    continue
            args += ["-i", src_path]
            idx, n_in = n_in, n_in + 1
            lab = f"im{idx}"
            chain = ["format=rgba"]
            if full:
                chain.append(f"scale={W}:{H}")
            else:
                chain.append(f"scale={W * l['w'] / 100:.0f}:-2")
            if l["type"] == "image" and l["rotate"]:
                chain.append(f"rotate=a={l['rotate']:g}*PI/180:c=none:ow=rotw({l['rotate']:g}*PI/180):oh=roth({l['rotate']:g}*PI/180)")
            if op < 1:
                chain.append(f"colorchannelmixer=aa={op:.3f}")
            fc.append(f"[{idx}:v]{','.join(chain)}[{lab}]")
            if lid in uses:
                n = uses[lid]
                outs = "".join(f"[hole_{lid}_{j}]" for j in range(n))
                fc.append(f"[{lab}]split=2[{lab}a][{lab}b];[{lab}b]alphaextract,negate" + (f",split={n}{outs}" if n > 1 else outs))
                hole[lid] = [f"hole_{lid}_{j}" for j in range(n)]
                lab = f"{lab}a"
            pos = "0:0" if full else f"{W * l['x'] / 100:.1f}-w/2:{H * l['y'] / 100:.1f}-h/2"
            x, y = pos.split(":")
            out = nxt()
            fc.append(f"[{cur}][{lab}]overlay=x='{x}':y='{y}':format=auto{_enable(l)}[{out}]")
            cur = out
        elif l["type"] == "box":
            out = nxt()
            bw, bh = W * l["w"] / 100, H * l["h"] / 100
            bx, by = W * l["x"] / 100 - bw / 2, H * l["y"] / 100 - bh / 2
            fc.append(f"[{cur}]drawbox=x={bx:.0f}:y={by:.0f}:w={bw:.0f}:h={bh:.0f}:color={l['color']}@{l['opacity']:.3f}:t=fill{_enable(l)}[{out}]")
            cur = out
        elif l["type"] == "text":
            text = wrap_text(fill(l["text"], variables), l["size"], l["wrap"])
            if not text.strip():
                continue
            tf = os.path.join(tmp, f"text_{lid}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(text)
            font = font_path(l["font"], files.get("font:" + lid))
            if not font:
                raise ItemProblem("No font is installed on the server for the overlay text.", "Pick another font, or give a custom font link.")
            dt = _drawtext(l, tf, font, _alpha(l))
            out = nxt()
            if hole.get(l["clip_to"]):
                t = f"tx{k}"
                mask = hole[l["clip_to"]].pop(0)
                fc.append(f"color=c=black@0.0:s={W}x{H}:r={rate}:d={D:.2f},format=rgba,{dt}[{t}]")
                fc.append(f"[{t}]split=2[{t}a][{t}b];[{t}b]alphaextract[{t}al];[{t}al][{mask}]blend=all_mode=multiply[{t}c];[{t}a][{t}c]alphamerge[{t}f]")
                fc.append(f"[{cur}][{t}f]overlay=0:0:format=auto{_enable(l)}[{out}]")
            else:
                fc.append(f"[{cur}]{dt}{_enable(l)}[{out}]")
            cur = out
    return args, fc, cur


# ------------------------------------------------------------------ small "burned in" watermark
WM_STYLES = {   # name -> (canvas colour, text colour, blend mode, strength): how the mark is mixed INTO the picture
    "glow": ("black", "white", "screen", 0.55),         # light print: brightens the footage under the letters, like light on the lens
    "soft": ("0x808080", "white", "overlay", 1.0),     # follows the picture's light and shade, very natural
    "ink": ("white", "black", "multiply", 0.5),         # dark print: darkens bright areas, like stamped ink
}
WM_SIZES = {"tiny": 22, "small": 28, "medium": 36}
WM_MARGIN = {"top-left": (48, 70, 0), "top-right": (-48, 70, 0), "bottom-left": (48, -230, 0), "bottom-right": (-48, -230, 0), "center": (0, 0, 1)}


def burn_watermark(wm, src_label, tmp, rate, duration, size_wh=None):
    """The channel name printed INTO the picture instead of stuck on top: the text is drawn on a flat canvas, softened a hair, then mixed
    with the video (screen / soft light / multiply), so it reacts to the footage like a print. Returns (filter parts, out label) or None."""
    text = str(wm.get("text") or "").strip()[:60]
    if not text:
        return None
    cw, ch = size_wh or (W, H)
    style = wm.get("style") if wm.get("style") in WM_STYLES else "glow"
    base, tcol, mode, strength = WM_STYLES[style]
    size = WM_SIZES.get(wm.get("size"), WM_SIZES["small"]) if not isinstance(wm.get("size"), (int, float)) else max(14, min(float(wm["size"]), 80))
    size = size * min(cw, ch) / 1080.0 if min(cw, ch) != 1080 else size       # the same look on any picture size
    op = max(0.1, min(float(wm.get("opacity", 1.0)), 1.0)) * strength
    font = font_path(wm.get("font") if wm.get("font") in FONTS else "sleek-light")
    if not font:
        return None
    tf = os.path.join(tmp, "wm_text.txt")
    with open(tf, "w", encoding="utf-8") as f:
        f.write(text)
    px, py, centre = WM_MARGIN.get(wm.get("position"), WM_MARGIN["bottom-right"])
    if centre:
        xe, ye = "(w-text_w)/2", "(h-text_h)/2"
    else:
        xe = f"{px}" if px > 0 else f"w-text_w{px}"
        ye = f"{py}" if py > 0 else f"h-text_h{py}"
    glow = f"drawtext=fontfile='{_fesc(font)}':textfile='{_fesc(tf)}':expansion=none:fontsize={size:g}:fontcolor={tcol}@0.6:x={xe}:y={ye}"
    d = f"{(duration or 60) + 1:.2f}"
    parts = [f"color=c={base}:s={cw}x{ch}:r={rate}:d={d},format=gbrp,"
             f"{glow},gblur=sigma={max(0.5, size / 28):.2f}[wmsoft]",              # a faint halo: the print bleeds a little, like ink or light
             f"color=c={base}:s={cw}x{ch}:r={rate}:d={d},format=gbrp,"
             f"drawtext=fontfile='{_fesc(font)}':textfile='{_fesc(tf)}':expansion=none:fontsize={size:g}:fontcolor={tcol}:x={xe}:y={ye},gblur=sigma=0.35[wmcore]",
             "[wmsoft][wmcore]blend=all_mode=lighten[wmmix]" if base != "white" else "[wmsoft][wmcore]blend=all_mode=darken[wmmix]",
             f"[wmmix][{src_label}]scale2ref=flags=bicubic[wmfit][wmref]",        # safety: the canvas always matches the real picture size
             f"[wmref]format=gbrp[wma];[wma][wmfit]blend=all_mode={mode}:all_opacity={op:.3f}[wmout]"]
    return parts, "wmout"
