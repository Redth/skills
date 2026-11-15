# Localisation

Apple asks for localised screenshots per market (https://developer.apple.com/app-store/product-page/); Play asks
for localised "graphic and branding text" but says "In-game UI does not need to be localized per market"
(https://support.google.com/googleplay/android-developer/answer/9866151). Read 2026-11-14.

## Strings and fallbacks

- Captions, kickers and proof lines are string keys in `strings.<locale>`. A locale missing a key falls back to the
  primary locale's string, key by key, and the render report marks the file `stringFallback: true`. `check.py`
  reports every fallback.
- Captures fall back the same way: a locale with no capture of its own uses the primary locale's, marked
  `captureFallback: true` (an English UI under a German caption).
- **A fallback isn't an error, and isn't done either.** Report each one to the user by locale and shot, and either
  fill it or have the user accept it. A shot meant to be translated mustn't ship quietly in the primary language.
- Machine translation is a draft: mark it as such and ask for a native speaker's read, especially for a short,
  punchy line, where tone is the whole point.

## Text grows

From IBM's guide, as the W3C quotes it (https://www.w3.org/International/articles/article-text-size):

| English length | Typical growth in translation |
|---|---|
| up to 10 characters | 200 to 300% |
| 11 to 20 | 180 to 200% |
| 21 to 30 | 160 to 180% |
| over 70 | about 130% |

Captions are short, so they grow the most. German, Finnish and Dutch build compounds that don't wrap; CJK needs
more width per character; Thai, Arabic and Devanagari more height.

**When a translation doesn't fit:** the caption shrinks from `sizePct` toward `floorPct`, and if it still needs more
than `maxLines` at the floor, `render.py` exits 1 and the report says `fits: false`. **Shorten the string; never
lower the floor or cut the words.** Ask the translator for a shorter line that keeps the one message, or drop a
word the picture already says. Two lines at the floor is a pass, but read it on the search-row mock: the floor is the
least legible a caption may be, not a target.

## Line breaking

Each locale renders with its own language set on the page, so hyphenation and line breaking follow it:
`hyphens: auto` breaks a long German compound with a hyphen, and lines are balanced. Hyphenation needs the
language's dictionary in the Chrome that renders (check a German set rendered on Linux CI the first time).
For CJK, read the breaks on the contact sheet: Korean reads best with words kept whole, Japanese with strict line
breaking (no small kana or closing punctuation starting a line). A bad break is a reason to reword, as a too-long
line is.

## Fonts and scripts

- A brand font rarely covers CJK, Arabic, Hebrew, Thai or Devanagari. Add a font that does to `theme.fonts`, with
  the right to use it (Noto's families are open-licensed, for example). Fonts are files in the project: nothing is
  fetched, and a font only installed on one machine renders differently on the next.
- The report's `missingGlyphs` lists characters no loaded font covers; `check.py` fails them. A caption that
  renders in a system fallback font looks wrong beside the others, and on a different machine renders differently.

## Right-to-left

- **Capture the app in its right-to-left mode** rather than flipping English shots: the app's own mirroring is what
  a shopper will see.
- The page renders right-to-left locales with `dir="rtl"`: captions align to the right edge, and layouts that place
  things by side mirror.
- Don't mirror logos, media controls, clocks or anything the app itself doesn't mirror.
- **Panoramas:** whether the carousel runs right to left in those storefronts is unverified
  ([panoramas.md](panoramas.md)).

## Captures per locale

- **Where the UI is the selling point** (a list, a plan, words the user reads), capture each locale: a German caption
  over an English UI undersells it, and Apple's asks for localised screenshots.
- **Where the picture sells** (a game's play, a photo, a map), the primary locale's captures with localised captions
  are a common, acceptable shortcut. Say it's what's happening.
- Same seed, clock and data in every locale, so the sets match shot for shot.
