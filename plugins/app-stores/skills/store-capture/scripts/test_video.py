"""Tests for video.py: the encode plan and command, the checks against the rules' ``video`` rules, the recording
commands and ``frames`` (its size, the two-process pipe, the count, the rotation note) through a fake ``RUNNER``;
then, where ffmpeg and ffprobe are installed, a real encode of a short ``testsrc`` clip made in a temp folder,
checked with ffprobe, and real frames of a variable-rate rotated clip. Those skip without ffmpeg.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture_testkit as kit  # noqa: E402
import video  # noqa: E402
from drivers import base  # noqa: E402

HAVE_FFMPEG = bool(video.find_tool("ffmpeg") and video.find_tool("ffprobe"))


def info(width=1320, height=2868, seconds=20.0, fps="30/1", avg=None, audio=True, codec="h264", profile="High",
         level=40, pix="yuv420p", channels=2, rate=48000, acodec="aac", size=5000000):
    """An ffprobe answer."""
    streams = [{"index": 0, "codec_type": "video", "codec_name": codec, "profile": profile, "level": level,
                "width": width, "height": height, "pix_fmt": pix, "r_frame_rate": fps,
                "avg_frame_rate": avg or fps}]
    if audio:
        streams.append({"index": 1, "codec_type": "audio", "codec_name": acodec, "channels": channels,
                        "sample_rate": str(rate)})
    return {"streams": streams, "format": {"duration": "%.6f" % seconds, "size": str(size),
                                           "format_name": "mov,mp4,m4a,3gp,3g2,mj2"}}


class RulesTests(unittest.TestCase):

    def setUp(self):
        self.apple = video.load_rules("apple")

    def test_preview_sizes_from_the_slots(self):
        self.assertEqual(video.preview_sizes(self.apple, "APP_IPHONE_67"), [(886, 1920), (1920, 886)])
        self.assertEqual(video.preview_sizes(self.apple, "APP_APPLE_TV"), [(1920, 1080)])
        self.assertEqual(video.preview_sizes(self.apple, "APP_IPAD_PRO_129"),
                         [(1200, 1600), (1600, 1200), (900, 1200), (1200, 900)])

    def test_a_slot_without_previews_is_usage(self):
        with self.assertRaises(video.VideoError) as cm:
            video.preview_sizes(self.apple, "APP_WATCH_ULTRA")
        self.assertEqual(cm.exception.code, 3)
        with self.assertRaises(video.VideoError):
            video.preview_sizes(self.apple, "APP_NOPE")

    def test_slots_for_a_size(self):
        self.assertIn("APP_IPHONE_67", video.slots_for_size(self.apple, 886, 1920))
        self.assertIn("APP_DESKTOP", video.slots_for_size(self.apple, 1920, 1080))
        self.assertEqual(video.slots_for_size(self.apple, 1320, 2868), [])

    def test_limits_fold_the_rules(self):
        lim = video._limits(video.video_rules(self.apple, "APP_IPHONE_67"))
        self.assertEqual((lim["fps"], lim["minSeconds"], lim["maxSeconds"]), (30, 15, 30))
        self.assertEqual(lim["maxBytes"], 500000000)


class PlanTests(unittest.TestCase):

    def test_size_follows_the_recordings_orientation(self):
        sizes = [(886, 1920), (1920, 886)]
        self.assertEqual(video.choose_size(1320, 2868, sizes), (886, 1920))
        self.assertEqual(video.choose_size(2868, 1320, sizes), (1920, 886))

    def test_a_near_aspect_is_cropped_and_said(self):
        plan = video.plan_encode(info(), 886, 1920, limits={"maxSeconds": 30, "minSeconds": 15})
        self.assertEqual(plan["fit"], "crop")
        self.assertIn("crop=886:1920", plan["vf"])
        self.assertIn("fps=30", plan["vf"])
        self.assertTrue(any("centre-cropped 0.3%" in w for w in plan["warnings"]), plan["warnings"])
        self.assertFalse(plan["addSilence"])
        self.assertEqual(plan["level"], "4.0")

    def test_a_far_aspect_needs_saying(self):
        with self.assertRaises(video.VideoError) as cm:
            video.plan_encode(info(1600, 1200), 886, 1920)
        self.assertIn("--fit crop or --fit pad", str(cm.exception))
        pad = video.plan_encode(info(1600, 1200), 1920, 1080, fit="pad", allow_upscale=True)
        self.assertIn("pad=1920:1080", pad["vf"])

    def test_never_scaled_up_unless_asked(self):
        with self.assertRaises(video.VideoError) as cm:
            video.plan_encode(info(750, 1624), 886, 1920)
        self.assertIn("smaller than the preview", str(cm.exception))
        ok = video.plan_encode(info(750, 1624), 886, 1920, allow_upscale=True)
        self.assertTrue(any("scaled up" in w for w in ok["warnings"]))

    def test_length_against_the_store(self):
        limits = {"minSeconds": 15, "maxSeconds": 30}
        with self.assertRaises(video.VideoError):
            video.plan_encode(info(seconds=42), 886, 1920, limits=limits)
        plan = video.plan_encode(info(seconds=42), 886, 1920, start=2, end=27, limits=limits)
        self.assertAlmostEqual(plan["length"], 25.0)
        with self.assertRaises(video.VideoError):
            video.plan_encode(info(seconds=10), 886, 1920, limits=limits)
        with self.assertRaises(video.VideoError):
            video.plan_encode(info(), 886, 1920, start=5, end=4)

    def test_silence_is_added_when_theres_no_audio(self):
        plan = video.plan_encode(info(audio=False), 886, 1920)
        self.assertTrue(plan["addSilence"])
        cmd = video.encode_command("ffmpeg", "raw.mov", "out.mp4", plan)
        line = " ".join(cmd)
        self.assertIn("-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000", line)
        self.assertIn("-map 0:v:0 -map 1:a:0", line)
        self.assertIn("-c:v libx264 -preset medium -profile:v high -level:v 4.0", line)
        self.assertIn("-b:v 11M -maxrate 12000k -bufsize 24000k", line)
        self.assertIn("-c:a aac -b:a 256k -ar 48000 -ac 2 -movflags +faststart", line)
        self.assertIn("-fps_mode cfr", line)
        self.assertEqual(cmd[-2:], ["-shortest", "out.mp4"])

    def test_trim_seeks_the_input(self):
        plan = video.plan_encode(info(seconds=40), 886, 1920, start=3.5, end=28)
        cmd = video.encode_command("ffmpeg", "raw.mov", "out.mp4", plan)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "3.500")
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-t") + 1], "24.500")

    def test_4k_is_level_5_1_with_a_note_and_prores_is_offered(self):
        plan = video.plan_encode(info(3840, 2160), 3840, 2160)
        self.assertEqual(plan["level"], "5.1")
        self.assertTrue(any("ProRes" in w for w in plan["warnings"]))
        pr = video.plan_encode(info(3840, 2160), 3840, 2160, codec="prores")
        cmd = video.encode_command("ffmpeg", "a.mov", "b.mov", pr)
        self.assertIn("prores_ks", cmd)
        self.assertIn("pcm_s16le", cmd)
        self.assertIn("format=yuv422p10le", pr["vf"])


class CheckTests(unittest.TestCase):

    def setUp(self):
        self.apple = video.load_rules("apple")

    def findings(self, probe, path="preview.mp4", slot="APP_IPHONE_67"):
        return video.check_info(path, probe, self.apple, slot)

    def test_a_good_file_meets_the_spec(self):
        self.assertEqual(self.findings(info(886, 1920, 20)), [])

    def test_what_gets_rejected(self):
        msgs = [f.message for f in self.findings(info(1320, 2868, 42, fps="60/1", avg="47/1", channels=1,
                                                      rate=22050, size=600000000), path="raw.avi")]
        joined = " | ".join(msgs)
        for part in ("47.00 fps, over 30", "a variable frame rate", "42.00 s, over 30 s", "600000000 bytes",
                     "1320x2868 isn't a APP_IPHONE_67 preview size", "a .avi file", "1 audio channel",
                     "22050 Hz"):
            self.assertIn(part, joined)

    def test_no_audio_is_a_warning_from_an_unverified_rule(self):
        (f,) = self.findings(info(886, 1920, 20, audio=False))
        self.assertEqual((f.rule_id, f.severity), ("apple.previews.audio_track", "warning"))
        self.assertIn("unverified", f.message)

    def test_without_a_slot_the_size_must_be_some_slots(self):
        self.assertEqual(video.check_info("p.mp4", info(1920, 1080, 20), self.apple), [])
        msgs = [f.message for f in video.check_info("p.mp4", info(1000, 1000, 20), self.apple)]
        self.assertIn("1000x1000 is no slot's preview size", msgs)

    def test_level_and_pixel_format_are_notes(self):
        found = self.findings(info(886, 1920, 20, level=51, pix="yuv444p"))
        self.assertEqual(sorted(f.severity for f in found), ["warning", "warning"])

    def test_variable_rate_helper(self):
        self.assertAlmostEqual(video._rate("30000/1001"), 29.97, places=2)
        self.assertEqual(video._rate("0/0"), 0.0)


class RecordTests(unittest.TestCase):

    def setUp(self):
        self.hooks = kit.Hooks()

    def tearDown(self):
        self.hooks.restore()

    def test_simctl_records_h264_unmasked_and_stops_with_sigint(self):
        cmd = video.record_simctl("00000000-0000-0000-0000-0000000000A1", "raw.mov", seconds=20)
        self.assertEqual(cmd[:2], ["/bin/sh", "-c"])
        self.assertIn("recordVideo --codec=h264 --mask=ignored", cmd[2])
        self.assertIn('kill -INT "$pid"', cmd[2])
        self.assertIn("Recording started", cmd[2])
        self.assertEqual(cmd[4:], ["00000000-0000-0000-0000-0000000000A1", "raw.mov", "20", "", ""])
        self.assertEqual(len(self.hooks.runner.lines), 1)

    def test_simctl_with_a_command_during(self):
        cmd = video.record_simctl("UDID", "raw.mov", during="maestro test flows/demo.yaml", tail=1.5,
                                  display="primary")
        self.assertEqual(cmd[4:], ["UDID", "raw.mov", "1.5", "maestro test flows/demo.yaml", "primary"])

    def test_adb_records_pulls_and_cleans_up(self):
        steps = video.record_adb("emulator-5554", "raw.mp4", seconds=25, size="1080x1920")
        lines = self.hooks.runner.lines
        self.assertEqual(len(lines), 3)
        self.assertIn("screenrecord --bit-rate 20000000 --time-limit", steps[0][2])
        self.assertEqual(steps[0][4:], ["adb", "emulator-5554", "/sdcard/appstores-recording.mp4", "25", "1080x1920", ""])
        self.assertEqual(lines[1], "adb -s emulator-5554 pull /sdcard/appstores-recording.mp4 raw.mp4")
        self.assertEqual(lines[2], "adb -s emulator-5554 shell -n rm -f /sdcard/appstores-recording.mp4")

    def test_adb_cleans_up_even_when_the_pull_fails(self):
        self.hooks.runner.on(r" pull ", code=1, err="remote object does not exist")
        with self.assertRaises(video.VideoError):
            video.record_adb("emulator-5554", "raw.mp4", seconds=5)
        self.assertTrue(self.hooks.runner.lines[-1].endswith("shell -n rm -f /sdcard/appstores-recording.mp4"))

    def test_dry_run_runs_nothing(self):
        video.record_simctl("UDID", "raw.mov", dry_run=True)
        video.record_adb("SERIAL", "raw.mp4", dry_run=True)
        self.assertEqual(self.hooks.runner.lines, [])

    def test_screencast_frames_last_until_the_next(self):
        text = video.concat_list([("/t/a.png", 100.0), ("/t/b.png", 100.5), ("/t/c'd.png", 102.0)], 5)
        self.assertEqual(text.splitlines(), [
            "ffconcat version 1.0", "file '/t/a.png'", "duration 0.5000", "file '/t/b.png'", "duration 1.5000",
            "file '/t/c'\\''d.png'", "duration 3.0000", "file '/t/c'\\''d.png'"])


def rotated(degrees):
    """ffprobe's answer for a stream's display rotation (``None``: no side data at all)."""
    stream = {"index": 0, "tags": {}}
    if degrees is not None:
        stream["side_data_list"] = [{"side_data_type": "Display Matrix", "rotation": degrees}]
    return json.dumps({"streams": [stream]})


class FramesPlanTests(unittest.TestCase):

    def test_the_size_is_kept_or_scaled_by_width(self):
        plan = video.plan_frames(info(1320, 2868))
        self.assertEqual((plan["width"], plan["height"], plan["warnings"]), (1320, 2868, []))
        plan = video.plan_frames(info(1320, 2868), width=660)
        self.assertEqual((plan["width"], plan["height"]), (660, 1434))

    def test_a_quarter_turn_writes_the_picture_upright_and_says_so(self):
        plan = video.plan_frames(info(2006, 2852), rotate=-90)
        self.assertEqual((plan["width"], plan["height"]), (2852, 2006))
        self.assertEqual(plan["display"], [2852, 2006])
        (note,) = plan["warnings"]
        self.assertIn("2006x2852 with a -90° display rotation", note)
        self.assertIn("--size WxH (landscape)", note)
        half = video.plan_frames(info(2006, 2852), rotate=-90, width=1426)
        self.assertEqual((half["width"], half["height"]), (1426, 1003))
        flipped = video.plan_frames(info(2006, 2852), rotate=180)
        self.assertEqual((flipped["width"], flipped["height"]), (2006, 2852))

    def test_size_forces_the_shape_and_warns_against_the_picture(self):
        plan = video.plan_frames(info(2006, 2852), rotate=-90, size=(2853, 2007))
        self.assertEqual((plan["width"], plan["height"], plan["warnings"]), (2853, 2007, []))
        squeezed = video.plan_frames(info(2006, 2852), rotate=-90, size=(2006, 2852))
        (note,) = squeezed["warnings"]
        self.assertIn("--size 2006x2852 is portrait but the picture is landscape", note)
        self.assertIn("after its -90° rotation", note)
        stretched = video.plan_frames(info(1320, 2868), size=(1000, 1600))
        self.assertIn("stretches", stretched["warnings"][0])

    def test_usage(self):
        for kw in ({"fmt": "gif"}, {"fmt": "png", "quality": 3}, {"quality": 40}, {"width": 0}, {"size": (0, 10)}):
            with self.assertRaises(video.VideoError) as cm:
                video.plan_frames(info(), **kw)
            self.assertEqual(cm.exception.code, 3, kw)

    def test_the_pipe_passes_every_frame_through_and_numbers_them_afresh(self):
        plan = video.plan_frames(info(1320, 2868), width=660, quality=3)
        decode, encode = video.frames_commands("ffmpeg", "raw.mov", "frames", plan)
        self.assertEqual(base.quote(decode),
                         "ffmpeg -nostdin -hide_banner -loglevel error -i raw.mov -map 0:v:0 -an -fps_mode passthrough "
                         "-vf scale=660:1434:flags=lanczos,setsar=1 -f rawvideo -pix_fmt rgb24 -")
        self.assertEqual(base.quote(encode),
                         "ffmpeg -hide_banner -loglevel error -y -f rawvideo -pix_fmt rgb24 -s 660x1434 -r 30 -i - "
                         "-qmin 1 -q:v 3 frames/frame-%05d.jpg")
        png = video.plan_frames(info(1320, 2868), fmt="png")
        _, encode = video.frames_commands("ffmpeg", "raw.mov", "frames", png)
        self.assertEqual(encode[-3:], ["-i", "-", "frames/frame-%05d.png"])
        for cmd in (decode, encode):
            self.assertNotIn("-ss", cmd)
            self.assertFalse(any("fps=" in c or "setpts" in c for c in cmd), cmd)

    def test_the_script_pipes_one_into_the_other_and_fails_with_either(self):
        decode, encode = video.frames_commands("ffmpeg", "my raw.mov", "out", video.plan_frames(info()))
        cmd = video.frames_script(decode, encode)
        self.assertEqual(cmd[:2], ["/bin/sh", "-c"])
        self.assertIn("{ %s; echo $? >\"$st\"; } | %s" % (base.quote(decode), base.quote(encode)), cmd[2])
        self.assertIn("'my raw.mov'", cmd[2])
        self.assertIn("writing the frames failed", cmd[2])
        self.assertIn("decoding the recording failed", cmd[2])


class FramesRunTests(unittest.TestCase):
    """``frames`` and ``main(["frames", …])`` through the fake runner, with ffmpeg and ffprobe stand-ins."""

    def setUp(self):
        self.hooks = kit.Hooks()
        self.tmp = tempfile.mkdtemp(prefix="appstores-video-test-")
        self.saved = {k: os.environ.get(k) for k in ("FFMPEG", "FFPROBE")}
        for name in ("ffmpeg", "ffprobe"):
            path = os.path.join(self.tmp, name)
            with open(path, "w") as f:
                f.write("")
            os.environ[name.upper()] = path
        self.src = os.path.join(self.tmp, "raw.mov")
        with open(self.src, "wb") as f:
            f.write(b"\0" * 16)
        self.out = os.path.join(self.tmp, "frames")

    def tearDown(self):
        self.hooks.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def answer(self, probe, degrees=None, written=154):
        runner = self.hooks.runner
        runner.on(r"format=duration", out=json.dumps(probe))
        runner.on(r"stream_side_data=rotation", out=rotated(degrees))

        def write(cmd):
            os.makedirs(self.out, exist_ok=True)
            for i in range(1, written + 1):
                open(os.path.join(self.out, "frame-%05d.jpg" % i), "w").close()
        runner.on(r"^/bin/sh -c ", then=write)

    def test_writes_and_counts_every_frame(self):
        p = info(1320, 2868, audio=False)
        p["streams"][0]["nb_frames"] = "154"
        self.answer(p)
        res = video.frames(self.src, self.out, width=660)
        self.assertEqual(res["count"], 154)
        self.assertEqual((res["files"][0], res["files"][-1]), ("frame-00001.jpg", "frame-00154.jpg"))
        self.assertEqual(res["plan"]["warnings"], [])
        (script,) = [l for l in self.hooks.runner.lines if l.startswith("/bin/sh -c ")]
        self.assertIn("-fps_mode passthrough", script)
        self.assertIn("-s 660x1434 -r 30 -i -", script)

    def test_a_count_that_differs_from_the_streams_is_noted(self):
        p = info(1320, 2868, audio=False)
        p["streams"][0]["nb_frames"] = "160"
        self.answer(p, written=154)
        res = video.frames(self.src, self.out)
        self.assertIn("the stream lists 160 frames and 154 were written", res["plan"]["warnings"])

    def test_the_command_line_prints_the_count_size_and_rotation_note(self):
        self.answer(info(2006, 2852, audio=False), degrees=-90, written=12)
        so = io.StringIO()
        with contextlib.redirect_stdout(so):
            code = video.main(["frames", self.src, self.out, "--width", "1426"])
        self.assertEqual(code, 0)
        text = so.getvalue()
        self.assertIn("note: the stream is 2006x2852 with a -90° display rotation", text)
        self.assertIn("wrote 12 frames (1426x1003 jpg)", text)
        self.assertIn("frame-00001.jpg to frame-00012.jpg", text)

    def test_size_on_the_command_line(self):
        self.answer(info(2006, 2852, audio=False), degrees=-90, written=3)
        so = io.StringIO()
        with contextlib.redirect_stdout(so):
            code = video.main(["frames", self.src, self.out, "--size", "2853x2007", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(so.getvalue())
        self.assertEqual((data["frames"], data["width"], data["height"], data["rotation"]), (3, 2853, 2007, -90))
        self.assertEqual(data["warnings"], [])
        self.assertIn("-s 2853x2007", " ".join(data["commands"][1]))
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                video.main(["frames", self.src, self.out, "--size", "10x10", "--width", "5"])

    def test_an_old_rotate_tag_counts_and_a_failed_rotation_probe_is_none(self):
        self.hooks.runner.on(r"stream_side_data", out=json.dumps({"streams": [{"tags": {"rotate": "90"}}]}))
        self.assertEqual(video.rotation(self.src), 90)
        self.hooks.runner.on(r"stream_side_data", code=1, err="Invalid section")
        self.assertEqual(video.rotation(self.src), 0)
        self.hooks.runner.on(r"stream_side_data", out=rotated(None))
        self.assertEqual(video.rotation(self.src), 0)

    def test_old_frames_in_the_folder_are_refused(self):
        self.answer(info(1320, 2868))
        os.makedirs(self.out)
        open(os.path.join(self.out, "frame-00001.jpg"), "w").close()
        with self.assertRaises(video.VideoError) as cm:
            video.frames(self.src, self.out)
        self.assertEqual(cm.exception.code, 3)
        self.assertFalse(any(l.startswith("/bin/sh") for l in self.hooks.runner.lines))

    def test_no_frames_or_a_failed_pipe_is_an_error(self):
        self.answer(info(1320, 2868), written=0)
        with self.assertRaises(video.VideoError) as cm:
            video.frames(self.src, self.out)
        self.assertIn("wrote no frames", str(cm.exception))
        self.hooks.runner.on(r"^/bin/sh -c ", code=1, err="writing the frames failed (exit 1)")
        with self.assertRaises(video.VideoError) as cm:
            video.frames(self.src, os.path.join(self.tmp, "other"))
        self.assertIn("writing the frames failed", str(cm.exception))

    def test_dry_run_runs_no_pipe(self):
        self.answer(info(1320, 2868))
        res = video.frames(self.src, self.out, dry_run=True)
        self.assertEqual(res["count"], 0)
        self.assertFalse(any(l.startswith("/bin/sh") for l in self.hooks.runner.lines))
        self.assertFalse(os.path.exists(self.out))


class ToolTests(unittest.TestCase):

    def test_missing_ffmpeg_is_exit_3_with_the_hint(self):
        saved = os.environ.get("FFPROBE")
        os.environ["FFPROBE"] = "/nonexistent/ffprobe"
        folder = tempfile.mkdtemp(prefix="appstores-video-test-")
        clip = os.path.join(folder, "x.mp4")
        with open(clip, "wb") as f:
            f.write(b"\0" * 16)
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = video.main(["check", clip])
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            if saved is None:
                os.environ.pop("FFPROBE", None)
            else:
                os.environ["FFPROBE"] = saved
        self.assertEqual(code, 3)
        self.assertIn("brew install ffmpeg", err.getvalue())

    def test_missing_input_is_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = video.main(["check", "/nonexistent/x.mp4"])
        self.assertEqual(code, 3)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg and ffprobe aren't installed")
class RealEncodeTests(unittest.TestCase):
    """A real encode: a short testsrc clip (no audio, 60 fps, a phone's aspect) to Apple's 750x1334 preview."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="appstores-video-test-")
        cls.raw = os.path.join(cls.tmp, "raw.mp4")
        base.run([video.find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                  "testsrc2=size=760x1352:rate=60", "-t", "18", "-c:v", "libx264", "-preset", "ultrafast",
                  "-pix_fmt", "yuv420p", cls.raw], timeout=300, quiet=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.saved_log = base.LOG
        base.LOG = lambda line: None

    def tearDown(self):
        base.LOG = self.saved_log

    def test_the_recording_as_it_is_fails_apples_checks(self):
        apple = video.load_rules("apple")
        msgs = " | ".join(f.message for f in video.check_file(self.raw, apple, "APP_IPHONE_47"))
        self.assertIn("60.00 fps, over 30", msgs)
        self.assertIn("760x1352 isn't a APP_IPHONE_47 preview size", msgs)
        self.assertIn("no audio track", msgs)

    def test_encode_meets_the_spec(self):
        out = os.path.join(self.tmp, "out", "preview.mp4")
        res = video.encode(self.raw, out, slot="APP_IPHONE_47", start=1.0, end=17.0, preset="veryfast")
        self.assertEqual(res["findings"], [])
        probe = video.probe(out)
        v = video.streams(probe, "video")[0]
        a = video.streams(probe, "audio")[0]
        self.assertEqual((v["width"], v["height"], v["codec_name"], v["profile"]), (750, 1334, "h264", "High"))
        self.assertEqual((v["r_frame_rate"], v["avg_frame_rate"]), ("30/1", "30/1"))
        self.assertLessEqual(int(v["level"]), 40)
        self.assertEqual((a["codec_name"], a["channels"], a["sample_rate"]), ("aac", 2, "48000"))
        self.assertAlmostEqual(video.duration(probe), 16.0, delta=0.1)
        self.assertFalse([n for n in os.listdir(os.path.dirname(out)) if n.startswith(".encoding-")])

    def test_the_command_line(self):
        out = os.path.join(self.tmp, "cli.mp4")
        so = io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(io.StringIO()):
            code = video.main(["encode", self.raw, "--out", out, "--slot", "APP_IPHONE_47", "--end", "16",
                               "--preset", "ultrafast"])
        self.assertEqual(code, 0, so.getvalue())
        self.assertIn("silent audio added", so.getvalue())
        self.assertIn("meets the spec", so.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(video.main(["check", out, "--slot", "APP_IPHONE_47"]), 0)
            self.assertEqual(video.main(["check", self.raw]), 1)

    def test_frames_of_a_variable_rate_recording_with_a_rotation(self):
        # A variable rate (20 frames in 0.2 s, then one every 0.3 s) stored on its side with a -90° display matrix,
        # as a two-screen simulator's inner display records: every frame comes out, upright.
        ffmpeg = video.find_tool("ffmpeg")
        vfr = os.path.join(self.tmp, "vfr.mp4")
        rot = os.path.join(self.tmp, "rot.mp4")
        base.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                  "testsrc2=size=240x320:rate=30", "-frames:v", "26", "-vf",
                  "setpts='if(lt(N,20),N*0.01/TB,0.2/TB+(N-20)*0.3/TB)'", "-fps_mode", "passthrough", "-c:v",
                  "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", vfr], timeout=300, quiet=True)
        base.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-display_rotation", "-90", "-i",
                  vfr, "-c", "copy", rot], timeout=300, quiet=True)
        out = os.path.join(self.tmp, "frames")
        res = video.frames(rot, out, width=160)
        self.assertEqual(res["count"], 26)
        self.assertEqual((res["plan"]["width"], res["plan"]["height"], res["plan"]["rotation"]), (160, 120, -90))
        first = video.streams(video.probe(os.path.join(out, "frame-00001.jpg")), "video")[0]
        self.assertEqual((first["width"], first["height"]), (160, 120))

    def test_too_long_is_refused_before_encoding(self):
        out = os.path.join(self.tmp, "short.mp4")
        with self.assertRaises(video.VideoError):
            video.encode(self.raw, out, slot="APP_IPHONE_47", start=10, preset="ultrafast")
        self.assertFalse(os.path.exists(out))


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
