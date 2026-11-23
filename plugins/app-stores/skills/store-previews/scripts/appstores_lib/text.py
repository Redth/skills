"""Counting text the way the stores do, finding emoji, and matching whole words.

Graphemes (user-perceived characters) are found without Unicode's break-property data files: a pragmatic
subset of UAX #29 that keeps together a base and its combining marks (``unicodedata``'s Mn, Me and Mc, and
anything with a combining class), variation selectors, emoji skin-tone modifiers, ZWJ sequences of emoji,
regional-indicator pairs (flags), tag sequences (subdivision flags such as England's), CR LF and Hangul
syllables made of conjoining jamo. That covers what a store listing holds; it doesn't attempt Indic conjuncts
or prepended marks.
"""

from __future__ import annotations

import re
import unicodedata

ZWJ = 0x200D
ZWNJ = 0x200C
VS15 = 0xFE0E
VS16 = 0xFE0F
KEYCAP = 0x20E3

# Characters that are pictographic (UTS #51's Extended_Pictographic, condensed into ranges).
_PICTOGRAPHIC = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122),
    (0x2139, 0x2139), (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328),
    (0x2388, 0x2388), (0x23CF, 0x23CF), (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2),
    (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0), (0x25FB, 0x25FE), (0x2600, 0x27BF),
    (0x2934, 0x2935), (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55),
    (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
    (0x1F000, 0x1F0FF), (0x1F10D, 0x1F10F), (0x1F12F, 0x1F12F), (0x1F16C, 0x1F171), (0x1F17E, 0x1F17F),
    (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1AD, 0x1F1E5), (0x1F201, 0x1F20F), (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F), (0x1F232, 0x1F23A), (0x1F23C, 0x1F23F), (0x1F249, 0x1F3FA), (0x1F400, 0x1F53D),
    (0x1F546, 0x1F64F), (0x1F680, 0x1F6FF), (0x1F774, 0x1F77F), (0x1F7D5, 0x1F7FF), (0x1F80C, 0x1F80F),
    (0x1F848, 0x1F84F), (0x1F85A, 0x1F85F), (0x1F888, 0x1F88F), (0x1F8AE, 0x1F8FF), (0x1F90C, 0x1F93A),
    (0x1F93C, 0x1F945), (0x1F947, 0x1FAFF), (0x1FC00, 0x1FFFD),
)

# Characters drawn as text by default (they're emoji only with VS16 after them).
_TEXT_DEFAULT = frozenset([0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299])

# Scripts written without spaces between words: whole-word matching can't use word boundaries there.
_NO_SPACE_SCRIPTS = (
    (0x0E00, 0x0EFF),    # Thai, Lao
    (0x1000, 0x109F),    # Myanmar
    (0x1780, 0x17FF),    # Khmer
    (0x2E80, 0x2FDF),    # CJK radicals
    (0x3040, 0x30FF),    # Hiragana, Katakana
    (0x3100, 0x312F),    # Bopomofo
    (0x31F0, 0x31FF),    # Katakana extensions
    (0x3400, 0x4DBF),    # CJK extension A
    (0x4E00, 0x9FFF),    # CJK unified ideographs
    (0xF900, 0xFAFF),    # CJK compatibility ideographs
    (0xFF66, 0xFF9F),    # half-width Katakana
    (0x20000, 0x3134F),  # CJK extensions B onwards
)


def _in(ranges, cp):
    for lo, hi in ranges:
        if cp < lo:
            return False
        if cp <= hi:
            return True
    return False


def is_pictographic(ch):
    """True if the character is pictographic (an emoji base, whether or not it's drawn as one by default)."""
    return _in(_PICTOGRAPHIC, ord(ch))


def _is_regional(cp):
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_skin_tone(cp):
    return 0x1F3FB <= cp <= 0x1F3FF


def _is_tag(cp):
    return 0xE0020 <= cp <= 0xE007F


def _is_variation_selector(cp):
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def _is_extend(ch):
    """True for characters that never start a grapheme: they join the one before."""
    cp = ord(ch)
    if cp in (ZWJ, ZWNJ) or _is_variation_selector(cp) or _is_skin_tone(cp) or _is_tag(cp):
        return True
    if unicodedata.combining(ch):
        return True
    return unicodedata.category(ch) in ("Mn", "Me", "Mc")


def _is_control(ch):
    cp = ord(ch)
    if cp in (ZWJ, ZWNJ) or _is_tag(cp):
        return False
    return unicodedata.category(ch) in ("Cc", "Zl", "Zp", "Cf")


# Hangul conjoining jamo: leading (L), vowel (V), trailing (T) and precomposed syllables (LV, LVT).
def _hangul(cp):
    if 0x1100 <= cp <= 0x115F or 0xA960 <= cp <= 0xA97C:
        return "L"
    if 0x1160 <= cp <= 0x11A7 or 0xD7B0 <= cp <= 0xD7C6:
        return "V"
    if 0x11A8 <= cp <= 0x11FF or 0xD7CB <= cp <= 0xD7FB:
        return "T"
    if 0xAC00 <= cp <= 0xD7A3:
        return "LV" if (cp - 0xAC00) % 28 == 0 else "LVT"
    return None


def graphemes(s):
    """Split ``s`` into graphemes (what a reader counts as one character) and return them as a list."""
    out = []
    cur = []
    regional_run = 0       # regional indicators in the current cluster
    pictographic = False   # the current cluster holds an emoji base
    for ch in s:
        cp = ord(ch)
        if not cur:
            cur = [ch]
            regional_run = 1 if _is_regional(cp) else 0
            pictographic = is_pictographic(ch)
            continue
        prev = cur[-1]
        pcp = ord(prev)
        join = False
        if pcp == 0x0D and cp == 0x0A:
            join = True
        elif _is_control(prev) or pcp in (0x0D, 0x0A) or _is_control(ch) or cp in (0x0D, 0x0A):
            join = False
        elif _is_extend(ch):
            join = True
        elif pcp == ZWJ and pictographic and is_pictographic(ch):
            join = True
        elif _is_regional(cp) and _is_regional(pcp) and regional_run % 2 == 1:
            join = True
        else:
            a, b = _hangul(pcp), _hangul(cp)
            if a == "L" and b in ("L", "V", "LV", "LVT"):
                join = True
            elif a in ("LV", "V") and b in ("V", "T"):
                join = True
            elif a in ("LVT", "T") and b == "T":
                join = True
        if join:
            cur.append(ch)
            if _is_regional(cp):
                regional_run += 1
            if is_pictographic(ch):
                pictographic = True
        else:
            out.append("".join(cur))
            cur = [ch]
            regional_run = 1 if _is_regional(cp) else 0
            pictographic = is_pictographic(ch)
    if cur:
        out.append("".join(cur))
    return out


def count(s, how="characters"):
    """Count ``s`` as a store does: ``characters`` (code points), ``graphemes`` or ``bytes`` (UTF-8)."""
    if s is None:
        return 0
    if how == "characters":
        return len(s)
    if how == "bytes":
        return len(s.encode("utf-8"))
    if how == "graphemes":
        return len(graphemes(s))
    raise ValueError("count must be characters, graphemes or bytes, not %r" % (how,))


def _emoji_grapheme(g):
    cps = [ord(c) for c in g]
    if VS16 in cps or KEYCAP in cps:
        return True
    if any(_is_regional(cp) or _is_skin_tone(cp) for cp in cps):
        return True
    first = cps[0]
    if first in _TEXT_DEFAULT:
        return False
    if VS15 in cps:
        return False
    if _in(_PICTOGRAPHIC, first):
        return True
    return first >= 0x1F000 and unicodedata.category(g[0]) in ("So", "Sk")


def find_emoji(s):
    """Return the emoji in ``s``, each a whole grapheme (a flag, a family, a keycap), in order."""
    if not s:
        return []
    return [g for g in graphemes(s) if _emoji_grapheme(g)]


def has_emoji(s):
    """True if ``s`` holds an emoji.

    Counted as emoji: symbols (Unicode categories So and Sk) in the emoji planes, the pictographic ranges
    of the Basic Multilingual Plane (Miscellaneous Symbols, Dingbats, the emoji arrows and shapes),
    regional-indicator flags, skin-tone modifiers, keycaps and anything followed by variation selector 16.
    Text-default symbols such as (c), (R) and TM count only with VS16 after them; VS15 asks for the text form.
    """
    return bool(find_emoji(s))


def _no_space_script(ch):
    return _in(_NO_SPACE_SCRIPTS, ord(ch))


def _word_pattern(word):
    parts = [re.escape(p) for p in word.split()]
    body = r"\s+".join(parts)
    first, last = word.strip()[0], word.strip()[-1]
    lead = r"(?<!\w)" if (first.isalnum() or first == "_") and not _no_space_script(first) else ""
    tail = r"(?!\w)" if (last.isalnum() or last == "_") and not _no_space_script(last) else ""
    return lead + body + tail


def find_words(s, words):
    """Return the entries of ``words`` that appear in ``s``, in ``words``' order, each once.

    Matching is case-insensitive and by whole words: "free" matches "Free!" but not "freedom". An entry
    that starts or ends with a symbol ("#1", "$0.99", "100%") is matched as written on that side, without a
    word boundary; an entry of several words matches across any run of spaces; entries in scripts written
    without spaces (Chinese, Japanese, Thai…) match anywhere.
    """
    if not s:
        return []
    found = []
    for word in words:
        if not word or not word.strip() or word in found:
            continue
        if re.search(_word_pattern(word), s, re.IGNORECASE):
            found.append(word)
    return found
