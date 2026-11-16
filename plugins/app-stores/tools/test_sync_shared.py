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
        self.assertEqual(drift, [], "run plugins/app-stores/tools/sync_shared.py:\n" + "\n".join(drift))

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
        self.put("shared/appstores_lib/__init__.py", "")
        self.put("shared/appstores_lib/png.py", "# png\n")
        self.put("shared/appstores_lib/test_png.py", "# a test, not copied\n")
        self.put("shared/appstores_lib/__pycache__/png.cpython-38.pyc", "x")
        self.put("shared/rules/google.json", "{}\n")
        self.put("shared/rules/rules.schema.json", "{}\n")
        os.makedirs(os.path.join(self.root, "skills", "store-listings"))
        self.table = {"store-listings": ("appstores_lib", "rules")}

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def put(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def read(self, rel):
        with open(self.path(rel)) as f:
            return f.read()

    def test_sync_copies_the_package_without_tests_and_the_rules(self):
        changes = sync_shared.sync(self.root, self.table)
        self.assertEqual(len(changes), 4)
        self.assertEqual(self.read("skills/store-listings/scripts/appstores_lib/png.py"), "# png\n")
        self.assertTrue(os.path.isfile(self.path("skills/store-listings/rules/google.json")))
        self.assertFalse(os.path.exists(self.path("skills/store-listings/scripts/appstores_lib/test_png.py")))
        self.assertFalse(os.path.exists(self.path("skills/store-listings/scripts/appstores_lib/__pycache__")))
        self.assertEqual(sync_shared.check(self.root, self.table), [])
        self.assertEqual(sync_shared.sync(self.root, self.table), [], "a second sync changes nothing")

    def test_check_lists_missing_changed_and_extra_files(self):
        self.assertIn("missing skills/store-listings/rules/google.json".replace("/", os.sep),
                      sync_shared.check(self.root, self.table))
        sync_shared.sync(self.root, self.table)
        self.put("skills/store-listings/scripts/appstores_lib/png.py", "# edited in the copy\n")
        self.put("skills/store-listings/rules/old.json", "{}\n")
        os.unlink(self.path("skills/store-listings/rules/rules.schema.json"))
        drift = sync_shared.check(self.root, self.table)
        self.assertEqual(sorted(d.split()[0] for d in drift), ["differs", "extra", "missing"])
        self.assertTrue(any(d.endswith("old.json") for d in drift))

    def test_sync_repairs_drift_and_removes_what_shared_no_longer_has(self):
        sync_shared.sync(self.root, self.table)
        self.put("skills/store-listings/scripts/appstores_lib/png.py", "# edited in the copy\n")
        self.put("skills/store-listings/scripts/appstores_lib/old/gone.py", "")
        sync_shared.sync(self.root, self.table)
        self.assertEqual(self.read("skills/store-listings/scripts/appstores_lib/png.py"), "# png\n")
        self.assertFalse(os.path.exists(self.path("skills/store-listings/scripts/appstores_lib/old")))
        self.assertEqual(sync_shared.check(self.root, self.table), [])

    def test_caches_in_a_copy_are_not_drift(self):
        sync_shared.sync(self.root, self.table)
        self.put("skills/store-listings/scripts/appstores_lib/__pycache__/png.cpython-312.pyc", "x")
        self.assertEqual(sync_shared.check(self.root, self.table), [])

    def test_a_skill_that_is_not_there(self):
        with self.assertRaises(FileNotFoundError):
            sync_shared.sync(self.root, {"store-capture": ("appstores_lib",)})
        self.assertEqual(sync_shared.check(self.root, {"store-capture": ("appstores_lib",)}),
                         ["missing " + os.path.join("skills", "store-capture")])

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
