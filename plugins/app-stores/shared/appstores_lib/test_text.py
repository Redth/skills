"""Tests for appstores_lib.text (stdlib unittest)."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import text  # noqa: E402

FAMILY = "\U0001F468‍\U0001F469‍\U0001F467"          # man ZWJ woman ZWJ girl
THUMBS_MEDIUM = "\U0001F44D\U0001F3FD"                         # thumbs up, medium skin tone
CANADA = "\U0001F1E8\U0001F1E6"
FRANCE = "\U0001F1EB\U0001F1F7"
ENGLAND = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
HEART = "❤️"
KEYCAP_ONE = "1️⃣"


class CountTests(unittest.TestCase):
    def test_characters_are_code_points(self):
        self.assertEqual(text.count("Sample Recipes", "characters"), 14)
        self.assertEqual(text.count("é", "characters"), 2)

    def test_bytes_are_utf8(self):
        self.assertEqual(text.count("abc", "bytes"), 3)
        self.assertEqual(text.count("é", "bytes"), 2)
        self.assertEqual(text.count("\U0001F355", "bytes"), 4)

    def test_none_counts_as_zero_and_unknown_ways_raise(self):
        self.assertEqual(text.count(None, "graphemes"), 0)
        with self.assertRaises(ValueError):
            text.count("a", "words")


class GraphemeTests(unittest.TestCase):
    def g(self, s):
        return text.count(s, "graphemes")

    def test_plain_text(self):
        self.assertEqual(self.g("Plan meals"), 10)
        self.assertEqual(self.g(""), 0)

    def test_combining_marks_join_their_base(self):
        self.assertEqual(self.g("Crème"), 5)                 # Mn
        self.assertEqual(self.g("ạ́"), 1)                # two marks
        self.assertEqual(self.g("कि"), 1)                 # Devanagari ki: spacing mark (Mc)
        self.assertEqual(self.g("a⃝"), 1)                      # enclosing circle (Me)

    def test_variation_selectors(self):
        self.assertEqual(self.g(HEART), 1)                          # VS16
        self.assertEqual(self.g("❤︎"), 1)                 # VS15
        self.assertEqual(self.g(KEYCAP_ONE), 1)                     # digit, VS16, keycap (Me)

    def test_zwj_sequences(self):
        self.assertEqual(self.g(FAMILY), 1)
        self.assertEqual(self.g(FAMILY + FAMILY), 2)
        self.assertEqual(self.g("\U0001F469‍\U0001F373"), 1)   # woman cook
        self.assertEqual(self.g("a‍b"), 2, "a ZWJ between letters doesn't join them")

    def test_skin_tone_modifiers(self):
        self.assertEqual(self.g(THUMBS_MEDIUM), 1)
        self.assertEqual(self.g("\U0001F469\U0001F3FD‍\U0001F373"), 1)

    def test_regional_indicator_pairs(self):
        self.assertEqual(self.g(CANADA), 1)
        self.assertEqual(self.g(CANADA + FRANCE), 2)
        self.assertEqual(self.g(CANADA + "\U0001F1EB"), 2, "an odd indicator stands alone")
        self.assertEqual(text.graphemes(CANADA + FRANCE), [CANADA, FRANCE])

    def test_tag_sequences(self):
        self.assertEqual(self.g(ENGLAND), 1)
        self.assertEqual(self.g(ENGLAND + " " + CANADA), 3)

    def test_crlf_and_controls(self):
        self.assertEqual(self.g("a\r\nb"), 3)
        self.assertEqual(self.g("\ń"), 2, "a mark after a control doesn't join it")

    def test_hangul(self):
        self.assertEqual(self.g("각"), 1)          # conjoining jamo
        self.assertEqual(self.g("한국"), 2)                 # precomposed syllables

    def test_graphemes_reassemble_the_string(self):
        s = "Plan " + FAMILY + " meals " + ENGLAND + HEART + "é"
        self.assertEqual("".join(text.graphemes(s)), s)


class EmojiTests(unittest.TestCase):
    def test_plain_text_has_none(self):
        for s in ("Sample Recipes", "Crème brûlée", "レシピ", "مرحبا", "20°C", "a → b",
                  "100% fresh", ""):
            self.assertFalse(text.has_emoji(s), s)

    def test_emoji_are_found(self):
        for s in ("Pasta \U0001F35D", FAMILY, THUMBS_MEDIUM, CANADA, ENGLAND, HEART, KEYCAP_ONE, "☕",
                  "\U0001F600"):
            self.assertTrue(text.has_emoji(s), s)

    def test_text_default_symbols_need_vs16(self):
        self.assertFalse(text.has_emoji("Example Studio©"))
        self.assertFalse(text.has_emoji("Sample Recipes™"))
        self.assertTrue(text.has_emoji("©️"))
        self.assertFalse(text.has_emoji("☕︎"), "VS15 asks for the text form")

    def test_find_emoji_returns_whole_graphemes(self):
        self.assertEqual(text.find_emoji("Hi " + FAMILY + " and " + CANADA + "!"), [FAMILY, CANADA])


class FindWordsTests(unittest.TestCase):
    def test_whole_words_case_insensitive(self):
        self.assertEqual(text.find_words("Totally FREE recipes", ["free"]), ["free"])
        self.assertEqual(text.find_words("Free!", ["free"]), ["free"])
        self.assertEqual(text.find_words("freedom to cook", ["free"]), [])
        self.assertEqual(text.find_words("carefree", ["free"]), [])

    def test_symbol_entries_match_as_written(self):
        self.assertEqual(text.find_words("The #1 recipe app", ["#1"]), ["#1"])
        self.assertEqual(text.find_words("Rated#1!", ["#1"]), ["#1"])
        self.assertEqual(text.find_words("#10 in food", ["#1"]), [])
        self.assertEqual(text.find_words("Only $0.99 today", ["$0.99"]), ["$0.99"])
        self.assertEqual(text.find_words("100% natural", ["100%"]), ["100%"])
        self.assertEqual(text.find_words("1100% natural", ["100%"]), [])

    def test_several_words_match_across_spaces(self):
        self.assertEqual(text.find_words("Start a free   trial", ["free trial"]), ["free trial"])
        self.assertEqual(text.find_words("free, trial", ["free trial"]), [])

    def test_scripts_without_spaces_match_anywhere(self):
        self.assertEqual(text.find_words("完全免费下载", ["免费"]), ["免费"])

    def test_order_and_duplicates(self):
        self.assertEqual(text.find_words("best free app", ["free", "best", "free", "", "sale"]), ["free", "best"])
        self.assertEqual(text.find_words("", ["free"]), [])
        self.assertEqual(text.find_words(None, ["free"]), [])

    def test_regex_characters_are_literal(self):
        self.assertEqual(text.find_words("a.b", ["a.b"]), ["a.b"])
        self.assertEqual(text.find_words("axb", ["a.b"]), [])


if __name__ == "__main__":
    unittest.main()
