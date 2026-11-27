"""Tests for design_color.py: OKLCH and sRGB conversions, WCAG contrast, mixing and the JavaScript-compatible
rounding the generators rely on.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_color as dc  # noqa: E402

WHITE = (1.0, 0.0, 0.0)
BLACK = (0.0, 0.0, 0.0)


class Conversions(unittest.TestCase):
    def test_known_hex_values_round_trip(self):
        for hx in ("#ffffff", "#000000", "#ff0000", "#00ff00", "#0000ff", "#18181b", "#007aff", "#3584e4",
                   "#7f7f7f", "#123456"):
            self.assertEqual(dc.to_hex(dc.parse_hex(hx)), hx, hx)

    def test_red_in_oklch(self):
        L, C, H, A = dc.parse_hex("#ff0000")
        self.assertAlmostEqual(L, 0.628, places=3)
        self.assertAlmostEqual(C, 0.2577, places=3)
        self.assertAlmostEqual(H, 29.23, places=1)
        self.assertEqual(A, 1.0)

    def test_short_and_alpha_hex(self):
        self.assertEqual(dc.to_hex(dc.parse_hex("#abc")), "#aabbcc")
        c = dc.parse_hex("#00000080")
        self.assertAlmostEqual(c[3], 128 / 255.0)
        self.assertEqual(dc.to_hex(c), "#00000080")

    def test_greys_have_no_hue(self):
        for hx in ("#ffffff", "#7f7f7f", "#1e1e1e"):
            L, C, H, _ = dc.parse_hex(hx)
            self.assertEqual((C, H), (0.0, 0.0), hx)

    def test_bad_hex_is_refused(self):
        for bad in ("#12", "#12345", "red", "#gggggg", "123456"):
            with self.assertRaises(ValueError):
                dc.parse_hex(bad)

    def test_from_value_takes_every_written_form(self):
        self.assertEqual(dc.from_value([0.5, 0.1, 200]), (0.5, 0.1, 200, 1.0))
        self.assertEqual(dc.from_value([0, 0, 0, 0.08]), (0, 0, 0, 0.08))
        self.assertEqual(dc.to_hex(dc.from_value("#0a84ff")), "#0a84ff")

    def test_css_form(self):
        self.assertEqual(dc.to_css((0.235, 0.014, 41)), "oklch(0.235 0.014 41)")
        self.assertEqual(dc.to_css((1.0, 0.0, 0)), "oklch(1.000 0.000 0)")
        self.assertEqual(dc.to_css((0, 0, 0, 0.08)), "oklch(0.000 0.000 0 / 0.08)")
        self.assertEqual(dc.to_css((0.5, 0.1, 41.900000000000006)), "oklch(0.500 0.100 41.9)")


class Gamut(unittest.TestCase):
    def test_in_and_out(self):
        self.assertFalse(dc.out_of_gamut((0.55, 0.15, 41)))
        self.assertTrue(dc.out_of_gamut((0.8, 0.35, 140)))
        self.assertTrue(dc.out_of_gamut((0.65, 0.15, 62)))  # a plausible amber that clips
        self.assertFalse(dc.out_of_gamut(WHITE))
        self.assertFalse(dc.out_of_gamut(BLACK))

    def test_clipped_hex_is_still_a_hex(self):
        self.assertRegex(dc.to_hex((0.8, 0.35, 140)), r"^#[0-9a-f]{6}$")


class Contrast(unittest.TestCase):
    def test_black_on_white_is_21(self):
        self.assertEqual(dc.to_fixed(dc.contrast_ratio(BLACK, WHITE), 2), "21.00")
        self.assertAlmostEqual(dc.contrast_ratio(WHITE, WHITE), 1.0)

    def test_order_does_not_matter(self):
        a, b = dc.parse_hex("#007aff"), WHITE
        self.assertAlmostEqual(dc.contrast_ratio(a, b), dc.contrast_ratio(b, a))

    def test_known_ratios(self):
        # White on the macOS system blue is the classic near miss.
        self.assertEqual(dc.to_fixed(dc.contrast_ratio(dc.parse_hex("#007aff"), WHITE), 2), "4.02")
        self.assertEqual(dc.to_fixed(dc.contrast_ratio(dc.parse_hex("#767676"), WHITE), 2), "4.54")

    def test_alpha_composites_over_the_background(self):
        half_black = (0.0, 0.0, 0.0, 0.5)
        rgb = dc.composite(half_black, WHITE)
        self.assertAlmostEqual(rgb[0], 0.5)
        mid = dc.contrast_over(half_black, WHITE)
        self.assertGreater(mid, 1.0)
        self.assertLess(mid, dc.contrast_ratio(BLACK, WHITE))
        self.assertAlmostEqual(mid, dc.ratio(dc.luminance_rgb((0.5, 0.5, 0.5)), 1.0))
        # Fully transparent is the background itself.
        self.assertAlmostEqual(dc.contrast_over((0.0, 0.0, 0.0, 0.0), WHITE), 1.0)
        # Opaque colours aren't composited.
        self.assertAlmostEqual(dc.contrast_over(BLACK, WHITE), dc.contrast_ratio(BLACK, WHITE))


class Mixing(unittest.TestCase):
    def test_mix_into_a_grey_keeps_the_coloured_hue(self):
        # The regression this rule exists for: dark ok-tint once came out at hue 27, a green pill on red.
        moss, coal = (0.74, 0.145, 152), (0.185, 0.0, 0)
        L, C, H, A = dc.mix(moss, coal, 0.18)
        self.assertAlmostEqual(H, 152)
        self.assertAlmostEqual(L, 0.185 + (0.74 - 0.185) * 0.18)
        self.assertAlmostEqual(C, 0.145 * 0.18)
        # And the other way round: a grey mixed into a colour keeps that colour's hue.
        self.assertAlmostEqual(dc.mix(coal, moss, 0.5)[2], 152)

    def test_two_greys_take_the_ground_hue(self):
        self.assertEqual(dc.mix((0.5, 0.0, 90), (0.9, 0.001, 30), 0.5)[2], 30)

    def test_hue_takes_the_short_way_round(self):
        self.assertAlmostEqual(dc.mix((0.5, 0.1, 350), (0.5, 0.1, 10), 0.5)[2] % 360, 0)
        self.assertAlmostEqual(dc.mix((0.5, 0.1, 10), (0.5, 0.1, 350), 0.25)[2], 355)
        self.assertAlmostEqual(dc.mix((0.5, 0.1, 100), (0.5, 0.1, 50), 0.5)[2], 75)

    def test_alpha_mixes_linearly(self):
        self.assertAlmostEqual(dc.mix((0, 0, 0, 0.2), (0, 0, 0, 1.0), 0.5)[3], 0.6)

    def test_hue_distance(self):
        self.assertEqual(dc.hue_distance(10, 350), 20)
        self.assertEqual(dc.hue_distance(350, 10), 20)
        self.assertEqual(dc.hue_distance(0, 180), 180)
        self.assertEqual(dc.hue_distance(41, 13), 28)
        self.assertEqual(dc.hue_distance(720, 0), 0)


class JavaScriptRounding(unittest.TestCase):
    def test_to_fixed_rounds_exact_halves_up(self):
        self.assertEqual(dc.to_fixed(0.125, 2), "0.13")  # Python's round() would say 0.12
        self.assertEqual(dc.to_fixed(0.5625, 3), "0.563")
        self.assertEqual(dc.to_fixed(1.0, 3), "1.000")
        self.assertEqual(dc.to_fixed(4.5249, 2), "4.52")

    def test_js_round(self):
        self.assertEqual(dc.js_round(2.5), 3)
        self.assertEqual(dc.js_round(0.5), 1)
        self.assertEqual(dc.js_round(-0.5), 0)
        self.assertEqual(dc.js_round(127.49), 127)

    def test_js_number(self):
        self.assertEqual(dc.js_number(1.0), "1")
        self.assertEqual(dc.js_number(1.45), "1.45")
        self.assertEqual(dc.js_number(400), "400")
        self.assertEqual(dc.js_number(0.00005), "0.00005")
        with self.assertRaises(TypeError):
            dc.js_number(True)

    def test_short_number(self):
        self.assertEqual(dc.short_number(152.0), "152")
        self.assertEqual(dc.short_number(0.08), "0.08")
        self.assertEqual(dc.short_number(41), "41")
        self.assertEqual(dc.short_number(-0.0001), "0")


if __name__ == "__main__":
    unittest.main()
