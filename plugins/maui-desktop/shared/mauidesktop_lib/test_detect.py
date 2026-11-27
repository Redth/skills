"""Tests for mauidesktop_lib.detect (stdlib unittest), on small projects written into a temp folder."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from mauidesktop_lib import detect  # noqa: E402

MAC = """<Project Sdk="Microsoft.NET.Sdk.Razor">
  <PropertyGroup>
    <TargetFramework>net11.0-macos</TargetFramework>
    <OutputType>Exe</OutputType>
    <UseMaui>true</UseMaui>
    <ApplicationTitle>Sample Monitor</ApplicationTitle>
    <ApplicationId>com.example.samplemonitor</ApplicationId>
    <RootNamespace>SampleMonitor.MacOS</RootNamespace>
  </PropertyGroup>
  <ItemGroup>%s</ItemGroup>
</Project>"""
WIN = """<Project Sdk="Microsoft.NET.Sdk.Razor">
  <PropertyGroup>
    <TargetFramework>net11.0-windows10.0.19041.0</TargetFramework>
    <OutputType>WinExe</OutputType>
    <UseMaui>true</UseMaui>
  </PropertyGroup>
  <ItemGroup>%s</ItemGroup>
</Project>"""
GTK = """<Project Sdk="Microsoft.NET.Sdk.Razor">
  <PropertyGroup><TargetFramework>net11.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>
  <ItemGroup><PackageReference Include="Microsoft.Maui.Platforms.Linux.Gtk4" Version="0.1.0" />%s</ItemGroup>
</Project>"""
RCL = """<Project Sdk="Microsoft.NET.Sdk.Razor">
  <PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup>
  <ItemGroup>%s</ItemGroup>
</Project>"""
LIB = """<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>"""


class TempTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def put(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return path

    def scan(self):
        return detect.scan(self.root)

    def roles(self, d):
        return {p["path"]: p["role"] for p in d["projects"]}

    def rcl_app(self):
        self.put("src/App.Ui/App.Ui.csproj", RCL % "")
        self.put("src/App.Ui/Pages/Home.razor", "@page \"/\"\n<NavLink href=\"/\">Home</NavLink>\n")
        ref = '<ProjectReference Include="../App.Ui/App.Ui.csproj" />'
        self.put("src/App.MacOS/App.MacOS.csproj", MAC % ('<PackageReference Include="Microsoft.Maui.Platforms.MacOS" '
                                                          'Version="0.1.0" />' + ref))
        self.put("src/App.Windows/App.Windows.csproj", WIN % ref)
        self.put("src/App.Core/App.Core.csproj", LIB)


class Roles(TempTree):
    def test_every_role(self):
        self.rcl_app()
        self.put("src/App.LinuxGtk/App.LinuxGtk.csproj", GTK % "")
        self.put("src/App.DevHost/App.DevHost.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"><ItemGroup>'
                                                        '<ProjectReference Include="../App.Ui/App.Ui.csproj" />'
                                                        '</ItemGroup></Project>')
        self.put("src/App.Cli/App.Cli.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                                               '<OutputType>Exe</OutputType><PackAsTool>true</PackAsTool>'
                                               '</PropertyGroup></Project>')
        self.put("src/App.Plugins/App.Plugins.csproj", LIB)
        self.put("src/App.Mobile/App.Mobile.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                                                     '<TargetFrameworks>net11.0-android;net11.0-ios</TargetFrameworks>'
                                                     '<UseMaui>true</UseMaui></PropertyGroup></Project>')
        self.put("tests/App.Tests/App.Tests.csproj", '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
                                                     '<PackageReference Include="xunit" Version="2.9.3" />'
                                                     '<PackageReference Include="bunit" Version="1.0.0" />'
                                                     '</ItemGroup></Project>')
        d = self.scan()
        self.assertEqual(self.roles(d), {
            "src/App.Cli/App.Cli.csproj": "tool", "src/App.Core/App.Core.csproj": "core",
            "src/App.DevHost/App.DevHost.csproj": "devhost", "src/App.LinuxGtk/App.LinuxGtk.csproj": "head-linux",
            "src/App.MacOS/App.MacOS.csproj": "head-macos", "src/App.Mobile/App.Mobile.csproj": "head-ios",
            "src/App.Plugins/App.Plugins.csproj": "other", "src/App.Ui/App.Ui.csproj": "ui",
            "src/App.Windows/App.Windows.csproj": "head-windows", "tests/App.Tests/App.Tests.csproj": "tests"})
        self.assertEqual(d["heads"]["android"], "src/App.Mobile/App.Mobile.csproj")
        self.assertEqual(d["heads"]["devhost"], "src/App.DevHost/App.DevHost.csproj")
        self.assertEqual(d["tests"], {"projects": ["tests/App.Tests/App.Tests.csproj"],
                                      "ui": ["tests/App.Tests/App.Tests.csproj"]})
        mobile = [p for p in d["projects"] if p["path"].endswith("App.Mobile.csproj")][0]
        self.assertEqual(mobile["platforms"], ["ios", "android"])
        self.assertEqual(d["app"]["namespace"], "SampleMonitor")

    def test_a_head_for_a_different_app_id_is_another_app(self):
        appid = "<PropertyGroup><ApplicationId>com.example.samplemonitor</ApplicationId></PropertyGroup>"
        self.put("src/App.MacOS/App.MacOS.csproj", MAC % ('<PackageReference Include="Microsoft.Maui.Platforms.MacOS" '
                                                          'Version="0.1.0" />'))
        self.put("src/App.Windows/App.Windows.csproj", (WIN % "").replace("</Project>", appid + "</Project>"))
        self.put("samples/Probe/Probe.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                                               '<TargetFrameworks>net11.0-android;net11.0-ios</TargetFrameworks>'
                                               '<UseMaui>true</UseMaui>'
                                               '<ApplicationId>com.example.samplemonitor.probe</ApplicationId>'
                                               '</PropertyGroup></Project>')
        d = self.scan()
        self.assertEqual(self.roles(d)["samples/Probe/Probe.csproj"], "other-app")
        self.assertIsNone(d["heads"]["ios"])
        self.assertIsNone(d["heads"]["android"])
        self.assertEqual(d["heads"]["macos"], "src/App.MacOS/App.MacOS.csproj")

    def test_a_single_project_is_head_and_ui(self):
        self.put("App/App.csproj", WIN % "")
        self.put("App/Pages/Home.razor", "@page \"/\"\n")
        d = self.scan()
        self.assertTrue(d["projects"][0]["alsoUi"])
        self.assertEqual(d["sharing"]["kind"], "single")


class Sharing(TempTree):
    def test_rcl(self):
        self.rcl_app()
        s = self.scan()["sharing"]
        self.assertEqual(s["kind"], "rcl")
        self.assertEqual([e.split(": ", 1)[0] for e in s["evidence"]],
                         ["src/App.MacOS/App.MacOS.csproj", "src/App.Windows/App.Windows.csproj"])
        self.assertTrue(all('<ProjectReference Include="../App.Ui/App.Ui.csproj" />' in e for e in s["evidence"]))
        self.assertTrue(all(len(e.split(": ", 1)[1]) <= 120 for e in s["evidence"]))

    def test_links_beat_a_class_library_used_for_something_else(self):
        self.rcl_app()
        self.put("src/App.LinuxGtk/App.LinuxGtk.csproj", GTK % '<Compile Include="..\\App.Windows\\**\\*.cs" />')
        d = self.scan()
        self.assertEqual(d["sharing"]["kind"], "links")
        first = d["sharing"]["evidence"][0]
        self.assertTrue(first.startswith("src/App.LinuxGtk/App.LinuxGtk.csproj: "), first)
        self.assertIn('<Compile Include="..\\App.Windows\\**\\*.cs" />', first)
        win = [p for p in d["projects"] if p["path"] == "src/App.Windows/App.Windows.csproj"][0]
        self.assertTrue(win["alsoUi"], "a head others link into is also the UI")

    def test_includes_outside_any_project_are_not_sharing(self):
        self.put("src/App.MacOS/App.MacOS.csproj", MAC % '<None Include="..\\..\\third_party\\NOTICE.txt" />')
        self.put("src/App.Windows/App.Windows.csproj", WIN % "")
        self.assertEqual(self.scan()["sharing"]["kind"], "unknown")

    def test_symlinks(self):
        self.put("src/App/App.csproj", WIN % "")
        self.put("src/App/Pages/Home.razor", "@page \"/\"\n")
        self.put("src/App.MacOS/App.MacOS.csproj", MAC % "")
        try:
            os.symlink(os.path.join("..", "App", "Pages"), os.path.join(self.root, "src", "App.MacOS", "Pages"),
                       target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as e:
            self.skipTest("symlinks aren't available here: %s" % e)
        d = self.scan()
        self.assertEqual(d["sharing"]["kind"], "symlinks")
        self.assertEqual(d["sharing"]["evidence"], ["src/App.MacOS/Pages -> ../App/Pages"])
        roles = {p["path"]: p for p in d["projects"]}
        self.assertTrue(roles["src/App/App.csproj"].get("alsoUi"))
        self.assertNotIn("alsoUi", roles["src/App.MacOS/App.MacOS.csproj"], "the symlinked pages aren't walked")

    def test_a_symlink_checked_out_as_a_file(self):
        self.put("src/App/App.csproj", WIN % "")
        self.put("src/App/_Imports.razor", "@using App\n")
        self.put("src/App.MacOS/App.MacOS.csproj", MAC % "")
        self.put("src/App.MacOS/_Imports.razor", "../App/_Imports.razor")
        d = self.scan()
        self.assertEqual(d["sharing"]["kind"], "symlinks")
        self.assertEqual(d["sharing"]["evidence"],
                         ["src/App.MacOS/_Imports.razor -> ../App/_Imports.razor (a symlink checked out as a file)"])


class Signals(TempTree):
    def test_comments_are_never_evidence(self):
        self.rcl_app()
        self.put("src/App.MacOS/Notes.cs", "// UNUserNotificationCenter needs a signed app\n"
                                           "/// <summary>NSStatusItem is for later</summary>\n"
                                           " * SMAppService too\n")
        self.put("src/App.MacOS/Info.plist", "<plist>\n<!-- CFBundleURLTypes\n  will go here -->\n</plist>\n")
        self.put("src/App.Ui/Pages/Tray.razor", "@* NotifyIcon in a Razor comment *@\n<!-- NotifyIcon in markup -->\n")
        self.put(".github/workflows/ci.yml", "jobs:\n  # codesign later\n  build:\n    steps:\n      - run: dotnet build\n")
        d = self.scan()
        for key in ("notifications", "tray", "launchAtLogin", "deepLinks"):
            self.assertEqual(d["integrations"][key], [], key)
        self.assertEqual(d["distribution"]["macos"], [])

    def test_platforms_come_from_the_signal_or_the_head(self):
        self.rcl_app()
        self.put("src/App.MacOS/Tray.cs", "var item = NSStatusBar.SystemStatusBar.CreateStatusItem(-1);\n")
        self.put("src/App.Windows/Hotkeys.cs", "RegisterHotKey(hwnd, 1, mods, key);\n")
        self.put("src/App.Windows/Sizes.cs", 'Preferences.Set("MainWindowWidth", w);\n')
        self.put("src/App.Core/Update.cs", "using Velopack;\n")
        d = self.scan()
        self.assertEqual(d["integrationPlatforms"]["tray"], ["macos"])
        self.assertEqual(d["integrationPlatforms"]["globalHotkey"], ["windows"])
        self.assertEqual(d["integrationPlatforms"]["windowState"], ["windows"], "a shared-code signal takes its head")
        self.assertEqual(d["integrationPlatforms"]["autoUpdate"], ["*"])

    def test_deep_link_schemes(self):
        self.rcl_app()
        self.put("src/App.MacOS/Info.plist", "<dict>\n<key>CFBundleURLTypes</key>\n<array><dict>\n"
                                             "<key>CFBundleURLSchemes</key>\n<array>\n<string>samplemonitor</string>\n"
                                             "</array></dict></array>\n</dict>\n")
        d = self.scan()
        self.assertEqual(d["deepLinkSchemes"], ["samplemonitor"])
        self.assertEqual(d["integrationPlatforms"]["deepLinks"], ["macos"])

    def test_window_state_keys_are_specific(self):
        self.rcl_app()
        self.put("src/App.Core/Js.cs", 'js.Invoke("window.__colResize.start");\nvar c = "windowsdesktop";\n')
        self.assertEqual(self.scan()["integrations"]["windowState"], [])

    def test_tests_are_not_the_app(self):
        self.rcl_app()
        self.put("tests/App.Tests/App.Tests.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                                                     '<IsTestProject>true</IsTestProject></PropertyGroup></Project>')
        self.put("tests/App.Tests/TrayTests.cs", "var x = typeof(NSStatusItem);\n")
        self.assertEqual(self.scan()["integrations"]["tray"], [])

    def test_long_lines_are_trimmed_around_the_match(self):
        self.rcl_app()
        self.put("src/App.Windows/Long.cs", "var x = " + "a" * 200 + " + AppNotificationManager.Default + " + "b" * 200 + ";\n")
        line = self.scan()["integrations"]["notifications"][0]
        path, text = line.split(": ", 1)
        self.assertEqual(path, "src/App.Windows/Long.cs")
        self.assertEqual(len(text), 120)
        self.assertIn("AppNotificationManager", text)
        self.assertTrue(text.startswith("…") and text.endswith("…"))

    def test_shell_kinds(self):
        self.rcl_app()
        self.put("src/App.Core/Shell/PageChrome.cs", "public sealed record PageChrome(string Title);\n")
        self.put("src/App.Core/Navigation/NavigationManifest.cs", "public static class NavigationManifest { }\n")
        self.put("src/App.Core/Shell/DialogSession.cs", "public sealed class DialogSession { }\n")
        self.put("src/App.Ui/Pages/Ask.razor", "@code { void A() => Shell.Show(new DialogRequest(\"x\")); }\n")
        self.put("src/App.Ui/Components/CommandPalette.razor", "<div class=\"palette\"></div>\n")
        self.put("src/App.MacOS/Sidebar.cs", "FlyoutPage? flyout;\nvar menu = NSApplication.SharedApplication.MainMenu;\n")
        d = self.scan()
        shell = d["shell"]
        self.assertEqual(shell["navigation"]["kind"], "manifest")
        self.assertEqual(shell["toolbar"]["kind"], "declared")
        self.assertEqual(shell["sidebar"], {"macos": "native", "windows": "web", "linux": None, "web": "web"})
        self.assertEqual(shell["menuBar"], {"macos": "custom-items", "windows": "none", "linux": None})
        self.assertTrue(shell["commandPalette"])
        self.assertEqual(d["dialogs"]["kind"], "session")
        self.assertEqual(d["dialogs"]["count"], 1)

    def test_the_main_window_is_not_a_second_window(self):
        self.rcl_app()
        self.put("src/App.MacOS/MacApp.cs", "protected override Window CreateWindow(IActivationState? s)\n"
                                            "    => new Window(new MainPage());\n")
        self.assertEqual(self.scan()["shell"]["multiWindow"], [])
        self.put("src/App.Core/Panels.cs", "var w = new Window(page);\nApplication.Current.OpenWindow(w);\n")
        self.assertEqual(self.scan()["shell"]["multiWindow"], ["src/App.Core/Panels.cs: var w = new Window(page);"])

    def test_web_only_shell_and_dialogs(self):
        self.rcl_app()
        self.put("src/App.Ui/Pages/Edit.razor", '<div class="toolbar"></div>\n<dialog open>Sure?</dialog>\n')
        d = self.scan()
        self.assertEqual(d["shell"]["navigation"]["kind"], "web")
        self.assertEqual(d["shell"]["toolbar"]["kind"], "web")
        self.assertEqual(d["dialogs"]["kind"], "web")
        self.assertEqual(d["dialogs"]["webOverlays"], 1)

    def test_stack_and_engineering(self):
        self.rcl_app()
        self.put("src/App.Ui/App.Ui.csproj", RCL % '<PackageReference Include="MudBlazor" Version="8.0.0" />'
                                                   '<PackageReference Include="Sentry.Maui" Version="5.0.0" />'
                                                   '<PackageReference Include="Microsoft.Maui.DevFlow.Agent" Version="0.1.0" />')
        self.put("src/App.Ui/Pages/Gallery.razor", '@page "/gallery"\n')
        d = self.scan()
        self.assertEqual(d["stack"], {"content": "blazor", "componentLibrary": "MudBlazor"})
        self.assertEqual(d["engineering"]["crashReporting"], "sentry")
        self.assertEqual(d["engineering"]["devflow"], ["src/App.Ui/App.Ui.csproj: Microsoft.Maui.DevFlow.Agent"])
        self.assertEqual(d["engineering"]["gallery"], ['src/App.Ui/Pages/Gallery.razor: @page "/gallery"'])


class Design(TempTree):
    def test_hex_counting(self):
        css = ":root { --a: #fff; --b: #12345678; }\n/* #000 */\n#fab { color: #abcdef; fill: url(#fade); }\n"
        self.assertEqual(detect.hex_count("a.css", css), 3)
        razor = ('<a href="#top">top</a> issue #123\n<p style="color: #c00; background:#fafafa">x</p>\n'
                 "<style>\n.x { border-color: #ddd; }\n</style>\n")
        self.assertEqual(detect.hex_count("a.razor", razor), 3)

    def test_generated_and_vendored_files_are_skipped(self):
        self.rcl_app()
        self.put("src/App.Ui/wwwroot/css/app.css", ".platform-macos .x { color: #111111; }\n"
                                                   '[data-platform="windows"] .x { color: #222; }\n')
        self.put("src/App.Ui/wwwroot/css/tokens.css", "/* Generated by tokens.py: do not edit. */\n:root { --a: #333; }\n")
        self.put("src/App.Ui/wwwroot/css/site.min.css", ":root{--a:#444}\n")
        self.put("src/App.Ui/wwwroot/lib/x/x.css", ".platform-linux { color: #555; }\n")
        self.put("design/tokens.json", '{"platforms": {"macos": {}, "$comment": "x"}}\n')
        self.put("design/icons.json", "{}\n")
        self.put("DESIGN.md", "# Design\n")
        des = self.scan()["design"]
        self.assertEqual(des["rawHex"], 2)
        self.assertEqual(des["platformSelectors"], {"macos": 1, "windows": 1, "linux": 0})
        self.assertEqual((des["designMd"], des["tokensJson"], des["iconsJson"]), (True, True, True))
        self.assertEqual(des["tokenPlatforms"], ["macos"])
        self.assertIn("DESIGN.md: (present)", des["evidence"])


class Distribution(TempTree):
    def test_tags_from_workflows_scripts_and_projects(self):
        self.rcl_app()
        self.put(".github/workflows/release.yml", "steps:\n  - run: hdiutil create x.dmg\n"
                                                   "  - run: dotnet publish -p:CreateDeb=false -p:CreateAppImage=true\n"
                                                   "  - run: signtool sign /fd sha256 x.exe\n")
        self.put("build/windows/App.iss", "[Setup]\n")
        self.put("build/linux/snapcraft.yaml", "name: app\n")
        self.put("src/App.Windows/App.Windows.csproj",
                 (WIN % "").replace("<UseMaui>", "<WindowsPackageType>MSIX</WindowsPackageType><UseMaui>"))
        dist = self.scan()["distribution"]
        self.assertEqual(dist["workflows"], [".github/workflows/release.yml"])
        self.assertEqual(dist["macos"], ["dmg"])
        self.assertEqual(dist["windows"], ["inno-setup", "msix", "signing"])
        self.assertEqual(dist["linux"], ["appimage", "snap"], "CreateDeb=false is not a deb")

    def test_nothing(self):
        self.rcl_app()
        dist = self.scan()["distribution"]
        self.assertEqual((dist["workflows"], dist["macos"], dist["windows"], dist["linux"]), ([], [], [], []))


class Errors(unittest.TestCase):
    def test_a_root_that_is_not_a_folder(self):
        with self.assertRaises(NotADirectoryError):
            detect.scan(os.path.join(tempfile.gettempdir(), "no-such-folder-for-detect"))

    def test_dotnet_version(self):
        self.assertEqual(detect.dotnet_version({"dotnet": {"sdk": "11.0.100", "tfms": []}}), "11.0")
        self.assertEqual(detect.dotnet_version({"dotnet": {"sdk": None, "tfms": ["net10.0", "net11.0-macos"]}}), "11.0")
        self.assertIsNone(detect.dotnet_version({"dotnet": {"sdk": None, "tfms": []}}))

    def test_trim(self):
        self.assertEqual(detect.trim("short"), "short")
        long = "x" * 300
        self.assertEqual(len(detect.trim(long, 150)), 120)


if __name__ == "__main__":
    unittest.main()
