"""Tests for mauidesktop_lib.schema (stdlib unittest): one test a keyword, and messages located by pointer."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from mauidesktop_lib import schema  # noqa: E402

validate = schema.validate


class KeywordTests(unittest.TestCase):
    def assertValid(self, instance, s):
        self.assertEqual(validate(instance, s), [])

    def assertInvalid(self, instance, s, pointer="(root)", contains=None):
        errors = validate(instance, s)
        self.assertTrue(errors, "expected %r to be invalid" % (instance,))
        self.assertTrue(errors[0].startswith(pointer + ": "), errors)
        if contains:
            self.assertIn(contains, errors[0])
        return errors

    def test_type(self):
        self.assertValid("a", {"type": "string"})
        self.assertValid(3, {"type": "integer"})
        self.assertValid(3.0, {"type": "integer"})
        self.assertValid(3.5, {"type": "number"})
        self.assertValid(None, {"type": "null"})
        self.assertValid({}, {"type": "object"})
        self.assertValid([], {"type": "array"})
        self.assertValid(True, {"type": "boolean"})
        self.assertInvalid(3.5, {"type": "integer"}, contains="expected integer, got number")
        self.assertInvalid(True, {"type": "integer"}, contains="got boolean")
        self.assertInvalid(1, {"type": "boolean"})

    def test_type_lists(self):
        s = {"type": ["string", "null"]}
        self.assertValid(None, s)
        self.assertValid("x", s)
        self.assertInvalid(1, s, contains="expected string or null")

    def test_properties_and_pointers(self):
        s = {"type": "object", "properties": {"app": {"type": "object", "properties": {"name": {"type": "string"}}}}}
        self.assertValid({"app": {"name": "Sample Recipes"}}, s)
        self.assertInvalid({"app": {"name": 5}}, s, pointer="/app/name")

    def test_pointer_escapes(self):
        s = {"properties": {"a/b": {"properties": {"c~d": {"type": "string"}}}}}
        self.assertInvalid({"a/b": {"c~d": 1}}, s, pointer="/a~1b/c~0d")

    def test_required(self):
        s = {"type": "object", "required": ["version", "app"]}
        errors = self.assertInvalid({"version": 1}, s, contains='"app" is required')
        self.assertEqual(len(errors), 1)

    def test_additional_properties_false(self):
        s = {"type": "object", "properties": {"a": {}}, "additionalProperties": False}
        self.assertValid({"a": 1}, s)
        self.assertInvalid({"a": 1, "b": 2}, s, contains='"b" isn\'t a known property')

    def test_additional_properties_schema(self):
        s = {"type": "object", "properties": {"a": {}}, "additionalProperties": {"type": "integer"}}
        self.assertValid({"a": "x", "b": 2}, s)
        self.assertInvalid({"b": "x"}, s, pointer="/b")

    def test_pattern_properties(self):
        s = {"type": "object", "patternProperties": {"^[a-z]{2}(-[A-Z]{2})?$": {"type": "object"}},
             "additionalProperties": False}
        self.assertValid({"en-US": {}, "de": {}}, s)
        self.assertInvalid({"en-US": 1}, s, pointer="/en-US")
        self.assertInvalid({"English": {}}, s, contains="isn't a known property")

    def test_items(self):
        s = {"type": "array", "items": {"type": "string"}}
        self.assertValid(["a", "b"], s)
        self.assertInvalid(["a", 2], s, pointer="/1")

    def test_prefix_items(self):
        s = {"type": "array", "prefixItems": [{"type": "integer"}, {"type": "integer"}], "items": False}
        self.assertValid([1290, 2796], s)
        self.assertInvalid([1290, "x"], s, pointer="/1")
        self.assertInvalid([1, 2, 3], s, pointer="/2")

    def test_min_and_max_items(self):
        s = {"type": "array", "minItems": 1, "maxItems": 2}
        self.assertValid([1], s)
        self.assertInvalid([], s, contains="fewer than 1")
        self.assertInvalid([1, 2, 3], s, contains="more than 2")

    def test_unique_items(self):
        s = {"uniqueItems": True}
        self.assertValid([1, "1", True, None, {"a": 1}, {"a": 2}], s)
        self.assertInvalid(["recipes", "grocery", "recipes"], s, contains="item 2 repeats item 0")
        self.assertInvalid([1, 1.0], s)
        self.assertInvalid([{"a": 1, "b": 2}, {"b": 2, "a": 1}], s)

    def test_enum(self):
        s = {"enum": ["phone", "tablet", "desktop", "tv", "watch", "xr"]}
        self.assertValid("tablet", s)
        self.assertInvalid("laptop", s, contains="isn't one of")
        self.assertInvalid(True, {"enum": [1]})

    def test_const(self):
        self.assertValid(1, {"const": 1})
        self.assertValid(1.0, {"const": 1})
        self.assertInvalid(2, {"const": 1}, contains="must be 1")

    def test_minimum_and_maximum(self):
        s = {"minimum": 1, "maximum": 5}
        self.assertValid(1, s)
        self.assertValid(5, s)
        self.assertInvalid(0, s, contains="less than the minimum")
        self.assertInvalid(5.5, s, contains="more than the maximum")
        self.assertValid("not a number", s)

    def test_exclusive_bounds(self):
        s = {"exclusiveMinimum": 0, "exclusiveMaximum": 1}
        self.assertValid(0.5, s)
        self.assertInvalid(0, s)
        self.assertInvalid(1, s)

    def test_min_and_max_length_count_code_points(self):
        s = {"minLength": 2, "maxLength": 3}
        self.assertValid("abc", s)
        self.assertValid("\U0001F355\U0001F355", s)
        self.assertInvalid("a", s, contains="shorter than 2")
        self.assertInvalid("abcd", s, contains="is 4 characters, longer than 3")

    def test_pattern(self):
        s = {"pattern": "^com\\.[a-z]+"}
        self.assertValid("com.example.samplerecipes", s)
        self.assertInvalid("org.example", s, contains="doesn't match the pattern")
        self.assertValid("xx-com.a", {"pattern": "com\\.a"})

    def test_format_uri(self):
        s = {"format": "uri"}
        for ok in ("https://example.com", "https://example.com/support?x=1", "mailto:support@example.com"):
            self.assertValid(ok, s)
        for bad in ("example.com", "https://", "https://exa mple.com", "http:// example.com"):
            self.assertInvalid(bad, s, contains="isn't a valid uri")

    def test_format_email(self):
        self.assertValid("support@example.com", {"format": "email"})
        for bad in ("support", "support@example", "a b@example.com", "@example.com"):
            self.assertInvalid(bad, {"format": "email"})

    def test_format_date(self):
        self.assertValid("2026-11-14", {"format": "date"})
        self.assertInvalid("2026-02-30", {"format": "date"})
        self.assertInvalid("14/11/2026", {"format": "date"})

    def test_unknown_formats_are_ignored(self):
        self.assertValid("anything", {"format": "hostname"})

    def test_ref(self):
        s = {"$defs": {"locale": {"type": "string", "pattern": "^[a-z]{2}"}},
             "type": "object", "properties": {"primaryLocale": {"$ref": "#/$defs/locale"}}}
        self.assertValid({"primaryLocale": "en-US"}, s)
        self.assertInvalid({"primaryLocale": "EN"}, s, pointer="/primaryLocale")
        with self.assertRaises(ValueError):
            validate(1, {"$ref": "#/$defs/missing"})
        with self.assertRaises(ValueError):
            validate(1, {"$ref": "https://example.com/other.json"})

    def test_recursive_ref(self):
        s = {"$defs": {"node": {"type": "object", "properties": {"children": {"type": "array", "items": {"$ref": "#/$defs/node"}}}}},
             "$ref": "#/$defs/node"}
        self.assertValid({"children": [{"children": []}]}, s)
        self.assertInvalid({"children": [{"children": [1]}]}, s, pointer="/children/0/children/0")

    def test_any_of(self):
        s = {"anyOf": [{"type": "null"}, {"type": "string", "maxLength": 3}]}
        self.assertValid(None, s)
        self.assertValid("abc", s)
        errors = self.assertInvalid("abcd", s, contains="longer than 3")
        self.assertEqual(len(errors), 1, "the branch the value aimed at explains the failure")
        self.assertInvalid(5, s, contains="doesn't match any of the 2 allowed shapes")

    def test_one_of(self):
        s = {"oneOf": [{"type": "integer"}, {"type": "number", "minimum": 10}]}
        self.assertValid(3, s)
        self.assertValid(10.5, s)
        self.assertInvalid(12, s, contains="must match exactly one")
        self.assertInvalid("x", s, contains="allowed shapes")

    def test_all_of(self):
        s = {"allOf": [{"type": "string"}, {"minLength": 2}]}
        self.assertValid("ab", s)
        self.assertInvalid("a", s, contains="shorter than 2")

    def test_not(self):
        s = {"not": {"const": ""}}
        self.assertValid("x", s)
        self.assertInvalid("", s, contains="must not match")

    def test_boolean_schemas(self):
        self.assertValid(1, True)
        self.assertInvalid(1, False, contains="no value is allowed")

    def test_annotations_are_ignored(self):
        s = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$comment": "x", "title": "t",
             "description": "d", "default": 1, "examples": [1], "type": "integer"}
        self.assertValid(1, s)

    def test_several_errors_are_all_reported(self):
        s = {"type": "object", "required": ["a"], "properties": {"b": {"type": "string"}, "c": {"maximum": 1}}}
        errors = validate({"b": 1, "c": 2}, s)
        self.assertEqual(len(errors), 3)


class UnsupportedTests(unittest.TestCase):
    def test_lists_keywords_this_validator_would_not_check(self):
        s = {"type": "object", "$comment": "fine", "properties": {
            "a": {"type": "string", "contentEncoding": "base64"},
            "b": {"anyOf": [{"dependentRequired": {}}]}},
            "$defs": {"x": {"if": {}, "then": {}}}}
        self.assertEqual(sorted(schema.unsupported(s)), sorted([
            "/properties/a: contentEncoding",
            "/properties/b/anyOf/0: dependentRequired",
            "/$defs/x: if",
            "/$defs/x: then",
        ]))

    def test_property_names_are_not_keywords(self):
        self.assertEqual(schema.unsupported({"properties": {"if": {"type": "string"}, "then": {}}}), [])


if __name__ == "__main__":
    unittest.main()
