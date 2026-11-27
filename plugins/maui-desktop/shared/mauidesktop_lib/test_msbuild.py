"""Tests for mauidesktop_lib.msbuild (stdlib unittest), on project files written into a temp folder."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from mauidesktop_lib import msbuild  # noqa: E402


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


class ReadProject(TempTree):
    def test_the_sdk_attribute_frameworks_and_properties(self):
        path = self.put("App/App.csproj", """<Project Sdk="Microsoft.NET.Sdk.Razor">
  <PropertyGroup>
    <TargetFrameworks>net11.0-macos;net11.0-windows10.0.19041.0</TargetFrameworks>
    <UseMaui>true</UseMaui>
    <OutputType>Exe</OutputType>
  </PropertyGroup>
</Project>""")
        p = msbuild.read_project(path)
        self.assertEqual(p.sdk, "Microsoft.NET.Sdk.Razor")
        self.assertEqual(p.target_frameworks, ["net11.0-macos", "net11.0-windows10.0.19041.0"])
        self.assertTrue(p.has_true("UseMaui"))
        self.assertEqual(p.prop("OutputType"), "Exe")
        self.assertIsNone(p.error)

    def test_sdk_imports_and_conditions_recorded_not_evaluated(self):
        path = self.put("Mac/Mac.csproj", """<Project>
  <Import Project="Sdk.props" Sdk="Microsoft.NET.Sdk.Razor" />
  <PropertyGroup Condition="!$([MSBuild]::IsOSPlatform('osx'))">
    <TargetFramework>net11.0</TargetFramework>
  </PropertyGroup>
  <PropertyGroup Condition="$([MSBuild]::IsOSPlatform('osx'))">
    <TargetFramework>net11.0-macos</TargetFramework>
    <UseMaui Condition="'$(Configuration)' == 'Debug'">true</UseMaui>
  </PropertyGroup>
  <Import Project="Sdk.targets" Sdk="Microsoft.NET.Sdk.Razor" />
</Project>""")
        p = msbuild.read_project(path)
        self.assertEqual(p.sdk, "Microsoft.NET.Sdk.Razor")
        self.assertEqual(p.sdks, ["Microsoft.NET.Sdk.Razor"])
        self.assertEqual(p.target_frameworks, ["net11.0", "net11.0-macos"])
        self.assertEqual(p.prop("TargetFramework"), "net11.0-macos", "the last one wins")
        conds = [c for _v, c in p.conditional["TargetFramework"]]
        self.assertIn("osx", conds[0])
        self.assertTrue(p.has_true("UseMaui"))
        self.assertIn("Debug", p.conditional["UseMaui"][0][1])
        self.assertIn("IsOSPlatform", p.conditional["UseMaui"][0][1], "group and element conditions combine")
        self.assertEqual([i[0] for i in p.imports], ["Sdk.props", "Sdk.targets"])

    def test_package_and_project_references(self):
        path = self.put("App/App.csproj", """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><MauiVersion>11.0.10</MauiVersion></PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.Maui.Controls" Version="$(MauiVersion)" />
    <PackageReference Include="Central.Only" />
    <PackageReference Include="Overridden" VersionOverride="2.0.0" />
    <PackageReference Include="Child.Version"><Version>3.1.0</Version></PackageReference>
    <PackageReference Include="Debug.Only" Condition="'$(Configuration)' == 'Debug'" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\\Core\\Core.csproj" />
  </ItemGroup>
</Project>""")
        p = msbuild.read_project(path, central={"Central.Only": "1.2.3", "Overridden": "1.0.0", "debug.only": "4.0.0"})
        refs = {r[0]: r for r in p.package_refs}
        self.assertEqual(refs["Microsoft.Maui.Controls"][1], "11.0.10")
        self.assertEqual(refs["Central.Only"][1], "1.2.3")
        self.assertEqual(refs["Overridden"][1], "2.0.0")
        self.assertEqual(refs["Child.Version"][1], "3.1.0")
        self.assertEqual(refs["Debug.Only"][1], "4.0.0", "central ids match case-insensitively")
        self.assertIn("Debug", refs["Debug.Only"][2])
        self.assertEqual(p.project_refs, ["../Core/Core.csproj"])
        self.assertEqual(p.package("microsoft.maui.controls"), "11.0.10")
        self.assertIsNone(p.package("Not.There"))

    def test_items_keep_raw_attributes_and_metadata(self):
        path = self.put("Gtk/Gtk.csproj", """<Project Sdk="Microsoft.NET.Sdk.Razor">
  <ItemGroup Condition="'$(X)' == 'y'">
    <Compile Include="..\\App\\Services\\*.cs" Link="Services\\%(Filename)%(Extension)" />
    <RazorComponent Include="..\\App\\**\\*.razor"><Link>%(RecursiveDir)%(Filename)</Link></RazorComponent>
  </ItemGroup>
</Project>""")
        p = msbuild.read_project(path)
        include, attrs = p.items["Compile"][0]
        self.assertEqual(include, "../App/Services/*.cs")
        self.assertEqual(attrs["Include"], "..\\App\\Services\\*.cs")
        self.assertEqual(attrs["Link"], "Services\\%(Filename)%(Extension)")
        self.assertIn("'$(X)'", attrs["Condition"])
        self.assertEqual(p.items["RazorComponent"][0][1]["Link"], "%(RecursiveDir)%(Filename)")

    def test_old_style_namespaces_and_choose(self):
        path = self.put("Old/Old.csproj", """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <Choose>
    <When Condition="'$(OS)' == 'Windows_NT'">
      <PropertyGroup><TargetFramework>net11.0-windows10.0.19041.0</TargetFramework></PropertyGroup>
    </When>
    <Otherwise>
      <PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup>
    </Otherwise>
  </Choose>
</Project>""")
        p = msbuild.read_project(path)
        self.assertEqual(p.target_frameworks, ["net11.0-windows10.0.19041.0", "net11.0"])
        self.assertEqual(p.conditional["TargetFramework"][1][1], "otherwise")

    def test_a_file_that_is_not_well_formed_is_read_by_regex(self):
        path = self.put("Bad/Bad.csproj", """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net11.0-macos</TargetFramework>
    <UseMaui>true</UseMaui>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.Maui.Platforms.MacOS" Version="0.1.0" />
  <!-- unclosed
</Project>""")
        p = msbuild.read_project(path)
        self.assertTrue(p.error)
        self.assertEqual(p.sdk, "Microsoft.NET.Sdk")
        self.assertEqual(p.target_frameworks, ["net11.0-macos"])
        self.assertEqual(p.package("Microsoft.Maui.Platforms.MacOS"), "0.1.0")

    def test_a_missing_file(self):
        with self.assertRaises(OSError):
            msbuild.read_project(os.path.join(self.root, "nope.csproj"))


class CentralAndGlobal(TempTree):
    def test_central_versions_and_switch(self):
        self.put("Directory.Packages.props", """<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
    <Preview>0.1.0-preview.1</Preview>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="Microsoft.Maui.Controls" Version="11.0.10" />
    <PackageVersion Include="Microsoft.Maui.Platforms.MacOS" Version="$(Preview)" />
    <GlobalPackageReference Include="Analyzers" Version="1.0.0" />
  </ItemGroup>
</Project>""")
        self.assertEqual(msbuild.central_versions(self.root), {
            "Microsoft.Maui.Controls": "11.0.10", "Microsoft.Maui.Platforms.MacOS": "0.1.0-preview.1",
            "Analyzers": "1.0.0"})
        self.assertTrue(msbuild.cpm_enabled(self.root))

    def test_the_nearest_props_file_applies(self):
        self.put("Directory.Packages.props", '<Project><ItemGroup><PackageVersion Include="A" Version="1.0" />'
                                             '</ItemGroup></Project>')
        self.put("sub/Directory.Packages.props", '<Project><ItemGroup><PackageVersion Include="A" Version="2.0" />'
                                                 '</ItemGroup></Project>')
        inner = self.put("sub/app/App.csproj", "<Project />")
        outer = self.put("other/App.csproj", "<Project />")
        self.assertEqual(msbuild.central_versions_for(inner, self.root), {"A": "2.0"})
        self.assertEqual(msbuild.central_versions_for(outer, self.root), {"A": "1.0"})

    def test_no_central_management(self):
        self.assertEqual(msbuild.central_versions(self.root), {})
        self.assertFalse(msbuild.cpm_enabled(self.root))

    def test_global_json_with_comments(self):
        self.assertIsNone(msbuild.sdk_version(self.root))
        self.put("global.json", '{\n  // the SDK\n  "sdk": { "version": "11.0.100", /* pinned */ "rollForward": "latestFeature", },\n}\n')
        self.assertEqual(msbuild.sdk_version(self.root), "11.0.100")
        self.put("global.json", '{"msbuild-sdks": {}}')
        self.assertIsNone(msbuild.sdk_version(self.root))
        self.put("global.json", "not json")
        self.assertIsNone(msbuild.sdk_version(self.root))

    def test_strings_keep_comment_markers(self):
        self.assertEqual(msbuild.strip_json_comments('{"a": "//x /*y*/"} // z'), '{"a": "//x /*y*/"} ')


class Walking(TempTree):
    def test_walk_skips_output_dependencies_and_vendored_assets(self):
        for rel in ("App/App.csproj", "App/bin/Debug/App.dll", "App/obj/project.assets.json", "node_modules/x/y.js",
                    ".git/HEAD", ".vs/state", "App/wwwroot/lib/bootstrap.css", "App/wwwroot/vendor/v.js",
                    "App/wwwroot/css/app.css", ".github/workflows/build.yml", "Tests/TestResults/r.trx",
                    "One.slnx", "deep/Two.sln"):
            self.put(rel, "x")
        files = [r for r, _a, _l in msbuild.walk(self.root)]
        self.assertEqual(sorted(files), [".github/workflows/build.yml", "App/App.csproj", "App/wwwroot/css/app.css",
                                         "One.slnx", "deep/Two.sln"])
        self.assertEqual(msbuild.project_files(self.root), ["App/App.csproj"])
        self.assertEqual(msbuild.solution_files(self.root), ["One.slnx", "deep/Two.sln"])

    def test_symlinks_are_listed_not_followed(self):
        self.put("Shared/Pages/Index.razor", "x")
        link = os.path.join(self.root, "Mac", "Pages")
        os.makedirs(os.path.dirname(link))
        try:
            os.symlink(os.path.join("..", "Shared", "Pages"), link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as e:
            self.skipTest("symlinks aren't available here: %s" % e)
        entries = list(msbuild.walk(self.root))
        self.assertIn(("Mac/Pages", link, True), entries)
        self.assertNotIn("Mac/Pages/Index.razor", [r for r, _a, _l in entries])

    def test_text_is_read_with_newlines_whatever_the_checkout(self):
        path = os.path.join(self.root, "crlf.cs")
        with open(path, "wb") as f:
            f.write(b"\xef\xbb\xbfline one\r\nline two\r\n")
        self.assertEqual(msbuild.read_text(path), "line one\nline two\n")
        self.assertIsNone(msbuild.read_text(path, limit=3))
        self.assertIsNone(msbuild.read_text(os.path.join(self.root, "missing.cs")))

    def test_rel_uses_forward_slashes(self):
        self.assertEqual(msbuild.rel(os.path.join(self.root, "a", "b.cs"), self.root), "a/b.cs")


class Frameworks(unittest.TestCase):
    def test_parse_tfm(self):
        self.assertEqual(msbuild.parse_tfm("net11.0-windows10.0.19041.0"), (11, 0, "windows", "10.0.19041.0"))
        self.assertEqual(msbuild.parse_tfm("net10.0-macos26.0"), (10, 0, "macos", "26.0"))
        self.assertEqual(msbuild.parse_tfm("net11.0"), (11, 0, None, None))
        self.assertIsNone(msbuild.parse_tfm("netstandard2.0"))
        self.assertEqual(msbuild.tfm_platform("net11.0-maccatalyst"), "maccatalyst")
        self.assertIsNone(msbuild.tfm_platform("net48"))

    def test_expand(self):
        self.assertEqual(msbuild.expand("$(A)-$(B)", {"A": "1"}), "1-$(B)")
        self.assertEqual(msbuild.expand("plain", {}), "plain")


if __name__ == "__main__":
    unittest.main()
