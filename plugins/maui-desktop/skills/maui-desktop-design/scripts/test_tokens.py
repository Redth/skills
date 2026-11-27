"""Tests for tokens.py: the schema, resolution, every output, --check, contrast, show and init.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Fixtures live in
``../evals/files/<scenario>/`` and are copied to a temp folder before anything writes. Nothing here reaches a
network or needs Node: the port check compares against values committed in
``evals/files/port-check/expected.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_color as dc  # noqa: E402
import design_testkit as kit  # noqa: E402
import tokens  # noqa: E402
from mauidesktop_lib import jsonio  # noqa: E402
from mauidesktop_lib import schema  # noqa: E402


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tokens-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def project(self, name):
        return kit.fixture(name, os.path.join(self.tmp, name))

    def edit(self, root, fn, path=os.path.join("design", "tokens.json")):
        full = os.path.join(root, path)
        data = kit.load(full)
        fn(data)
        kit.dump(data, full)
        return data

    def tokens(self, *argv):
        return kit.run(tokens, list(argv))

    def tokens_json(self, *argv):
        return kit.run_json(tokens, list(argv))


def oklch_numbers(value):
    m = re.match(r"^oklch\(([-\d.]+) ([-\d.]+) ([-\d.]+)(?: / ([-\d.]+))?\)$", value)
    return [float(x) for x in m.groups() if x is not None] if m else None


class Schemas(unittest.TestCase):
    def test_both_schemas_use_only_supported_keywords(self):
        for name in ("tokens.schema.json", "icons.schema.json"):
            sch = jsonio.load(os.path.join(kit.SKILL_DIR, "schema", name))
            self.assertEqual(schema.unsupported(sch), [], name)

    def test_templates_and_fixtures_are_valid(self):
        sch = jsonio.load(os.path.join(kit.SKILL_DIR, "schema", "tokens.schema.json"))
        paths = [os.path.join(kit.TEMPLATES, "tokens.json")]
        for name in ("tokens-basic", "tokens-platforms", "tokens-bad-contrast", "lint-legacy", "port-check"):
            paths.append(os.path.join(kit.FILES, name, "design", "tokens.json"))
        for path in paths:
            self.assertEqual(schema.validate(jsonio.load(path), sch), [], path)


class Template(TempDir):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(self.root, "design"))
        shutil.copy(os.path.join(kit.TEMPLATES, "tokens.json"), os.path.join(self.root, "design", "tokens.json"))

    def test_contrast_passes(self):
        code, report = self.tokens_json("contrast", "--root", self.root)
        self.assertEqual(code, 0, report["findings"])
        self.assertEqual(report["findings"], [])
        self.assertGreater(len(report["pairs"]), 60)

    def test_contrast_passes_with_the_template_as_the_root_file(self):
        root = os.path.join(self.tmp, "bare")
        os.makedirs(root)
        shutil.copy(os.path.join(kit.TEMPLATES, "tokens.json"), os.path.join(root, "tokens.json"))
        code, out, err = self.tokens("contrast", "--root", root, "--quiet")
        self.assertEqual(code, 0, out + err)

    def test_builds_every_output_cleanly(self):
        def outputs(d):
            d["outputs"] = {"css": "src/App.Ui/wwwroot/css/tokens.css",
                            "csharp": {"path": "src/App.Core/Theme/Tokens.g.cs", "namespace": "App.Core.Theme",
                                       "scale": ["radius", "control"]},
                            "design": "DESIGN.md",
                            "macosAccent": {"path": "src/App.MacOS/Assets.xcassets/AccentColor.colorset/Contents.json",
                                            "role": "accent"}}
        self.edit(self.root, outputs)
        kit.write(os.path.join(self.root, "DESIGN.md"), "\n".join(
            "<!-- generated:%s:start -->\n<!-- generated:%s:end -->\n" % (m, m)
            for m in ("palette-light", "palette-dark", "platform-matrix")))
        code, out, err = self.tokens("build", "--root", self.root)
        self.assertEqual(code, 0, out + err)
        code, out, err = self.tokens("build", "--root", self.root, "--check")
        self.assertEqual(code, 0, out + err)
        css = kit.read(os.path.join(self.root, "src/App.Ui/wwwroot/css/tokens.css"))
        for selector in (':root[data-platform="macos"]', ':root[data-platform="windows"]',
                         ':root[data-platform="linux"]', ".density-compact", "prefers-reduced-motion"):
            self.assertIn(selector, css)
        cs = kit.read(os.path.join(self.root, "src/App.Core/Theme/Tokens.g.cs"))
        self.assertIn("public enum AppPlatform { MacOS, Windows, Linux }", cs)
        self.assertIn("public static double Radius(AppPlatform platform, AppRadius token)", cs)
        matrix = kit.marker_rows(kit.read(os.path.join(self.root, "DESIGN.md")), "platform-matrix")
        self.assertTrue(any(r.startswith("| `--text-base` | `14px` | `13px` |") for r in matrix), matrix)

    def test_status_tints_are_opaque_and_inks_meet_aa(self):
        tok = tokens.load_tokens(os.path.join(self.root, "design", "tokens.json"), self.root)
        for theme in tokens.THEMES:
            for role, color in tok.palette[theme].items():
                if role.endswith("-bg") or role.startswith("surface") or role == "bg":
                    self.assertEqual(dc.alpha(color), 1, "%s/%s" % (theme, role))
                if role.startswith("border-"):
                    self.assertLess(dc.alpha(color), 1, "%s/%s" % (theme, role))


class Basic(TempDir):
    def setUp(self):
        super().setUp()
        self.root = self.project("tokens-basic")

    def test_build_writes_css_csharp_and_design(self):
        code, out, err = self.tokens("build", "--root", self.root)
        self.assertEqual(code, 0, out + err)
        css = kit.read(os.path.join(self.root, "src/SampleNotes/wwwroot/css/tokens.css"))
        values, hexes = kit.parse_css(css)
        self.assertEqual(sorted(values), sorted([
            ":root", ".density-compact", '@media (prefers-color-scheme: dark) > :root:not([data-theme="light"])',
            ':root[data-theme="dark"]', ':root[data-theme="light"]', "@media (prefers-reduced-motion: reduce) > :root"]))
        light = values[":root"]
        self.assertEqual(light["color-scheme"], "light")
        self.assertEqual(light["--bg"], "oklch(1.000 0.000 0)")
        self.assertEqual(hexes[":root"]["--ink"], "#18181b")
        self.assertEqual(light["--space-1"], "4px")
        self.assertEqual(light["--text-body"], "0.875rem")
        self.assertEqual(light["--text-body-weight"], "400")
        self.assertEqual(light["--text-body-lh"], "1.45")
        self.assertEqual(light["--z-popover"], "30")
        self.assertEqual(light["--row-h"], "36px")
        self.assertEqual(light["--shadow-popover"], "0 10px 28px oklch(0 0 0 / 12%)")
        self.assertEqual(values[".density-compact"], {"--row-h": "28px"})
        self.assertEqual(values["@media (prefers-reduced-motion: reduce) > :root"],
                         {"--motion-fast": "1ms", "--motion-slow": "1ms"})
        dark = values[':root[data-theme="dark"]']
        self.assertEqual(dark["color-scheme"], "dark")
        self.assertEqual(dark, values['@media (prefers-color-scheme: dark) > :root:not([data-theme="light"])'])
        self.assertEqual(values[':root[data-theme="light"]']["--accent"], light["--accent"])
        # The mix into a grey kept the green's hue.
        self.assertEqual(oklch_numbers(dark["--ok-tint"])[2], 150)

        cs = kit.read(os.path.join(self.root, "src/SampleNotes.Core/Theme/Tokens.g.cs"))
        self.assertIn("namespace SampleNotes.Core.Theme;", cs)
        self.assertIn("public enum SampleNotesColor", cs)
        self.assertIn("public readonly record struct SampleNotesRgb(byte R, byte G, byte B, byte A = 255)", cs)
        self.assertIn("public static double Radius(SampleNotesRadius token) => token switch", cs)
        self.assertIn("SampleNotesRadius.Md => 8,", cs)
        self.assertNotIn("SampleNotesPlatform", cs)
        self.assertEqual(kit.parse_cs_colors(cs, "Light")["Ink"], [24, 24, 27])

        design = kit.read(os.path.join(self.root, "DESIGN.md"))
        rows = kit.marker_rows(design, "palette-light")
        self.assertEqual(rows[0], "| Token | OKLCH | Hex | Contrast |")
        self.assertEqual(rows[2], "| `--bg` | `oklch(1.000 0.000 0)` | `#ffffff` | — |")
        self.assertTrue(rows[4].startswith("| `--ink` | `oklch(0.210 0.006 285.885)` | `#18181b` | "), rows[4])
        self.assertTrue(rows[4].endswith(":1 vs bg |"))

    def test_design_md_changes_only_between_markers(self):
        before = kit.read(os.path.join(self.root, "DESIGN.md"))
        self.tokens("build", "--root", self.root)
        after = kit.read(os.path.join(self.root, "DESIGN.md"))
        strip = lambda t: re.sub(r"(<!-- generated:([\w-]+):start -->).*?(<!-- generated:\2:end -->)", r"\1\3", t,
                                 flags=re.S)  # noqa: E731
        self.assertEqual(strip(before), strip(after))
        self.assertTrue(after.startswith("---\nname: Sample Notes\n---\n"))
        self.assertTrue(after.endswith("The accent is the only saturated fill.\n"))

    def test_check_is_clean_after_build_and_names_stale_outputs(self):
        self.tokens("build", "--root", self.root)
        code, report = self.tokens_json("build", "--root", self.root, "--check")
        self.assertEqual(code, 0, report)
        self.assertEqual({s["status"] for s in report["outputs"]}, {"current"})
        css = os.path.join(self.root, "src/SampleNotes/wwwroot/css/tokens.css")
        kit.write(css, kit.read(css).replace("--bg:", "--bg-old:"))
        code, report = self.tokens_json("build", "--root", self.root, "--check")
        self.assertEqual(code, 1)
        self.assertEqual([f["where"] for f in report["findings"]], ["src/SampleNotes/wwwroot/css/tokens.css"])
        self.assertIn("--bg-old:", kit.read(css))  # --check wrote nothing

    def test_check_skips_a_missing_ignored_output_but_not_a_tracked_one(self):
        code, report = self.tokens_json("build", "--root", self.root, "--check")
        self.assertEqual(code, 1)
        stale = sorted(f["where"] for f in report["findings"])
        # csharp is in outputs.ignored and doesn't exist yet: not stale. The css and DESIGN.md are.
        self.assertEqual(stale, ["DESIGN.md", "src/SampleNotes/wwwroot/css/tokens.css"])
        by_output = {s["output"]: s["status"] for s in report["outputs"]}
        self.assertEqual(by_output["csharp"], "absent (ignored)")

    def test_check_ignores_crlf_line_endings(self):
        self.tokens("build", "--root", self.root)
        css = os.path.join(self.root, "src/SampleNotes/wwwroot/css/tokens.css")
        with open(css, "rb") as f:
            data = f.read()
        with open(css, "wb") as f:
            f.write(data.replace(b"\n", b"\r\n"))
        code, out, err = self.tokens("build", "--root", self.root, "--check")
        self.assertEqual(code, 0, out + err)

    def test_outputs_are_written_with_lf(self):
        self.tokens("build", "--root", self.root)
        with open(os.path.join(self.root, "src/SampleNotes.Core/Theme/Tokens.g.cs"), "rb") as f:
            self.assertNotIn(b"\r\n", f.read())

    def test_contrast_passes_with_separation_by_hue(self):
        code, report = self.tokens_json("contrast", "--root", self.root)
        self.assertEqual(code, 0, report["findings"])
        sep = [p for p in report["pairs"] if p["kind"] == "separation"]
        self.assertEqual(len(sep), 2)
        for p in sep:
            self.assertLess(p["ratio"], 1.7)  # luminance alone would fail...
            self.assertTrue(p["byHue"])  # ...the hue carries it
            self.assertEqual(p["status"], "pass")

    def test_srgb_color_space_writes_hex(self):
        self.edit(self.root, lambda d: d["meta"].update(colorSpace="srgb"))
        self.tokens("build", "--root", self.root)
        values, hexes = kit.parse_css(kit.read(os.path.join(self.root, "src/SampleNotes/wwwroot/css/tokens.css")))
        self.assertEqual(values[":root"]["--ink"], "#18181b")
        self.assertEqual(hexes, {})

    def test_show(self):
        code, report = self.tokens_json("show", "--root", self.root, "--theme", "dark")
        self.assertEqual(code, 0)
        self.assertEqual(list(report["palette"]), ["dark"])
        self.assertEqual(report["palette"]["dark"]["bg"]["hex"], "#161616")
        self.assertEqual(report["scale"]["radius-md"], "8px")
        self.assertEqual(report["modes"]["density"]["default"], "comfortable")
        code, out, _ = self.tokens("show", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertIn("Palette: light", out)
        self.assertIn("--accent", out)
        code, _, err = self.tokens("show", "--root", self.root, "--platform", "macos")
        self.assertEqual(code, 3)


class Platforms(TempDir):
    def setUp(self):
        super().setUp()
        self.root = self.project("tokens-platforms")
        code, out, err = self.tokens("build", "--root", self.root)
        self.assertEqual(code, 0, out + err)

    def read(self, path):
        return kit.read(os.path.join(self.root, path))

    def test_css_platform_blocks(self):
        values, _ = kit.parse_css(self.read("src/SampleMonitor.Ui/wwwroot/css/tokens.css"))
        self.assertEqual(values[':root[data-platform="macos"]'],
                         {"--radius-md": "10px", "--radius-lg": "16px", "--text-body": "13px", "--motion-fast": "120ms"})
        self.assertEqual(values[':root[data-platform="windows"]'],
                         {"--radius-md": "4px", "--radius-lg": "8px", "--control-height-md": "32px"})
        light_media = '@media (prefers-color-scheme: light) > :root[data-platform="macos"]:not([data-theme="dark"])'
        dark_media = '@media (prefers-color-scheme: dark) > :root[data-platform="macos"]:not([data-theme="light"])'
        self.assertEqual(values[light_media], values[':root[data-platform="macos"][data-theme="light"]'])
        self.assertEqual(values[dark_media], values[':root[data-platform="macos"][data-theme="dark"]'])
        self.assertEqual(values[light_media]["--shadow-popover"], "0 14px 36px oklch(0 0 0 / 15%)")
        self.assertNotIn("--shadow-popover", values[dark_media])
        self.assertIn("--accent", values[dark_media])
        # A platform's motion override still yields to reduced motion.
        self.assertIn('@media (prefers-reduced-motion: reduce) > :root, :root[data-platform]', values)
        # Alpha comes through.
        self.assertEqual(values[":root"]["--line-strong"], "oklch(0.000 0.000 0 / 0.22)")

    def test_csharp_platform_api(self):
        cs = self.read("src/SampleMonitor.Core/Theme/Tokens.g.cs")
        self.assertIn("public enum SampleMonitorPlatform { MacOS, Windows, Linux }", cs)
        self.assertIn("public static SampleMonitorRgb Get(SampleMonitorPlatform platform, SampleMonitorTheme theme, "
                      "SampleMonitorColor color)", cs)
        self.assertIn("(SampleMonitorPlatform.MacOS, SampleMonitorRadius.Md) => 10,", cs)
        self.assertIn("(_, SampleMonitorRadius.Md) => 8,", cs)
        self.assertIn("(SampleMonitorPlatform.Linux, SampleMonitorControl.HeightMd) => 34,", cs)
        self.assertEqual(kit.parse_cs_colors(cs, "MacOSLight"), {"Accent": [0, 122, 255], "OnAccent": [255, 255, 255]})
        self.assertEqual(kit.parse_cs_colors(cs, "MacOSDark")["Accent"], [10, 132, 255])
        self.assertEqual(kit.parse_cs_colors(cs, "Light")["LineStrong"], [0, 0, 0, 56])
        self.assertIn("(SampleMonitorPlatform.MacOS, SampleMonitorTheme.Dark) => MacOSDark,", cs)

    def test_macos_accent_uses_the_macos_override(self):
        accent = kit.load(os.path.join(self.root, "src/SampleMonitor.MacOS/Assets.xcassets/AccentColor.colorset/"
                                                  "Contents.json"))
        light, dark = accent["colors"]
        self.assertEqual(light["color"]["components"], {"red": "0.000", "green": "0.478", "blue": "1.000",
                                                        "alpha": "1.000"})
        self.assertEqual(dark["appearances"], [{"appearance": "luminosity", "value": "dark"}])
        self.assertEqual(dark["color"]["components"]["green"], "0.518")

    def test_design_platform_tables(self):
        design = self.read("DESIGN.md")
        mac_light = kit.marker_rows(design, "palette-macos-light")
        self.assertTrue(any("`#007aff`" in r and r.startswith("| `--accent`") for r in mac_light), mac_light)
        base_light = kit.marker_rows(design, "palette-light")
        self.assertFalse(any("`#007aff`" in r for r in base_light))
        matrix = kit.marker_rows(design, "platform-matrix")
        self.assertEqual(matrix[0], "| Token | Base | macOS | Windows | Linux |")
        self.assertIn("| `--radius-md` | `8px` | `10px` | `4px` | `8px` |", matrix)
        self.assertIn("| `--radius-lg` | `12px` | `16px` | `8px` | — |", matrix)
        self.assertIn("| `--accent` (dark) | `#46c6cd` | `#0a84ff` | — | — |", matrix)

    def test_contrast_rechecks_overridden_pairs_and_honours_platform_exceptions(self):
        code, report = self.tokens_json("contrast", "--root", self.root)
        self.assertEqual(code, 0, report["findings"])
        contexts = sorted(set(p["context"] for p in report["pairs"]))
        self.assertEqual(contexts, ["dark", "light", "macos/dark", "macos/light"])
        mac = [p for p in report["pairs"] if p["context"] == "macos/light"]
        self.assertEqual(sorted(p["pair"] for p in mac), ["on-accent on accent", "separation accent vs danger"])
        excepted = [p for p in report["pairs"] if p["status"] == "excepted"]
        self.assertEqual([(p["context"], p["ratio"]) for p in excepted], [("macos/light", 4.02), ("macos/dark", 3.65)])
        # The alpha hairline was composited over its ground before measuring.
        hairline = [p for p in report["pairs"] if p["pair"] == "line-strong on bg" and p["context"] == "light"][0]
        self.assertEqual(hairline["ratio"], 1.69)

    def test_a_platform_exception_does_not_cover_the_base(self):
        def base_fails(d):
            d["semantic"]["light"]["accent"] = "apple-blue"
        self.edit(self.root, base_fails)
        code, report = self.tokens_json("contrast", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertEqual([(f["id"], f["where"]) for f in report["findings"]],
                         [("contrast", "light: on-accent on accent")])

    def test_a_platform_only_overrides_what_exists(self):
        def bad(d):
            d["platforms"]["linux"]["semantic"] = {"light": {"brand": "white"}}
            d["platforms"]["linux"]["scale"]["radius"]["huge"] = "40px"
        self.edit(self.root, bad)
        code, report = self.tokens_json("build", "--root", self.root)
        self.assertEqual(code, 3)
        self.assertEqual(sorted(kit.ids(report)), ["platform-unknown-role", "platform-unknown-scale"])


class BadContrast(TempDir):
    def test_failures_stale_exception_and_gamut(self):
        root = self.project("tokens-bad-contrast")
        code, report = self.tokens_json("contrast", "--root", root)
        self.assertEqual(code, 1)
        ids = kit.ids(report)
        self.assertEqual(ids.count("contrast"), 1)
        self.assertEqual(ids.count("separation"), 2)
        self.assertEqual(ids.count("stale-exception"), 2)
        self.assertIn("gamut", ids)
        gamut = [f for f in report["findings"] if f["id"] == "gamut"][0]
        self.assertEqual(gamut["where"], "/primitives/neon-green")
        code, out, _ = self.tokens("contrast", "--root", root, "--quiet")
        self.assertEqual(code, 1)
        self.assertNotIn("PASS", out)
        self.assertIn("[stale-exception]", out)

    def test_narrowing_an_exception_to_the_failing_theme(self):
        root = self.project("tokens-bad-contrast")

        def narrow(d):
            d["contrast"]["exceptions"] = {"muted-light": {
                "applies": "light", "rule": "muted on bg", "reason": "r", "control": "c"}}
            d["contrast"]["separation"]["rules"] = []
            del d["primitives"]["neon-green"]
            for t in ("light", "dark"):
                del d["semantic"][t]["highlight"]
        self.edit(root, narrow)
        code, report = self.tokens_json("contrast", "--root", root)
        self.assertEqual(code, 0, report["findings"])
        self.assertEqual([p["status"] for p in report["pairs"] if p["pair"] == "muted on bg"], ["excepted", "pass"])

    def test_grey_pairs_cannot_pass_separation_by_hue(self):
        root = self.project("tokens-basic")

        def greys(d):
            d["primitives"]["tinted"] = [0.52, 0.001, 200]
            d["semantic"]["light"]["ok"] = "tinted"
            d["contrast"]["rules"] = []
        self.edit(root, greys)
        code, report = self.tokens_json("contrast", "--root", root)
        self.assertEqual(code, 1)
        self.assertEqual([(f["id"], f["where"]) for f in report["findings"]],
                         [("separation", "light: separation accent vs ok")])

    def test_alpha_background_is_an_error(self):
        root = self.project("tokens-platforms")
        self.edit(root, lambda d: d["contrast"]["rules"].append({"fg": "ink", "bg": "line-strong", "min": 4.5}))
        code, report = self.tokens_json("contrast", "--root", root)
        self.assertEqual(code, 1)
        self.assertEqual(kit.ids(report).count("alpha-background"), 2)

    def test_unknown_role_in_a_rule(self):
        root = self.project("tokens-basic")
        self.edit(root, lambda d: d["contrast"]["rules"].append({"fg": "nope", "bg": "bg", "min": 3}))
        code, report = self.tokens_json("contrast", "--root", root)
        self.assertEqual(code, 1)
        self.assertEqual([f["id"] for f in report["findings"]], ["unknown-role"])


class MixAssertion(TempDir):
    def test_a_broken_mix_fails_the_build_and_writes_nothing(self):
        root = self.project("tokens-basic")

        def naive_mix(a, b, amount):  # the old bug: interpolate towards the grey's placeholder hue of 0
            return tuple(y + (x - y) * amount for x, y in zip(dc.from_value(list(a)), dc.from_value(list(b))))
        with mock.patch.object(dc, "mix", naive_mix):
            code, report = self.tokens_json("build", "--root", root)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(set(kit.ids(report))), ["mix-grey-hue"])
        # White is a grey too: every tint in this file mixes into one.
        self.assertEqual([f["where"] for f in report["findings"]], [
            "/semantic/light/accent-soft", "/semantic/light/ok-tint", "/semantic/dark/accent-soft",
            "/semantic/dark/ok-tint"])
        self.assertFalse(os.path.exists(os.path.join(root, "src")))


class InvalidInput(TempDir):
    def setUp(self):
        super().setUp()
        self.root = self.project("tokens-basic")
        self.path = os.path.join(self.root, "design", "tokens.json")

    def expect(self, fn, ids, command="build"):
        self.edit(self.root, fn)
        code, report = self.tokens_json(command, "--root", self.root)
        self.assertEqual(code, 3, report)
        self.assertEqual(sorted(set(kit.ids(report))), sorted(ids), report["findings"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "src")))
        return report

    def test_missing_file(self):
        code, report = self.tokens_json("build", "--root", self.root, "--tokens", "design/nope.json")
        self.assertEqual(code, 3)
        self.assertEqual(kit.ids(report), ["missing-file"])

    def test_invalid_json_names_the_line(self):
        kit.write(self.path, '{\n  "version": 1,\n  oops\n}\n')
        code, report = self.tokens_json("build", "--root", self.root)
        self.assertEqual(code, 3)
        self.assertEqual(kit.ids(report), ["invalid-json"])
        self.assertIn(":3:", report["findings"][0]["message"])

    def test_schema_violation(self):
        report = self.expect(lambda d: d["primitives"].update({"bad": [2, 0, 0]}), ["schema"])
        self.assertIn("/primitives/bad", report["findings"][0]["message"])

    def test_unknown_primitive(self):
        self.expect(lambda d: d["semantic"]["dark"].update({"ink": "ink-050"}), ["unknown-primitive"])

    def test_role_missing_from_a_theme(self):
        self.expect(lambda d: d["semantic"]["dark"].pop("muted"), ["role-missing"])

    def test_csharp_scale_takes_only_px_and_numbers(self):
        def rem(d):
            d["outputs"]["csharp"]["scale"] = ["text"]
        self.expect(rem, ["csharp-scale"])

    def test_mode_errors(self):
        def modes(d):
            d["modes"]["density"]["default"] = "roomy"
        self.expect(modes, ["mode-default"])

    def test_mode_keys_follow_the_default(self):
        self.expect(lambda d: d["modes"]["density"]["values"]["compact"].update({"gap": "2px"}), ["mode-key"])

    def test_duplicate_custom_property(self):
        self.expect(lambda d: d["scale"].update({"extra": {"$prefix": "", "bg": "1px"}}), ["duplicate-property"])

    def test_unknown_accent_role(self):
        def accent(d):
            d["outputs"]["macosAccent"] = {"path": "a/Contents.json", "role": "brand"}
        self.expect(accent, ["unknown-role"])

    def test_root_is_not_a_folder(self):
        code, out, err = self.tokens("build", "--root", os.path.join(self.root, "nope"))
        self.assertEqual(code, 3)
        self.assertIn("isn't a folder", err)


class DesignMarkers(TempDir):
    def test_missing_markers_fail(self):
        root = self.project("tokens-basic")
        kit.write(os.path.join(root, "DESIGN.md"), "# Design\n\n<!-- generated:palette-light:start -->\n"
                                                   "<!-- generated:palette-light:end -->\n")
        code, report = self.tokens_json("build", "--root", root)
        self.assertEqual(code, 1)
        self.assertEqual(kit.ids(report), ["design-markers"])
        self.assertIn("palette-dark", report["findings"][0]["message"])

    def test_markers_out_of_order_fail(self):
        root = self.project("tokens-basic")
        text = kit.read(os.path.join(root, "DESIGN.md"))
        kit.write(os.path.join(root, "DESIGN.md"), text.replace("<!-- generated:palette-dark:start -->", "") +
                  "\n<!-- generated:palette-dark:start -->\n")
        code, report = self.tokens_json("build", "--root", root)
        self.assertEqual(code, 1)
        self.assertIn("design-markers", kit.ids(report))

    def test_missing_design_md(self):
        root = self.project("tokens-basic")
        os.unlink(os.path.join(root, "DESIGN.md"))
        code, report = self.tokens_json("build", "--root", root)
        self.assertEqual(code, 1)
        self.assertIn("design-missing", kit.ids(report))


class PortCheck(TempDir):
    """The port check: a shipping app's token file, converted to this schema, generates what the source app's Node
    pipeline generated (values compared; formatting, comments and the banner may differ)."""

    def setUp(self):
        super().setUp()
        self.root = self.project("port-check")
        self.expected = kit.load(os.path.join(self.root, "expected.json"))
        code, out, err = self.tokens("build", "--root", self.root)
        self.assertEqual(code, 0, out + err)

    def test_css_values_match(self):
        values, hexes = kit.parse_css(kit.read(os.path.join(self.root, "src/SampleMonitor.Ui/wwwroot/css/tokens.css")))
        expected = self.expected["css"]
        self.assertEqual(sorted(values), sorted(expected))
        for ctx, props in expected.items():
            self.assertEqual(sorted(values[ctx]), sorted(props), ctx)
            for name, value in props.items():
                mine = values[ctx][name]
                ours, theirs = oklch_numbers(mine), oklch_numbers(value)
                if theirs:
                    self.assertIsNotNone(ours, "%s %s: %s" % (ctx, name, mine))
                    for a, b in zip(ours, theirs):
                        self.assertAlmostEqual(a, b, delta=0.0005 + 1e-9, msg="%s %s" % (ctx, name))
                else:
                    self.assertEqual(mine, value, "%s %s" % (ctx, name))
        self.assertEqual(hexes, self.expected["cssHex"])

    def test_csharp_tables_match(self):
        cs = kit.read(os.path.join(self.root, "src/SampleMonitor.Core/Theme/Tokens.g.cs"))
        for table in ("Light", "Dark"):
            self.assertEqual(kit.parse_cs_colors(cs, table), self.expected["csharp"][table], table)
        self.assertIn("public enum SampleMonitorColor", cs)

    def test_accent_matches(self):
        accent = kit.load(os.path.join(self.root, "src/SampleMonitor.MacOS/Assets.xcassets/AccentColor.colorset/Contents.json"))
        got = [{"appearances": c.get("appearances"), "components": c["color"]["components"]} for c in accent["colors"]]
        self.assertEqual(got, self.expected["accent"])

    def test_palette_rows_match(self):
        design = kit.read(os.path.join(self.root, "DESIGN.md"))
        for marker, rows in self.expected["palette"].items():
            self.assertEqual(kit.marker_rows(design, marker), rows, marker)

    def test_contrast_verdicts_match(self):
        code, report = self.tokens_json("contrast", "--root", self.root)
        self.assertEqual(code, 0, report["findings"])
        contrast = [p for p in report["pairs"] if p["kind"] == "contrast"]
        self.assertEqual(len(contrast), 58)  # what the source app's verify-contrast.mjs counted
        self.assertEqual([(p["context"], p["pair"]) for p in report["pairs"] if p["status"] == "excepted"],
                         [("dark", "separation brand vs danger")])
        # the source app's warn-never-filled exception names "white text on `warn`", which no rule checks.
        self.assertEqual([(f["id"], f["severity"]) for f in report["findings"]], [("exception-unused", "warning")])


class Init(TempDir):
    def test_init_from_blueprint_and_layout(self):
        root = os.path.join(self.tmp, "app")
        kit.make_layout(root)
        kit.make_blueprint(root, ["macos", "windows", "web"])
        code, out, err = self.tokens("init", "--root", root)
        self.assertEqual(code, 0, out + err)
        data = kit.load(os.path.join(root, "design", "tokens.json"))
        self.assertEqual(data["meta"]["name"], "Sample Notes")
        self.assertEqual(data["meta"]["csharpPrefix"], "SampleNotes")
        self.assertEqual([p for p in data["platforms"] if not p.startswith("$")], ["macos", "windows", "web"])
        self.assertEqual(data["platforms"]["web"], {})
        outputs = data["outputs"]
        self.assertEqual(outputs["css"], "src/SampleNotes.Ui/wwwroot/css/tokens.css")
        self.assertEqual(outputs["csharp"], {"path": "src/SampleNotes.Core/Theme/Tokens.g.cs",
                                             "namespace": "SampleNotes.Core.Theme", "scale": ["radius", "control"]})
        self.assertEqual(outputs["design"], "DESIGN.md")
        self.assertEqual(outputs["macosAccent"]["path"],
                         "src/SampleNotes.MacOS/Assets.xcassets/AccentColor.colorset/Contents.json")
        self.assertIn("\n    \"white\": [1, 0, 0],\n", kit.read(os.path.join(root, "design", "tokens.json")))
        # What init wrote builds and passes as it stands.
        code, out, err = self.tokens("build", "--root", root)
        self.assertEqual(code, 0, out + err)
        cs = kit.read(os.path.join(root, "src/SampleNotes.Core/Theme/Tokens.g.cs"))
        self.assertIn("public enum SampleNotesPlatform { MacOS, Windows, Web }", cs)
        code, out, err = self.tokens("contrast", "--root", root, "--quiet")
        self.assertEqual(code, 0, out + err)

    def test_init_refuses_to_overwrite(self):
        root = os.path.join(self.tmp, "app")
        kit.write(os.path.join(root, "design", "tokens.json"), "{}\n")
        code, out, _ = self.tokens("init", "--root", root)
        self.assertEqual(code, 2)
        self.assertEqual(kit.read(os.path.join(root, "design", "tokens.json")), "{}\n")

    def test_init_without_a_blueprint(self):
        root = os.path.join(self.tmp, "app")
        kit.make_layout(root, design_md=False)
        code, out, err = self.tokens("init", "--root", root, "--out", "tokens/design-tokens.json")
        self.assertEqual(code, 0, out + err)
        data = kit.load(os.path.join(root, "tokens", "design-tokens.json"))
        self.assertEqual(data["meta"]["name"], "SampleNotes")  # from the solution's name
        self.assertEqual([p for p in data["platforms"] if not p.startswith("$")], ["macos", "windows", "linux"])
        self.assertNotIn("design", data["outputs"])
        self.assertIn("note:", out)

    def test_an_explicit_blueprint_must_exist(self):
        root = os.path.join(self.tmp, "app")
        os.makedirs(root)
        code, _, err = self.tokens("init", "--root", root, "--blueprint", "nope.json")
        self.assertEqual(code, 3)

    def test_guess_layout_on_an_empty_folder(self):
        os.makedirs(os.path.join(self.tmp, "empty"))
        self.assertEqual(tokens.guess_layout(os.path.join(self.tmp, "empty")),
                         {"ui": None, "core": None, "macos": None})


class Helpers(unittest.TestCase):
    def test_pascal(self):
        self.assertEqual(tokens.pascal("on-accent"), "OnAccent")
        self.assertEqual(tokens.pascal("surface-2"), "Surface2")
        self.assertEqual(tokens.pascal("Sample Notes"), "SampleNotes")
        self.assertEqual(tokens.csharp_prefix({"name": "3D Notes"}), "_3DNotes")

    def test_pretty_json_keeps_short_lists_inline(self):
        text = tokens.pretty_json({"a": [1, 0, 0], "b": {"c": "d"}, "e": [{"f": 1}]})
        self.assertEqual(json.loads(text), {"a": [1, 0, 0], "b": {"c": "d"}, "e": [{"f": 1}]})
        self.assertIn('"a": [1, 0, 0]', text)

    def test_px_number(self):
        self.assertEqual(tokens.px_number("10px"), 10)
        self.assertEqual(tokens.px_number("13.5px"), 13.5)
        self.assertEqual(tokens.px_number(1.45), 1.45)
        self.assertIsNone(tokens.px_number("1rem"))
        self.assertIsNone(tokens.px_number(True))


if __name__ == "__main__":
    unittest.main()
