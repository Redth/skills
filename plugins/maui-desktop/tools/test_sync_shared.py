"""Tests for sync_shared.py (stdlib unittest): the real copies match shared/, and the sync and check work."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sync_shared  # noqa: E402


class RepositoryTests(unittest.TestCase):
    def test_the_skills_copies_match_shared(self):
        drift = sync_shared.check()
        self.assertEqual(drift, [], "run plugins/maui-desktop/tools/sync_shared.py:\n" + "\n".join(drift))

    def test_every_skill_in_the_table_exists(self):
        for skill in sync_shared.SYNC:
            self.assertTrue(os.path.isdir(os.path.join(sync_shared.PLUGIN_ROOT, "skills", skill)), skill)
            for item in sync_shared.SYNC[skill]:
                self.assertIn(item, sync_shared.ITEMS)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.put("shared/mauidesktop_lib/__init__.py", "")
        self.put("shared/mauidesktop_lib/jsonio.py", "# jsonio\n")
        self.put("shared/mauidesktop_lib/sub/detail.py", "# a nested module\n")
        self.put("shared/mauidesktop_lib/test_jsonio.py", "# a test, not copied\n")
        self.put("shared/mauidesktop_lib/__pycache__/jsonio.cpython-38.pyc", "x")
        os.makedirs(os.path.join(self.root, "skills", "maui-desktop-blueprint"))
        os.makedirs(os.path.join(self.root, "skills", "maui-desktop-design"))
        self.table = {"maui-desktop-blueprint": ("mauidesktop_lib",), "maui-desktop-design": ("mauidesktop_lib",)}

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def put(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as f:
            return f.read()

    def test_the_table_gives_both_skills_the_package(self):
        self.assertEqual(sync_shared.ITEMS["mauidesktop_lib"][2], ("test_*.py",))
        self.assertEqual(sorted(sync_shared.SYNC), ["maui-desktop-blueprint", "maui-desktop-design"])

    def test_sync_copies_the_package_without_tests_into_every_skill(self):
        changes = sync_shared.sync(self.root, self.table)
        self.assertEqual(len(changes), 6)
        for skill in ("maui-desktop-blueprint", "maui-desktop-design"):
            lib = "skills/%s/scripts/mauidesktop_lib/" % skill
            self.assertEqual(self.read(lib + "jsonio.py"), "# jsonio\n")
            self.assertEqual(self.read(lib + "sub/detail.py"), "# a nested module\n")
            self.assertFalse(os.path.exists(self.path(lib + "test_jsonio.py")))
            self.assertFalse(os.path.exists(self.path(lib + "__pycache__")))
        self.assertEqual(sync_shared.check(self.root, self.table), [])
        self.assertEqual(sync_shared.sync(self.root, self.table), [], "a second sync changes nothing")

    def test_check_lists_missing_changed_and_extra_files(self):
        self.assertIn("missing skills/maui-desktop-design/scripts/mauidesktop_lib/jsonio.py".replace("/", os.sep),
                      sync_shared.check(self.root, self.table))
        sync_shared.sync(self.root, self.table)
        lib = "skills/maui-desktop-blueprint/scripts/mauidesktop_lib/"
        self.put(lib + "jsonio.py", "# edited in the copy\n")
        self.put(lib + "old.py", "# gone from shared\n")
        os.unlink(self.path(lib + "sub/detail.py"))
        drift = sync_shared.check(self.root, self.table)
        self.assertEqual(sorted(d.split()[0] for d in drift), ["differs", "extra", "missing"])
        self.assertTrue(any(d.endswith("old.py") for d in drift))

    def test_sync_repairs_drift_and_removes_what_shared_no_longer_has(self):
        sync_shared.sync(self.root, self.table)
        lib = "skills/maui-desktop-design/scripts/mauidesktop_lib/"
        self.put(lib + "jsonio.py", "# edited in the copy\n")
        self.put(lib + "old/gone.py", "")
        sync_shared.sync(self.root, self.table)
        self.assertEqual(self.read(lib + "jsonio.py"), "# jsonio\n")
        self.assertFalse(os.path.exists(self.path(lib + "old")))
        self.assertEqual(sync_shared.check(self.root, self.table), [])

    def test_caches_in_a_copy_are_not_drift(self):
        sync_shared.sync(self.root, self.table)
        self.put("skills/maui-desktop-blueprint/scripts/mauidesktop_lib/__pycache__/jsonio.cpython-312.pyc", "x")
        self.assertEqual(sync_shared.check(self.root, self.table), [])

    def test_a_skill_that_is_not_there(self):
        with self.assertRaises(FileNotFoundError):
            sync_shared.sync(self.root, {"maui-desktop-shell": ("mauidesktop_lib",)})
        self.assertEqual(sync_shared.check(self.root, {"maui-desktop-shell": ("mauidesktop_lib",)}),
                         ["missing " + os.path.join("skills", "maui-desktop-shell")])

    def test_the_command_line_check_exits_1_on_drift(self):
        out = io.StringIO()
        old = sync_shared.SYNC
        sync_shared.SYNC = self.table
        try:
            with redirect_stdout(out):
                self.assertEqual(sync_shared.main(["--check", "--root", self.root]), 1)
                self.assertEqual(sync_shared.main(["--root", self.root]), 0)
                self.assertEqual(sync_shared.main(["--check", "--root", self.root]), 0)
        finally:
            sync_shared.SYNC = old
        self.assertIn("missing", out.getvalue())


if __name__ == "__main__":
    unittest.main()
