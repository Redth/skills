"""Tests for video.py: the encode plan and command, the checks against the rules' ``video`` rules, and the
recording commands (through a fake ``RUNNER``); then, where ffmpeg and ffprobe are installed, a real encode of a
short ``testsrc`` clip made in a temp folder, checked with ffprobe. Those skip without ffmpeg.
"""

from __future__ import annotations

import contextlib
import io
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

    def test_too_long_is_refused_before_encoding(self):
        out = os.path.join(self.tmp, "short.mp4")
        with self.assertRaises(video.VideoError):
            video.encode(self.raw, out, slot="APP_IPHONE_47", start=10, preset="ultrafast")
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
