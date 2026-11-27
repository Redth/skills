"""Tests for install.py: what it copies, the version guard, and that the installed copy runs on its own.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. The last test runs the installed
scripts with this same Python interpreter (no shell) against a copy of an eval fixture. Offline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_testkit as kit  # noqa: E402
import install  # noqa: E402


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="install-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "app")
        os.makedirs(self.root)

    def install(self, *argv):
        return kit.run(install, ["--root", self.root] + list(argv))

    def folder(self, *parts):
        return os.path.join(self.root, "build", "design", *parts)


class Copies(TempDir):
    def test_installs_scripts_schemas_package_and_version(self):
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        for name in ("tokens.py", "icons.py", "lint.py", "design_color.py", "VERSION",
                     os.path.join("schema", "tokens.schema.json"), os.path.join("schema", "icons.schema.json"),
                     os.path.join("mauidesktop_lib", "__init__.py"), os.path.join("mauidesktop_lib", "schema.py"),
                     os.path.join("mauidesktop_lib", "findings.py"), os.path.join("mauidesktop_lib", "jsonio.py")):
            self.assertTrue(os.path.isfile(self.folder(name)), name)
        self.assertEqual(kit.read(self.folder("VERSION")).strip(), install.skill_version())
        everything = [os.path.join(d, f) for d, _, fs in os.walk(self.folder()) for f in fs]
        self.assertFalse([f for f in everything if os.path.basename(f).startswith("test_")])
        self.assertFalse([f for f in everything if "testkit" in f or "install.py" in f or "__pycache__" in f])
        for f in everything:
            with open(f, "rb") as fh:
                self.assertNotIn(b"\r\n", fh.read(), f)

    def test_into_another_folder(self):
        code, out, err = self.install("--into", "tools/design")
        self.assertEqual(code, 0, out + err)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "tools", "design", "tokens.py")))

    def test_the_same_version_refreshes(self):
        self.install()
        kit.write(self.folder("tokens.py"), "# edited\n")
        kit.write(self.folder("README.md"), "ours\n")
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertNotEqual(kit.read(self.folder("tokens.py")), "# edited\n")
        self.assertEqual(kit.read(self.folder("README.md")), "ours\n")

    def test_another_version_is_refused_unless_forced(self):
        self.install()
        kit.write(self.folder("VERSION"), "0.0.1\n")
        kit.write(self.folder("old_helper.py"), "# from 0.0.1\n")
        code, out, _ = self.install()
        self.assertEqual(code, 2)
        self.assertIn("0.0.1", out)
        self.assertEqual(kit.read(self.folder("VERSION")), "0.0.1\n")
        code, out, err = self.install("--force")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(kit.read(self.folder("VERSION")).strip(), install.skill_version())
        self.assertFalse(os.path.exists(self.folder("old_helper.py")))

    def test_a_folder_of_other_files_is_refused(self):
        kit.write(self.folder("notes.txt"), "mine\n")
        code, _, _ = self.install()
        self.assertEqual(code, 2)
        self.assertEqual(kit.read(self.folder("notes.txt")), "mine\n")

    def test_root_must_be_a_folder(self):
        code, _, _ = kit.run(install, ["--root", os.path.join(self.tmp, "nope")])
        self.assertEqual(code, 3)


class InstalledCopyRuns(TempDir):
    def run_installed(self, script, *argv):
        proc = subprocess.run([sys.executable, self.folder(script)] + list(argv), cwd=self.root,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        return proc.returncode, proc.stdout + proc.stderr

    def test_ci_commands_work_without_the_skill(self):
        shutil.rmtree(self.root)
        kit.fixture("tokens-basic", self.root)
        self.install()
        code, out = self.run_installed("tokens.py", "build", "--check")
        self.assertEqual(code, 1, out)  # nothing generated yet: stale
        code, out = self.run_installed("tokens.py", "build")
        self.assertEqual(code, 0, out)
        code, out = self.run_installed("tokens.py", "build", "--check")
        self.assertEqual(code, 0, out)
        code, out = self.run_installed("tokens.py", "contrast", "--quiet")
        self.assertEqual(code, 0, out)
        code, out = self.run_installed("lint.py")
        self.assertEqual(code, 0, out)
        self.assertIn("0 file(s) scanned", out)  # src/ holds only generated outputs, which lint skips
        code, out = self.run_installed("tokens.py", "init")
        self.assertEqual(code, 2, out)  # tokens.json exists; and the installed copy has no templates anyway


if __name__ == "__main__":
    unittest.main()
