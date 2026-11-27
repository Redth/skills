"""Tests for blueprint.py (init, check, questions, set, confirm, gaps, show) and the blueprint schema, against
the eval fixtures copied into a temp folder (stdlib unittest).

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here reaches a network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import blueprint_testkit as kit  # noqa: E402
from mauidesktop_lib import blueprint as bpl  # noqa: E402
from mauidesktop_lib import detect  # noqa: E402
from mauidesktop_lib import schema  # noqa: E402

SEAMS = ["UI sharing", "Navigation", "Page chrome", "Icons", "Design tokens", "Platform styling", "Dialogs",
         "Menus and shortcuts", "Windows"]


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="blueprint-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def project(self, name):
        return kit.copy_project(name, self.tmp)

    def init(self, name, *extra):
        root = self.project(name)
        code, out, err = kit.run_blueprint(["init", "--root", root] + list(extra))
        self.assertEqual(code, 0, err)
        return root, os.path.join(root, "desktop-blueprint.json"), out

    def bp_file(self, fixture_name):
        return kit.copy_blueprint(fixture_name, os.path.join(self.tmp, fixture_name))


class Schema(unittest.TestCase):
    def setUp(self):
        self.schema = kit.read_json(kit.SCHEMA)

    def test_the_schema_uses_only_checked_keywords(self):
        self.assertEqual(schema.unsupported(self.schema), [])
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_the_blueprint_fixtures_match_it(self):
        for name in ("valid-tool", "bad-consistency", "monitor-linux-tray"):
            self.assertEqual(schema.validate(kit.read_json(kit.fixture("blueprints", name + ".json")), self.schema),
                             [], name)

    def test_a_draft_of_every_fixture_matches_it(self):
        for name in kit.PROJECTS:
            for kind in (None,) + bpl.KINDS:
                bp = bpl.draft(detect.scan(kit.fixture(name)), kind=kind)
                self.assertEqual(schema.validate(bp, self.schema), [], "%s as %s" % (name, kind))

    def test_per_platform_fields_take_a_value_or_an_object(self):
        bp = kit.read_json(kit.fixture("blueprints", "valid-tool.json"))
        bp["chrome"]["sidebar"] = {"macos": "native", "*": "web"}
        self.assertEqual(schema.validate(bp, self.schema), [])
        bp["chrome"]["sidebar"] = {"mac": "native"}
        self.assertTrue(schema.validate(bp, self.schema))
        bp["chrome"]["sidebar"] = "sideways"
        self.assertTrue(schema.validate(bp, self.schema))

    def test_comments_are_allowed_where_json_has_no_comments(self):
        bp = kit.read_json(kit.fixture("blueprints", "valid-tool.json"))
        bp["$comment"] = "a note"
        bp["chrome"]["$comment"] = "another"
        self.assertEqual(schema.validate(bp, self.schema), [])


class Init(TempDir):
    def test_legacy_hybrid_drafts_a_tool_that_keeps_what_it_has(self):
        _root, path, out = self.init("legacy-hybrid")
        self.assertIn("a tool app (no tray icon found) on macOS, Windows, Linux", out)
        bp = kit.read_json(path)
        self.assertEqual(bp["confirmedByUser"], False)
        self.assertEqual(bp["decided"], [])
        self.assertEqual(bp["app"], {"name": "Sample Notes", "id": "com.example.samplenotes",
                                     "namespace": "SampleNotes", "kind": "tool", "existing": True})
        self.assertEqual([p for p in ("macos", "windows", "linux") if bp["platforms"][p]["enabled"]],
                         ["macos", "windows", "linux"])
        self.assertTrue(bp["platforms"]["macos"]["home"])
        self.assertEqual(bp["platforms"]["windows"]["minimum"], "10.0.19041.0")
        self.assertEqual(bp["stack"]["sharing"], "links")
        self.assertEqual(bp["stack"]["dotnet"], "11.0")
        self.assertEqual(bp["chrome"]["sidebar"], "native")
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "windows": "none", "linux": "none"})
        self.assertEqual(bp["chrome"]["dialogs"], "native-frame")
        self.assertEqual(bp["distribution"]["channels"], {"macos": ["direct"], "windows": ["installer", "winget"],
                                                          "linux": ["deb"]})
        self.assertEqual(bp["distribution"]["signing"], {"macos": "available", "windows": "later", "linux": "none"})
        self.assertEqual(list(bp)[:6], ["version", "confirmedByUser", "decided", "app", "platforms", "stack"])

    def test_declared_shell_drafts_a_monitor_on_its_two_platforms(self):
        _root, path, out = self.init("declared-shell")
        self.assertIn("a monitor app (a tray icon was found)", out)
        bp = kit.read_json(path)
        self.assertEqual(bp["app"]["kind"], "monitor")
        self.assertEqual(bp["platforms"]["linux"], {"enabled": False})
        self.assertEqual(bp["stack"]["sharing"], "rcl")
        self.assertEqual(bp["stack"]["dotnet"], "11.0", "from the target frameworks: there's no global.json")
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "windows": "none"})
        self.assertEqual(bp["integrations"]["tray"], True)
        self.assertEqual(bp["integrations"]["closeToTray"], True)
        self.assertNotIn("linux", bp["distribution"]["channels"])

    def test_a_new_app_gets_the_defaults(self):
        _root, path, out = self.init("new-app", "--name", "Sample Notes", "--id", "com.example.samplenotes")
        self.assertIn("a new app: no projects found", out)
        bp = kit.read_json(path)
        self.assertEqual(bp["app"]["existing"], False)
        self.assertEqual(bp["app"]["namespace"], "SampleNotes")
        self.assertEqual(bp["stack"]["sharing"], "rcl")
        self.assertEqual(bp["integrations"], bpl.defaults("tool")["integrations"])

    def test_kind_and_platforms_from_the_command_line(self):
        _root, path, _out = self.init("new-app", "--kind", "launcher", "--platforms", "macos,windows")
        bp = kit.read_json(path)
        self.assertEqual(bp["app"]["kind"], "launcher")
        self.assertEqual(bp["chrome"]["sidebar"], "none")
        self.assertEqual(bp["integrations"]["globalHotkey"], True)
        self.assertEqual(bp["platforms"]["linux"], {"enabled": False})
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "windows": "none"})

    def test_init_never_overwrites(self):
        root, path, _out = self.init("legacy-hybrid")
        before = kit.read_text(path)
        code, _out, err = kit.run_blueprint(["init", "--root", root])
        self.assertEqual(code, 2)
        self.assertIn("exists", err)
        self.assertEqual(kit.read_text(path), before)

    def test_bad_arguments(self):
        root = self.project("new-app")
        self.assertEqual(kit.run_blueprint(["init", "--root", root, "--platforms", "macos,amiga"])[0], 3)
        self.assertEqual(kit.run_blueprint(["init", "--root", os.path.join(self.tmp, "nowhere")])[0], 3)
        self.assertEqual(kit.run_blueprint(["init", "--root", root, "--id", "not an id"])[0], 3)
        self.assertFalse(os.path.exists(os.path.join(root, "desktop-blueprint.json")))
        self.assertEqual(kit.run_blueprint([])[0], 3)


class Check(TempDir):
    def test_a_valid_blueprint_passes(self):
        code, report = kit.check_json(self.bp_file("valid-tool"))
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(kit.finding_ids(report), ["gtk-native-chrome"])
        for f in report["findings"]:
            self.assertEqual(sorted(f), ["id", "message", "severity", "where"])

    def test_consistency_errors_fail(self):
        code, report = kit.check_json(self.bp_file("bad-consistency"))
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(kit.finding_ids(report, "error"), ["deep-link-scheme", "macos-menu-bar", "per-platform-key"])
        where = [f["where"] for f in report["findings"] if f["id"] == "per-platform-key"]
        self.assertEqual(where, ["chrome.sidebar.linux"])

    def test_warnings_alone_pass(self):
        code, report = kit.check_json(self.bp_file("monitor-linux-tray"))
        self.assertEqual(code, 0)
        self.assertEqual(kit.finding_ids(report, "warning"),
                         ["flatpak-autostart", "hotkey-wayland", "tray-gnome", "update-owned-by-channel"])
        self.assertEqual(len([f for f in report["findings"] if f["id"] == "update-owned-by-channel"]), 2)

    def test_schema_errors_are_findings(self):
        path = self.bp_file("valid-tool")
        data = kit.read_json(path)
        data["app"]["kind"] = "game"
        kit.write_json(path, data)
        code, report = kit.check_json(path)
        self.assertEqual(code, 1)
        self.assertEqual(kit.finding_ids(report), ["schema"])
        self.assertEqual(report["findings"][0]["where"], "/app/kind")

    def test_unreadable_blueprints(self):
        missing = os.path.join(self.tmp, "none.json")
        self.assertEqual(kit.run_blueprint(["check", "--blueprint", missing])[0], 3)
        broken = os.path.join(self.tmp, "broken.json")
        with open(broken, "w", encoding="utf-8") as f:
            f.write('{"version": 1,\n  oops }')
        code, _out, err = kit.run_blueprint(["check", "--blueprint", broken])
        self.assertEqual(code, 3)
        self.assertIn("broken.json:2", err)

    def test_people_output(self):
        code, out, _ = kit.run_blueprint(["check", "--blueprint", self.bp_file("bad-consistency")])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("ERROR "))
        self.assertIn("3 errors.", out)


class Questions(TempDir):
    def test_every_group_in_order_with_a_proposal_and_a_reason(self):
        root, path, _ = self.init("legacy-hybrid")
        code, out, _ = kit.run_blueprint(["questions", "--blueprint", path, "--root", root])
        self.assertEqual(code, 0)
        groups = re.findall(r"^## (.+)$", out, re.MULTILINE)
        self.assertEqual(groups, ["Product", "Chrome (per platform)", "Look", "Background and integrations",
                                  "Distribution", "Engineering"])
        self.assertIn("Ask them in ONE message", out)
        self.assertIn("`chrome.sidebar` proposed: macOS native, Windows native, Linux native.", out)
        self.assertIn("`app.kind` proposed: tool. Why: no tray icon was found.", out)
        self.assertIn("`stack.sharing` proposed: links. Why: what the project does today", out)
        self.assertIn("`integrations.autoUpdate` proposed: yes. Why: the default for every kind of app, and the "
                      "project has it (src/SampleNotes.Core/Services/UpdateService.cs:", out)
        self.assertIn("`integrations.notifications` proposed: yes. Why: the default for a tool app; not found in the "
                      "project yet.", out)
        for line in out.splitlines():
            if line.startswith("   - "):
                self.assertIn("Why: ", line)

    def test_a_monitor_explains_its_kind(self):
        root, path, _ = self.init("declared-shell")
        _code, out, _ = kit.run_blueprint(["questions", "--blueprint", path, "--root", root])
        self.assertIn("`app.kind` proposed: monitor. Why: a tray icon was found (src/SampleMonitor.MacOS/StatusItem.cs:", out)
        self.assertIn("Proposed: macOS, Windows; home: macOS; off: Linux.", out)

    def test_decided_fields_are_not_asked_again(self):
        root, path, _ = self.init("legacy-hybrid")
        kit.run_blueprint(["set", "app.kind=tool", "chrome.search=content", "--reason", "It's a tool.",
                           "--blueprint", path])
        _code, out, _ = kit.run_blueprint(["questions", "--blueprint", path, "--root", root])
        self.assertNotIn("What kind of app is it?", out)
        self.assertNotIn("Where does search live?", out)
        self.assertIn("Sidebar: native, web or none?", out)

    def test_a_platform_answer_is_credited_to_the_user(self):
        root, path, _ = self.init("legacy-hybrid")
        kit.run_blueprint(["set", "chrome.sidebar.linux=web", "--reason", "Linux is a preview.", "--blueprint", path])
        _code, out, _ = kit.run_blueprint(["questions", "--blueprint", path, "--root", root])
        line = [l for l in out.splitlines() if l.startswith("   - `chrome.sidebar`")][0]
        self.assertIn("Linux web", line)
        self.assertIn("Linux: you said so", line)

    def test_all_answered(self):
        root, path, _ = self.init("new-app")
        bp = kit.read_json(path)
        bp["decided"] = ["app", "platforms", "chrome", "look", "integrations", "distribution", "stack", "engineering"]
        kit.write_json(path, bp)
        _code, out, _ = kit.run_blueprint(["questions", "--blueprint", path, "--root", root])
        self.assertIn("Every question", out)
        self.assertIn("blueprint.py confirm", out)

    def test_an_invalid_blueprint_is_a_usage_error(self):
        path = self.bp_file("valid-tool")
        data = kit.read_json(path)
        data["chrome"]["dialogs"] = "popups"
        kit.write_json(path, data)
        self.assertEqual(kit.run_blueprint(["questions", "--blueprint", path, "--root", self.tmp])[0], 3)


class Set(TempDir):
    def setUp(self):
        super().setUp()
        self.root, self.path, _ = self.init("legacy-hybrid")
        self.log = os.path.join(self.root, "docs", "desktop", "decisions.md")

    def set(self, *args):
        return kit.run_blueprint(["set"] + list(args) + ["--blueprint", self.path, "--date", kit.DATE])

    def test_one_platform_of_a_single_value(self):
        code, out, err = self.set("chrome.sidebar.linux=web", "--reason",
                                  "We only ship Linux as a preview; a web sidebar is fine there.")
        self.assertEqual(code, 0, err)
        bp = kit.read_json(self.path)
        self.assertEqual(bp["chrome"]["sidebar"], {"macos": "native", "windows": "native", "linux": "web", "web": "web"})
        self.assertEqual(bp["decided"], ["chrome.sidebar.linux"])
        self.assertIn("Set chrome.sidebar.linux = web (was native), by user.", out)
        self.assertEqual(kit.read_text(self.log), (
            "# Desktop decisions\n\n"
            "## 2026-11-27: chrome.sidebar.linux = web\n\n"
            "- **By:** user\n"
            "- **Reason:** \"We only ship Linux as a preview; a web sidebar is fine there.\"\n"
            "- **Was:** native\n"))

    def test_several_fields_json_values_and_appending(self):
        self.set("chrome.search=content", "--reason", "Search sits in the page.")
        code, _out, err = self.set('integrations.deepLinks={"scheme": "samplenotes"}', "platforms.macos.minimum=15.0",
                                   "integrations.fileDrop=true", "--reason", "Links from the docs site.")
        self.assertEqual(code, 0, err)
        bp = kit.read_json(self.path)
        self.assertEqual(bp["integrations"]["deepLinks"], {"scheme": "samplenotes"})
        self.assertEqual(bp["platforms"]["macos"]["minimum"], "15.0", "a bare number stays a string")
        self.assertIs(bp["integrations"]["fileDrop"], True)
        self.assertEqual(bp["decided"], ["chrome.search", "integrations.deepLinks", "platforms.macos.minimum",
                                         "integrations.fileDrop"])
        log = kit.read_text(self.log)
        self.assertEqual(log.count("\n## "), 4)
        self.assertEqual(log.count("# Desktop decisions"), 1)
        self.assertIn('## 2026-11-27: integrations.deepLinks = {"scheme": "samplenotes"}\n\n- **By:** user\n'
                      '- **Reason:** "Links from the docs site."\n- **Was:** false\n', log)
        self.assertIn("\n\n## 2026-11-27: integrations.deepLinks", log, "entries are separated by a blank line")

    def test_a_proposal_is_logged_but_not_decided(self):
        code, _out, _err = self.set("look.density=true", "--by", "proposal", "--reason", "Dense lists suit a tool.")
        self.assertEqual(code, 0)
        bp = kit.read_json(self.path)
        self.assertIs(bp["look"]["density"], True)
        self.assertEqual(bp["decided"], [])
        self.assertIn("- **By:** proposal\n", kit.read_text(self.log))

    def test_null_removes_a_field_so_its_default_applies(self):
        self.set("chrome.search=content", "--reason", "x")
        code, out, _ = self.set("chrome.search=null", "--reason", "Back to the default.")
        self.assertEqual(code, 0)
        self.assertNotIn("search", kit.read_json(self.path)["chrome"])
        self.assertIn("Set chrome.search = (unset) (was content)", out)

    def test_nothing_is_written_on_a_schema_violation(self):
        before = kit.read_text(self.path)
        code, _out, err = self.set("chrome.sidebar=sideways", "chrome.search=content", "--reason", "x")
        self.assertEqual(code, 3)
        self.assertIn("nothing was written", err)
        self.assertEqual(kit.read_text(self.path), before)
        self.assertFalse(os.path.exists(self.log))

    def test_bad_paths(self):
        before = kit.read_text(self.path)
        for args in (["chrome.search.extra=x"], ["chrome..search=x"], ["confirmedByUser=true"], ["decided=[]"],
                     ["no-equals-sign"], ["chrome.colour=red"]):
            code, _out, _err = self.set(*(args + ["--reason", "x"]))
            self.assertEqual(code, 3, args)
        self.assertEqual(kit.read_text(self.path), before)
        self.assertEqual(self.set("chrome.search=content", "--reason", "  ")[0], 3)
        self.assertEqual(kit.run_blueprint(["set", "chrome.search=content"])[0], 3, "--reason is required")

    def test_set_reports_new_consistency_problems(self):
        code, out, _ = self.set("chrome.menuBar.macos=none", "--reason", "x")
        self.assertEqual(code, 0)
        self.assertIn("[macos-menu-bar]", out)


class Confirm(TempDir):
    def test_confirm_needs_a_clean_check(self):
        path = self.bp_file("bad-consistency")
        before = kit.read_text(path)
        code, out, _ = kit.run_blueprint(["confirm", "--note", "Looks right.", "--blueprint", path])
        self.assertEqual(code, 1)
        self.assertIn("Not confirmed", out)
        self.assertEqual(kit.read_text(path), before)

    def test_confirm_then_a_proposal_unconfirms(self):
        path = self.bp_file("valid-tool")
        code, _out, err = kit.run_blueprint(["confirm", "--note", "Yes, that's the app.", "--blueprint", path,
                                             "--date", kit.DATE])
        self.assertEqual(code, 0, err)
        self.assertIs(kit.read_json(path)["confirmedByUser"], True)
        log = kit.read_text(os.path.join(os.path.dirname(path), "docs", "desktop", "decisions.md"))
        self.assertIn('## 2026-11-27: confirmedByUser = true\n\n- **By:** user\n- **Reason:** "Yes, that\'s the app."\n'
                      '- **Was:** false\n', log)
        code, out, _ = kit.run_blueprint(["set", "look.density=true", "--by", "proposal", "--reason", "Denser lists.",
                                          "--blueprint", path])
        self.assertEqual(code, 0)
        self.assertIs(kit.read_json(path)["confirmedByUser"], False)
        self.assertIn("confirmedByUser is now false", out)

    def test_a_note_is_required(self):
        self.assertEqual(kit.run_blueprint(["confirm", "--note", "", "--blueprint", self.bp_file("valid-tool")])[0], 3)


class Gaps(TempDir):
    def gaps(self, root, path, *extra):
        return kit.run_blueprint(["gaps", "--blueprint", path, "--root", root, "--date", kit.DATE] + list(extra))

    def rows(self, text):
        out = {}
        for line in text.splitlines():
            if line.startswith("| ") and not line.startswith("| Seam") and not line.startswith("|---"):
                cells = [c.strip() for c in line.strip("|").split(" | ")]
                out[cells[0]] = cells
        return out

    def test_the_report_for_the_older_app(self):
        root, path, _ = self.init("legacy-hybrid")
        kit.run_blueprint(["set", "stack.sharing=rcl", "--reason", "Move to a class library.", "--blueprint", path])
        code, out, err = self.gaps(root, path)
        self.assertEqual(code, 0, err)
        report = os.path.join(root, "docs", "desktop", "gap-report.md")
        self.assertIn("Wrote", out)
        text = kit.read_text(report)
        self.assertIn("| Seam | Now | Target | Move | Skill |\n|---|---|---|---|---|\n", text)
        rows = self.rows(text)
        names = list(rows)
        self.assertEqual(names[:len(SEAMS)], SEAMS)
        self.assertEqual(names[-1], "Distribution")
        self.assertEqual(rows["UI sharing"][1:], ["compile links", "Razor class library", "L", "maui-desktop-shell"])
        self.assertEqual(rows["Navigation"][3:], ["M", "maui-desktop-shell"])
        self.assertEqual(rows["Page chrome"][1], "an imperative toolbar service (SF Symbol names in the action)")
        self.assertEqual(rows["Icons"][4], "maui-desktop-design")
        self.assertEqual(rows["Design tokens"][1:4], ["hand-kept CSS, 6 raw hex colours",
                                                      "design/tokens.json generating the CSS (and C#)", "S"])
        self.assertEqual(rows["Platform styling"][4], "maui-desktop-design")
        self.assertEqual(rows["Dialogs"][3:], ["M", "maui-desktop-dialogs"])
        self.assertEqual(rows["Auto-update"][1:4], ["found in shared code", "on: macOS, Windows, Linux", "none"])
        self.assertEqual(rows["Window size and position"][1:4], ["found on macOS, Windows", "on: macOS, Windows, Linux", "S"])
        self.assertEqual(rows["Notifications"][3:], ["S", "maui-desktop-integrations"])
        self.assertNotIn("Tray icon", rows, "only the integrations the blueprint asks for")
        self.assertEqual(rows["Distribution"][3:], ["none", "maui-desktop-ship"])
        for name in rows:
            self.assertIn(rows[name][3], ("none", "S", "M", "L"))
            self.assertIn("\n## %s\n\n" % name, text)
        sections = text.split("\n## ")[1:]
        self.assertEqual(len(sections), len(rows))
        for section in sections:
            body = section.split("\n", 2)[2].strip()
            self.assertTrue(body)
            self.assertLessEqual(len(re.findall(r"[.!?](?:\s|$)", body)), 3, body)

    def test_the_newer_app_has_little_to_move(self):
        root, path, _ = self.init("declared-shell")
        code, out, _ = self.gaps(root, path, "--print")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(root, "docs", "desktop", "gap-report.md")), "--print writes nothing")
        rows = self.rows(out)
        for seam in ("UI sharing", "Navigation", "Page chrome", "Design tokens", "Platform styling", "Dialogs",
                     "Tray icon"):
            self.assertEqual(rows[seam][3], "none", seam)
        self.assertEqual(rows["Notifications"][1:4], ["found on Windows", "on: macOS, Windows", "S"])
        self.assertEqual(rows["Icons"][3], "S")

    def test_a_new_app_has_no_gaps(self):
        root, path, _ = self.init("new-app")
        code, out, _ = self.gaps(root, path)
        self.assertEqual(code, 0)
        self.assertIn("no gaps to report", out)
        self.assertFalse(os.path.exists(os.path.join(root, "docs")))

    def test_out_and_errors(self):
        root, path, _ = self.init("legacy-hybrid")
        out_file = os.path.join(self.tmp, "reports", "gaps.md")
        self.assertEqual(self.gaps(root, path, "--out", out_file)[0], 0)
        self.assertTrue(kit.read_text(out_file).startswith("# Desktop gap report: Sample Notes\n"))
        self.assertEqual(self.gaps(os.path.join(self.tmp, "nowhere"), path)[0], 3)
        self.assertEqual(self.gaps(root, os.path.join(self.tmp, "none.json"))[0], 3)


class Show(TempDir):
    def test_one_column_a_platform(self):
        path = self.bp_file("valid-tool")
        code, out, _ = kit.run_blueprint(["show", "--blueprint", path])
        self.assertEqual(code, 0)
        self.assertIn("| Field | macOS | Windows | Linux | Web |", out)
        self.assertIn("| chrome.sidebar | native | native | native | web |", out)
        self.assertIn("| chrome.menuBar | standard | none | none | - |", out)
        self.assertIn("| distribution.channels | direct, homebrew | installer, winget | appimage | - |", out)
        self.assertIn("| integrations.deepLinks.scheme | samplenotes |", out)
        self.assertEqual(out.count("integrations.contextMenus"), 1)

    def test_disabled_platforms_have_no_column(self):
        code, out, _ = kit.run_blueprint(["show", "--blueprint", self.bp_file("bad-consistency")])
        self.assertEqual(code, 0)
        self.assertIn("| Field | macOS | Windows | Web |", out)
        self.assertIn("Not enabled: Linux.", out)

    def test_json(self):
        code, out, _ = kit.run_blueprint(["show", "--blueprint", self.bp_file("monitor-linux-tray"), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["ok"], True)
        self.assertEqual(data["findings"], [])
        self.assertEqual(data["blueprint"]["app"]["name"], "Sample Monitor")
        self.assertEqual(data["resolved"]["chrome.sidebar"], {"macos": "native", "windows": "native", "linux": "web",
                                                              "web": "web"})
        self.assertEqual(data["resolved"]["integrations.globalHotkey"], {"macos": True, "windows": False, "linux": True})


class Fixtures(unittest.TestCase):
    def test_fixtures_hold_no_tests_and_only_plain_json(self):
        for dirpath, _dirs, files in os.walk(kit.FILES):
            for name in files:
                self.assertFalse(name.startswith("test_") and name.endswith(".py"), name)
                if name.endswith(".json"):
                    with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                        json.load(f)

    def test_fixtures_name_only_the_invented_apps(self):
        for dirpath, _dirs, files in os.walk(kit.FILES):
            for name in files:
                text = kit.read_text(os.path.join(dirpath, name))
                for word in ("Sherpa", "Dray", "redth", "codes."):
                    self.assertNotIn(word, text, os.path.join(dirpath, name))


if __name__ == "__main__":
    unittest.main()
