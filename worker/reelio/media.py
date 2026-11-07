"""ffmpeg: make every video a clean Reel/Short (H.264 + AAC, even size, sane bitrate) and apply the user's look."""
import os, re, json, shutil, subprocess
from .errors import ItemProblem, AccountProblem
from . import layers as layers_mod


def _warm(a, b, g, sat, con=1.0, br=0.0):
    return lambda s: (f"colorbalance=rs={a*s:.3f}:gs={g*s:.3f}:bs={-b*s:.3f}:rm={a*s:.3f}:gm={g*s:.3f}:bm={-b*s:.3f}"
                      f":rh={a*s:.3f}:gh={g*s:.3f}:bh={-b*s:.3f},eq=saturation={1+(sat-1)*s:.3f}:contrast={1+(con-1)*s:.3f}:brightness={br*s:.3f}")


PRESETS = {
    "none": "",
    "golden": _warm(0.08, 0.14, 0.05, 1.08, 1.03, 0.01),
    "warm_yellow": _warm(0.05, 0.09, 0.03, 1.05),
    "soft_warm": _warm(0.03, 0.05, 0.015, 1.0, 0.97, 0.01),
    "clean_pop": lambda s: f"eq=contrast={1+0.06*s:.3f}:saturation={1+0.08*s:.3f}",
    "warm": "eq=saturation=1.2:contrast=1.05,colorbalance=rs=.08:bs=-.08",
    "cool": "eq=saturation=1.1,colorbalance=rs=-.08:bs=.1",
    "vintage": "curves=preset=vintage",
    "bw": "hue=s=0,eq=contrast=1.1",
    "vivid": "eq=saturation=1.5:contrast=1.1",
    "fade": "eq=contrast=0.9:brightness=0.04:saturation=0.85",
}
FILTER_LABELS = {"none": "No filter", "golden": "Golden", "warm_yellow": "Warm yellow", "soft_warm": "Soft warm", "clean_pop": "Clean pop",
                 "warm": "Warm", "cool": "Cool", "vintage": "Vintage", "bw": "Black & white", "vivid": "Vivid", "fade": "Faded"}


def exe(name="ffmpeg"):
    p = shutil.which(name)
    if not p:
        raise AccountProblem(f"{name} is not installed on the server.", "This should never happen on GitHub's runner; open Help > Why is it failing?", kind="setup")
    return p


def probe(path):
    p = subprocess.run([exe("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], capture_output=True, text=True)
    try:
        j = json.loads(p.stdout or "{}")
    except Exception:
        j = {}
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = None
    try:
        dur = float((j.get("format") or {}).get("duration") or (v or {}).get("duration"))
    except Exception:
        pass
    fps = None
    try:
        n, d = (v or {}).get("avg_frame_rate", "0/1").split("/"); fps = float(n) / float(d) if float(d) else None
    except Exception:
        pass
    return {"video": v, "audio": a, "duration": dur, "fps": fps, "w": (v or {}).get("width"), "h": (v or {}).get("height")}


def look_filter(edit):
    edit = edit or {}
    name = str(edit.get("filter", "none") or "none").strip()
    strength = float(edit.get("strength", 1.0) or 1.0)
    f = PRESETS.get(name.lower(), name)       # unknown name = raw ffmpeg expression
    return f(strength) if callable(f) else f


def filter_chain(edit, info):
    edit = edit or {}
    look = look_filter(edit)
    fit = edit.get("fit", "keep")
    chain = []
    if fit in ("blur", "crop", "pad"):
        W, H = 1080, 1920
        if fit == "crop":
            chain.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}")
        elif fit == "pad":
            chain.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
        # blur handled via filter_complex below
    else:
        chain.append("scale='if(lt(iw,720),720,iw)':-2:flags=lanczos")
        chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if look:
        chain.append(look)
    fps = info.get("fps")
    if fps and not (23 <= fps <= 60):
        chain.append("fps=30")
    chain.append("format=yuv420p")
    return chain


def _font():
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return p
    return None


def _esc(t):
    return re.sub(r"([\\:'%])", r"\\\1", t)


POS = {"top-left": "x=40:y=60", "top-right": "x=w-tw-40:y=60", "bottom-left": "x=40:y=h-th-120",
       "bottom-right": "x=w-tw-40:y=h-th-120", "center": "x=(w-tw)/2:y=(h-th)/2"}
POS_IMG = {"top-left": "40:60", "top-right": "W-w-40:60", "bottom-left": "40:H-h-120", "bottom-right": "W-w-40:H-h-120", "center": "(W-w)/2:(H-h)/2"}


def prepare(src, out, edit=None, logo_path=None, music_path=None, assets=None, variables=None):
    """Re-encode `src` to `out`. Raises ItemProblem for bad files.
    assets = {layer id: local file} and variables = {title, n, date, ...} are for the overlay layers (layers.py)."""
    edit = edit or {}
    info = probe(src)
    if not info["video"]:
        raise ItemProblem("This file has no video in it.", "Skip it, or re-upload the original.")
    d = info["duration"]
    if d is not None and not (3 <= d <= 900):
        raise ItemProblem(f"The video is {d:.0f} seconds long; Reels must be between 3 seconds and 15 minutes.", "Skip it, or trim it and re-upload.")
    fit = edit.get("fit", "keep")
    spec, rbox = layers_mod.normalize(edit.get("layers")), layers_mod.reel_box(edit)
    layered = bool(spec or rbox)
    if layered and fit == "keep":
        fit = "pad"; edit = dict(edit, fit="pad")           # overlays need a fixed 9:16 screen to be placed on
    chain = filter_chain(edit, info)
    wm = edit.get("watermark") or {}
    rate_n = round(info["fps"]) if (info["fps"] and 23 <= info["fps"] <= 60) else 30
    args = [exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    n_in = 1
    logo_idx = music_idx = None
    if wm.get("image") and logo_path:
        args += ["-i", logo_path]; logo_idx = n_in; n_in += 1
    if music_path and (edit.get("audio", {}) or {}).get("mode") == "music":
        args += ["-stream_loop", "-1", "-i", music_path]; music_idx = n_in; n_in += 1
    fc = []
    cur = "0:v:0"
    if fit == "blur":
        fc.append("[0:v:0]split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:4[b];"
                  "[fg]scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos[f];[b][f]overlay=(W-w)/2:(H-h)/2[fit]")
        cur = "fit"
    pos = wm.get("position", "bottom-right")
    burn = bool(wm.get("text")) and wm.get("style") != "plain"
    wm_text = None
    if wm.get("text") and not burn and _font():
        op = max(0.1, min(float(wm.get("opacity", 0.7)), 1.0))
        wm_text = f"drawtext=fontfile={_font()}:text='{_esc(wm['text'])}':fontsize=44:fontcolor=white@{op}:borderw=2:bordercolor=black@{op}:{POS.get(pos, POS['bottom-right'])}"
    if rbox:                                                # the reel sits inside a window on a coloured screen
        bw, bh = round(1080 * rbox["w"] / 100 / 2) * 2, round(1920 * rbox["h"] / 100 / 2) * 2
        cover = rbox["fit"] == "cover"
        rv = [f"scale={bw}:{bh}:force_original_aspect_ratio={'increase' if cover else 'decrease'}:flags=lanczos"] + ([f"crop={bw}:{bh}"] if cover else [])
        look = look_filter(edit)
        if look:
            rv.append(look)
        rv += ["setsar=1", "format=yuv420p"]
        cx, cy = 1080 * rbox["x"] / 100, 1920 * rbox["y"] / 100
        dur_bg = (d or 60) + 1
        fc.append(f"[{cur}]{','.join(rv)}[rv]")
        fc.append(f"color=c={layers_mod.canvas_bg(edit)}:s=1080x1920:r={rate_n}:d={dur_bg:.2f},format=yuv420p[bgc]")
        fc.append(f"[bgc][rv]overlay=x='{cx:.1f}-w/2':y='{cy:.1f}-h/2':shortest=1[v0]")
        if wm_text:
            fc.append(f"[v0]{wm_text}[v0w]"); last = "v0w"
        else:
            last = "v0"
    else:
        if wm_text:
            chain.append(wm_text)
        fc.append(f"[{cur}]{','.join(chain)}[v0]")
        last = "v0"
    if spec:
        extra_args, parts, last = layers_mod.build(spec, last, n_in, assets or {}, os.path.dirname(os.path.abspath(out)), d, rate_n, variables or {})
        args += extra_args
        fc += parts
        n_in += sum(1 for a in extra_args if a == "-i")
    if burn:                                   # printed into the picture, on top of any overlays, under the logo picture
        try:
            dims = (info.get("w") // 2 * 2, info.get("h") // 2 * 2) if (fit == "keep" and not layered and info.get("w") and info.get("h")) else None
            b = layers_mod.burn_watermark(wm, last, os.path.dirname(os.path.abspath(out)), rate_n, d, dims)
        except OSError:
            b = None
        if b:
            fc += b[0]; last = b[1]
    if logo_idx is not None:
        op = max(0.1, min(float(wm.get("opacity", 0.8)), 1.0))
        fc.append(f"[{logo_idx}:v]scale=iw*min(1\\,200/iw):-1,format=rgba,colorchannelmixer=aa={op}[lg];[{last}][lg]overlay={POS_IMG.get(pos, POS_IMG['bottom-right'])}[v1]")
        last = "v1"
    audio = (edit.get("audio") or {}).get("mode", "keep")
    amap, acodec = [], []
    if audio == "mute" or (not info["audio"] and music_idx is None):
        amap = ["-an"]
    elif music_idx is not None:
        vol = float((edit.get("audio") or {}).get("music_volume", 0.6))
        if info["audio"]:
            fc.append(f"[0:a:0]volume=1.0[a0];[{music_idx}:a]volume={vol}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]")
        else:
            fc.append(f"[{music_idx}:a]volume={vol}[aout]")
        amap = ["-map", "[aout]"]
    else:
        amap = ["-map", "0:a:0"]
    if amap != ["-an"]:
        acodec = ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    rate = str(round(info["fps"])) if (info["fps"] and 23 <= info["fps"] <= 60) else "30"
    args += ["-filter_complex", ";".join(fc), "-map", f"[{last}]", *amap,
             "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
             "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "veryfast", "-crf", "22",
             "-g", "60", "-keyint_min", "30", "-sc_threshold", "0", "-bf", "2", "-maxrate", "8M", "-bufsize", "16M",
             "-pix_fmt", "yuv420p", "-r", rate, *acodec, *(["-shortest"] if music_idx is not None else []),
             "-movflags", "+faststart", out]
    p = subprocess.run(args, capture_output=True, timeout=3600)
    if p.returncode != 0 or not os.path.exists(out):
        raise ItemProblem("The video could not be converted: " + p.stderr.decode(errors="ignore")[-300:],
                          "The file may be damaged. Skip it, or re-upload the original.")
    return info
