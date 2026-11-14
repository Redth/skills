"""Tests for appstores_lib.rules (stdlib unittest), against small rules files written to a temp folder."""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import rules  # noqa: E402

SOURCE = "https://support.google.com/googleplay/android-developer/answer/9898842"

GOOGLE = {
    "$schema": "./rules.schema.json",
    "store": "google",
    "checked": "2026-11-14",
    "rules": [
        {"id": "google.title.length", "kind": "limit", "applies": {"field": "google.title"}, "max": 30,
         "count": "characters", "severity": "error", "source": SOURCE, "checked": "2026-11-14", "status": "verified"},
        {"id": "google.short.length", "kind": "limit", "applies": {"field": "google.shortDescription"}, "max": 80,
         "min": 10, "count": "graphemes", "severity": "error", "source": SOURCE, "checked": "2026-11-14",
         "status": "observed"},
        {"id": "google.words.price", "kind": "words", "words": ["free", "#1", "best"],
         "fields": ["google.title", "google.shortDescription"], "severity": "error", "source": SOURCE,
         "checked": "2026-11-14", "status": "verified"},
        {"id": "google.title.emoji_like", "kind": "pattern", "applies": {"fields": ["google.title"]},
         "regex": "!{2,}", "forbid": True, "severity": "warning", "source": SOURCE, "checked": "2026-11-14",
         "status": "verified"},
        {"id": "google.screenshots.phone.count", "kind": "count", "applies": {"slot": "phone"}, "min": 2, "max": 8,
         "severity": "error", "source": SOURCE, "checked": "2026-11-14", "status": "verified"},
        {"id": "google.screenshots.tablet10.count", "kind": "count", "applies": {"slots": ["tablet7", "tablet10"]},
         "min": 4, "severity": "error", "source": SOURCE, "checked": "2026-11-14", "status": "verified"},
        {"id": "google.graphics.feature.size", "kind": "size", "applies": {"slot": "featureGraphic"},
         "sizes": [[1024, 500]], "severity": "error", "source": SOURCE, "checked": "2026-11-14", "status": "verified"},
    ],
    "slots": {"$comment": "Play's image types", "phone": {"imageType": "phoneScreenshots"}},
}

APPLE = {
    "store": "apple",
    "rules": [
        {"id": "apple.keywords.length", "kind": "limit", "applies": {"field": "apple.keywords"}, "max": 100,
         "count": "bytes", "severity": "error", "source": "https://developer.apple.com/help/app-store-connect/",
         "checked": "2026-11-14", "status": "unverified"},
        {"id": "apple.keywords.count", "kind": "count", "applies": {"field": "apple.keywords"}, "min": 1},
        {"id": "apple.copyright.pattern", "kind": "pattern", "applies": {"field": "app.copyright"},
         "regex": "^\\d{4} ", "severity": "warning", "status": "verified"},
        {"id": "apple.name.case", "kind": "pattern", "applies": {"field": "apple.name"},
         "regex": "^sample", "flags": "i", "status": "verified"},
    ],
}


class RulesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.write("google", GOOGLE)
        self.write("apple", APPLE)
        self.google = rules.load("google", self.dir)
        self.apple = rules.load("apple", self.dir)

    def write(self, store, data):
        with open(os.path.join(self.dir, store + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)


class LoadTests(RulesTestCase):
    def test_loads_rules_and_slots(self):
        self.assertEqual(len(self.google), 7)
        self.assertEqual(self.google.store, "google")
        self.assertEqual(self.google.checked, "2026-11-14")
        self.assertEqual(self.google.slots, {"phone": {"imageType": "phoneScreenshots"}})
        self.assertEqual([r.id for r in self.google][0], "google.title.length")

    def test_get(self):
        r = self.google.get("google.title.length")
        self.assertEqual((r.kind, r.get("max"), r.source, r.checked), ("limit", 30, SOURCE, "2026-11-14"))
        self.assertIsNone(self.google.get("google.nothing"))

    def test_for_field_reads_field_fields_and_a_words_rules_fields(self):
        ids = [r.id for r in self.google.for_field("google.title")]
        self.assertEqual(ids, ["google.title.length", "google.words.price", "google.title.emoji_like"])
        self.assertEqual([r.id for r in self.google.for_field("description")], [])

    def test_for_slot(self):
        self.assertEqual([r.id for r in self.google.for_slot("tablet7")], ["google.screenshots.tablet10.count"])
        self.assertEqual([r.id for r in self.google.for_slot("phone")], ["google.screenshots.phone.count"])

    def test_by_kind(self):
        self.assertEqual(len(self.google.by_kind("count")), 2)

    def test_severity_of_an_unverified_rule_is_a_warning(self):
        self.assertEqual(self.google.get("google.title.length").severity, "error")
        observed = self.google.get("google.short.length")
        self.assertEqual((observed.declared_severity, observed.severity), ("error", "warning"))
        missing = self.apple.get("apple.keywords.count")
        self.assertEqual((missing.status, missing.severity), ("unverified", "warning"))

    def test_a_missing_file(self):
        with self.assertRaises(rules.RulesError) as cm:
            rules.load("steam", self.dir)
        self.assertIn("steam.json", str(cm.exception))

    def test_malformed_files_name_the_problem(self):
        def bad(data, expected):
            self.write("amazon", data)
            with self.assertRaises(rules.RulesError) as cm:
                rules.load("amazon", self.dir)
            self.assertIn("amazon.json", str(cm.exception))
            self.assertIn(expected, str(cm.exception))

        one = {"id": "amazon.title.length", "kind": "limit", "max": 1}
        bad({"rules": {}}, '"rules" list')
        bad({"store": "google", "rules": []}, "says it's for")
        bad({"rules": [dict(one, id="google.x")]}, "doesn't start with")
        bad({"rules": [one, one]}, "used twice")
        bad({"rules": [{"id": "amazon.x"}]}, "has no kind")
        bad({"rules": [dict(one, severity="fatal")]}, "severity")
        bad({"rules": [dict(one, status="maybe")]}, "status")
        bad({"rules": [dict(one, count="words")]}, "counts")

    def test_invalid_json_names_the_line(self):
        with open(os.path.join(self.dir, "itch.json"), "w") as f:
            f.write('{\n "rules": [\n  {"id": "itch.a",}\n ]\n}')
        with self.assertRaises(rules.RulesError) as cm:
            rules.load("itch", self.dir)
        self.assertIn("itch.json:3", str(cm.exception))


class RelaxTests(RulesTestCase):
    def test_relaxed_rules_are_left_out_and_reported(self):
        relax = [{"id": "google.screenshots.tablet10.count", "reason": "no tablet build yet"},
                 {"id": "apple.keywords.length", "reason": "another store's"},
                 "google.title.emoji_like"]
        out = rules.relaxed(self.google, relax)
        self.assertEqual(len(out), 5)
        self.assertIsNone(out.get("google.screenshots.tablet10.count"))
        self.assertEqual([(r.id, why) for r, why in out.relaxed_rules],
                         [("google.screenshots.tablet10.count", "no tablet build yet"), ("google.title.emoji_like", "")])
        self.assertEqual(out.unknown_relaxed, [])
        self.assertEqual(len(self.google), 7, "the original set is untouched")
        self.assertEqual(out.slots, self.google.slots)

    def test_unknown_ids_of_this_store_are_kept_for_the_report(self):
        out = rules.relaxed(self.google, [{"id": "google.title.lenght", "reason": "typo"}])
        self.assertEqual(out.unknown_relaxed, ["google.title.lenght"])
        self.assertEqual(len(out), 7)

    def test_nothing_to_relax(self):
        self.assertEqual(len(rules.relaxed(self.google, None)), 7)
        with self.assertRaises(ValueError):
            rules.relaxed(self.google, [{"reason": "no id"}])


class EvaluateTests(RulesTestCase):
    def test_limit_characters(self):
        r = self.google.get("google.title.length")
        self.assertEqual(rules.evaluate(r, "Sample Recipes: Meal Planner", "en-US google.title"), [])
        found = rules.evaluate(r, "Sample Recipes: The Meal Planner App", "en-US google.title")
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual((f.rule_id, f.severity, f.where, f.source, f.status),
                         ("google.title.length", "error", "en-US google.title", SOURCE, "verified"))
        self.assertIn("is 36 characters; the limit is 30", f.message)
        self.assertNotIn("unverified", f.message)

    def test_limit_graphemes_and_min_and_unverified_warning(self):
        r = self.google.get("google.short.length")
        family = "\U0001F468‍\U0001F469‍\U0001F467"
        self.assertEqual(rules.evaluate(r, family * 10, "w"), [], "10 graphemes, though 50 code points")
        found = rules.evaluate(r, "Too short", "w")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, "warning")
        self.assertIn("at least 10", found[0].message)
        self.assertIn("unverified rule: observed, checked 2026-11-14", found[0].message)

    def test_limit_bytes_joins_a_list_with_commas(self):
        r = self.apple.get("apple.keywords.length")
        self.assertEqual(rules.evaluate(r, ["recipes", "meal plan", "grocery"], "k"), [])
        found = rules.evaluate(r, ["é" * 30, "é" * 30], "k")   # 61 characters, 121 bytes
        self.assertIn("is 121 bytes; the limit is 100", found[0].message)

    def test_none_is_not_checked(self):
        self.assertEqual(rules.evaluate(self.google.get("google.title.length"), None, "w"), [])
        self.assertEqual(rules.evaluate(self.google.get("google.words.price"), None, "w"), [])

    def test_words(self):
        r = self.google.get("google.words.price")
        self.assertEqual(rules.evaluate(r, "Sample Recipes: Meal Planner", "w"), [])
        found = rules.evaluate(r, "The #1 FREE meal planner", "w")
        self.assertEqual(len(found), 1)
        self.assertIn('"free"', found[0].message)
        self.assertIn('"#1"', found[0].message)
        self.assertEqual(rules.evaluate(r, "freedom", "w"), [])

    def test_words_with_a_configs_extra_words(self):
        r = self.google.get("google.words.price")
        found = rules.check_words(r, "Now on sale", "w", extra_words=["sale"])
        self.assertIn('"sale"', found[0].message)
        found = rules.evaluate(r, ["meal plan", "free recipes"], "w")
        self.assertEqual(len(found), 1)

    def test_pattern_forbid(self):
        r = self.google.get("google.title.emoji_like")
        self.assertEqual(rules.evaluate(r, "Sample Recipes!", "w"), [])
        found = rules.evaluate(r, "Sample Recipes!!!", "w")
        self.assertEqual(found[0].severity, "warning")
        self.assertIn("'!!!'", found[0].message)

    def test_pattern_required_and_flags(self):
        r = self.apple.get("apple.copyright.pattern")
        self.assertEqual(rules.evaluate(r, "2026 Example Studio", "c"), [])
        self.assertIn("doesn't match", rules.evaluate(r, "Example Studio", "c")[0].message)
        r = self.apple.get("apple.name.case")
        self.assertEqual(rules.evaluate(r, "SAMPLE Recipes", "n"), [])

    def test_count(self):
        r = self.google.get("google.screenshots.phone.count")
        self.assertEqual(rules.evaluate(r, ["a.png", "b.png"], "en-US phone"), [])
        few = rules.evaluate(r, ["a.png"], "en-US phone")
        self.assertIn("has 1 pictures; at least 2 are needed", few[0].message)
        many = rules.evaluate(r, 9, "en-US phone")
        self.assertIn("at most 8", many[0].message)
        items = rules.evaluate(self.apple.get("apple.keywords.count"), [], "k")
        self.assertIn("has 0 items", items[0].message)

    def test_other_kinds_are_the_callers(self):
        with self.assertRaises(ValueError):
            rules.evaluate(self.google.get("google.graphics.feature.size"), "x.png", "w")

    def test_finding_for_a_callers_check(self):
        r = self.google.get("google.graphics.feature.size")
        f = rules.finding(r, "graphics/feature.png", "is 1000x500, not 1024x500")
        self.assertEqual(f, rules.Finding("google.graphics.feature.size", "error", "graphics/feature.png",
                                          "is 1000x500, not 1024x500", SOURCE, "verified"))


if __name__ == "__main__":
    unittest.main()
