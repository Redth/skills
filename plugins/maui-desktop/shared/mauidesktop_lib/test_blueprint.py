"""Tests for mauidesktop_lib.blueprint (stdlib unittest): defaults, values, changes, the consistency rules, the
decisions log, drafting and the interview catalogue."""

import copy
import datetime
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from mauidesktop_lib import blueprint as bpl  # noqa: E402

# CONTRACT.md 2.4, transcribed: field -> (tool, monitor, document, launcher, dashboard)
TABLE = {
    "chrome.sidebar": ("native", "native", "native", "none", "native"),
    "chrome.toolbar": ("native", "native", "native", "none", "native"),
    "chrome.commandPalette": (True, True, True, True, False),
    "chrome.multiWindow": (False, False, True, False, False),
    "integrations.tray": (False, True, False, True, False),
    "integrations.closeToTray": (False, True, False, True, False),
    "integrations.launchAtLogin": (False, True, False, True, False),
    "integrations.notifications": (True, True, False, False, True),
    "integrations.badge": (False, True, False, False, False),
    "integrations.progress": (True, False, False, False, False),
    "integrations.singleInstance": (True, True, True, True, True),
    "integrations.globalHotkey": (False, False, False, True, False),
    "integrations.windowState": (True, True, True, False, True),
}
SHARED = {
    "chrome.menuBar": {"macos": "standard", "windows": "none", "linux": "none"},
    "chrome.dialogs": "native-frame", "chrome.settings": "dialog", "chrome.search": "toolbar",
    "look.fidelity": "adaptive", "look.accent": "brand", "look.theme": "system-with-override", "look.density": False,
    "integrations.contextMenus": "web", "integrations.fileDrop": False, "integrations.deepLinks": False,
    "integrations.fileTypes": [], "integrations.autoUpdate": True, "engineering.devHost": True,
    "engineering.gallery": True, "engineering.devflow": True, "engineering.accessibility": "wcag-aa",
    "stack.sharing": "rcl",
}


def base(**changes):
    """A small consistent blueprint for a tool on all three desktops (plus the dev host)."""
    bp = {
        "version": 1, "confirmedByUser": False, "decided": [],
        "app": {"name": "Sample Notes", "kind": "tool"},
        "platforms": {"macos": {"enabled": True, "home": True}, "windows": {"enabled": True},
                      "linux": {"enabled": True}, "web": {"enabled": True, "role": "devhost"}},
        "chrome": {"sidebar": "native", "toolbar": "web"},
        "integrations": {"notifications": False},
        "distribution": {"channels": {"macos": ["direct"], "windows": ["installer"], "linux": ["appimage"]},
                         "signing": {"macos": "available", "windows": "later", "linux": "none"}},
    }
    for path, val in changes.items():
        bpl.set_path(bp, path.replace("__", "."), val)
    return bp


def ids(found):
    return sorted(set(f.id for f in found))


class Defaults(unittest.TestCase):
    def test_the_table_exactly(self):
        for i, kind in enumerate(bpl.KINDS):
            d = bpl.defaults(kind)
            for path, values in TABLE.items():
                self.assertEqual(bpl.get(d, path), values[i], "%s for %s" % (path, kind))
            for path, val in SHARED.items():
                self.assertEqual(bpl.get(d, path), val, "%s for %s" % (path, kind))
            leaves = []

            def walk(node, prefix):
                for k, v in node.items():
                    p = prefix + k
                    if isinstance(v, dict) and p != "chrome.menuBar":
                        walk(v, p + ".")
                    else:
                        leaves.append(p)
            walk(d, "")
            self.assertEqual(sorted(leaves), sorted(list(TABLE) + list(SHARED)), "nothing more, nothing less")

    def test_defaults_are_fresh_copies(self):
        bpl.defaults("tool")["chrome"]["menuBar"]["macos"] = "full"
        self.assertEqual(bpl.defaults("tool")["chrome"]["menuBar"]["macos"], "standard")

    def test_an_unknown_kind(self):
        with self.assertRaises(ValueError):
            bpl.defaults("game")


class Values(unittest.TestCase):
    def test_single_values_objects_star_and_defaults(self):
        bp = base()
        self.assertEqual(bpl.value(bp, "chrome.sidebar", "linux"), "native")
        bp["chrome"]["sidebar"] = {"macos": "native", "*": "web"}
        self.assertEqual(bpl.value(bp, "chrome.sidebar", "macos"), "native")
        self.assertEqual(bpl.value(bp, "chrome.sidebar", "linux"), "web")
        bp["chrome"]["sidebar"] = {"macos": "web"}
        self.assertEqual(bpl.value(bp, "chrome.sidebar", "windows"), "native", "falls back to the default")
        self.assertEqual(bpl.value(bp, "chrome.menuBar", "macos"), "standard", "a missing field is its default")
        self.assertEqual(bpl.value(bp, "chrome.menuBar", "linux"), "none")
        self.assertEqual(bpl.value(bp, "distribution.channels", "linux"), ["appimage"])
        self.assertIsNone(bpl.value(bp, "engineering.crashReporting"))
        bp["app"]["kind"] = "launcher"
        del bp["chrome"]["sidebar"]
        self.assertEqual(bpl.value(bp, "chrome.sidebar", "macos"), "none", "defaults follow the kind")

    def test_integration_platforms(self):
        bp = base()
        bpl.set_path(bp, "integrations.tray", True)
        self.assertEqual(bpl.integration_platforms(bp, "tray"), ["macos", "windows", "linux"])
        bpl.set_path(bp, "integrations.tray", {"platforms": ["macos"]})
        self.assertEqual(bpl.integration_platforms(bp, "tray"), ["macos"])
        bpl.set_path(bp, "integrations.deepLinks", {"scheme": "samplenotes"})
        self.assertEqual(bpl.integration_platforms(bp, "deepLinks"), ["macos", "windows", "linux"])
        self.assertEqual(bpl.integration_platforms(bp, "notifications"), [])
        bpl.set_path(bp, "integrations.fileTypes", [{"extension": ".samplenote"}])
        self.assertEqual(bpl.integration_platforms(bp, "fileTypes"), ["macos", "windows", "linux"])
        self.assertEqual(bpl.integration_platforms(bp, "contextMenus"), [], "web context menus aren't native")
        self.assertEqual(bpl.integration_platforms(bp, "singleInstance"), ["macos", "windows", "linux"],
                         "a default counts")


class Changing(unittest.TestCase):
    def test_one_platform_of_a_single_value_spreads_it(self):
        bp = base()
        was = bpl.set_path(bp, "chrome.sidebar.linux", "web")
        self.assertEqual(was, "native")
        self.assertEqual(bp["chrome"]["sidebar"], {"macos": "native", "windows": "native", "linux": "web", "web": "web"})

    def test_one_platform_of_a_missing_field_starts_from_its_default(self):
        bp = base()
        was = bpl.set_path(bp, "chrome.menuBar.windows", "minimal")
        self.assertEqual(was, "none")
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "windows": "minimal", "linux": "none"})

    def test_new_objects_and_bad_paths(self):
        bp = base()
        self.assertIsNone(bpl.set_path(bp, "engineering.crashReporting", "sentry"))
        self.assertEqual(bp["engineering"], {"crashReporting": "sentry"})
        self.assertIs(bpl.set_path(bp, "look.density", True), False, "was: the default")
        for bad in ("", "a..b", "chrome.sidebar linux", "app.name.first"):
            with self.assertRaises(ValueError):
                bpl.set_path(bp, bad, "x")

    def test_decided(self):
        bp = base()
        self.assertTrue(bpl.mark_decided(bp, "chrome.sidebar.linux"))
        self.assertFalse(bpl.mark_decided(bp, "chrome.sidebar.linux"))
        self.assertTrue(bpl.is_decided(bp, "chrome.sidebar.linux"))
        self.assertFalse(bpl.is_decided(bp, "chrome.sidebar"))
        bpl.mark_decided(bp, "platforms")
        self.assertTrue(bpl.is_decided(bp, "platforms.macos.enabled"), "a parent decides its children")

    def test_format_value(self):
        self.assertEqual(bpl.format_value("web"), "web")
        self.assertEqual(bpl.format_value(True), "true")
        self.assertEqual(bpl.format_value({"scheme": "samplenotes"}), '{"scheme": "samplenotes"}')
        self.assertEqual(bpl.format_value(["deb", "flatpak"]), '["deb", "flatpak"]')
        self.assertEqual(bpl.format_value(None), "(unset)")


class Consistency(unittest.TestCase):
    def test_a_consistent_blueprint_has_only_the_gtk_note(self):
        self.assertEqual(ids(bpl.consistency(base())), ["gtk-native-chrome"])

    def test_no_platform(self):
        bp = base()
        for p in ("macos", "windows", "linux"):
            bp["platforms"][p]["enabled"] = False
        bp["distribution"] = {}
        self.assertIn("no-platform", ids(bpl.consistency(bp)))

    def test_two_homes(self):
        self.assertIn("two-homes", ids(bpl.consistency(base(platforms__windows__home=True))))

    def test_macos_menu_bar(self):
        found = bpl.consistency(base(chrome__menuBar={"macos": "none", "windows": "none", "linux": "none"}))
        self.assertIn("macos-menu-bar", ids(found))
        self.assertIn("macos-menu-bar", ids(bpl.consistency(base(chrome__menuBar="none"))))
        self.assertNotIn("macos-menu-bar", ids(bpl.consistency(base(chrome__menuBar="minimal"))))

    def test_deep_link_scheme(self):
        for bad in (True, {}, {"scheme": "Sample Notes"}, {"scheme": "1notes"}, {"scheme": ""}):
            self.assertIn("deep-link-scheme", ids(bpl.consistency(base(integrations__deepLinks=bad))), bad)
        for good in (False, {"scheme": "samplenotes"}, {"scheme": "sample-notes+x.y"}):
            self.assertNotIn("deep-link-scheme", ids(bpl.consistency(base(integrations__deepLinks=good))), good)

    def test_per_platform_key(self):
        bp = base(platforms__linux__enabled=False)
        found = bpl.consistency(bp)
        wheres = sorted(f.where for f in found if f.id == "per-platform-key")
        self.assertEqual(wheres, ["distribution.channels.linux", "distribution.signing.linux"])
        bp["chrome"]["sidebar"] = {"macos": "native", "linux": "web", "*": "native"}
        bp["integrations"]["tray"] = {"platforms": ["macos", "linux"]}
        wheres = sorted(f.where for f in bpl.consistency(bp) if f.id == "per-platform-key")
        self.assertEqual(wheres, ["chrome.sidebar.linux", "distribution.channels.linux", "distribution.signing.linux",
                                  "integrations.tray.platforms"])
        bp = base(platforms__web__enabled=False, chrome__sidebar={"macos": "native", "web": "web"})
        self.assertIn("chrome.sidebar.web", [f.where for f in bpl.consistency(bp) if f.id == "per-platform-key"])

    def test_gtk_native_chrome(self):
        found = [f for f in bpl.consistency(base()) if f.id == "gtk-native-chrome"]
        self.assertEqual([f.severity for f in found], ["info"])
        self.assertNotIn("gtk-native-chrome", ids(bpl.consistency(base(chrome__sidebar__linux="web"))))

    def test_tray_gnome_and_hotkey_wayland(self):
        found = bpl.consistency(base(integrations__tray=True, integrations__globalHotkey={"platforms": ["linux"]}))
        self.assertTrue({"tray-gnome", "hotkey-wayland"} <= set(ids(found)))
        self.assertEqual(set(f.severity for f in found if f.id in ("tray-gnome", "hotkey-wayland")), {"warning"})
        found = bpl.consistency(base(integrations__tray={"platforms": ["macos"]}))
        self.assertNotIn("tray-gnome", ids(found))

    def test_unsigned_macos(self):
        bp = base(integrations__notifications=True)
        self.assertNotIn("unsigned-macos", ids(bpl.consistency(bp)))
        bp["distribution"]["signing"]["macos"] = "later"
        self.assertIn("unsigned-macos", ids(bpl.consistency(bp)))
        bp = base(integrations__launchAtLogin={"platforms": ["macos"]})
        bp["distribution"]["signing"]["macos"] = "none"
        self.assertIn("unsigned-macos", ids(bpl.consistency(bp)))

    def test_update_owned_by_channel(self):
        bp = base()
        self.assertNotIn("update-owned-by-channel", ids(bpl.consistency(bp)), "auto-update on, appimage owns nothing")
        for chan in ("mac-app-store", "microsoft-store", "msix", "flatpak", "snap"):
            plat = "macos" if chan == "mac-app-store" else "windows" if chan in ("microsoft-store", "msix") else "linux"
            bp = base(**{"distribution__channels__" + plat: [chan]})
            self.assertIn("update-owned-by-channel", ids(bpl.consistency(bp)), chan)
        for chan in ("deb", "rpm"):
            found = bpl.consistency(base(distribution__channels__linux=[chan]))
            self.assertNotIn("update-owned-by-channel", ids(found), chan)
            self.assertIn("update-package-repo", ids(found), chan)
        bp = base(distribution__channels__linux=["flatpak"], integrations__autoUpdate={"platforms": ["macos", "windows"]})
        self.assertNotIn("update-owned-by-channel", ids(bpl.consistency(bp)))

    def test_flatpak_autostart(self):
        bp = base(distribution__channels__linux=["flatpak"], integrations__launchAtLogin=True)
        self.assertIn("flatpak-autostart", ids(bpl.consistency(bp)))
        bp = base(distribution__channels__linux=["flatpak"])
        self.assertNotIn("flatpak-autostart", ids(bpl.consistency(bp)))

    def test_faithful_cost_sharing_and_content(self):
        found = bpl.consistency(base(look__fidelity={"macos": "native-faithful", "*": "adaptive"},
                                     stack__sharing="symlinks", stack__content="other"))
        self.assertTrue({"faithful-cost", "sharing-not-rcl", "content-other"} <= set(ids(found)))
        sev = {f.id: f.severity for f in found}
        self.assertEqual((sev["faithful-cost"], sev["sharing-not-rcl"], sev["content-other"]), ("warning", "warning", "info"))
        self.assertIn("sharing-not-rcl", ids(bpl.consistency(base(stack__sharing="links"))))
        self.assertNotIn("sharing-not-rcl", ids(bpl.consistency(base(stack__sharing="single"))))


class DecisionsLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log = os.path.join(self._tmp.name, "docs", "desktop", "decisions.md")

    def read(self):
        with open(self.log, encoding="utf-8") as f:
            return f.read()

    def test_the_contract_format(self):
        bpl.append_decision(self.log, "chrome.sidebar.linux", "web", "native", "user",
                            "We only ship Linux as a preview; a web sidebar is fine there.", datetime.date(2026, 11, 27))
        self.assertEqual(self.read(), "# Desktop decisions\n\n"
                                      "## 2026-11-27: chrome.sidebar.linux = web\n\n"
                                      "- **By:** user\n"
                                      "- **Reason:** \"We only ship Linux as a preview; a web sidebar is fine there.\"\n"
                                      "- **Was:** native\n")

    def test_appending_keeps_one_blank_line_between_entries(self):
        os.makedirs(os.path.dirname(self.log))
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("# Desktop decisions\n\nEdited by hand.")
        bpl.append_decision(self.log, "look.density", True, False, "proposal", "\"Dense lists.\"", "2026-11-28")
        bpl.append_decision(self.log, "integrations.deepLinks", {"scheme": "samplenotes"}, None, "user", "", "2026-11-29")
        text = self.read()
        self.assertIn("Edited by hand.\n\n## 2026-11-28: look.density = true\n\n- **By:** proposal\n"
                      "- **Reason:** \"Dense lists.\"\n- **Was:** false\n\n"
                      "## 2026-11-29: integrations.deepLinks = {\"scheme\": \"samplenotes\"}\n", text)
        self.assertIn("- **Reason:** (none given)\n- **Was:** (unset)\n", text)

    def test_who(self):
        with self.assertRaises(ValueError):
            bpl.append_decision(self.log, "a.b", 1, 0, "agent", "x")

    def test_log_path_is_relative_to_the_blueprint(self):
        bp = {"decisionsLog": "notes/decisions.md"}
        self.assertEqual(bpl.log_path(bp, os.path.join("proj", "desktop-blueprint.json")),
                         os.path.join(os.path.abspath("proj"), "notes", "decisions.md"))
        self.assertTrue(bpl.log_path({}, "desktop-blueprint.json").endswith(os.path.join("docs", "desktop", "decisions.md")))


def detection(**extra):
    d = {
        "root": "sample-notes", "projects": [{"path": "src/A/A.csproj"}],
        "heads": {"macos": "src/A.MacOS/A.MacOS.csproj", "windows": "src/A/A.csproj", "linux": None},
        "backends": {"macos": "Microsoft.Maui.Platforms.MacOS 0.1.0", "windows": "Microsoft.Maui.Controls 11.0.10",
                     "linux": None},
        "dotnet": {"sdk": "11.0.100", "tfms": []},
        "sharing": {"kind": "links", "evidence": []},
        "shell": {"sidebar": {"macos": "native", "windows": "web"}, "toolbar": {"kind": "imperative"},
                  "menuBar": {"macos": "custom-items", "windows": "custom-items"}, "commandPalette": [], "multiWindow": []},
        "dialogs": {"kind": "page-subclass", "count": 2, "webOverlays": 5},
        "design": {"platformSelectors": {"macos": 120, "windows": 3, "linux": 0}},
        "integrations": {"tray": [], "notifications": ["x: AppNotificationManager"], "deepLinks": ["x: CFBundleURLTypes"],
                         "globalHotkey": ["x: RegisterHotKey"], "contextMenus": ["x: ContextFlyout"]},
        "integrationPlatforms": {"notifications": ["windows"], "deepLinks": ["macos"], "globalHotkey": ["windows"],
                                 "contextMenus": ["windows"]},
        "deepLinkSchemes": ["samplenotes"],
        "distribution": {"macos": ["codesign", "homebrew"], "windows": ["winget"], "linux": []},
        "app": {"name": "Sample Notes", "id": "com.example.samplenotes", "namespace": "SampleNotes",
                "minimums": {"macos": "14.0"}},
        "stack": {"content": "blazor", "componentLibrary": "custom"},
        "engineering": {"crashReporting": "sentry"},
    }
    d.update(extra)
    return d


class Drafting(unittest.TestCase):
    def test_detection_overrides_defaults_where_it_found_something(self):
        bp = bpl.draft(detection())
        self.assertEqual(bp["app"], {"name": "Sample Notes", "id": "com.example.samplenotes", "namespace": "SampleNotes",
                                     "kind": "tool", "existing": True})
        self.assertEqual(bp["platforms"]["linux"], {"enabled": False})
        self.assertEqual(bp["platforms"]["macos"], {"enabled": True, "home": True, "minimum": "14.0"})
        self.assertEqual(bp["platforms"]["windows"], {"enabled": True, "minimum": "10.0.19041"})
        self.assertEqual(bp["stack"]["sharing"], "links")
        self.assertEqual(bp["stack"]["dotnet"], "11.0")
        self.assertEqual(bp["stack"]["backends"], {"macos": "Microsoft.Maui.Platforms.MacOS 0.1.0",
                                                   "windows": "Microsoft.Maui.Controls 11.0.10"})
        self.assertEqual(bp["chrome"]["sidebar"], {"macos": "native", "windows": "web", "web": "web"})
        self.assertEqual(bp["chrome"]["toolbar"], "native")
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "windows": "standard"})
        self.assertEqual(bp["chrome"]["dialogs"], "mixed", "more web overlays than native dialogs")
        self.assertEqual(bp["look"]["fidelity"], {"macos": "native-faithful", "windows": "adaptive"})
        self.assertIs(bp["integrations"]["notifications"], True, "already on by default for a tool")
        self.assertEqual(bp["integrations"]["deepLinks"], {"scheme": "samplenotes"})
        self.assertEqual(bp["integrations"]["globalHotkey"], {"platforms": ["windows"]})
        self.assertEqual(bp["integrations"]["contextMenus"], "native")
        self.assertEqual(bp["distribution"]["channels"], {"macos": ["direct", "homebrew"], "windows": ["winget"]})
        self.assertEqual(bp["distribution"]["signing"], {"macos": "available", "windows": "later"})
        self.assertEqual(bp["engineering"]["crashReporting"], "sentry")
        self.assertEqual((bp["confirmedByUser"], bp["decided"]), (False, []))

    def test_a_tray_icon_makes_a_monitor(self):
        d = detection(integrations={"tray": ["x: NSStatusItem"]}, integrationPlatforms={"tray": ["macos"]})
        bp = bpl.draft(d)
        self.assertEqual(bp["app"]["kind"], "monitor")
        self.assertIs(bp["integrations"]["tray"], True, "on by default for a monitor")
        self.assertEqual(bpl.draft(d, kind="tool")["integrations"]["tray"], {"platforms": ["macos"]})

    def test_nothing_detected(self):
        bp = bpl.draft({"root": os.path.join("somewhere", "sample-notes")})
        self.assertEqual(bp["app"]["name"], "sample notes")
        self.assertEqual(bp["app"]["namespace"], "SampleNotes")
        self.assertFalse(bp["app"]["existing"])
        self.assertEqual([p for p in bpl.DESKTOP if bp["platforms"][p]["enabled"]], list(bpl.DESKTOP))
        self.assertEqual(bp["stack"]["sharing"], "rcl")
        self.assertEqual(bp["chrome"], dict(bpl.defaults("tool")["chrome"]))
        self.assertEqual(bp["distribution"]["channels"], bpl.DEFAULT_CHANNELS)

    def test_overrides(self):
        bp = bpl.draft({}, overrides={"app.name": "Sample Monitor", "app.id": "com.example.samplemonitor",
                                      "platforms": ["macos", "windows"], "look.accent": "system", "app.kind": "monitor"})
        self.assertEqual(bp["app"]["kind"], "monitor")
        self.assertEqual(bp["app"]["namespace"], "SampleMonitor")
        self.assertEqual(bp["look"]["accent"], "system")
        self.assertFalse(bp["platforms"]["linux"]["enabled"])
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "windows": "none"})
        self.assertEqual(ids([f for f in bpl.consistency(bp) if f.severity == "error"]), [])

    def test_prune_removes_disabled_platform_keys(self):
        bp = base(platforms__linux__enabled=False)
        bp["chrome"]["menuBar"] = {"macos": "standard", "linux": "none", "*": "none"}
        bpl.prune(bp)
        self.assertEqual(bp["chrome"]["menuBar"], {"macos": "standard", "*": "none"})
        self.assertNotIn("linux", bp["distribution"]["channels"])


class Interview(unittest.TestCase):
    def test_groups_in_order(self):
        self.assertEqual([g["group"] for g in bpl.QUESTIONS],
                         ["Product", "Chrome (per platform)", "Look", "Background and integrations", "Distribution",
                          "Engineering"])

    def test_every_question_names_real_fields(self):
        known = set(TABLE) | set(SHARED) | {
            "app.kind", "app.existing", "platforms.*.enabled", "platforms.*.home", "platforms.*.minimum",
            "distribution.channels", "distribution.signing", "stack.content", "stack.componentLibrary",
            "engineering.crashReporting", "engineering.locales"}
        seen = set()
        for g in bpl.QUESTIONS:
            for q in g["questions"]:
                self.assertTrue(q["ask"].endswith("?"), q["ask"])
                for path in q["paths"]:
                    self.assertIn(path, known)
                    seen.add(path)
        for path in ("integrations.tray", "integrations.deepLinks", "chrome.multiWindow", "look.density",
                     "engineering.devflow"):
            self.assertIn(path, seen)

    def test_open_questions_skip_what_is_decided(self):
        bp = base()
        total = sum(len(g["questions"]) for g in bpl.QUESTIONS)
        self.assertEqual(len(bpl.open_questions(bp)), total)
        bp["decided"] = ["app.kind", "platforms", "chrome.sidebar.macos"]
        open_ids = [q["id"] for _g, q, _p in bpl.open_questions(bp)]
        self.assertNotIn("kind", open_ids)
        self.assertNotIn("platforms", open_ids)
        self.assertNotIn("minimums", open_ids)
        self.assertIn("sidebar", open_ids, "one platform decided leaves the field open")
        tray = [p for _g, q, p in bpl.open_questions(bp) if q["id"] == "tray"][0]
        self.assertEqual(tray, ["integrations.tray", "integrations.closeToTray", "integrations.launchAtLogin"])
        self.assertEqual(bpl.expand_path(bp, "platforms.*.minimum"), ["platforms.macos.minimum", "platforms.windows.minimum"])


if __name__ == "__main__":
    unittest.main()
