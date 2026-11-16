#!/usr/bin/env python3
"""``video.py``: record an app's screen, encode it to a store's preview spec, and check the file.

- ``record --from simctl|adb|chrome``: ``xcrun simctl io <udid> recordVideo`` (stopped with SIGINT),
  ``adb shell screenrecord`` (then pulled), or headless Chrome's screencast (frames encoded with ffmpeg).
- ``encode <in> --out <file> (--slot <display type> | --size WxH)``: a constant frame rate, H.264 High (or
  ProRes 422 HQ), the exact size, a stereo AAC track (silent when the recording has none), trimmed with
  ``--start``/``--end``. The size comes from the rules' preview sizes for the slot; the picture is scaled
  and centre-cropped only when the aspect differs by at most 2 % (``--fit crop|pad`` to choose otherwise),
  and never scaled up without ``--allow-upscale``.
- ``check <file>… [--slot …]``: ffprobe against the rules' ``video`` rules (codec, container, frame rate and
  whether it's constant, length, size, bytes, the audio track).

ffmpeg and ffprobe are found at run time (``$FFMPEG``/``$FFPROBE``, then ``PATH``) and never bundled; without
them the command says how to install them and exits 3. Every command goes through ``drivers.base.run``.

Exit codes: 0 done; 1 a check error, or an encode that couldn't meet the spec; 3 usage or environment.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import rules as rules_mod  # noqa: E402
from drivers import base  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "rules")

INSTALL_HINT = ("ffmpeg and ffprobe are needed for video and aren't bundled: install them (macOS: `brew install "
                "ffmpeg`; Debian/Ubuntu: `sudo apt install ffmpeg`; or https://ffmpeg.org/download.html), or "
                "point $FFMPEG and $FFPROBE at them.")

# How far the recording's aspect may differ from the target's before cropping needs saying (--fit crop).
CROP_TOLERANCE = 0.02
# Apple's preview page: H.264 up to High Profile Level 4.0, 10-12 Mbps; stereo AAC 256 kbps, 44.1 or 48 kHz.
H264_MAX_LEVEL = 40
DEFAULT_BITRATE = "11M"
AUDIO_RATES = (44100, 48000)
CONTAINERS = {".mp4": "mp4", ".m4v": "m4v", ".mov": "mov"}


class VideoError(Exception):
    """Something the person has to fix (the message says what); ``code`` is the exit code."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# -- tools ----------------------------------------------------------------------------------------------

def find_tool(name):
    """``$FFMPEG``/``$FFPROBE`` (by ``name``), else ``name`` on ``PATH``; ``None`` when absent."""
    env = os.environ.get(name.upper())
    if env:
        return env if (os.path.isfile(env) or shutil.which(env)) else None
    return shutil.which(name)


def need_tool(name):
    """The tool's path, or a ``VideoError`` (exit 3) with the install hint."""
    path = find_tool(name)
    if not path:
        raise VideoError("%s not found. %s" % (name, INSTALL_HINT), 3)
    return path


def _run(cmd, timeout=600, what=None):
    """Run ``cmd`` through ``drivers.base.run`` and return its result; a non-zero exit is a ``VideoError``."""
    try:
        res = base.run(cmd, timeout=timeout, check=False)
    except base.ToolMissing as e:
        raise VideoError(str(e), 3) from None
    except base.DriverError as e:
        raise VideoError(str(e)) from None
    if res.code != 0:
        tail = (res.err or res.out or "").strip().splitlines()[-8:]
        raise VideoError("%s failed (exit %s): %s" % (what or cmd[0], res.code, "\n".join(tail)))
    return res


def probe(path, ffprobe=None):
    """ffprobe's view of ``path``: ``{"format": {...}, "streams": [...]}``."""
    ffprobe = ffprobe or need_tool("ffprobe")
    res = _run([ffprobe, "-v", "error", "-of", "json", "-show_entries",
                "format=duration,size,format_name:stream=index,codec_type,codec_name,profile,level,width,"
                "height,pix_fmt,r_frame_rate,avg_frame_rate,channels,channel_layout,sample_rate,bit_rate,"
                "sample_aspect_ratio,nb_frames", path], timeout=120, what="ffprobe")
    try:
        return json.loads(res.out or "{}")
    except ValueError:
        raise VideoError("ffprobe's answer for %s isn't JSON" % path) from None


def _rate(text):
    """A frame rate written ``30/1`` or ``30000/1001`` as a float (0 for ``0/0`` or nonsense)."""
    try:
        if "/" in str(text):
            num, den = str(text).split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def streams(info, kind):
    """The streams of ``kind`` (``video`` or ``audio``) in an ffprobe answer."""
    return [s for s in info.get("streams") or [] if s.get("codec_type") == kind]


def duration(info):
    """The file's length in seconds (0 when ffprobe doesn't say)."""
    try:
        return float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        return 0.0


# -- the rules ------------------------------------------------------------------------------------------

def load_rules(store, rules_dir=RULES_DIR):
    """The store's ``RuleSet``."""
    try:
        return rules_mod.load(store, rules_dir)
    except rules_mod.RulesError as e:
        raise VideoError(str(e), 3) from None


def video_rules(ruleset, slot=None):
    """The ``video`` rules that apply to ``slot`` (or to any slot when ``None``)."""
    out = []
    for rule in ruleset.by_kind("video"):
        slots = rule.slots
        if slot is None or not slots or slot in slots:
            out.append(rule)
    return out


def preview_sizes(ruleset, slot):
    """The preview sizes a slot accepts, as ``[(w, h), …]`` with both orientations unless the slot says
    ``landscape``/``portrait``/``asListed``. Raises ``VideoError`` for an unknown slot or one without previews."""
    data = ruleset.slots.get(slot)
    if data is None:
        known = sorted(k for k, v in ruleset.slots.items() if isinstance(v, dict) and v.get("preview"))
        raise VideoError("%s has no slot %r (slots with previews: %s)" % (ruleset.store, slot, ", ".join(known)), 3)
    preview = data.get("preview")
    if not preview or not preview.get("sizes"):
        raise VideoError("%s's %s takes no preview video" % (ruleset.store, slot), 3)
    orientation = preview.get("orientation") or data.get("orientation")
    out = []
    for w, h in preview["sizes"]:
        for cand in ((w, h), (h, w)):
            if orientation == "landscape" and cand[0] < cand[1]:
                continue
            if orientation == "portrait" and cand[0] > cand[1]:
                continue
            if orientation == "asListed" and cand != (w, h):
                continue
            if cand not in out:
                out.append(cand)
    return out


def slots_for_size(ruleset, width, height):
    """The slots whose preview sizes include ``width``×``height``."""
    found = []
    for slot, data in ruleset.slots.items():
        if isinstance(data, dict) and data.get("preview") and data["preview"].get("sizes"):
            if (width, height) in preview_sizes(ruleset, slot):
                found.append(slot)
    return found


def _limits(rules):
    """Fold a slot's video rules into one set of limits (the strictest of each)."""
    lim = {"codecs": None, "containers": None, "fps": None, "minSeconds": None, "maxSeconds": None,
           "maxBytes": None}
    for rule in rules:
        for key in ("codecs", "containers"):
            if rule.get(key):
                lim[key] = list(rule.get(key))
        for key in ("fps", "maxSeconds", "maxBytes"):
            if rule.get(key) is not None:
                lim[key] = rule.get(key) if lim[key] is None else min(lim[key], rule.get(key))
        if rule.get("minSeconds") is not None:
            lim["minSeconds"] = rule.get("minSeconds") if lim["minSeconds"] is None else max(
                lim["minSeconds"], rule.get("minSeconds"))
    return lim


# -- encode ---------------------------------------------------------------------------------------------

def choose_size(src_w, src_h, sizes):
    """The target from ``sizes`` whose aspect is nearest the recording's (ties: the first)."""
    if not sizes:
        raise VideoError("no target size", 3)
    src = float(src_w) / src_h
    return min(sizes, key=lambda s: abs((float(s[0]) / s[1]) - src))


def crop_fraction(src_w, src_h, dst_w, dst_h):
    """How much of the recording a fill-and-crop to ``dst`` cuts away along one side (0.0–1.0)."""
    a, b = float(src_w) / src_h, float(dst_w) / dst_h
    return 1.0 - min(a, b) / max(a, b)


def plan_encode(info, width, height, fps=30, start=None, end=None, fit="auto", codec="h264",
                bitrate=DEFAULT_BITRATE, allow_upscale=False, limits=None):
    """Decide how to encode: returns a dict with the filter, the trimmed length, whether audio must be
    added, and the warnings. Raises ``VideoError`` when the spec can't be met as asked."""
    vids = streams(info, "video")
    if not vids:
        raise VideoError("the recording has no video stream")
    v = vids[0]
    src_w, src_h = int(v.get("width") or 0), int(v.get("height") or 0)
    if not src_w or not src_h:
        raise VideoError("ffprobe didn't report the recording's size")
    warnings = []
    total = duration(info)
    t0 = float(start or 0)
    t1 = float(end) if end is not None else total
    if t0 < 0 or (total and t0 >= total):
        raise VideoError("--start %.2f is outside the recording (%.2f s)" % (t0, total), 3)
    if end is not None and t1 <= t0:
        raise VideoError("--end must be after --start", 3)
    if total and t1 > total + 0.05:
        warnings.append("--end %.2f is past the recording's end (%.2f s): it ends there" % (t1, total))
        t1 = total
    length = t1 - t0
    limits = limits or {}
    if limits.get("maxSeconds") is not None and length > limits["maxSeconds"] + 1e-6:
        raise VideoError("%.2f s is longer than the store's %s s: trim with --start/--end" % (
            length, limits["maxSeconds"]))
    if limits.get("minSeconds") is not None and length < limits["minSeconds"] - 1e-6:
        raise VideoError("%.2f s is shorter than the store's %s s: record longer" % (length, limits["minSeconds"]))
    if limits.get("fps") is not None and fps > limits["fps"]:
        raise VideoError("--fps %s is over the store's %s" % (fps, limits["fps"]), 3)
    cut = crop_fraction(src_w, src_h, width, height)
    mode = fit
    if fit == "auto":
        if cut > CROP_TOLERANCE:
            raise VideoError(
                "the recording is %dx%d and the preview %dx%d: cropping to fit would cut %.0f%% of the picture. "
                "Record at the preview's aspect (the device that has it), or say --fit crop or --fit pad"
                % (src_w, src_h, width, height, cut * 100))
        mode = "crop"
    if mode == "crop" and cut > 0:
        warnings.append("centre-cropped %.1f%% of the picture to fit %dx%d" % (cut * 100, width, height))
    if mode == "pad" and cut > 0:
        warnings.append("padded with black bars to fit %dx%d (stores dislike bars; record at the aspect)" % (
            width, height))
    fits_w = width / float(src_w)
    fits_h = height / float(src_h)
    scale = max(fits_w, fits_h) if mode == "crop" else min(fits_w, fits_h)
    if scale > 1.0001:
        if not allow_upscale:
            raise VideoError("the recording (%dx%d) is smaller than the preview (%dx%d): it would be scaled up. "
                             "Record on a device with more pixels, or say --allow-upscale" % (
                                 src_w, src_h, width, height))
        warnings.append("scaled up %.0f%%: expect softness" % ((scale - 1) * 100))
    if mode == "crop":
        vf = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (width, height, width, height))
    else:
        vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black"
              % (width, height, width, height))
    pix = "yuv422p10le" if codec == "prores" else "yuv420p"
    vf += ",setsar=1,fps=%s,format=%s" % (fps, pix)
    level = None
    if codec == "h264":
        macroblocks = ((width + 15) // 16) * ((height + 15) // 16)
        level = "4.0" if macroblocks <= 8192 else "5.1"
        if level != "4.0":
            warnings.append("%dx%d is too big for H.264 Level 4.0 (Apple's stated maximum): encoded at Level 5.1; "
                            "ProRes 422 HQ (--codec prores, .mov) is the other way Apple takes" % (width, height))
    has_audio = bool(streams(info, "audio"))
    return {"width": width, "height": height, "vf": vf, "fps": fps, "start": t0, "length": length,
            "addSilence": not has_audio, "codec": codec, "level": level, "bitrate": bitrate,
            "fit": mode, "warnings": warnings}


def encode_command(ffmpeg, src, out, plan, preset="medium"):
    """The ffmpeg command for ``plan`` (from ``plan_encode``)."""
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if plan["start"]:
        cmd += ["-ss", "%.3f" % plan["start"]]
    cmd += ["-i", src]
    if plan["addSilence"]:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0" if plan["addSilence"] else "0:a:0"]
    cmd += ["-t", "%.3f" % plan["length"], "-vf", plan["vf"], "-r", str(plan["fps"]), "-fps_mode", "cfr"]
    if plan["codec"] == "prores":
        cmd += ["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    else:
        rate = plan["bitrate"]
        cmd += ["-c:v", "libx264", "-preset", preset, "-profile:v", "high", "-level:v", plan["level"],
                "-b:v", rate, "-maxrate", _scale_rate(rate, 12.0 / 11.0), "-bufsize", _scale_rate(rate, 24.0 / 11.0),
                "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    cmd += ["-shortest", out]
    return cmd


def _scale_rate(rate, factor):
    """``11M`` × factor as ffmpeg's rate text (``12M``)."""
    text = str(rate).strip()
    mult = 1
    if text[-1:].upper() in ("K", "M"):
        mult = 1000 if text[-1:].upper() == "K" else 1000000
        text = text[:-1]
    value = float(text) * mult * factor
    return "%dk" % round(value / 1000.0)


def encode(src, out, slot=None, size=None, store="apple", start=None, end=None, fps=30, fit="auto",
           codec="h264", bitrate=DEFAULT_BITRATE, allow_upscale=False, preset="medium", rules_dir=RULES_DIR,
           dry_run=False):
    """Encode ``src`` to ``out`` for ``slot`` (a rules slot with previews) or an explicit ``size`` (w, h).
    Returns ``{"out", "plan", "command", "findings"}``; ``findings`` is ``check``'s on the result."""
    ffmpeg = need_tool("ffmpeg")
    ext = os.path.splitext(out)[1].lower()
    if ext not in CONTAINERS:
        raise VideoError("write a .mp4, .m4v or .mov (not %r)" % (ext or out), 3)
    if codec == "prores" and ext != ".mov":
        raise VideoError("ProRes goes in a .mov", 3)
    limits = {}
    ruleset = None
    if slot:
        ruleset = load_rules(store, rules_dir)
        sizes = preview_sizes(ruleset, slot)
        limits = _limits(video_rules(ruleset, slot))
    elif size:
        sizes = [tuple(size)]
    else:
        raise VideoError("say --slot (a display type with previews) or --size WxH", 3)
    info = probe(src)
    v = streams(info, "video")
    if not v:
        raise VideoError("%s has no video stream" % src)
    width, height = choose_size(int(v[0]["width"]), int(v[0]["height"]), sizes)
    plan = plan_encode(info, width, height, fps=fps, start=start, end=end, fit=fit, codec=codec,
                       bitrate=bitrate, allow_upscale=allow_upscale, limits=limits)
    cmd = encode_command(ffmpeg, src, out, plan, preset=preset)
    result = {"out": out, "plan": plan, "command": cmd, "findings": []}
    if dry_run:
        return result
    folder = os.path.dirname(os.path.abspath(out))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".encoding-" + os.path.basename(out))
    cmd[-1] = tmp
    try:
        _run(cmd, timeout=3600, what="ffmpeg")
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    cmd[-1] = out
    if ruleset is not None:
        result["findings"] = check_file(out, ruleset, slot)
    return result


# -- check ----------------------------------------------------------------------------------------------

def check_info(path, info, ruleset, slot=None, size_bytes=None):
    """The findings for one file's ffprobe answer against the store's ``video`` rules (for ``slot``, or any
    slot that takes its size)."""
    found = []
    vids = streams(info, "video")
    auds = streams(info, "audio")
    if size_bytes is None:
        try:
            size_bytes = int((info.get("format") or {}).get("size") or 0)
        except ValueError:
            size_bytes = 0
    width = int(vids[0].get("width") or 0) if vids else 0
    height = int(vids[0].get("height") or 0) if vids else 0
    slots = [slot] if slot else slots_for_size(ruleset, width, height)
    rules = video_rules(ruleset, slot) if slot else ruleset.by_kind("video")
    where = os.path.basename(path)
    for rule in rules:
        if rule.get("audioRequired") and not any(rule.get(k) for k in ("codecs", "fps", "sizes", "fromSlots")):
            if not auds:
                found.append(rules_mod.finding(rule, where, "no audio track: add a silent stereo one "
                                                            "(video.py encode does)"))
            continue
        if not vids:
            found.append(rules_mod.finding(rule, where, "no video stream"))
            continue
        v = vids[0]
        codec = (v.get("codec_name") or "").lower()
        codecs = [c.lower() for c in (rule.get("codecs") or [])]
        if codecs and codec not in codecs:
            found.append(rules_mod.finding(rule, where, "codec %s, not %s" % (codec or "unknown", " or ".join(codecs))))
        containers = rule.get("containers") or []
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if containers and ext not in containers:
            found.append(rules_mod.finding(rule, where, "a .%s file, not %s" % (
                ext, ", ".join("." + c for c in containers))))
        if codec == "prores" and ext and ext != "mov":
            found.append(rules_mod.finding(rule, where, "ProRes only in a .mov"))
        r_rate, avg = _rate(v.get("r_frame_rate")), _rate(v.get("avg_frame_rate"))
        fps = avg or r_rate
        if rule.get("fps") is not None and fps > rule.get("fps") + 0.01:
            found.append(rules_mod.finding(rule, where, "%.2f fps, over %s" % (fps, rule.get("fps"))))
        if r_rate and avg and abs(r_rate - avg) > 0.05:
            found.append(rules_mod.finding(rule, where, "a variable frame rate (%.2f average, %.2f base): make it "
                                                        "constant (video.py encode)" % (avg, r_rate)))
        length = duration(info)
        if rule.get("minSeconds") is not None and length < rule.get("minSeconds") - 0.01:
            found.append(rules_mod.finding(rule, where, "%.2f s, under %s s" % (length, rule.get("minSeconds"))))
        if rule.get("maxSeconds") is not None and length > rule.get("maxSeconds") + 0.01:
            found.append(rules_mod.finding(rule, where, "%.2f s, over %s s" % (length, rule.get("maxSeconds"))))
        if rule.get("maxBytes") is not None and size_bytes > rule.get("maxBytes"):
            found.append(rules_mod.finding(rule, where, "%d bytes, over %d" % (size_bytes, rule.get("maxBytes"))))
        sizes = [tuple(s) for s in rule.get("sizes") or []]
        if rule.get("fromSlots"):
            if slot:
                sizes = preview_sizes(ruleset, slot)
                if (width, height) not in sizes:
                    found.append(rules_mod.finding(rule, where, "%dx%d isn't a %s preview size (%s)" % (
                        width, height, slot, ", ".join("%dx%d" % s for s in sizes))))
            elif not slots:
                found.append(rules_mod.finding(rule, where, "%dx%d is no slot's preview size" % (width, height)))
        elif sizes and (width, height) not in sizes and (height, width) not in sizes:
            found.append(rules_mod.finding(rule, where, "%dx%d isn't an accepted size" % (width, height)))
        if codec == "h264":
            profile = (v.get("profile") or "").lower()
            level = int(v.get("level") or 0)
            if profile and profile not in ("high", "main", "baseline", "constrained baseline"):
                found.append(rules_mod.finding(rule, where, "H.264 profile %s: up to High is taken" % profile))
            if level > H264_MAX_LEVEL:
                found.append(rules_mod.Finding(rule.id, "warning", where,
                                               "H.264 Level %.1f, over the 4.0 Apple's page states" % (level / 10.0),
                                               rule.source, "observed"))
            if (v.get("pix_fmt") or "") not in ("yuv420p", "yuvj420p"):
                found.append(rules_mod.Finding(rule.id, "warning", where,
                                               "pixel format %s: yuv420p is the safe one" % v.get("pix_fmt"),
                                               rule.source, "observed"))
        for a in auds[:1]:
            ch = int(a.get("channels") or 0)
            rate = int(a.get("sample_rate") or 0)
            acodec = (a.get("codec_name") or "").lower()
            if ch != 2:
                found.append(rules_mod.finding(rule, where, "%d audio channel(s): stereo is wanted" % ch))
            if rate not in AUDIO_RATES:
                found.append(rules_mod.finding(rule, where, "audio at %d Hz: 44.1 or 48 kHz is wanted" % rate))
            if codec == "h264" and acodec != "aac":
                found.append(rules_mod.finding(rule, where, "%s audio: AAC goes with H.264" % acodec))
            if codec == "prores" and not acodec.startswith("pcm"):
                found.append(rules_mod.finding(rule, where, "%s audio: PCM goes with ProRes" % acodec))
    return found


def check_file(path, ruleset, slot=None):
    """Probe ``path`` and return its findings."""
    if not os.path.isfile(path):
        raise VideoError("%s doesn't exist" % path, 3)
    return check_info(path, probe(path), ruleset, slot, os.path.getsize(path))


# -- record ---------------------------------------------------------------------------------------------

# Start simctl's recorder, wait for its "Recording started", run the person's command (if any), wait, then
# stop it with SIGINT and let it finalise the file. Arguments: udid, out, seconds, during, display.
SIMCTL_SCRIPT = r'''
log=$(mktemp "${TMPDIR:-/tmp}/appstores-rec.XXXXXX")
if [ -n "$5" ]; then
  xcrun simctl io "$1" recordVideo --codec=h264 --mask=ignored --display="$5" --force "$2" 2>"$log" </dev/null &
else
  xcrun simctl io "$1" recordVideo --codec=h264 --mask=ignored --force "$2" 2>"$log" </dev/null &
fi
pid=$!
i=0
until grep -q "Recording started" "$log"; do
  sleep 0.2; i=$((i+1))
  if ! kill -0 "$pid" 2>/dev/null; then cat "$log" >&2; rm -f "$log"; exit 70; fi
  if [ "$i" -gt 150 ]; then kill -INT "$pid"; wait "$pid"; cat "$log" >&2; rm -f "$log"; exit 70; fi
done
if [ -n "$4" ]; then sh -c "$4"; fi
sleep "$3"
kill -INT "$pid"
wait "$pid"
code=$?
rm -f "$log"
exit $code
'''

# Run screenrecord on the device (it stops itself at --time-limit), with the person's command alongside.
# Arguments: adb, serial, remote file, seconds, size, during.
ADB_SCRIPT = r'''
if [ -n "$5" ]; then size="--size $5"; else size=""; fi
"$1" -s "$2" shell screenrecord --bit-rate 20000000 --time-limit "$4" $size "$3" </dev/null &
pid=$!
sleep 1
if [ -n "$6" ]; then sh -c "$6"; fi
wait "$pid"
'''


def record_simctl(udid, out, seconds=30, during=None, tail=1.0, display=None, dry_run=False):
    """Record a booted simulator's screen to ``out`` (H.264 .mov, the unmasked framebuffer): ``seconds``
    long, or while ``during`` runs then ``tail`` seconds more. Simulator recordings run at a variable frame
    rate with no audio: ``encode`` fixes both."""
    wait = tail if during else seconds
    cmd = ["/bin/sh", "-c", SIMCTL_SCRIPT, "appstores-record", udid, out, "%g" % wait, during or "",
           display or ""]
    if not dry_run:
        _run(cmd, timeout=wait + 600, what="simctl recordVideo")
    return cmd


def record_adb(serial, out, seconds=30, during=None, size=None, adb="adb", dry_run=False):
    """Record an Android device's or emulator's screen with ``screenrecord`` (``seconds``, at most 180 on
    older Android), pull it to ``out`` and delete it from the device."""
    remote = "/sdcard/appstores-recording.mp4"
    steps = [["/bin/sh", "-c", ADB_SCRIPT, "appstores-record", adb, serial, remote, "%d" % int(seconds),
              size or "", during or ""],
             [adb, "-s", serial, "pull", remote, out],
             [adb, "-s", serial, "shell", "-n", "rm", "-f", remote]]
    if not dry_run:
        try:
            _run(steps[0], timeout=seconds + 600, what="adb screenrecord")
            _run(steps[1], timeout=600, what="adb pull")
        finally:
            base.run(steps[2], timeout=60, check=False)
    return steps


def screencast_frames(chrome, url, width, height, scale, seconds, out_dir, fmt="png"):
    """Load ``url`` in ``chrome`` (an ``appstores_lib.chrome.Chrome``) at ``width``×``height`` device pixels and
    save its screencast frames to ``out_dir`` for ``seconds``; return ``[(file, timestamp), …]``."""
    target = chrome.call("Target.createTarget", {"url": "about:blank"})["targetId"]
    try:
        session = chrome.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        chrome.call("Page.enable", session_id=session)
        chrome.call("Emulation.setDeviceMetricsOverride", {
            "width": int(round(width / scale)), "height": int(round(height / scale)),
            "deviceScaleFactor": scale, "mobile": False}, session_id=session)
        chrome.call("Page.navigate", {"url": url}, session_id=session)
        chrome.call("Page.startScreencast", {"format": fmt, "maxWidth": width, "maxHeight": height,
                                             "everyNthFrame": 1}, session_id=session)
        frames = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                params = chrome.wait_event("Page.screencastFrame", session_id=session,
                                           timeout=max(0.2, end - time.monotonic()))
            except Exception:  # noqa: BLE001 - no frame before the end: the page stood still
                break
            stamp = (params.get("metadata") or {}).get("timestamp") or time.time()
            name = os.path.join(out_dir, "frame-%05d.%s" % (len(frames), "jpg" if fmt == "jpeg" else fmt))
            with open(name, "wb") as f:
                f.write(base64.b64decode(params.get("data") or ""))
            frames.append((name, float(stamp)))
            chrome.call("Page.screencastFrameAck", {"sessionId": params.get("sessionId")}, session_id=session)
        chrome.call("Page.stopScreencast", session_id=session)
        return frames
    finally:
        try:
            chrome.call("Target.closeTarget", {"targetId": target}, timeout=10)
        except Exception:  # noqa: BLE001
            pass


def concat_list(frames, seconds):
    """ffmpeg's concat-demuxer list for frames with their timestamps: each shown until the next, the last
    until ``seconds`` after the first."""
    lines = ["ffconcat version 1.0"]
    if not frames:
        return "\n".join(lines) + "\n"
    first = frames[0][1]
    for i, (name, stamp) in enumerate(frames):
        nxt = frames[i + 1][1] if i + 1 < len(frames) else first + seconds
        lines.append("file '%s'" % name.replace("'", "'\\''"))
        lines.append("duration %.4f" % max(0.001, nxt - stamp))
    lines.append("file '%s'" % frames[-1][0].replace("'", "'\\''"))
    return "\n".join(lines) + "\n"


def record_chrome(url, out, width, height, scale=1.0, seconds=30, fps=30, dry_run=False):
    """Record a web page with headless Chrome's screencast, as a constant-rate H.264 file at ``out``."""
    if dry_run:
        return [["chrome", "--headless=new", url, "(screencast %dx%d @%g for %gs)" % (width, height, scale, seconds)]]
    ffmpeg = need_tool("ffmpeg")
    from appstores_lib import chrome as chrome_mod
    work = tempfile.mkdtemp(prefix="appstores-screencast-")
    try:
        with chrome_mod.Chrome() as chrome:
            frames = screencast_frames(chrome, url, width, height, scale, seconds, work)
        if not frames:
            raise VideoError("Chrome sent no frames for %s" % url)
        listing = os.path.join(work, "frames.ffconcat")
        with open(listing, "w") as f:
            f.write(concat_list(frames, seconds))
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
               "-vf", "scale=%d:%d,setsar=1,fps=%d,format=yuv420p" % (width - width % 2, height - height % 2, fps),
               "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-fps_mode", "cfr", out]
        _run(cmd, timeout=3600, what="ffmpeg")
        return [cmd]
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -- the command line -----------------------------------------------------------------------------------

def _size(text):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("a size is WIDTHxHEIGHT, e.g. 886x1920") from None


def _print_findings(path, findings):
    if not findings:
        print("%s: meets the spec" % path)
        return
    for f in findings:
        print("%s: %s %s: %s (%s)" % (path, f.severity, f.rule_id, f.message, f.source))


def main(argv=None):
    """The command line; returns the exit code."""
    parser = argparse.ArgumentParser(prog="video.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record", help="record a simulator, an Android device or a web page")
    rec.add_argument("--from", dest="source", required=True, choices=("simctl", "adb", "chrome"))
    rec.add_argument("--device", help="the simulator's UDID or the Android serial")
    rec.add_argument("--out", required=True)
    rec.add_argument("--seconds", type=float, default=30)
    rec.add_argument("--during", help="a command to run while recording (the moments to show)")
    rec.add_argument("--tail", type=float, default=1.0, help="seconds to keep recording after --during")
    rec.add_argument("--display", help="simctl: which display (a two-screen simulator)")
    rec.add_argument("--size", type=_size, help="adb: screenrecord's --size")
    rec.add_argument("--url", help="chrome: the page")
    rec.add_argument("--width", type=int)
    rec.add_argument("--height", type=int)
    rec.add_argument("--scale", type=float, default=1.0)
    rec.add_argument("--dry-run", action="store_true")

    enc = sub.add_parser("encode", help="encode a recording to a store's preview spec")
    enc.add_argument("input")
    enc.add_argument("--out", required=True)
    enc.add_argument("--store", default="apple")
    enc.add_argument("--slot", help="the display type, e.g. APP_IPHONE_67 (its preview sizes)")
    enc.add_argument("--size", type=_size, help="an explicit WIDTHxHEIGHT instead of a slot")
    enc.add_argument("--start", type=float)
    enc.add_argument("--end", type=float)
    enc.add_argument("--fps", type=int, default=30)
    enc.add_argument("--fit", choices=("auto", "crop", "pad"), default="auto")
    enc.add_argument("--codec", choices=("h264", "prores"), default="h264")
    enc.add_argument("--bitrate", default=DEFAULT_BITRATE)
    enc.add_argument("--preset", default="medium")
    enc.add_argument("--allow-upscale", action="store_true")
    enc.add_argument("--rules-dir", default=RULES_DIR)
    enc.add_argument("--dry-run", action="store_true")
    enc.add_argument("--json", action="store_true")

    chk = sub.add_parser("check", help="check files against a store's preview rules")
    chk.add_argument("files", nargs="+")
    chk.add_argument("--store", default="apple")
    chk.add_argument("--slot")
    chk.add_argument("--rules-dir", default=RULES_DIR)
    chk.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 3
    try:
        if args.command == "record":
            if args.source == "simctl":
                if not args.device:
                    raise VideoError("--device <simulator UDID> is needed", 3)
                cmds = [record_simctl(args.device, args.out, args.seconds, args.during, args.tail, args.display,
                                      args.dry_run)]
            elif args.source == "adb":
                if not args.device:
                    raise VideoError("--device <serial> is needed", 3)
                size = "%dx%d" % args.size if args.size else None
                cmds = record_adb(args.device, args.out, args.seconds, args.during, size, dry_run=args.dry_run)
            else:
                if not (args.url and args.width and args.height):
                    raise VideoError("--url, --width and --height are needed", 3)
                cmds = record_chrome(args.url, args.out, args.width, args.height, args.scale, args.seconds,
                                     dry_run=args.dry_run)
            for c in cmds:
                print(("would run: " if args.dry_run else "ran: ") + " ".join(c[:3] if c[:2] == ["/bin/sh", "-c"]
                                                                              else c))
            if not args.dry_run:
                print("recorded %s" % args.out)
            return 0
        if args.command == "encode":
            res = encode(args.input, args.out, slot=args.slot, size=args.size, store=args.store, start=args.start,
                         end=args.end, fps=args.fps, fit=args.fit, codec=args.codec, bitrate=args.bitrate,
                         allow_upscale=args.allow_upscale, preset=args.preset, rules_dir=args.rules_dir,
                         dry_run=args.dry_run)
            errors = [f for f in res["findings"] if f.severity == "error"]
            if args.json:
                print(json.dumps({"out": res["out"], "plan": res["plan"], "command": res["command"],
                                  "findings": [f._asdict() for f in res["findings"]]}, indent=2))
            else:
                for w in res["plan"]["warnings"]:
                    print("note: " + w)
                if args.dry_run:
                    print("would run: " + " ".join(res["command"]))
                else:
                    print("wrote %s (%dx%d, %.2f s, %s fps%s)" % (
                        res["out"], res["plan"]["width"], res["plan"]["height"], res["plan"]["length"],
                        res["plan"]["fps"], ", silent audio added" if res["plan"]["addSilence"] else ""))
                    _print_findings(res["out"], res["findings"])
            return 1 if errors else 0
        ruleset = load_rules(args.store, args.rules_dir)
        report = []
        errors = 0
        for path in args.files:
            findings = check_file(path, ruleset, args.slot)
            errors += sum(1 for f in findings if f.severity == "error")
            report.append({"path": path, "findings": [f._asdict() for f in findings]})
            if not args.json:
                _print_findings(path, findings)
        if args.json:
            print(json.dumps({"files": report}, indent=2))
        return 1 if errors else 0
    except VideoError as e:
        print("video.py: %s" % e, file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
