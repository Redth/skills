"""Tests for detect.py against the eval fixtures (stdlib unittest).

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here writes into the
fixtures or reaches a network.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import blueprint_testkit as kit  # noqa: E402


def by_path(detection):
    return {p["path"]: p for p in detection["projects"]}


class EvidenceShape(object):
    """Every evidence line is ``<path>: <text>`` (or ``<path> -> <target>`` for a symlink), the path uses ``/``
    and exists, and the text is at most 120 characters."""

    root = None

    def assert_evidence(self, detection):
        lines = kit.all_evidence(detection)
        self.assertTrue(lines)
        for line in lines:
            if " -> " in line and ": " not in line.split(" -> ")[0]:
                path, text = line.split(" -> ", 1)
            else:
                self.assertIn(": ", line, line)
                path, text = line.split(": ", 1)
            self.assertNotIn("\\", path, line)
            self.assertTrue(os.path.exists(os.path.join(self.root, *path.split("/"))), line)
            self.assertLessEqual(len(text), 120, line)


class LegacyHybrid(unittest.TestCase, EvidenceShape):
    """Sample Notes, built the older way."""

    @classmethod
    def setUpClass(cls):
        cls.root = kit.fixture("legacy-hybrid")
        cls.d = kit.detect_json(cls.root)

    def test_solution_sdk_and_frameworks(self):
        self.assertEqual(self.d["solution"], ["SampleNotes.slnx"])
        self.assertEqual(self.d["dotnet"]["sdk"], "11.0.100")
        self.assertEqual(self.d["dotnet"]["tfms"], ["net11.0", "net11.0-macos", "net11.0-windows10.0.19041.0"])

    def test_roles_and_the_head_that_is_also_the_ui(self):
        p = by_path(self.d)
        self.assertEqual(p["src/SampleNotes/SampleNotes.csproj"]["role"], "head-windows")
        self.assertTrue(p["src/SampleNotes/SampleNotes.csproj"]["alsoUi"])
        self.assertEqual(p["src/SampleNotes.MacOS/SampleNotes.MacOS.csproj"]["role"], "head-macos")
        self.assertNotIn("alsoUi", p["src/SampleNotes.MacOS/SampleNotes.MacOS.csproj"])
        self.assertEqual(p["src/SampleNotes.LinuxGtk/SampleNotes.LinuxGtk.csproj"]["role"], "head-linux")
        self.assertEqual(p["src/SampleNotes.Core/SampleNotes.Core.csproj"]["role"], "core")
        self.assertEqual(p["tests/SampleNotes.Core.Tests/SampleNotes.Core.Tests.csproj"]["role"], "tests")

    def test_central_package_versions_fill_in_references(self):
        mac = by_path(self.d)["src/SampleNotes.MacOS/SampleNotes.MacOS.csproj"]
        self.assertEqual(mac["packages"]["Microsoft.Maui.Platforms.MacOS"], "0.1.0-preview.16.26575.3")
        self.assertEqual(self.d["backends"], {
            "macos": "Microsoft.Maui.Platforms.MacOS 0.1.0-preview.16.26575.3",
            "windows": "Microsoft.Maui.Controls 11.0.10",
            "linux": "Microsoft.Maui.Platforms.Linux.Gtk4 0.1.0-preview.16.26575.3"})

    def test_heads(self):
        h = self.d["heads"]
        self.assertEqual(h["macos"], "src/SampleNotes.MacOS/SampleNotes.MacOS.csproj")
        self.assertEqual(h["windows"], "src/SampleNotes/SampleNotes.csproj")
        self.assertEqual(h["linux"], "src/SampleNotes.LinuxGtk/SampleNotes.LinuxGtk.csproj")
        self.assertIsNone(h["devhost"])
        self.assertIsNone(h["maccatalyst"])

    def test_sharing_by_compile_links(self):
        s = self.d["sharing"]
        self.assertEqual(s["kind"], "links")
        self.assertIn('src/SampleNotes.MacOS/SampleNotes.MacOS.csproj: <Compile Include="..\\SampleNotes\\Services\\*.cs" '
                      'Link="Services\\Shared\\%(Filename)%(Extension)" />', s["evidence"])
        self.assertTrue(any("<RazorComponent Include=" in e for e in s["evidence"]))

    def test_shell(self):
        shell = self.d["shell"]
        self.assertEqual(shell["navigation"]["kind"], "per-head")
        self.assertEqual(shell["toolbar"]["kind"], "imperative")
        self.assertIn("src/SampleNotes.Core/Interfaces.cs: public record ToolbarAction(string Id, string Label, "
                      "string SfSymbol, bool IsPrimary = true);", shell["toolbar"]["evidence"])
        self.assertEqual(shell["sidebar"], {"macos": "native", "windows": "native", "linux": "native", "web": "web"})
        self.assertEqual(shell["menuBar"], {"macos": "custom-items", "windows": "none", "linux": "none"})

    def test_a_comment_naming_a_sidebar_is_not_evidence(self):
        self.assertIn("src/SampleNotes.MacOS/MacApp.cs: FlyoutPage? _flyout;", self.d["shell"]["sidebarEvidence"])
        self.assertFalse(any("Builds the window" in e for e in self.d["shell"]["sidebarEvidence"]))

    def test_dialogs_count_subclasses_not_the_base_or_a_comment(self):
        dlg = self.d["dialogs"]
        self.assertEqual(dlg["kind"], "page-subclass")
        self.assertEqual(dlg["count"], 2)
        self.assertEqual(dlg["webOverlays"], 1)
        self.assertFalse(any("ExportDraftPage" in e or "abstract" in e for e in dlg["evidence"]))

    def test_design(self):
        des = self.d["design"]
        self.assertTrue(des["designMd"])
        self.assertFalse(des["tokensJson"])
        self.assertFalse(des["iconsJson"])
        # app.css: 3 (not the comment, not the selector); Notes.razor: 2 in <style>, 1 in style="", not href="#top"
        # or "issue #123"; the vendored bootstrap.css is skipped.
        self.assertEqual(des["rawHex"], 6)
        self.assertEqual(des["platformSelectors"], {"macos": 2, "windows": 1, "linux": 0})
        self.assertEqual(des["iconSources"], {"sf-symbols": 1})

    def test_integrations(self):
        integ = self.d["integrations"]
        self.assertEqual(integ["autoUpdate"], ['src/SampleNotes.Core/Services/UpdateService.cs: const string ReleasesUrl = '
                                               '"https://api.github.com/repos/example/samplenotes/releases";'])
        self.assertEqual(len(integ["windowState"]), 2)
        self.assertEqual(self.d["integrationPlatforms"]["windowState"], ["macos", "windows"])
        self.assertEqual(self.d["integrationPlatforms"]["autoUpdate"], ["*"])
        self.assertEqual(integ["tray"], [], "a test project naming NSStatusItem isn't the app's tray icon")
        self.assertEqual(integ["deepLinks"], [], "Info.plist has no URL types")
        self.assertEqual(self.d["deepLinkSchemes"], [])
        for key in ("tray", "notifications", "singleInstance", "deepLinks", "launchAtLogin", "globalHotkey",
                    "autoUpdate", "windowState"):
            self.assertIn(key, integ)

    def test_distribution(self):
        dist = self.d["distribution"]
        self.assertEqual(dist["workflows"], [".github/workflows/build.yml"])
        self.assertEqual(dist["macos"], ["codesign", "notarize"])
        self.assertEqual(dist["windows"], ["inno-setup", "winget"])
        self.assertEqual(dist["linux"], ["deb"], "CreateFlatpak=false isn't a flatpak")
        self.assertIn(".github/workflows/build.yml: - run: xcrun notarytool submit SampleNotes.zip --wait",
                      dist["evidence"])
        self.assertNotIn("mac-app-store", dist["macos"], "altool --upload is only in a comment")

    def test_tests_docs_app_and_stack(self):
        self.assertEqual(self.d["tests"], {"projects": ["tests/SampleNotes.Core.Tests/SampleNotes.Core.Tests.csproj"],
                                           "ui": []})
        self.assertEqual(self.d["agentDocs"], ["AGENTS.md", "DESIGN.md"])
        self.assertEqual(self.d["app"], {"name": "Sample Notes", "id": "com.example.samplenotes",
                                         "namespace": "SampleNotes",
                                         "minimums": {"macos": "14.0", "windows": "10.0.19041.0"}})
        self.assertEqual(self.d["stack"], {"content": "blazor", "componentLibrary": "custom"})

    def test_evidence_lines_are_well_formed(self):
        self.assert_evidence(self.d)


class DeclaredShell(unittest.TestCase, EvidenceShape):
    """Sample Monitor, built the newer way."""

    @classmethod
    def setUpClass(cls):
        cls.root = kit.fixture("declared-shell")
        cls.d = kit.detect_json(cls.root)

    def test_roles_with_conditional_frameworks(self):
        p = by_path(self.d)
        mac = p["src/SampleMonitor.MacOS/SampleMonitor.MacOS.csproj"]
        self.assertEqual(mac["role"], "head-macos")
        self.assertEqual(mac["tfms"], ["net11.0", "net11.0-macos"])
        self.assertEqual(p["src/SampleMonitor.Windows/SampleMonitor.Windows.csproj"]["role"], "head-windows")
        self.assertEqual(p["src/SampleMonitor.Ui/SampleMonitor.Ui.csproj"]["role"], "ui")
        self.assertEqual(p["src/SampleMonitor.Ui/SampleMonitor.Ui.csproj"]["packages"],
                         {"Microsoft.AspNetCore.Components.Web": "11.0.0"})
        self.assertIsNone(self.d["heads"]["linux"])
        self.assertIsNone(self.d["backends"]["linux"])

    def test_the_newer_contracts(self):
        self.assertEqual(self.d["sharing"]["kind"], "rcl")
        self.assertEqual(self.d["shell"]["navigation"]["kind"], "manifest")
        self.assertEqual(self.d["shell"]["toolbar"]["kind"], "declared")
        self.assertEqual(self.d["dialogs"]["kind"], "session")
        self.assertEqual(self.d["dialogs"]["count"], 1)
        self.assertEqual(self.d["shell"]["menuBar"], {"macos": "default", "windows": "none", "linux": None})

    def test_design_tokens(self):
        des = self.d["design"]
        self.assertTrue(des["tokensJson"])
        self.assertEqual(des["tokenPlatforms"], ["macos", "windows"])
        self.assertEqual(des["rawHex"], 0)

    def test_integrations_and_their_platforms(self):
        plats = self.d["integrationPlatforms"]
        self.assertEqual(plats["tray"], ["macos", "windows"])
        self.assertEqual(plats["notifications"], ["windows"], "the macOS comment naming UNUserNotificationCenter "
                                                              "is not a notification")
        self.assertEqual(plats["singleInstance"], ["windows"])
        self.assertIn("src/SampleMonitor.Windows/Platforms/Windows/Program.cs: var main = "
                      'AppInstance.FindOrRegisterForKey("main");', self.d["integrations"]["singleInstance"])

    def test_app_namespace_drops_the_head_suffix(self):
        self.assertEqual(self.d["app"]["namespace"], "SampleMonitor")
        self.assertIsNone(self.d["dotnet"]["sdk"])

    def test_evidence_lines_are_well_formed(self):
        self.assert_evidence(self.d)


class NewApp(unittest.TestCase):
    def test_nothing_found_is_not_an_error(self):
        d = kit.detect_json(kit.fixture("new-app"))
        self.assertEqual(d["projects"], [])
        self.assertEqual(d["solution"], [])
        self.assertEqual(d["sharing"], {"kind": "unknown", "evidence": []})
        self.assertTrue(all(v is None for v in d["heads"].values()))
        self.assertEqual(d["dialogs"]["kind"], "none")

    def test_the_summary_says_new_app(self):
        code, out, _ = kit.run_detect(["--root", kit.fixture("new-app")])
        self.assertEqual(code, 0)
        self.assertIn("No .NET projects found", out)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="detect-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_summary_is_markdown(self):
        code, out, _ = kit.run_detect(["--root", kit.fixture("legacy-hybrid")])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# Detected: Sample Notes\n"))
        self.assertIn("- UI sharing: compile links into another project", out)
        self.assertIn("Windows `src/SampleNotes/SampleNotes.csproj` (also the shared UI)", out)
        self.assertIn("Run with `--json`", out)

    def test_out_writes_the_json_and_json_prints_it(self):
        out_file = os.path.join(self.tmp, "nested", "detection.json")
        code, out, _ = kit.run_detect(["--root", kit.fixture("declared-shell"), "--out", out_file, "--json"])
        self.assertEqual(code, 0)
        printed = json.loads(out)
        self.assertEqual(kit.read_json(out_file), printed)
        for key in ("root", "solution", "dotnet", "projects", "heads", "backends", "sharing", "shell", "dialogs",
                    "design", "integrations", "distribution", "tests", "agentDocs"):
            self.assertIn(key, printed)

    def test_a_relative_root_from_another_folder(self):
        code, out, _ = kit.run_detect(["--root", os.path.join("files", "legacy-hybrid"), "--json"],
                                      cwd=os.path.join(kit.SKILL_DIR, "evals"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["root"], "files/legacy-hybrid")
        self.assertEqual(d["heads"]["windows"], "src/SampleNotes/SampleNotes.csproj")

    def test_a_root_that_is_not_a_folder(self):
        code, _out, err = kit.run_detect(["--root", os.path.join(self.tmp, "nowhere")])
        self.assertEqual(code, 3)
        self.assertIn("isn't a folder", err)

    def test_bad_arguments(self):
        code, _out, _err = kit.run_detect(["--bogus"])
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
