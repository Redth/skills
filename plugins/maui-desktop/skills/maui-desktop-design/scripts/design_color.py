"""design_color.py: the colour maths behind tokens.py (OKLCH, sRGB, WCAG contrast). Stdlib only.

A colour here is a tuple ``(L, C, H, A)``: OKLCH lightness 0-1, chroma >= 0, hue in degrees and alpha 0-1
(``A`` may be left off; it means 1). The functions:

    parse_hex("#18181b")          -> (L, C, H, A), through linear sRGB and OKLab
    oklch_to_srgb(color)          -> gamma-encoded sRGB channels 0-1, unclamped (out of gamut shows as <0 or >1)
    out_of_gamut(color)           -> True when a channel falls outside sRGB by more than 0.001
    to_hex(color)                 -> "#rrggbb", or "#rrggbbaa" when the colour has alpha
    to_css(color)                 -> "oklch(0.235 0.014 41)", or "oklch(… / 0.08)" with alpha
    relative_luminance(color), contrast_ratio(a, b)        WCAG 2 definitions
    composite(fg, bg)             -> the sRGB triple of ``fg`` (with its alpha) painted over an opaque ``bg``
    mix(a, b, amount)             -> ``amount`` of ``a`` into ``b`` in OKLCH (the hue rules below)
    hue_distance(h1, h2)          -> the shortest angle between two hues, 0-180

Mixing hue: a grey (chroma < 0.002) has no hue. Its H is written as 0 because the field has to hold
something, not because the colour is red, so interpolating towards it would drag the result round the wheel
towards red (a dark success tint that came out at hue 27: a green pill on a red ground). So a grey end
contributes no hue and the other end's is kept; where both ends have a hue the mix takes the short way round
(350 to 10 passes through 0, not through green).

Rounding follows JavaScript's ``Math.round`` and ``Number.prototype.toFixed`` (halves go up), so the numbers
match the Node pipeline this was ported from.
"""

from __future__ import annotations

import decimal
import math
import re

GREY_CHROMA = 0.002
GAMUT_EPSILON = 0.001

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


# ------------------------------------------------------------------ numbers


def js_round(x):
    """``Math.round``: the nearest integer, halves rounded up (towards +infinity)."""
    return int(math.floor(x + 0.5))


def to_fixed(x, digits):
    """``Number.prototype.toFixed``: ``x`` with exactly ``digits`` decimals, an exact half rounded away from 0."""
    q = decimal.Decimal(1).scaleb(-digits)
    return format(decimal.Decimal(x).quantize(q, rounding=decimal.ROUND_HALF_UP), "f")


def js_number(x):
    """A number as JavaScript prints it: ``41`` not ``41.0``, ``1.45``, no exponent for ordinary sizes."""
    if isinstance(x, bool):
        raise TypeError("a boolean isn't a number here")
    if isinstance(x, int):
        return str(x)
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    text = repr(x)
    if "e" in text and abs(x) >= 1e-6:
        text = format(decimal.Decimal(text), "f")
    return text


def short_number(x, digits=3):
    """``x`` rounded to ``digits`` decimals with trailing zeros dropped: ``152``, ``41.9``, ``0.08``."""
    if isinstance(x, int) and not isinstance(x, bool):
        return str(x)
    text = to_fixed(x, digits)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text


def clamp01(v):
    return min(1.0, max(0.0, v))


# ------------------------------------------------------------------ conversions


def _parts(color):
    if len(color) == 3:
        return color[0], color[1], color[2], 1.0
    return color[0], color[1], color[2], color[3]


def alpha(color):
    """The colour's alpha (1 when it has none)."""
    return _parts(color)[3]


def oklch_to_oklab(color):
    L, C, H, _ = _parts(color)
    h = H * math.pi / 180.0
    return L, C * math.cos(h), C * math.sin(h)


def oklab_to_linear_srgb(L, a, b):
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _cbrt(x):
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def linear_srgb_to_oklab(r, g, b):
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = _cbrt(l), _cbrt(m), _cbrt(s)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_oklch(L, a, b, alpha_=1.0):
    C = math.hypot(a, b)
    if C < 1e-4:  # a grey: its hue is noise, write it as 0
        return (L, 0.0, 0.0, alpha_)
    H = math.degrees(math.atan2(b, a)) % 360.0
    return (L, C, H, alpha_)


def gamma(v):
    """Linear light to the sRGB transfer curve (not clamped: negative stays negative)."""
    return 12.92 * v if v <= 0.0031308 else 1.055 * math.pow(max(v, 0.0), 1 / 2.4) - 0.055


def linearize(v):
    """An sRGB channel (clamped to 0-1) back to linear light."""
    c = clamp01(v)
    return c / 12.92 if c <= 0.04045 else math.pow((c + 0.055) / 1.055, 2.4)


def oklch_to_srgb(color):
    """OKLCH to gamma-encoded sRGB ``(r, g, b)`` in 0-1. Not clamped, so an out-of-gamut colour shows."""
    lr, lg, lb = oklab_to_linear_srgb(*oklch_to_oklab(color))
    return gamma(lr), gamma(lg), gamma(lb)


def srgb_to_oklch(r, g, b, alpha_=1.0):
    """Gamma-encoded sRGB channels (0-1) to an OKLCH colour."""
    return oklab_to_oklch(*linear_srgb_to_oklab(linearize(r), linearize(g), linearize(b)), alpha_=alpha_)


def is_hex(text):
    return isinstance(text, str) and bool(_HEX.match(text))


def parse_hex(text):
    """``#rgb``, ``#rrggbb`` or ``#rrggbbaa`` to an OKLCH colour. Raises ``ValueError`` for anything else."""
    if not is_hex(text):
        raise ValueError("%r isn't a #rgb, #rrggbb or #rrggbbaa colour" % (text,))
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    channels = [int(digits[i:i + 2], 16) / 255.0 for i in range(0, len(digits), 2)]
    a = channels[3] if len(channels) == 4 else 1.0
    return srgb_to_oklch(channels[0], channels[1], channels[2], a)


def from_value(value):
    """A primitive as written in tokens.json (``[L, C, H]``, ``[L, C, H, A]`` or a hex string) to a colour."""
    if isinstance(value, str):
        return parse_hex(value)
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        parts = tuple(value)
        if len(parts) == 3:
            parts = parts + (1.0,)
        return parts
    raise ValueError("a colour is [L, C, H], [L, C, H, A] or a hex string, not %r" % (value,))


def out_of_gamut(color, epsilon=GAMUT_EPSILON):
    """True when the colour falls outside sRGB: a silent clip that would ship a different colour."""
    return any(c < -epsilon or c > 1 + epsilon for c in oklch_to_srgb(color))


def srgb_bytes(color):
    """The colour as 0-255 sRGB bytes ``(r, g, b, a)``, clamped and rounded as JavaScript rounds."""
    r, g, b = oklch_to_srgb(color)
    return (js_round(clamp01(r) * 255), js_round(clamp01(g) * 255), js_round(clamp01(b) * 255),
            js_round(clamp01(alpha(color)) * 255))


def to_hex(color):
    """``#rrggbb``, or ``#rrggbbaa`` when the colour isn't opaque."""
    r, g, b, a = srgb_bytes(color)
    text = "#%02x%02x%02x" % (r, g, b)
    if alpha(color) < 1:
        text += "%02x" % a
    return text


def to_css(color):
    """``oklch(L C H)`` with L and C to 3 decimals; ``oklch(L C H / A)`` when the colour has alpha."""
    L, C, H, A = _parts(color)
    text = "oklch(%s %s %s" % (to_fixed(L, 3), to_fixed(C, 3), short_number(H))
    if A < 1:
        text += " / %s" % short_number(A)
    return text + ")"


# ------------------------------------------------------------------ contrast


def luminance_rgb(rgb):
    """WCAG relative luminance of gamma-encoded sRGB channels (0-1)."""
    r, g, b = (linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def relative_luminance(color):
    """WCAG relative luminance of a colour, ignoring its alpha."""
    return luminance_rgb(oklch_to_srgb(color))


def ratio(la, lb):
    """The WCAG contrast ratio of two relative luminances, 1-21."""
    hi, lo = (la, lb) if la > lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def contrast_ratio(a, b):
    """The WCAG contrast ratio of two colours, ignoring alpha (see ``composite`` for a see-through one)."""
    return ratio(relative_luminance(a), relative_luminance(b))


def composite(fg, bg):
    """``fg`` painted over an opaque ``bg``, as a browser blends: per sRGB channel, by ``fg``'s alpha."""
    a = clamp01(alpha(fg))
    top = [clamp01(c) for c in oklch_to_srgb(fg)]
    under = [clamp01(c) for c in oklch_to_srgb(bg)]
    return tuple(t * a + u * (1 - a) for t, u in zip(top, under))


def contrast_over(fg, bg):
    """The contrast of ``fg`` (composited over ``bg`` when it has alpha) against ``bg``."""
    if alpha(fg) < 1:
        return ratio(luminance_rgb(composite(fg, bg)), relative_luminance(bg))
    return contrast_ratio(fg, bg)


# ------------------------------------------------------------------ mixing and hue


def is_grey(color):
    return color[1] < GREY_CHROMA


def mix(a, b, amount):
    """``amount`` (0-1) of ``a`` into ``b``, in OKLCH. A grey end contributes no hue; otherwise the hue takes
    the short way round the wheel. Alpha mixes linearly."""
    aL, aC, aH, aA = _parts(a)
    bL, bC, bH, bA = _parts(b)
    aH %= 360.0
    bH %= 360.0
    if bC < GREY_CHROMA:
        hue = bH if aC < GREY_CHROMA else aH
    elif aC < GREY_CHROMA:
        hue = bH
    else:
        delta = ((aH - bH + 540.0) % 360.0) - 180.0
        hue = (bH + delta * amount + 360.0) % 360.0
    return (bL + (aL - bL) * amount, bC + (aC - bC) * amount, hue, bA + (aA - bA) * amount)


def hue_distance(h1, h2):
    """The shortest angular distance between two hues, 0-180."""
    d = abs((h1 - h2) % 360.0)
    return 360.0 - d if d > 180 else d
