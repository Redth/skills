"""Tests for lint.py: each rule, suppression, skipped folders and generated outputs, and the baseline ratchet.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Offline.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_testkit as kit  # noqa: E402
import lint  # noqa: E402

LEGACY = [
    ("raw-hex", "src/SampleNotes.Core/Theme/Palette.cs:6:35"),
    ("raw-hex", "src/SampleNotes/Pages/Home.razor:3:38"),
    ("raw-radius", "src/SampleNotes/Pages/Home.razor:3:47"),
    ("px-font-size", "src/SampleNotes/Pages/Home.razor:4:16"),
    ("native-select", "src/SampleNotes/Pages/Home.razor:5:5"),
    ("raw-rgb-hsl", "src/SampleNotes/wwwroot/css/app.css:2:15"),
    ("px-font-size", "src/SampleNotes/wwwroot/css/app.css:3:3"),
    ("magic-z-index", "src/SampleNotes/wwwroot/css/app.css:4:3"),
    ("named-color", "src/SampleNotes/wwwroot/css/app.css:10:3"),
    ("raw-modern-color", "src/SampleNotes/wwwroot/css/app.css:17:29"),
    ("raw-radius", "src/SampleNotes/wwwroot/css/app.css:17:49"),
]


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lint-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = kit.fixture("lint-legacy", os.path.join(self.tmp, "lint-legacy"), fresh=False)

    def lint(self, *argv):
        return kit.run_json(lint, ["--root", self.root] + list(argv))

    def errors(self, report):
        return [(f["id"], f["where"]) for f in report["findings"] if f["severity"] == "error"]

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def append(self, rel, text):
        with open(self.path(rel), "a", encoding="utf-8", newline="\n") as f:
            f.write(text)


class Legacy(TempDir):
    def test_every_rule_fires_where_expected(self):
        code, report = self.lint()
        self.assertEqual(code, 1)
        self.assertEqual(self.errors(report), LEGACY)
        self.assertEqual(report["scanned"], 3)  # tokens.css is a generated output: skipped

    def test_suppressed_lines_are_not_reported(self):
        _, report = self.lint()
        wheres = [f["where"] for f in report["findings"]]
        self.assertFalse([w for w in wheres if w.startswith("src/SampleNotes/Pages/Home.razor:9:")])  # @* … *@ above
        self.assertFalse([w for w in wheres if w.startswith("src/SampleNotes/wwwroot/css/app.css:15:")])  # block above
        self.assertFalse([w for w in wheres if "tokens.css" in w])

    def test_text_output(self):
        code, out, _ = kit.run(lint, ["--root", self.root])
        self.assertEqual(code, 1)
        self.assertIn("ERROR src/SampleNotes/wwwroot/css/app.css:4:3 [magic-z-index] z-index: 999:", out)
        self.assertIn("design-lint-ok: <reason>", out)

    def test_rules_can_be_switched_off(self):
        path = self.path("design/tokens.json")
        data = kit.load(path)
        data["lint"]["rules"] = {"raw-hex": False, "native-select": False}
        kit.dump(data, path)
        _, report = self.lint()
        found = set(f["id"] for f in report["findings"] if f["severity"] == "error")
        self.assertNotIn("raw-hex", found)
        self.assertNotIn("native-select", found)
        self.assertNotIn("raw-radius", found)  # off by default
        self.assertIn("px-font-size", found)

    def test_defaults_without_a_tokens_file(self):
        os.unlink(self.path("design/tokens.json"))
        code, report = self.lint()
        self.assertEqual(code, 1)
        found = self.errors(report)
        self.assertNotIn("native-select", [i for i, _ in found])
        self.assertNotIn("raw-radius", [i for i, _ in found])
        # Without outputs to skip, the hand-made tokens.css is scanned too.
        self.assertTrue([w for _, w in found if w.startswith("src/SampleNotes/wwwroot/css/tokens.css:")])

    def test_an_explicit_tokens_file_must_exist(self):
        code, report = self.lint("--tokens", "design/nope.json")
        self.assertEqual(code, 3)

    def test_paths_override_scan(self):
        code, report = self.lint(self.path("src/SampleNotes.Core"))
        self.assertEqual(code, 1)
        self.assertEqual(self.errors(report), [("raw-hex", "src/SampleNotes.Core/Theme/Palette.cs:6:35")])
        code, report = self.lint("src/SampleNotes/Pages/Home.razor")  # relative to the root
        self.assertEqual(len(self.errors(report)), 4)

    def test_skipped_folders_and_icon_outputs(self):
        kit.write(self.path("src/SampleNotes/bin/Debug/site.css"), ".x { color: #fff; }\n")
        kit.write(self.path("src/SampleNotes/wwwroot/lib/vendor.css"), ".x { color: #fff; }\n")
        kit.write(self.path("src/SampleNotes/wwwroot/library/mine.css"), ".x { color: #fff; }\n")
        kit.write(self.path("src/SampleNotes/wwwroot/icons/sprite.svg.css"), ".x { color: #fff; }\n")
        kit.dump({"version": 1, "icons": {}, "outputs": {"sprite": "src/SampleNotes/wwwroot/icons/sprite.svg.css"}},
                 self.path("design/icons.json"))
        _, report = self.lint()
        wheres = [w for _, w in self.errors(report)]
        self.assertTrue([w for w in wheres if w.startswith("src/SampleNotes/wwwroot/library/mine.css:")])
        for skipped in ("/bin/", "/wwwroot/lib/", "sprite.svg.css"):
            self.assertFalse([w for w in wheres if skipped in w], skipped)


class Patterns(unittest.TestCase):
    def hits(self, line, path="x.css"):
        tmp = tempfile.mkdtemp(prefix="lint-pattern-")
        self.addCleanup(shutil.rmtree, tmp, True)
        kit.write(os.path.join(tmp, path), line + "\n")
        rules = [r for r in lint.RULES]
        return [h[0] for h in lint.scan_file(tmp, path, rules)]

    def test_hex(self):
        self.assertEqual(self.hits("color: #abc;"), ["raw-hex"])
        self.assertEqual(self.hits("color: #aabbccdd;"), ["raw-hex"])
        self.assertEqual(self.hits("a { background: url(icons.svg#abc); }"), [])  # after a word character
        self.assertEqual(self.hits("&#123; and #abcde"), [])
        self.assertEqual(self.hits("#region Colours", "x.cs"), [])

    def test_functions(self):
        self.assertEqual(self.hits("background: color-mix(in oklab, var(--accent) 10%, transparent);"), [])
        self.assertEqual(self.hits("background: hsl(20 10% 50%);"), ["raw-rgb-hsl"])
        self.assertEqual(self.hits("background: lab(50% 10 10);"), ["raw-modern-color"])

    def test_z_index(self):
        for ok in ("z-index: var(--z-popover);", "z-index: 0;", "z-index: -1;", "z-index: auto;", "z-index:inherit"):
            self.assertEqual(self.hits(ok), [], ok)
        self.assertEqual(self.hits("z-index: 10;"), ["magic-z-index"])

    def test_radius(self):
        for ok in ("border-radius: var(--radius-md);", "border-radius: 0;", "border-radius: 50%;",
                   "border-top-left-radius: var(--radius-sm);"):
            self.assertEqual(self.hits(ok), [], ok)
        self.assertEqual(self.hits("border-radius: 0.5rem;"), ["raw-radius"])
        self.assertEqual(self.hits("border-bottom-right-radius: 4px;"), ["raw-radius"])

    def test_select_only_in_markup(self):
        self.assertEqual(self.hits('<select class="x">', "x.razor"), ["native-select"])
        self.assertEqual(self.hits('var html = "<select>";', "x.cs"), [])
        self.assertEqual(self.hits("<SelectList>", "x.razor"), [])

    def test_suppression_needs_a_comment_and_an_unbroken_block(self):
        lines = ["/* design-lint-ok: system colour", " * second line */", ".a { color: #fff; }"]
        self.assertTrue(lint.suppressed(lines, 2))
        lines = ["/* design-lint-ok: system colour */", ".b { }", ".a { color: #fff; }"]
        self.assertFalse(lint.suppressed(lines, 2))
        self.assertTrue(lint.suppressed([".a { color: #fff; } // design-lint-ok: brand"], 0))
        self.assertFalse(lint.suppressed([".a { content: 'design-lint-ok'; color: #fff; }"], 0))
        self.assertTrue(lint.suppressed(["<!-- design-lint-ok: email client -->", "<td bgcolor=\"#fff\">"], 1))


class Baseline(TempDir):
    def test_write_then_ratchet(self):
        code, out, _ = kit.run(lint, ["--root", self.root, "--write-baseline"])
        self.assertEqual(code, 0, out)
        baseline = kit.load(self.path("design/lint-baseline.json"))
        self.assertEqual(baseline["counts"]["src/SampleNotes/Pages/Home.razor"],
                         {"native-select": 1, "px-font-size": 1, "raw-hex": 1, "raw-radius": 1})
        self.assertEqual(sum(sum(r.values()) for r in baseline["counts"].values()), len(LEGACY))

        code, report = self.lint()
        self.assertEqual(code, 0, report["findings"])
        self.assertEqual(report["covered"], len(LEGACY))

        # A new raw value fails, in a file that had none of that rule and in one that had some.
        self.append("src/SampleNotes/wwwroot/css/app.css", ".new { color: #123456; }\n")
        self.append("src/SampleNotes/Pages/Home.razor", '<p style="font-size: 11px">x</p>\n')
        code, report = self.lint()
        self.assertEqual(code, 1)
        errors = self.errors(report)
        self.assertEqual(errors, [("px-font-size", "src/SampleNotes/Pages/Home.razor:4:16"),
                                  ("px-font-size", "src/SampleNotes/Pages/Home.razor:12:11"),
                                  ("raw-hex", "src/SampleNotes/wwwroot/css/app.css:20:15")])
        self.assertIn("the baseline allows 1", [f for f in report["findings"]
                                                if f["where"].endswith("Home.razor:12:11")][0]["message"])

    def test_a_cleaned_file_suggests_lowering_the_baseline(self):
        kit.run(lint, ["--root", self.root, "--write-baseline"])
        palette = self.path("src/SampleNotes.Core/Theme/Palette.cs")
        kit.write(palette, kit.read(palette).replace('"#4f46e5"', "SampleNotesTokens.Get(theme, SampleNotesColor.Accent)"
                                                     ".ToHex()"))
        code, report = self.lint()
        self.assertEqual(code, 0)
        info = [f for f in report["findings"] if f["id"] == "baseline-improved"]
        self.assertEqual([f["where"] for f in info], ["src/SampleNotes.Core/Theme/Palette.cs"])

    def test_without_lint_baseline_the_file_goes_to_the_default(self):
        path = self.path("design/tokens.json")
        data = kit.load(path)
        del data["lint"]["baseline"]
        kit.dump(data, path)
        code, out, _ = kit.run(lint, ["--root", self.root, "--write-baseline"])
        self.assertEqual(code, 0)
        self.assertIn("set lint.baseline", out)
        self.assertTrue(os.path.isfile(self.path("design/lint-baseline.json")))
        code, report = self.lint()
        self.assertEqual(code, 1)  # not configured, so not applied


if __name__ == "__main__":
    unittest.main()
