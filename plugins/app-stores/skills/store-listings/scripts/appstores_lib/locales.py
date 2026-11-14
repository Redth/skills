"""BCP 47 locales to and from each store's own locale codes.

$comment: these tables were written from the stores' published lists as known on 2026-11-14. The stores add
languages from time to time: re-check them against App Store Connect's "App Store localizations" page and
Play Console's "Add translations" list (Google Play's "Languages for store listings" help page), and update
the date here. The 2025 additions to App Store Connect (``APPLE_ADDED_2025``) were checked least.

A config names its locales in BCP 47 (``en-US``, ``pt-BR``, ``zh-Hans``). ``apple(code)`` and ``google(code)``
give the store's code for one, choosing sensibly where the store spells it differently (``zh-Hans`` is
Play's ``zh-CN``, ``he`` is Play's ``iw-IL``, ``nb`` is Apple's ``no`` and Play's ``no-NO``) and raising
``LocaleError`` for a locale the store doesn't list. ``from_apple`` and ``from_google`` go back.
"""

from __future__ import annotations

import re

# App Store Connect's locale codes (the API's ``locale`` values) and their names.
APPLE = {
    "ar-SA": "Arabic",
    "bn-BD": "Bangla",
    "ca": "Catalan",
    "cs": "Czech",
    "da": "Danish",
    "de-DE": "German",
    "el": "Greek",
    "en-AU": "English (Australia)",
    "en-CA": "English (Canada)",
    "en-GB": "English (U.K.)",
    "en-US": "English (U.S.)",
    "es-ES": "Spanish (Spain)",
    "es-MX": "Spanish (Mexico)",
    "fi": "Finnish",
    "fr-CA": "French (Canada)",
    "fr-FR": "French",
    "gu-IN": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn-IN": "Kannada",
    "ko": "Korean",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "ms": "Malay",
    "nl-NL": "Dutch",
    "no": "Norwegian",
    "or-IN": "Odia",
    "pa-IN": "Punjabi",
    "pl": "Polish",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl-SI": "Slovenian",
    "sv": "Swedish",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur-PK": "Urdu",
    "vi": "Vietnamese",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
}

# The languages App Store Connect added in 2025; their codes are the least certain here.
APPLE_ADDED_2025 = frozenset(["bn-BD", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "or-IN", "pa-IN", "sl-SI", "ta-IN",
                              "te-IN", "ur-PK"])

# Google Play's store-listing language codes (the Publishing API's ``language`` values) and their names.
GOOGLE = {
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "az-AZ": "Azerbaijani",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn-BD": "Bangla",
    "ca": "Catalan",
    "cs-CZ": "Czech",
    "da-DK": "Danish",
    "de-DE": "German",
    "el-GR": "Greek",
    "en-AU": "English (Australia)",
    "en-CA": "English (Canada)",
    "en-GB": "English (United Kingdom)",
    "en-IN": "English (India)",
    "en-SG": "English (Singapore)",
    "en-US": "English (United States)",
    "en-ZA": "English (South Africa)",
    "es-419": "Spanish (Latin America)",
    "es-ES": "Spanish (Spain)",
    "es-US": "Spanish (United States)",
    "et": "Estonian",
    "eu-ES": "Basque",
    "fa": "Persian",
    "fa-AE": "Persian (United Arab Emirates)",
    "fa-AF": "Persian (Afghanistan)",
    "fa-IR": "Persian (Iran)",
    "fi-FI": "Finnish",
    "fil": "Filipino",
    "fr-CA": "French (Canada)",
    "fr-FR": "French (France)",
    "gl-ES": "Galician",
    "gu": "Gujarati",
    "hi-IN": "Hindi",
    "hr": "Croatian",
    "hu-HU": "Hungarian",
    "hy-AM": "Armenian",
    "id": "Indonesian",
    "is-IS": "Icelandic",
    "it-IT": "Italian",
    "iw-IL": "Hebrew",
    "ja-JP": "Japanese",
    "ka-GE": "Georgian",
    "kk": "Kazakh",
    "km-KH": "Khmer",
    "kn-IN": "Kannada",
    "ko-KR": "Korean",
    "ky-KG": "Kyrgyz",
    "lo-LA": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk-MK": "Macedonian",
    "ml-IN": "Malayalam",
    "mn-MN": "Mongolian",
    "mr-IN": "Marathi",
    "ms": "Malay",
    "ms-MY": "Malay (Malaysia)",
    "my-MM": "Burmese",
    "ne-NP": "Nepali",
    "nl-NL": "Dutch",
    "no-NO": "Norwegian",
    "pa": "Punjabi",
    "pl-PL": "Polish",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "rm": "Romansh",
    "ro": "Romanian",
    "ru-RU": "Russian",
    "si-LK": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv-SE": "Swedish",
    "sw": "Swahili",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "th": "Thai",
    "tr-TR": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh-CN": "Chinese (Simplified)",
    "zh-HK": "Chinese (Hong Kong)",
    "zh-TW": "Chinese (Traditional)",
    "zu": "Zulu",
}

# Spanish for Latin America: the regions that map to Play's es-419 (and Apple's es-MX).
_LATAM = frozenset(["419", "AR", "BO", "CL", "CO", "CR", "CU", "DO", "EC", "GT", "HN", "MX", "NI", "PA", "PE",
                    "PR", "PY", "SV", "UY", "VE"])

# Deprecated or alternative language subtags.
_LANGUAGE_ALIASES = {"iw": "he", "in": "id", "ji": "yi", "tl": "fil", "nb": "no"}

# Where a store spells a locale its own way (keys are canonical BCP 47 after _LANGUAGE_ALIASES).
_APPLE_ALIASES = {
    "no-NO": "no",
    "es-US": "es-MX",
}
_GOOGLE_ALIASES = {
    "he": "iw-IL",
    "he-IL": "iw-IL",
    "no": "no-NO",
    "fil-PH": "fil",
    "zh-MO": "zh-HK",
    "zh-Hant-MO": "zh-HK",
}

# The store code for a bare language with several variants.
_APPLE_DEFAULTS = {"en": "en-US", "es": "es-ES", "fr": "fr-FR", "pt": "pt-BR", "zh": "zh-Hans"}
_GOOGLE_DEFAULTS = {"en": "en-US", "es": "es-ES", "fr": "fr-FR", "pt": "pt-BR", "zh": "zh-CN", "ms": "ms",
                    "fa": "fa"}

# Back from a store's code to the BCP 47 a config uses, where they differ.
_FROM_APPLE = {}
_FROM_GOOGLE = {"iw-IL": "he-IL", "zh-CN": "zh-Hans", "zh-TW": "zh-Hant", "zh-HK": "zh-Hant-HK"}


class LocaleError(ValueError):
    """A locale that isn't well-formed, or that a store doesn't offer."""


def canonical(code):
    """Return a BCP 47 tag in its usual case (``en_us`` -> ``en-US``, ``zh-hant-hk`` -> ``zh-Hant-HK``)."""
    if not isinstance(code, str) or not re.match(r"^[A-Za-z]{2,8}([-_][A-Za-z0-9]{1,8})*$", code.strip()):
        raise LocaleError("%r isn't a BCP 47 language tag (like en-US, pt-BR or zh-Hans)" % (code,))
    parts = re.split(r"[-_]", code.strip())
    out = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 4 and p.isalpha():
            out.append(p.title())
        elif (len(p) == 2 and p.isalpha()) or (len(p) == 3 and p.isdigit()):
            out.append(p.upper())
        else:
            out.append(p.lower())
    return "-".join(out)


def _parse(tag):
    parts = tag.split("-")
    lang = _LANGUAGE_ALIASES.get(parts[0], parts[0])
    script = region = None
    for p in parts[1:]:
        if len(p) == 4 and p.isalpha() and script is None and region is None:
            script = p
        elif ((len(p) == 2 and p.isalpha()) or (len(p) == 3 and p.isdigit())) and region is None:
            region = p
    return lang, script, region


def _resolve(code, store, codes, aliases, defaults):
    tag = canonical(code)
    if tag in codes:
        return tag
    if tag in aliases:
        return aliases[tag]
    lang, script, region = _parse(tag)
    if lang == "zh":
        if script is None:
            script = "Hant" if region in ("TW", "HK", "MO") else "Hans"
        if region is None:
            region = "TW" if script == "Hant" else "CN"
    candidates = []
    if script and region:
        candidates.append("%s-%s-%s" % (lang, script, region))
    if region:
        candidates.append("%s-%s" % (lang, region))
    if script:
        candidates.append("%s-%s" % (lang, script))
    if lang == "es" and region in _LATAM:
        candidates += ["es-419", "es-MX"]
    if not region:
        candidates.append(lang)
    for c in candidates:
        if c in codes:
            return c
        if c in aliases:
            return aliases[c]
    if lang in codes:
        return lang
    if lang in aliases:
        return aliases[lang]
    variants = sorted(c for c in codes if c.split("-")[0] == lang)
    if not region and lang in defaults:
        return defaults[lang]
    if len(variants) == 1:
        return variants[0]
    if variants:
        raise LocaleError("%s has no %s: use one of %s" % (store, tag, ", ".join(variants)))
    raise LocaleError("%s doesn't offer %s for store listings" % (store, tag))


def apple(code):
    """Return App Store Connect's locale code for a BCP 47 locale; raise ``LocaleError`` if it has none."""
    return _resolve(code, "The App Store", APPLE, _APPLE_ALIASES, _APPLE_DEFAULTS)


def google(code):
    """Return Google Play's listing language code for a BCP 47 locale; raise ``LocaleError`` if it has none."""
    return _resolve(code, "Google Play", GOOGLE, _GOOGLE_ALIASES, _GOOGLE_DEFAULTS)


def for_store(store, code):
    """``apple(code)`` or ``google(code)`` by the store's name (``apple`` or ``google``)."""
    if store == "apple":
        return apple(code)
    if store == "google":
        return google(code)
    raise LocaleError("no locale table for the store %r" % (store,))


def from_apple(code):
    """Return the BCP 47 locale for an App Store Connect locale code (raises ``LocaleError`` if unknown)."""
    if code not in APPLE:
        raise LocaleError("%r isn't an App Store Connect locale" % (code,))
    return _FROM_APPLE.get(code, code)


def from_google(code):
    """Return the BCP 47 locale for a Google Play language code (raises ``LocaleError`` if unknown)."""
    if code not in GOOGLE:
        raise LocaleError("%r isn't a Google Play listing language" % (code,))
    return _FROM_GOOGLE.get(code, code)


def store_codes(store, codes):
    """Map each BCP 47 locale in ``codes`` to ``store``'s code; return ``{bcp47: store_code}``.

    Raises ``LocaleError`` for a locale the store doesn't offer, or when two locales would become the same
    store locale (``de-AT`` and ``de-DE`` are both Apple's ``de-DE``).
    """
    out = {}
    taken = {}
    for code in codes:
        mapped = for_store(store, code)
        if mapped in taken:
            raise LocaleError("%s and %s would both be %s's %s" % (taken[mapped], code, store, mapped))
        taken[mapped] = code
        out[code] = mapped
    return out
