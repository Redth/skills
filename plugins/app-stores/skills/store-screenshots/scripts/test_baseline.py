"""Tests for the style file, the baseline and the design sheets: styles.py's merging and roles, render.py's --style
and --out, baseline.py's approve, status and unlock, check.py's drift and style rules, and sheet.py's
--inspiration, --directions and --compare. Synthetic projects only (invented data); Chrome only where installed."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import baseline  # noqa: E402
import check  # noqa: E402
import check_testkit as tk  # noqa: E402
import render  # noqa: E402
import render_testkit as rk  # noqa: E402
import sheet  # noqa: E402
import styles  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import schema  # noqa: E402

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None

THEME = {"palette": {"background": "#0E3B2E", "ink": "#FFFFFF", "accent": "#FFC94D"},
         "background": {"kind": "color"},
         "caption": {"placement": "top", "align": "center", "maxLines": 2, "sizePct": 10.0, "floorPct": 7.0},
         "frame": "phone"}


def a_style(**over):
    data = {"version": 1, "name": "Test bold", "locked": False,
            "traits": {"captionPosition": "top", "captionSize": "standard", "mood": "bold"},
            "theme": copy.deepcopy(THEME),
            "roles": {"hero": {"layout": "hero"}, "feature": {"layout": "framed-bleed"},
                      "accent": {"layout": "tilt", "maxPerSet": 1}},
            "stores": {"google": {"frame": "none"}},
            "copy": {"maxWords": 5, "maxLines": 2, "case": "sentence"},
            "drift": {"captionSize": 0.05, "captionPosition": 0.005, "deviceBox": 0.01, "textShare": 0.03}}
    data.update(over)
    return data


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Project:
    """A styled project in a folder: config, style, captures, and (``fake_render``) a render report and PNGs as
    render.py would write them, without Chrome."""

    def __init__(self, root, targets=None):
        self.root = root
        cfg = tk.base_config(targets=targets)
        cfg["theme"] = {}
        cfg["style"] = "screenshot-style.json"
        for s in cfg["shots"]:
            s.pop("layout")
            s["role"] = "feature"
        self.config = cfg
        self.style = a_style()
        os.makedirs(root, exist_ok=True)
        self.write()
        for t in cfg["targets"].values():
            for s in cfg["shots"]:
                rk.write_capture(os.path.join(root, "captures", "en-US", t["capture"], s["capture"] + ".png"),
                                 t["width"], t["height"])

    @property
    def config_path(self):
        return os.path.join(self.root, "store-screenshots.json")

    @property
    def style_path(self):
        return os.path.join(self.root, "screenshot-style.json")

    @property
    def out(self):
        return os.path.join(self.root, "screenshots")

    def write(self):
        jsonio.dump(self.config, self.config_path)
        jsonio.dump(self.style, self.style_path)
        return self.config_path

    def load_style(self):
        self.style = jsonio.load(self.style_path)
        return self.style

    def fake_render(self, tweak=None):
        """Write a current render report and PNGs; ``tweak(entry)`` may change an entry first."""
        self.write()
        cfg = render.load_config(self.config_path)
        res, wanted = render.expected(self.config_path)
        files = []
        for u in res.units():
            entry = tk.file_entry(cfg, u["locale"], u["target"], u["shot"])
            entry.update({"layout": u["layout"], "role": u.get("role"), "tilt": u.get("tilt"),
                          "inputsSha256": wanted[u["path"]],
                          "background": render.background_summary(u["job"]["theme"])})
            entry["caption"].update({"ink": "#FFFFFF", "case": "none"})
            if tweak:
                tweak(entry)
            path = os.path.join(self.out, entry["path"])
            tk.write_png(path, entry["width"], entry["height"], tk.GREEN,
                         tk.text_rects(entry["caption"]["box"], tk.WHITE))
            entry["sha256"] = png.sha256(path)
            files.append(entry)
        report = {"version": 1, "renderedAt": "2026-11-14T10:00:00Z", "config": "store-screenshots.json",
                  "configSha256": styles.config_sha256(cfg["_raw"]), "style": render.style_entry(cfg, self.config_path),
                  "inputsSha256": "x", "files": files, "errors": []}
        jsonio.dump(report, os.path.join(self.out, "render-report.json"))
        return report


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="baseline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def project(self, **kw):
        return Project(os.path.join(self.tmp, "p"), **kw)

    def quiet(self, fn, *a, **kw):
        lines = []
        kw.setdefault("log", lines.append)
        return fn(*a, **kw), lines

    def main(self, module, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def ids(self, report, severity=None):
        return [f.rule_id for _, f in report.findings if severity is None or f.severity == severity]


# ------------------------------------------------------------------------------------------------ the style file

class StyleFile(Case):
    def test_the_style_schema_uses_only_supported_keywords(self):
        self.assertEqual(schema.unsupported(styles.style_schema()), [])

    def test_the_vocabulary_lives_in_one_place(self):
        vocab = styles.trait_vocabulary()
        for trait in ("captionPosition", "captionSize", "captionWeight", "captionCase", "emphasis", "device",
                      "background", "density", "colour", "mood"):
            self.assertIn(trait, vocab)
            self.assertGreaterEqual(len(vocab[trait]), 3 if trait != "captionAlign" else 2)
        self.assertEqual(vocab["captionSize"], ["quiet", "standard", "loud"])

    def test_every_starting_style_validates_and_says_who_it_suits(self):
        found = styles.starting_styles()
        self.assertGreaterEqual(len(found), 5)
        for name, (path, data) in found.items():
            with self.subTest(name=name):
                self.assertEqual(styles.validate_style(data), [])
                self.assertFalse(data.get("locked"))
                self.assertIn("Suits", data["$comment"])
                self.assertTrue(data["traits"])

    def test_an_unknown_trait_value_is_refused(self):
        data = a_style(traits={"mood": "grumpy"})
        problems = styles.validate_style(data)
        self.assertTrue(any("/traits/mood" in p for p in problems), problems)

    def test_the_styles_theme_is_checked_against_the_configs_theme(self):
        data = a_style()
        data["theme"]["caption"]["placement"] = "middle"
        self.assertTrue(any("caption/placement" in p for p in styles.validate_style(data)))

    def test_inspiration_shape(self):
        good = {"version": 1, "examples": [{"file": "a.png", "source": "a listing", "likes": ["big words"],
                                            "dislikes": [], "traits": {"captionSize": ["standard", "loud"]}}],
                "summary": {"traits": {"mood": "calm"}, "confirmedByUser": False}}
        self.assertEqual(styles.validate_inspiration(good), [])
        bad = copy.deepcopy(good)
        bad["examples"][0]["traits"]["device"] = "hologram"
        self.assertTrue(styles.validate_inspiration(bad))


class Merging(Case):
    def test_the_style_wins_key_by_key_and_roles_give_layouts(self):
        cfg = tk.base_config()
        cfg["theme"] = {"palette": {"background": "#000000", "band": "#123456"}, "caption": {"sizePct": 7.0}}
        cfg["stores"] = {"google": {"layout": "band"}, "apple": {}}
        cfg["shots"][0].pop("layout")
        cfg["shots"][0]["role"] = "accent"
        out = styles.apply(cfg, a_style())
        self.assertEqual(out["theme"]["palette"]["background"], "#0E3B2E")   # the style's
        self.assertEqual(out["theme"]["palette"]["band"], "#123456")         # the config's, the style has none
        self.assertEqual(out["theme"]["caption"]["sizePct"], 10.0)
        self.assertEqual(out["stores"]["google"], {"layout": "band", "frame": "none"})
        self.assertEqual(out["shots"][0]["layout"], "tilt")
        self.assertEqual(cfg["theme"]["palette"]["background"], "#000000")  # the input isn't changed

    def test_a_shots_own_layout_beats_its_role_and_a_store_beats_both(self):
        p = self.project()
        p.config["shots"][0]["layout"] = "framed"
        p.config["shots"][1]["role"] = "accent"
        p.config["stores"]["google"] = {"layout": "fullbleed"}
        cfg = render.load_config(p.write())
        res = render.Resolver(cfg, p.config_path)
        self.assertEqual(res.settings(cfg["shots"][0], "iphone")["layout"], "framed")
        self.assertEqual(res.settings(cfg["shots"][1], "iphone")["layout"], "tilt")
        self.assertEqual(res.settings(cfg["shots"][1], "android-phone")["layout"], "fullbleed")

    def test_a_role_the_style_lacks_or_a_role_without_a_style_is_usage(self):
        p = self.project()
        p.config["shots"][0]["role"] = "banner"
        with self.assertRaises(render.UsageError) as e:
            render.load_config(p.write())
        self.assertIn("banner", str(e.exception))
        p.config["shots"][0]["role"] = "feature"
        del p.config["style"]
        with self.assertRaises(render.UsageError):
            render.load_config(p.write())

    def test_style_override_and_out(self):
        p = self.project()
        other = a_style(name="Other", theme=dict(THEME, palette={"background": "#FFFFFF", "ink": "#111111"}))
        jsonio.dump(other, os.path.join(self.tmp, "other.json"))
        cfg = render.load_config(p.config_path, os.path.join(self.tmp, "other.json"))
        self.assertEqual(cfg["theme"]["palette"]["background"], "#FFFFFF")
        self.assertEqual(cfg["_style"]["data"]["name"], "Other")
        res = render.Resolver(cfg, p.config_path, "design/explore/other")
        self.assertEqual(res.out, os.path.join(p.root, "design", "explore", "other"))
        _, a = render.expected(p.config_path)
        _, b = render.expected(p.config_path, os.path.join(self.tmp, "other.json"))
        self.assertNotEqual(a, b)

    def test_locking_a_style_doesnt_change_its_hash_or_the_renders(self):
        p = self.project()
        _, before = render.expected(p.config_path)
        h = styles.style_sha256(p.style)
        p.style["locked"] = True
        p.write()
        _, after = render.expected(p.config_path)
        self.assertEqual(before, after)
        self.assertEqual(styles.style_sha256(p.style), h)

    def test_background_summary(self):
        self.assertEqual(render.background_summary({"palette": {"background": "#0e3b2e"},
                                                    "background": {"kind": "color"}}),
                         {"kind": "color", "colours": ["#0E3B2E"]})
        g = render.background_summary({"palette": {"background": "#000000", "background2": "#222222"},
                                       "background": {"kind": "gradient", "angle": 180}})
        self.assertEqual((g["kind"], g["colours"], g["angle"]), ("gradient", ["#222222", "#000000"], 180))


# ------------------------------------------------------------------------------------------------ baseline.py

class Approve(Case):
    def test_refuses_without_a_report(self):
        p = self.project()
        code, _, err = self.main(baseline, "approve", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_REFUSED)
        self.assertIn("no render report", err)
        self.assertFalse(p.load_style().get("locked"))

    def test_refuses_a_report_from_other_inputs(self):
        p = self.project()
        p.fake_render()
        p.config["strings"]["en-US"]["cap.plan"] = "Plan a fortnight"
        p.write()
        code, _, err = self.main(baseline, "approve", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_REFUSED)
        self.assertIn("other inputs", err)
        self.assertIn("en-US/iphone/plan.png", err)

    def test_refuses_a_file_changed_on_disk(self):
        p = self.project()
        p.fake_render()
        tk.write_png(os.path.join(p.out, "en-US/iphone/plan.png"), 1320, 2868, (1, 2, 3))
        code, _, err = self.main(baseline, "approve", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_REFUSED)
        self.assertIn("changed on disk", err)

    def test_refuses_without_a_style_or_with_a_contradicting_theme(self):
        p = self.project()
        p.config["theme"] = {"palette": {"background": "#FF0000"}}
        p.fake_render()
        code, _, err = self.main(baseline, "approve", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_REFUSED)
        self.assertIn("theme.palette.background", err)
        p.config["theme"] = copy.deepcopy(THEME)
        del p.config["style"]
        for s in p.config["shots"]:
            s["layout"] = s.pop("role") and "framed-bleed"
        p.fake_render()
        code, _, err = self.main(baseline, "approve", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_REFUSED)
        self.assertIn("no style", err)

    def test_refuses_a_set_with_check_errors(self):
        p = self.project()

        def broken(e):
            if e["path"] == "en-US/iphone/plan.png":
                e["caption"]["fits"] = False
        p.fake_render(broken)
        code, _, err = self.main(baseline, "approve", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_REFUSED)
        self.assertIn("check.py finds", err)

    def test_approve_copies_locks_and_logs(self):
        p = self.project()
        p.fake_render()
        when = baseline.datetime.datetime(2026, 11, 14, 9, 30, tzinfo=baseline.datetime.timezone.utc)
        meta, lines = self.quiet(baseline.approve, p.config_path, "Bold and blue: what the user picked", now=when)
        folder = os.path.join(p.root, "design", "baseline")
        self.assertEqual(meta["approvedAt"], "2026-11-14T09:30:00Z")
        self.assertEqual(len(meta["files"]), 9)
        self.assertEqual(jsonio.load(os.path.join(folder, "baseline.json")), meta)
        for rel in meta["files"]:
            self.assertEqual(png.sha256(os.path.join(folder, rel)), png.sha256(os.path.join(p.out, rel)))
        self.assertTrue(p.load_style()["locked"])
        self.assertTrue(jsonio.load(os.path.join(folder, "screenshot-style.json"))["locked"])
        self.assertEqual(meta["styleSha256"], styles.style_sha256(p.style))
        self.assertEqual(len(jsonio.load(os.path.join(folder, "render-report.json"))["files"]), 9)
        log = read(os.path.join(p.root, "design", "decisions.md"))
        self.assertIn("## 2026-11-14: baseline approved", log)
        self.assertIn("Bold and blue: what the user picked", log)

    def test_a_second_approval_keeps_the_first_in_history(self):
        p = self.project()
        p.fake_render()
        first = baseline.datetime.datetime(2026, 11, 14, tzinfo=baseline.datetime.timezone.utc)
        self.quiet(baseline.approve, p.config_path, "first", now=first)
        p.load_style()
        p.config["strings"]["en-US"]["cap.plan"] = "Plan the week"
        p.fake_render()
        self.quiet(baseline.approve, p.config_path, "second", now=first.replace(day=20))
        history = os.path.join(p.root, "design", "baseline", "history", "2026-11-14")
        self.assertEqual(jsonio.load(os.path.join(history, "baseline.json"))["note"], "first")
        self.assertTrue(os.path.isfile(os.path.join(history, "en-US", "iphone", "plan.png")))
        self.assertEqual(jsonio.load(os.path.join(p.root, "design", "baseline", "baseline.json"))["note"], "second")
        log = read(os.path.join(p.root, "design", "decisions.md"))
        self.assertEqual(log.count("baseline approved"), 2)
        self.assertEqual(log.count("# Design decisions"), 1)


class StatusAndUnlock(Case):
    def approved(self):
        p = self.project()
        p.fake_render()
        self.quiet(baseline.approve, p.config_path, "ok")
        p.load_style()
        return p

    def test_status_before_and_after(self):
        p = self.project()
        st = baseline.status(p.config_path)
        self.assertIsNone(st["baseline"])
        self.assertFalse(st["report"]["current"])
        p = self.approved()
        st = baseline.status(p.config_path)
        self.assertEqual(st["baseline"]["files"], 9)
        self.assertFalse(st["style"]["changed"])
        self.assertFalse(st["configChanged"])
        self.assertTrue(st["report"]["current"])
        self.assertEqual(st["newShots"], [])

    def test_status_names_new_shots_and_a_changed_locked_style(self):
        p = self.approved()
        p.config["shots"].append({"id": "pantry", "capture": "plan", "role": "feature", "caption": "cap.plan"})
        p.style["theme"]["caption"]["sizePct"] = 12.0
        p.write()
        st = baseline.status(p.config_path)
        self.assertIn("iphone/pantry", st["newShots"])
        self.assertTrue(st["configChanged"])
        self.assertTrue(st["lockedStyleChanged"])
        code, out, _ = self.main(baseline, "status", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_CHANGED)
        self.assertIn("The locked style changed", out)

    def test_unlock_needs_a_reason_and_logs_it(self):
        p = self.approved()
        code, _, _ = self.main(baseline, "unlock", "--config", p.config_path)
        self.assertEqual(code, baseline.EXIT_USAGE)
        code, _, _ = self.main(baseline, "unlock", "--config", p.config_path, "--reason", "  ")
        self.assertEqual(code, baseline.EXIT_USAGE)
        self.assertTrue(p.load_style()["locked"])
        code, out, _ = self.main(baseline, "unlock", "--config", p.config_path, "--reason",
                                 "The rebrand: new colours for the spring release")
        self.assertEqual(code, 0)
        self.assertFalse(p.load_style()["locked"])
        log = read(os.path.join(p.root, "design", "decisions.md"))
        self.assertIn("style unlocked", log)
        self.assertIn("The rebrand: new colours for the spring release", log)
        _, out, _ = self.main(baseline, "unlock", "--config", p.config_path, "--reason", "again")
        self.assertIn("isn't locked", out)
        self.assertEqual(read(os.path.join(p.root, "design", "decisions.md")), log)


# ------------------------------------------------------------------------------------------------ check: drift

def entry(**over):
    e = {"path": "en-US/iphone/plan.png", "locale": "en-US", "target": "iphone", "shot": "plan", "role": "feature",
         "layout": "framed-bleed", "width": 1000, "height": 2172, "tilt": None,
         "caption": {"text": "Plan your week", "lines": 2, "fontPx": 95.0, "box": [80, 190, 840, 205],
                     "textShare": 0.08, "ink": "#FFFFFF", "accent": "#FFC94D"},
         "frame": {"name": "phone", "box": [70, 610, 860, 1815], "tilted": False},
         "background": {"kind": "color", "colours": ["#0E3B2E"]}}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(e.get(k), dict):
            e[k] = dict(e[k], **v)
        else:
            e[k] = v
    return e


class Drift(unittest.TestCase):
    tol = styles.drift_tolerances(None)

    def drift(self, **over):
        return check.drift_messages(entry(**over), entry(), self.tol)

    def test_the_same_file_has_no_drift(self):
        self.assertEqual(self.drift(), [])

    def test_caption_size_within_and_past_its_tolerance(self):
        self.assertEqual(self.drift(caption={"fontPx": 92.0}), [])                    # -3%
        found = self.drift(caption={"fontPx": 85.0})                                   # -11%
        self.assertEqual(len(found), 1)
        self.assertIn("caption size 8.5u, the baseline's 9.5u", found[0])

    def test_caption_top_and_lines(self):
        self.assertEqual(self.drift(caption={"box": [80, 194, 840, 205]}), [])        # 0.4u
        self.assertIn("caption top", self.drift(caption={"box": [80, 200, 840, 205]})[0])
        found = self.drift(caption={"lines": 3, "box": [80, 190, 840, 307]})
        self.assertTrue(any("runs to 3 lines; the baseline's 2" in m for m in found), found)

    def test_the_device_box_frame_and_tilt(self):
        self.assertEqual(self.drift(frame={"box": [74, 610, 860, 1815]}), [])         # 0.4u
        found = self.drift(frame={"box": [70, 640, 860, 1815]})
        self.assertIn("the device moved: y 64.0u, was 61.0u", found[0])
        self.assertIn("frame none, the baseline's phone", self.drift(frame={"name": "none"})[0])
        self.assertTrue(self.drift(frame={"tilted": True}))

    def test_text_share_colours_background_and_layout(self):
        self.assertTrue(self.drift(caption={"textShare": 0.13}))
        self.assertEqual(self.drift(caption={"ink": "#FEFEFE"}), [])                   # delta E under 2
        self.assertIn("caption ink #FFE000", self.drift(caption={"ink": "#FFE000"})[0])
        self.assertIn("background gradient", self.drift(background={"kind": "gradient", "colours": ["#0E3B2E"]})[0])
        self.assertIn("background colours", self.drift(background={"colours": ["#1E4FD6"]})[0])
        self.assertIn("layout is tilt", self.drift(layout="tilt")[0])

    def test_a_changed_caption_class_is_drift_whatever_the_tolerance(self):
        # A baseline rendered before the caption class was reported: its aspect class is what sized its words.
        old = entry(store="apple", aspectClass="mid", caption={"fontPx": 62.7})
        new = entry(store="apple", aspectClass="mid", captionClass="tall", caption={"fontPx": 98.0})
        found = check.drift_messages(new, old, self.tol)
        self.assertTrue(any(m.startswith("captions sized as a tall slot's, the baseline's as a mid slot's")
                            and "\"captionClass\": \"mid\"" in m for m in found), found)
        self.assertTrue(any(m.startswith("caption size 9.8u, the baseline's 6.3u") for m in found), found)
        loose = styles.drift_tolerances({"drift": {"captionSize": 1.0}})
        self.assertEqual(len(check.drift_messages(new, old, loose)), 1)       # the class is still said
        same = entry(store="apple", aspectClass="mid", captionClass="mid")
        self.assertEqual(check.drift_messages(same, entry(store="apple", aspectClass="mid"), self.tol), [])

    def test_the_styles_tolerances_are_used(self):
        loose = styles.drift_tolerances({"drift": {"captionSize": 0.2}})
        self.assertEqual(check.drift_messages(entry(caption={"fontPx": 85.0}), entry(), loose), [])

    def test_matching_by_shot_then_role_then_layout(self):
        base = [entry(), entry(path="en-US/iphone/hero.png", shot="hero", role="hero", layout="hero")]
        cur = [entry(locale="de-DE", path="de-DE/iphone/plan.png"), entry(shot="new", path="en-US/iphone/new.png"),
               entry(shot="splash", role="hero", layout="hero", path="en-US/iphone/splash.png")]
        pairs, new, gone = check.match_baseline(cur, base, "en-US")
        got = dict((c["shot"], b["shot"]) for c, b in pairs)
        self.assertEqual(got, {"plan": "plan", "new": "plan", "splash": "hero"})
        self.assertEqual(new, ["en-US/iphone/new", "en-US/iphone/splash"])
        self.assertEqual(gone, ["iphone/hero"])

    def test_case_rules(self):
        self.assertTrue(check.case_ok("Plan your *week*", "sentence"))
        self.assertFalse(check.case_ok("Plan Your Whole Week", "sentence"))
        self.assertTrue(check.case_ok("Eine Woche Essen planen", "sentence"))
        self.assertFalse(check.case_ok("plan your week", "sentence"))
        self.assertTrue(check.case_ok("Save the king", "upper", drawn="upper"))
        self.assertFalse(check.case_ok("Save the king", "upper"))


class CheckWithBaseline(Case):
    def approved(self):
        p = self.project()
        p.fake_render()
        self.quiet(baseline.approve, p.config_path, "ok")
        p.load_style()
        return p

    def test_the_baseline_is_used_by_itself_and_says_so(self):
        p = self.approved()
        report = check.run_check(p.config_path)
        self.assertEqual(report.errors, [], report.to_text())
        self.assertTrue(any(n.startswith("compared with the baseline") for n in report.notes))
        report = check.run_check(p.config_path, baseline=None)
        self.assertFalse(any(n.startswith("compared with the baseline") for n in report.notes))
        code, _, err = self.main(check, "--config", p.config_path, "--baseline", os.path.join(self.tmp, "nowhere"))
        self.assertEqual(code, 3)
        self.assertIn("no baseline", err)

    def test_a_three_line_caption_is_drift(self):
        p = self.approved()

        def longer(e):
            if e["path"] == "en-US/iphone/recipe.png":
                e["caption"].update(lines=3, box=[66, 230, 1188, 430])
        p.fake_render(longer)
        report = check.run_check(p.config_path)
        drift = [f for _, f in report.findings if f.rule_id == "design.baseline.drift"]
        self.assertTrue(any("runs to 3 lines" in f.message and f.where == "en-US/iphone/recipe.png" for f in drift),
                        report.to_text())
        self.assertTrue(all(f.severity == "warning" for f in drift))
        self.assertIn("design.style.copy.lines", self.ids(report))

    def test_an_apple_phone_slot_whose_class_changed_drifts_against_its_baseline(self):
        duo = {"store": "apple", "width": 1398, "height": 2034, "capture": "duo-outer"}
        p = Project(os.path.join(self.tmp, "p"), targets=dict(tk.TARGETS, **{"duo-outer": duo}))

        def before(e):   # the approved render: the mid factor, no caption class reported
            e["aspectClass"] = render.aspect_class(e["width"], e["height"])
            if e["target"] == "duo-outer":
                e["caption"]["fontPx"] = round(1398 * 0.0627, 1)
        p.fake_render(before)
        self.quiet(baseline.approve, p.config_path, "ok")
        p.load_style()

        def after(e):    # rendered again: the tall factor
            e["aspectClass"] = render.aspect_class(e["width"], e["height"])
            e["captionClass"] = render.caption_class(p.config["targets"][e["target"]])[0]
        p.fake_render(after)
        report = check.run_check(p.config_path)
        drift = [f for _, f in report.findings if f.rule_id == "design.baseline.drift"]
        where = set(f.where for f in drift)
        self.assertEqual(where, {"en-US/duo-outer/plan.png", "en-US/duo-outer/recipe.png",
                                 "en-US/duo-outer/shop.png"}, report.to_text())
        self.assertTrue(any("captions sized as a tall slot's" in f.message for f in drift))
        self.assertTrue(any("caption size 10.0u, the baseline's 6.3u" in f.message for f in drift))

    def test_a_changed_locked_style_is_an_error(self):
        p = self.approved()
        p.style["theme"]["caption"]["sizePct"] = 12.0
        p.write()
        report = check.run_check(p.config_path)
        self.assertIn("design.baseline.style_changed", self.ids(report, "error"))
        self.assertIn("approve a new baseline", report.to_text())

    def test_an_unlocked_style_is_a_note_not_an_error(self):
        p = self.approved()
        self.quiet(baseline.unlock, p.config_path, "the user's rebrand")
        p.load_style()
        p.style["theme"]["caption"]["sizePct"] = 12.0
        p.write()
        report = check.run_check(p.config_path)
        self.assertNotIn("design.baseline.style_changed", self.ids(report))
        self.assertTrue(any("unlocked" in n for n in report.notes))

    def test_a_config_theme_against_a_locked_style_is_an_error(self):
        p = self.approved()
        p.config["theme"] = {"palette": {"accent": "#FF0000"}, "frame": "phone"}
        p.write()
        report = check.run_check(p.config_path)
        errors = [f for _, f in report.findings if f.rule_id == "design.style.theme_override"]
        self.assertEqual([f.where for f in errors], ["theme.palette.accent"])  # the same value isn't a conflict

    def test_a_layout_outside_the_locked_styles_roles_warns(self):
        p = self.approved()
        p.config["shots"][2].pop("role")
        p.config["shots"][2]["layout"] = "band"
        p.write()
        report = check.run_check(p.config_path)
        self.assertIn("design.style.layout_outside_roles", self.ids(report, "warning"))

    def test_copy_rules_warn(self):
        p = self.project()
        p.config["strings"]["en-US"]["cap.plan"] = "Plan Every Single Meal For Your Week"
        p.fake_render()
        report = check.run_check(p.config_path)
        ids = self.ids(report, "warning")
        self.assertIn("design.style.copy.words", ids)
        self.assertIn("design.style.copy.case", ids)


class SetRules(Case):
    def test_a_device_or_caption_moving_inside_a_set_warns(self):
        s = tk.SetBuilder(self.tmp)
        f = s.find("en-US/iphone/recipe.png")
        f["frame"]["box"][1] += 20       # 1.5u
        g = s.find("en-US/iphone/shop.png")
        g["caption"]["box"][1] += 13      # 1u
        report = check.run_check(s.write())
        found = dict((x.rule_id, x) for _, x in report.findings)
        self.assertIn("recipe", found["design.set.device"].message)
        self.assertIn("shop", found["design.set.caption"].message)

    def test_small_first_captions_warn_on_play_too(self):
        s = tk.SetBuilder(self.tmp)
        for f in s.files:
            if f["target"] == "android-phone" and f["shot"] == "plan":
                f["caption"]["fontPx"] = 1080 * 0.085
        report = check.run_check(s.write())
        found = [x for st, x in report.findings if x.rule_id == "design.caption.search_size" and st == "google"]
        self.assertEqual(len(found), 1)
        self.assertIn("8.5u (plan)", found[0].message)


# ------------------------------------------------------------------------------------------------ sheets

class DesignSheets(Case):
    def inspiration(self, p):
        folder = os.path.join(p.root, "design", "inspiration")
        tk.write_png(os.path.join(folder, "liked.png"), 60, 130, (30, 79, 214))
        tk.write_png(os.path.join(folder, "nope.png"), 60, 130, (200, 40, 120))
        jsonio.dump({"version": 1, "examples": [
            {"file": "liked.png", "source": "a to-do app's listing", "likes": ["one bold line"],
             "traits": {"captionWeight": "heavy"}},
            {"file": "nope.png", "source": "a game's listing", "likes": [], "dislikes": ["badges everywhere"],
             "traits": {"density": "packed"}}],
            "summary": {"traits": {"mood": "bold"}, "confirmedByUser": False}},
            os.path.join(folder, "inspiration.json"))

    def test_inspiration(self):
        p = self.project()
        self.inspiration(p)
        code, out, err = self.main(sheet, "--config", p.config_path, "--inspiration")
        self.assertEqual(code, 0, err)
        page = read(os.path.join(p.root, "design", "sheets", "inspiration.html"))
        self.assertIn("../inspiration/liked.png", page)
        self.assertIn("one bold line", page)
        self.assertIn("badges everywhere", page)
        self.assertIn("not this", page)
        self.assertIn("Not confirmed yet", page)
        self.assertIn("<b>captionWeight</b>heavy", page)

    def test_inspiration_needs_its_file(self):
        p = self.project()
        code, _, err = self.main(sheet, "--config", p.config_path, "--inspiration")
        self.assertEqual(code, 3)
        self.assertIn("inspiration.json", err)

    def test_directions(self):
        p = self.project()
        p.fake_render()
        explore = os.path.join(p.root, "design", "explore")
        for name in ("bold", "calm"):
            shutil.copytree(p.out, os.path.join(explore, name))
        code, _, err = self.main(sheet, "--config", p.config_path, "--directions",
                                 "design/explore/bold,design/explore/calm")
        self.assertEqual(code, 0, err)
        page = read(os.path.join(p.root, "design", "sheets", "directions.html"))
        self.assertEqual(page.count('<section class="card">'), 2)
        self.assertIn("Test bold", page)
        self.assertIn("In search (118 pt a shot)", page)
        self.assertIn("11.8 pt", page)
        self.assertIn("../explore/bold/en-US/iphone/plan.png", page)

    def test_compare_writes_the_drift_under_each_pair(self):
        p = self.project()
        p.fake_render()
        self.quiet(baseline.approve, p.config_path, "ok")

        def moved(e):
            if e["shot"] == "recipe":
                e["caption"]["fontPx"] = round(e["width"] * 0.08, 1)
        p.fake_render(moved)
        code, _, err = self.main(sheet, "--config", p.config_path, "--compare", "design/baseline")
        self.assertEqual(code, 0, err)
        folder = os.path.join(p.out, "sheets")
        self.assertEqual(sorted(n for n in os.listdir(folder) if n.endswith(".html")),
                         ["compare-android-phone.html", "compare-iphone-medium.html", "compare-iphone.html"])
        page = read(os.path.join(folder, "compare-iphone.html"))
        self.assertEqual(page.count('<div class="pair"') + page.count('<div class="pair drift"'), 3)
        self.assertEqual(page.count('class="pair drift"'), 1)
        self.assertIn("caption size 8.0u, the baseline&#x27;s 10.0u", page)
        self.assertIn("../../design/baseline/en-US/iphone/plan.png", page)
        self.assertIn("1 of 3 pairs drifted", page)
        # The store mocks and the compare pages don't remove each other.
        self.main(sheet, "--config", p.config_path)
        self.assertTrue(os.path.isfile(os.path.join(folder, "compare-iphone.html")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "contact-sheet.html")))

    @unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
    def test_the_design_sheets_render(self):
        p = self.project()
        self.inspiration(p)
        p.fake_render()
        self.quiet(baseline.approve, p.config_path, "ok")
        shutil.copytree(p.out, os.path.join(p.root, "design", "explore", "bold"))
        for argv, path in ((["--inspiration"], "design/sheets/inspiration.png"),
                           (["--directions", "design/explore/bold"], "design/sheets/directions.png"),
                           (["--compare", "design/baseline"], "screenshots/sheets/compare-iphone.png")):
            code, _, err = self.main(sheet, "--config", p.config_path, "--png", *argv)
            self.assertEqual(code, 0, err)
            info = png.info(os.path.join(p.root, path))
            self.assertGreater(info.height, 300)


@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class RenderWithStyle(Case):
    def test_an_exploration_renders_elsewhere_with_its_style_in_the_report(self):
        root = os.path.join(self.tmp, "r")
        cfg = rk.base_config()
        cfg["theme"] = {}
        cfg["style"] = "screenshot-style.json"
        cfg["shots"][0].pop("layout")
        cfg["shots"][0]["role"] = "feature"
        path = rk.make_project(root, cfg)
        jsonio.dump(a_style(), os.path.join(root, "screenshot-style.json"))
        other = a_style(name="Calm", theme=dict(THEME, palette={"background": "#F6F2EA", "ink": "#17150F",
                                                                "accent": "#B4441C"}))
        jsonio.dump(other, os.path.join(root, "calm.json"))
        code, out, err = self.main(render, "--config", path, "--style", os.path.join(root, "calm.json"),
                                   "--out", "design/explore/calm")
        self.assertEqual(code, 0, out + err)
        report = jsonio.load(os.path.join(root, "design", "explore", "calm", "render-report.json"))
        self.assertEqual(report["style"]["name"], "Calm")
        f = report["files"][0]
        self.assertEqual((f["role"], f["layout"]), ("feature", "framed-bleed"))
        self.assertEqual(f["background"], {"kind": "color", "colours": ["#F6F2EA"]})
        self.assertFalse(os.path.isdir(os.path.join(root, "out")))
        w, h, rgb = png.decode_rgb(os.path.join(root, "design", "explore", "calm", f["path"]))
        self.assertEqual(rgb[0:3], bytes([0xF6, 0xF2, 0xEA]))


if __name__ == "__main__":
    unittest.main()
