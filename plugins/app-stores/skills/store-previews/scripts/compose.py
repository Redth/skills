#!/usr/bin/env python3
"""``compose.py``: render an App Store / Google Play preview video from recorded takes and an edit.

An *edit* (``schema/preview-edit.schema.json``, ``references/edit.md``) says which recorded frames show when (a frame
held for a beat, a run of frames played at the output rate), how the parts join (a dissolve, or a slide across the
water), where the camera is (the screen floating on the background or pushed in), and what sits over it: headlines
on the background, touch hotspots, a spotlight on one element, an end card. Frames are numbered images from
store-capture's ``video.py frames`` (never cut by a recording's timestamps).

Everything that moves is a function of the frame number: this script works out each frame's footage, camera, pan
and spotlight; ``templates/preview.html`` draws it (headlines, touches and the end card animate from the time) in
headless Chrome, one screenshot a frame; ffmpeg joins them into a master at a constant rate. Then store-capture's
``video.py encode`` and ``check`` bring it to a store's spec.

    python3 scripts/compose.py edit.json --dry-run          # check the edit: length, marks, frames found
    python3 scripts/compose.py edit.json --frames 0,150,300 --stills   # a few frames as PNGs, to look at first
    python3 scripts/compose.py edit.json                    # every frame, then <out>/<name>-master.mp4

Exit codes: 0; 1 (a render or the encode failed); 3 (usage: an invalid edit, a missing frame, no Chrome or ffmpeg).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from appstores_lib import chrome as chrome_lib  # noqa: E402
from appstores_lib import jsonio, schema  # noqa: E402

TEMPLATE = os.path.join(SKILL, "templates", "preview.html")
SCHEMA = os.path.join(SKILL, "schema", "preview-edit.schema.json")

# Apple takes previews of 15 to 30 seconds (references/apple-previews.md); encode refuses others.
MIN_SECONDS, MAX_SECONDS = 15.0, 30.0
# How far (footage pixels) a spotlight's margin starts wider than its settled pad, closing as it fades in.
SPOT_SETTLE = 60.0
# The drawn device frames, as store-screenshots draws them (its frames.py CLASSES): bezel and screen corner radius as
# fractions of the screen's short side. Kept in step with it by hand; "none" draws the screen alone.
FRAME_CLASSES = {
    "phone": (0.034, 0.12),
    "phone-classic": (0.04, 0.045),
    "foldable-outer": (0.036, 0.10),
    "foldable-inner": (0.028, 0.05),
    "tablet": (0.045, 0.03),
    "none": (0.0, 0.0),
}


class EditError(ValueError):
    """The edit is invalid: exit 3 with this message."""


# -- easing -------------------------------------------------------------------------------------------------------

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def lerp(a, b, k):
    return a + (b - a) * k


def ramp(t, t0, d):
    return clamp((t - t0) / d) if d > 0 else (1.0 if t >= t0 else 0.0)


def in_out_quart(t):
    return 8 * t ** 4 if t < 0.5 else 1 - (-2 * t + 2) ** 4 / 2


def in_out_cubic(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def out_expo(t):
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def in_cubic(t):
    return t ** 3


# -- the edit -----------------------------------------------------------------------------------------------------

def load_edit(path):
    """The edit at ``path``, checked against the schema; frame folders made absolute (relative to the edit)."""
    try:
        edit = jsonio.load(path)
    except (OSError, ValueError) as e:
        raise EditError("can't read the edit %s: %s" % (path, e))
    problems = schema.validate(edit, jsonio.load(SCHEMA))
    if problems:
        raise EditError("the edit %s doesn't match the schema:\n  %s" % (path, "\n  ".join(str(p) for p in problems[:12])))
    base = os.path.dirname(os.path.abspath(path))
    for seg in edit["segments"]:
        if "frames" in seg:
            seg["frames"] = os.path.normpath(os.path.join(base, seg["frames"]))
    for key in ("style", "background", "styleRoot"):
        if edit.get(key) and not os.path.isabs(edit[key]):
            edit[key] = os.path.normpath(os.path.join(base, edit[key]))
    theme = edit.get("theme") or {}
    for key in ("fontSrc", "backgroundImage"):
        if theme.get(key) and not os.path.isabs(theme[key]):
            theme[key] = os.path.normpath(os.path.join(base, theme[key]))
    end = edit.get("end") or {}
    if end.get("mark") and not os.path.isabs(end["mark"]):
        end["mark"] = os.path.normpath(os.path.join(base, end["mark"]))
    return edit


def frame_path(folder, index, pattern):
    return os.path.join(folder, pattern % index)


def build_frames(edit):
    """Each output frame's footage: ``{"a", "fa", "b", "fb", "mix", "slide", "shift"}``, and the marks' times.

    A segment's ``ops``: ``["hold", i, seconds]`` (frame i for that long), ``["play", a, b]`` or ``["play", a, b,
    step]`` (frames a..b, one an output frame, or every ``step``-th), ``["mark", name]`` (the time reached, after a
    transition's overlap). A ``{"dissolve": s}`` or ``{"slide": s, "shift": px}`` between two segments overlaps the
    last ``s`` seconds of the one before with the start of the next: ``b`` fades in over ``a`` (``mix`` 0..1), or for a
    slide the outgoing screen holds its last frame (``slide`` 0..1, ``shift`` the distance)."""
    fps = edit.get("fps", 30)
    pattern = edit.get("framePattern", "frame-%05d.jpg")
    out, marks = [], {}
    pending, kind, shift = 0, "dissolve", None
    for seg in edit["segments"]:
        if "dissolve" in seg or "slide" in seg:
            pending = int(round((seg.get("dissolve") if "dissolve" in seg else seg["slide"]) * fps))
            kind = "slide" if "slide" in seg else "dissolve"
            shift = seg.get("shift")
            continue
        folder, fkey = seg["frames"], seg.get("footage", "main")
        overlap = min(pending, len(out)) if pending else 0
        mine = []
        for op in seg["ops"]:
            if op[0] == "mark":
                marks[op[1]] = (len(out) - overlap + len(mine)) / float(fps)
            elif op[0] == "hold":
                mine += [frame_path(folder, int(op[1]), pattern)] * max(1, int(round(float(op[2]) * fps)))
            elif op[0] == "play":
                a, b = int(op[1]), int(op[2])
                step = float(op[3]) if len(op) > 3 else 1.0
                i = float(a)
                while i <= b + 1e-9:
                    mine.append(frame_path(folder, int(round(i)), pattern))
                    i += step
            else:
                raise EditError("unknown op %r in a segment of %s" % (op[0], folder))
        n = min(overlap, len(mine))
        for k in range(n):
            f = out[len(out) - n + k]
            f["b"], f["fb"] = mine[k], fkey
            f["mix"] = (k + 1) / float(n + 1)
            if kind == "slide":
                f["a"] = out[len(out) - n - 1]["a"] if len(out) > n else f["a"]  # the outgoing screen holds still
                f["slide"] = f["mix"]
                if shift:
                    f["shift"] = shift
        out += [{"a": p, "fa": fkey, "b": None, "mix": 0.0} for p in mine[n:]]
        pending, shift = 0, None
    return out, marks


def resolve(value, marks):
    """An edit time: a number of seconds, or ``"@mark"``, ``"@mark+1.5"``, ``"@mark-0.2"``."""
    if isinstance(value, str):
        if not value.startswith("@"):
            raise EditError("a time must be seconds or @mark±seconds, not %r" % value)
        body, off = value[1:], 0.0
        for sign in ("+", "-"):
            if sign in body:
                body, num = body.split(sign, 1)
                off = float(num) * (1 if sign == "+" else -1)
                break
        if body not in marks:
            raise EditError("no mark named %r (marks: %s)" % (body, ", ".join(sorted(marks)) or "none"))
        return marks[body] + off
    return float(value)


TIME_KEYS = ("in", "out", "press", "moveIn")


def resolve_times(edit, marks):
    """Every time in the edit's overlays, camera, pan, end card and ``endOut`` made seconds."""
    for o in edit.get("overlays", []):
        for k in TIME_KEYS:
            if k in o:
                o[k] = resolve(o[k], marks)
        if o["out"] <= o["in"]:
            raise EditError("a %s overlay ends (%.2f s) before it starts (%.2f s)" % (o["kind"], o["out"], o["in"]))
    edit["camera"] = [[resolve(t, marks), float(k)] for t, k in edit.get("camera") or [[0, 0]]]
    edit["pan"] = [[resolve(t, marks), float(x)] for t, x in edit.get("pan") or [[0, 0]]]
    for name in ("camera", "pan"):
        times = [t for t, _ in edit[name]]
        for a, b in zip(times, times[1:]):
            if b < a:
                raise EditError("%s keys must run forward in time: %.2f s comes after %.2f s" % (name, b, a))
    if edit.get("end"):
        edit["end"]["in"] = resolve(edit["end"]["in"], marks)
    if edit.get("endOut") is not None:
        edit["endOut"] = resolve(edit["endOut"], marks)
    return edit


def keyed(keys, t, ease):
    """A value from ``[[time, value], ...]`` keys at ``t``, eased between neighbours, held outside them."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return lerp(v0, v1, ease(clamp((t - t0) / max(1e-6, t1 - t0))))
    return keys[-1][1]


def camera_at(keys, t):
    """The camera at ``t``: 0 the screen floating on the background, 1 pushed in (to the footage's ``full``)."""
    return keyed(keys, t, in_out_quart)


def pan_at(keys, t):
    """The pan at ``t`` (stage pixels): for a wide screen shown a pane at a time."""
    return keyed(keys, t, in_out_cubic)


def spotlight_at(o, t):
    """A spotlight's hole at ``t`` (footage pixels), or ``None`` when it's off.

    The hole is the element's rect grown by an even margin ``pad`` all round, its corners concentric with the
    element's own (radius ``r + pad``), so the margin is the same along the edges and round the corners; as it fades
    in the margin starts ``SPOT_SETTLE`` wider and closes, like a lens focusing. ``alpha`` is how far it's in."""
    alpha = out_expo(ramp(t, o["in"], 0.8)) * (1 - in_cubic(ramp(t, o["out"] - 0.4, 0.4)))
    if alpha <= 0.001:
        return None
    pad = float(o.get("pad", 0)) + (1 - alpha) * SPOT_SETTLE
    x, y, w, h = [float(v) for v in o["rect"]]
    return {"x": x - pad, "y": y - pad, "w": w + 2 * pad, "h": h + 2 * pad, "r": float(o.get("r", 0)) + pad,
            "alpha": alpha, "dim": float(o.get("dim", 0.5))}


def frame_geometry(fp):
    """A footage's drawn frame (``fp["frame"]``, a class above): bezel and screen radius in footage pixels."""
    bezel, radius = FRAME_CLASSES.get(fp.get("frame", "phone"), FRAME_CLASSES["phone"])
    short = min(fp["w"], fp["h"])
    return {"bezel": int(round(bezel * short)), "radius": int(round(radius * short))}


def timeline(edit):
    """The edit resolved to one entry a frame: footage, camera ``k``, ``pan`` and the spotlight. Also returns the
    marks. ``edit`` is changed in place (times resolved, footages' frames worked out)."""
    frames, marks = build_frames(edit)
    resolve_times(edit, marks)
    fps = edit.get("fps", 30)
    footages = {"main": edit["footage"]}
    footages.update(edit.get("footages") or {})
    for fp in footages.values():
        fp.setdefault("frame", "phone")
        fp["frameGeometry"] = frame_geometry(fp)
    edit["footages"] = footages
    spots = [o for o in edit.get("overlays", []) if o["kind"] == "spotlight"]
    for i, f in enumerate(frames):
        t = i / float(fps)
        f["k"] = camera_at(edit["camera"], t)
        f["pan"] = pan_at(edit["pan"], t)
        f["spot"] = None
        if not footages[f["fa"]].get("pan"):
            for o in spots:
                s = spotlight_at(o, t)
                if s:
                    f["spot"] = s
    return frames, marks


# -- the style --------------------------------------------------------------------------------------------------

DEFAULT_THEME = {"background": "#0B2540", "background2": "#061524", "ink": "#FFFFFF", "accent": "#6CC6F5",
                 "font": None, "fontSrc": None, "fontWeight": "100 900", "backgroundImage": None}


def find_rel(src, bases):
    """``src`` as it is if absolute, else the first of ``bases`` it exists under (else under the first base)."""
    if os.path.isabs(src):
        return src
    for b in bases:
        cand = os.path.normpath(os.path.join(b, src))
        if os.path.exists(cand):
            return cand
    return os.path.normpath(os.path.join(bases[0], src))


def theme_of(edit):
    """The look: a locked ``screenshot-style.json`` (store-screenshots) named by ``style``, else the edit's ``theme``,
    else plain defaults. The style's relative paths (fonts, the background image) are looked for under
    ``styleRoot`` (the screenshots config's folder), then the style's folder and its parents. Paths become URLs."""
    theme = dict(DEFAULT_THEME)
    style_path = edit.get("style")
    if style_path:
        try:
            st = jsonio.load(style_path)
        except (OSError, ValueError) as e:
            raise EditError("can't read the style %s: %s" % (style_path, e))
        here = os.path.dirname(style_path)
        bases = ([edit["styleRoot"]] if edit.get("styleRoot") else []) + [
            here, os.path.dirname(here), os.path.dirname(os.path.dirname(here)),
            os.path.dirname(os.path.dirname(os.path.dirname(here)))]
        t = st.get("theme") or st
        pal = t.get("palette") or {}
        for k in ("background", "background2", "ink", "accent"):
            if pal.get(k):
                theme[k] = pal[k]
        fonts = t.get("fonts") or []
        if fonts:
            theme["font"] = fonts[0].get("family")
            if fonts[0].get("src"):
                theme["fontSrc"] = find_rel(fonts[0]["src"], bases)
            theme["fontWeight"] = fonts[0].get("weight", theme["fontWeight"])
        bg = t.get("background") or {}
        if bg.get("kind") == "image" and bg.get("src"):
            theme["backgroundImage"] = find_rel(bg["src"], bases)
    theme.update({k: v for k, v in (edit.get("theme") or {}).items() if v is not None})
    if edit.get("background"):
        theme["backgroundImage"] = edit["background"]
    for k in ("fontSrc", "backgroundImage"):
        if theme.get(k):
            theme[k] = chrome_lib.to_url(theme[k])
    return theme


# -- rendering --------------------------------------------------------------------------------------------------

def page_edit(edit, frames):
    """What the page needs: the edit with its frames as file URLs."""
    data = dict(edit)
    data["frames"] = [dict(f, a=chrome_lib.to_url(f["a"]), b=chrome_lib.to_url(f["b"]) if f.get("b") else None)
                      for f in frames]
    data["theme"] = theme_of(edit)
    if data.get("end", {}).get("mark"):
        data["end"] = dict(data["end"], mark=chrome_lib.to_url(data["end"]["mark"]))
    return data


def missing_frames(frames):
    seen, missing = set(), []
    for f in frames:
        for p in (f["a"], f.get("b")):
            if p and p not in seen:
                seen.add(p)
                if not os.path.isfile(p):
                    missing.append(p)
    return missing


def find_ffmpeg():
    env = os.environ.get("FFMPEG")
    if env:
        return env if (os.path.isfile(env) or shutil.which(env)) else None
    return shutil.which("ffmpeg")


def render(edit, frames, out_dir, picks=None, stills=False, log=print):
    """Draw ``picks`` (default every frame) into ``out_dir``: numbered JPEGs, or ``still-<n>.png`` with ``stills``."""
    width, height = edit["width"], edit["height"]
    data = page_edit(edit, frames)
    picks = list(range(len(frames))) if picks is None else picks
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.monotonic()
    with chrome_lib.Chrome() as c:
        target, session = c._open(60)
        try:
            c.call("Emulation.setDeviceMetricsOverride",
                   {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, session_id=session)
            c._load(session, chrome_lib.to_url(TEMPLATE), time.monotonic() + 60)
            c._evaluate(session, "setup(%s).then(() => true)" % json.dumps(data), 60)
            for n, i in enumerate(picks):
                c._evaluate(session, "frame(%d)" % i, 60)
                params = {"format": "png" if stills else "jpeg", "captureBeyondViewport": False, "fromSurface": True}
                if not stills:
                    params["quality"] = 95
                shot = c.call("Page.captureScreenshot", params, session_id=session, timeout=60)
                name = ("still-%05d.png" % i) if stills else ("%05d.jpg" % (n + 1))
                with open(os.path.join(out_dir, name), "wb") as fh:
                    fh.write(base64.b64decode(shot["data"]))
                if n and n % 100 == 0:
                    log("  %d/%d frames (%.0f s)" % (n, len(picks), time.monotonic() - t0))
        finally:
            c._close_target(target)
    return time.monotonic() - t0


def encode_master(frames_dir, fps, out_path, ffmpeg):
    subprocess.run([ffmpeg, "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(frames_dir, "%05d.jpg"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "12", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", out_path], check=True)


def summary(edit, frames, marks):
    fps = edit.get("fps", 30)
    secs = len(frames) / float(fps)
    lines = ["%s: %d frames, %.2f s at %d fps, %dx%d" % (edit["name"], len(frames), secs, fps, edit["width"],
                                                          edit["height"])]
    if marks:
        lines.append("marks: " + ", ".join("%s %.2f s" % (k, v) for k, v in sorted(marks.items(), key=lambda kv: kv[1])))
    if not MIN_SECONDS <= secs <= MAX_SECONDS:
        lines.append("warning: %.2f s is outside the stores' 15-30 s; video.py encode will refuse it" % secs)
    return lines, secs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a preview video from recorded takes and an edit.")
    ap.add_argument("edit", help="the edit (JSON, schema/preview-edit.schema.json)")
    ap.add_argument("--out", help="the folder for frames and the master (default: <edit's folder>/out)")
    ap.add_argument("--frames", help="only these output frames (comma-separated numbers)")
    ap.add_argument("--stills", action="store_true", help="write the chosen frames as PNGs to look at")
    ap.add_argument("--dry-run", action="store_true", help="check the edit and its frames; render nothing")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    a = ap.parse_args(argv)
    try:
        edit = load_edit(a.edit)
        frames, marks = timeline(edit)
    except EditError as e:
        print("compose.py: %s" % e, file=sys.stderr)
        return 3
    lines, secs = summary(edit, frames, marks)
    missing = missing_frames(frames)
    if a.json:
        print(json.dumps({"name": edit["name"], "frames": len(frames), "seconds": round(secs, 3), "marks": marks,
                          "missing": missing[:20]}, indent=2))
    else:
        print("\n".join(lines))
    if missing:
        print("compose.py: %d frame file(s) missing, e.g. %s (dump the take with video.py frames, or fix the edit's "
              "frame numbers)" % (len(missing), missing[0]), file=sys.stderr)
        return 3
    if a.dry_run:
        return 0
    out_dir = a.out or os.path.join(os.path.dirname(os.path.abspath(a.edit)), "out")
    picks = None
    if a.frames:
        try:
            picks = [int(x) for x in a.frames.split(",")]
        except ValueError:
            print("compose.py: --frames takes comma-separated numbers", file=sys.stderr)
            return 3
        bad = [i for i in picks if not 0 <= i < len(frames)]
        if bad:
            print("compose.py: frame(s) %s outside 0-%d" % (bad, len(frames) - 1), file=sys.stderr)
            return 3
    ffmpeg = None
    if picks is None:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            print("compose.py: the master needs ffmpeg (install it, or set $FFMPEG)", file=sys.stderr)
            return 3
    frames_dir = os.path.join(out_dir, edit["name"])
    if picks is None and os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir)
    try:
        took = render(edit, frames, frames_dir, picks, a.stills)
    except chrome_lib.ChromeNotFound as e:
        print("compose.py: %s" % e, file=sys.stderr)
        return 3
    except chrome_lib.ChromeError as e:
        print("compose.py: rendering failed: %s" % e, file=sys.stderr)
        return 1
    if picks is not None:
        print("wrote %d frame(s) to %s" % (len(picks), frames_dir))
        return 0
    master = os.path.join(out_dir, "%s-master.mp4" % edit["name"])
    try:
        encode_master(frames_dir, edit.get("fps", 30), master, ffmpeg)
    except (subprocess.CalledProcessError, OSError) as e:
        print("compose.py: ffmpeg failed: %s" % e, file=sys.stderr)
        return 1
    print("master %s (%.0f s to render); next: video.py encode %s --slot <display type>, then video.py check"
          % (master, took, master))
    return 0


if __name__ == "__main__":
    sys.exit(main())
