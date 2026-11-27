"""Tests for mauidesktop_lib.jsonio (stdlib unittest)."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from mauidesktop_lib import jsonio  # noqa: E402


class JsonioTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_load_reads_plain_json(self):
        path = self.write("a.json", b'{"name": "Sample Recipes", "n": [1, 2]}')
        self.assertEqual(jsonio.load(path), {"name": "Sample Recipes", "n": [1, 2]})

    def test_load_tolerates_a_byte_order_mark(self):
        path = self.write("bom.json", b'\xef\xbb\xbf{"a": 1}')
        self.assertEqual(jsonio.load(path), {"a": 1})

    def test_a_syntax_error_names_the_file_and_line(self):
        path = self.write("bad.json", b'{\n  "a": 1,\n  "b": ,\n}\n')
        with self.assertRaises(jsonio.JsonError) as cm:
            jsonio.load(path)
        self.assertEqual(cm.exception.line, 3)
        self.assertIn("bad.json:3:", str(cm.exception))
        self.assertIsInstance(cm.exception, ValueError)

    def test_comments_are_not_json(self):
        path = self.write("c.json", b'{\n  // a comment\n  "a": 1\n}')
        with self.assertRaises(jsonio.JsonError) as cm:
            jsonio.load(path)
        self.assertEqual(cm.exception.line, 2)

    def test_bytes_that_are_not_utf8_name_the_line(self):
        path = self.write("latin.json", b'{\n"a": "caf\xe9"}')
        with self.assertRaises(jsonio.JsonError) as cm:
            jsonio.load(path)
        self.assertIn("latin.json:2", str(cm.exception))

    def test_a_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            jsonio.load(os.path.join(self.dir, "missing.json"))

    def test_dump_writes_two_space_indent_keeps_order_and_ends_with_a_newline(self):
        path = os.path.join(self.dir, "out.json")
        jsonio.dump({"z": 1, "a": {"b": "Crème brûlée"}}, path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text, '{\n  "z": 1,\n  "a": {\n    "b": "Crème brûlée"\n  }\n}\n')
        self.assertEqual(jsonio.load(path), {"z": 1, "a": {"b": "Crème brûlée"}})

    def test_dump_makes_folders_and_leaves_no_temporary_files(self):
        path = os.path.join(self.dir, "deep", "er", "out.json")
        jsonio.dump([1, 2, 3], path)
        jsonio.dump([4], path)
        self.assertEqual(jsonio.load(path), [4])
        self.assertEqual(os.listdir(os.path.dirname(path)), ["out.json"])

    def test_dump_keeps_a_replaced_files_permissions(self):
        path = os.path.join(self.dir, "mode.json")
        jsonio.dump({}, path)
        os.chmod(path, 0o640)
        jsonio.dump({"a": 1}, path)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    def test_a_new_file_is_readable_not_private(self):
        path = os.path.join(self.dir, "new.json")
        jsonio.dump({}, path)
        self.assertTrue(os.stat(path).st_mode & 0o044, "a new file follows the umask, not mkstemp's 0600")

    def test_canonical_sorts_keys_and_drops_spaces(self):
        self.assertEqual(jsonio.canonical({"b": [1, {"d": 1, "c": 2}], "a": "é"}), '{"a":"é","b":[1,{"c":2,"d":1}]}')


if __name__ == "__main__":
    unittest.main()
