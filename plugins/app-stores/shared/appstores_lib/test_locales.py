"""Tests for appstores_lib.locales (stdlib unittest)."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import locales  # noqa: E402


class TableTests(unittest.TestCase):
    def test_tables_hold_the_well_known_codes(self):
        for code in ("en-US", "en-GB", "de-DE", "zh-Hans", "zh-Hant", "pt-BR", "es-MX", "ar-SA", "he", "no", "ja"):
            self.assertIn(code, locales.APPLE)
        for code in ("en-US", "de-DE", "zh-CN", "zh-TW", "iw-IL", "no-NO", "fil", "es-419", "ja-JP", "ko-KR"):
            self.assertIn(code, locales.GOOGLE)
        self.assertGreaterEqual(len(locales.APPLE), 39)
        self.assertGreaterEqual(len(locales.GOOGLE), 80)

    def test_codes_are_written_canonically(self):
        for code in list(locales.APPLE) + list(locales.GOOGLE):
            self.assertEqual(locales.canonical(code), code)

    def test_the_tables_say_when_to_check_them_again(self):
        self.assertIn("2026-11-14", locales.__doc__)
        self.assertTrue(locales.APPLE_ADDED_2025 <= set(locales.APPLE))


class CanonicalTests(unittest.TestCase):
    def test_case_and_separators(self):
        self.assertEqual(locales.canonical("en_us"), "en-US")
        self.assertEqual(locales.canonical("ZH-hant-hk"), "zh-Hant-HK")
        self.assertEqual(locales.canonical("es-419"), "es-419")

    def test_malformed(self):
        for bad in ("", "e", "en--US", "en US", None, 5):
            with self.assertRaises(locales.LocaleError):
                locales.canonical(bad)


class AppleTests(unittest.TestCase):
    def test_exact_codes(self):
        for code in locales.APPLE:
            self.assertEqual(locales.apple(code), code)

    def test_mapping(self):
        cases = {
            "en": "en-US", "en-us": "en-US", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "pt": "pt-BR",
            "ja-JP": "ja", "ko-KR": "ko", "sv-SE": "sv", "ar": "ar-SA", "he-IL": "he", "iw": "he",
            "nb": "no", "nb-NO": "no", "no-NO": "no",
            "zh": "zh-Hans", "zh-CN": "zh-Hans", "zh-SG": "zh-Hans", "zh-Hans-CN": "zh-Hans",
            "zh-TW": "zh-Hant", "zh-HK": "zh-Hant", "zh-Hant-HK": "zh-Hant",
            "es-419": "es-MX", "es-AR": "es-MX", "es-US": "es-MX", "in": "id",
        }
        for given, expected in cases.items():
            self.assertEqual(locales.apple(given), expected, given)

    def test_what_apple_does_not_have(self):
        with self.assertRaises(locales.LocaleError) as cm:
            locales.apple("en-NZ")
        self.assertIn("en-AU", str(cm.exception), "it suggests the variants there are")
        for code in ("fil", "sw", "is-IS", "fr-BE"):
            with self.assertRaises(locales.LocaleError):
                locales.apple(code)


class GoogleTests(unittest.TestCase):
    def test_exact_codes(self):
        for code in locales.GOOGLE:
            self.assertEqual(locales.google(code), code)

    def test_mapping(self):
        cases = {
            "zh-Hans": "zh-CN", "zh": "zh-CN", "zh-Hant": "zh-TW", "zh-Hant-HK": "zh-HK", "zh-MO": "zh-HK",
            "he": "iw-IL", "he-IL": "iw-IL", "iw": "iw-IL",
            "nb": "no-NO", "no": "no-NO", "nb-NO": "no-NO",
            "tl": "fil", "fil-PH": "fil",
            "ja": "ja-JP", "ko": "ko-KR", "de": "de-DE", "en": "en-US", "pt": "pt-BR", "es": "es-ES",
            "es-MX": "es-419", "es-CO": "es-419", "ar-SA": "ar", "ar-EG": "ar", "cs": "cs-CZ", "sv": "sv-SE",
            "tr": "tr-TR", "fi": "fi-FI",
        }
        for given, expected in cases.items():
            self.assertEqual(locales.google(given), expected, given)

    def test_what_play_does_not_have(self):
        for code in ("en-NZ", "fr-CH", "xx", "pt-AO"):
            with self.assertRaises(locales.LocaleError):
                locales.google(code)


class RoundTripTests(unittest.TestCase):
    def test_store_codes_come_back(self):
        for code in locales.APPLE:
            self.assertEqual(locales.apple(locales.from_apple(code)), code)
        for code in locales.GOOGLE:
            self.assertEqual(locales.google(locales.from_google(code)), code)

    def test_back_to_bcp47(self):
        self.assertEqual(locales.from_google("iw-IL"), "he-IL")
        self.assertEqual(locales.from_google("zh-CN"), "zh-Hans")
        self.assertEqual(locales.from_google("zh-TW"), "zh-Hant")
        self.assertEqual(locales.from_apple("zh-Hans"), "zh-Hans")
        with self.assertRaises(locales.LocaleError):
            locales.from_apple("en")
        with self.assertRaises(locales.LocaleError):
            locales.from_google("he")


class StoreCodesTests(unittest.TestCase):
    def test_maps_a_configs_locales(self):
        self.assertEqual(locales.store_codes("google", ["en-US", "zh-Hans", "he"]),
                         {"en-US": "en-US", "zh-Hans": "zh-CN", "he": "iw-IL"})
        self.assertEqual(locales.for_store("apple", "nb"), "no")

    def test_two_locales_becoming_one_is_an_error(self):
        with self.assertRaises(locales.LocaleError) as cm:
            locales.store_codes("apple", ["de-DE", "de-AT"])
        self.assertIn("de-AT", str(cm.exception))
        with self.assertRaises(locales.LocaleError):
            locales.store_codes("google", ["zh-Hans", "zh-CN"])

    def test_unknown_store(self):
        with self.assertRaises(locales.LocaleError):
            locales.for_store("amazon", "en-US")


if __name__ == "__main__":
    unittest.main()
