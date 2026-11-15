# Legibility

A caption is read twice: big on the product page, and tiny in search, where the decision is mostly made. Design
for the tiny one.

## How small the shots are shown

Apple doesn't publish the search row's sizes. The estimate the mocks use (derived; **unverified on devices**):

- A phone about 400 pt wide shows three portrait shots side by side, with about 16 pt margins and 8 pt gaps: each
  shot is about **118 pt wide**.
- A 1320-px iPhone shot is then drawn at about 11 source pixels a point (a 1206-px one at about 10).
- A single landscape shot fills the row, about three times as large.
- How many product-page shots show before scrolling isn't documented; practitioners say the first two portrait
  shots, and iOS 27's header pushes them down.

## The caption-size rule (9.5u on a tall shot)

u is 1% of the slot's width. iOS's minimum text size is 11 pt and its default 17 pt
(https://developer.apple.com/design/human-interface-guidelines/typography). At about 118 pt a shot, a caption in the
search row reads as 11 pt when its font size is about **9.5u** on a portrait phone shot (about 125 px on a 1320-px
shot). A single landscape shot needs about 3u.

What strong sets do (16 top-captioned iPhone sets measured 2026-11-14; font sizes estimated from ink height, plus or
minus 10 to 15%): a median headline of **8.9u** (middle half 7.6 to 10.3u, range 5.9 to 12u), two lines, leading
about 1.1, 12 to 18 characters a line. iPad (mid) sets: 4.2 to 6.1u. The generators: goldie 8.2u
(https://github.com/software-mansion-labs/goldie/blob/699578c/src/layouts.ts), the ParthJadhav skill 9.2u
(https://github.com/ParthJadhav/app-store-screenshots/blob/e889033/skills/app-store-screenshots/template/src/lib/layouts.ts),
fastlane frameit 10% of the width (https://github.com/fastlane/fastlane/blob/ca02a52/frameit/lib/frameit/editor.rb),
Koubou "minimum 10vw, recommended 11-14vw" (https://github.com/bitomule/koubou/blob/11c5a12/skills/koubou/design-guide.md).
Vendor guides that say 56 to 72 px on a 1290-px canvas (4.3 to 5.6u) are half what good sets do: too small in search.

| Aspect class | Starts at | Floor | Shots 1-3 warn under |
|---|---|---|---|
| tall (iPhone, Play phone) | 9.5u | 7u (about 12 pt on the product page) | 9.5u |
| mid (iPad) | about 6.1u | about 4.5u | 6u |
| square (Wear) | about 8u | about 5.9u | none |
| wide (landscape, TV, Mac) | about 4.6u | about 3.4u | 4u |

**How the config expresses it:** `caption.sizePct` (theme or style) is the font size it starts at and `floorPct`
the smallest it may shrink to, both in u on a tall slot; other aspect classes scale them (mid 0.64, square 0.84, wide
0.48). The defaults are 9.5 and 7. The caption shrinks from one toward the other until it fits in `maxLines` (2), and
keeps room for two lines at its starting size so the device and the caption's top stay put across the set.

**How to check it:**

1. In `<out>/render-report.json`, each file's `caption.fontPx` over its `width` is the size it rendered at (`125.4 /
   1320` is 9.5u); `atFloor: true` means it shrank all the way. `check.py --json` lists it as `captionU`.
2. `check.py` warns (`design.caption.search_size`) when one of shots 1 to 3 comes out under the table's size, and
   gives the size in points in Apple's search row for Apple phone targets.
3. `sheet.py --png` draws shots 1 to 3 in the search row at its real width and prints each caption's size in points.
   Open `<out>/sheets/` and read them there: 11 pt or more for shots 1 to 3 is the aim.
4. Under 11 pt in search: fewer words (so it fits bigger), a bigger `sizePct`, or a layout that gives the caption
   more width. Never a lower floor to make a long caption fit.

The floor is the least legible a caption may be anywhere, not a target.

## Words and lines

- At most two lines (the check fails three); 2 to 5 words; the check warns over six.
- Bold or heavy weight: every sampled set used one.
- Lines balanced, not one long and one orphan. No word broken except by proper hyphenation.
- One message: if it needs "and", it's two shots.

## Contrast

- WCAG asks 4.5:1 for normal text and 3:1 for large (https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
  Captions are large on the page but small in search, so the check asks **4.5:1**.
- Measured against the **real pixels behind the caption** (the median behind its box, decoded from the rendered
  PNG), not the theme's background colour: a caption over a capture, a photo or a gradient can fail where the
  palette passes.
- A failing caption gets a plate, a darker or lighter field, or a move off the busy part of the capture.

## How much of the picture is words

- `textShare` in the report is the summed area of every text box over the slot's area.
- Play: taglines no more than **20%** of the image (the rules' `design.maxTextShare`); the check warns over it on Play
  targets. Google calls it highly recommended, and it counts for the recommendation formats.
- Play's tablets: "exclude additional text that is not part of your core app experience, as this can get cut off".
  Consider `caption: false` for Play's tablet targets.

## Where the words go

- **Never over the app's own UI** where it matters: a button, the board, the content being sold. Choose top or
  bottom shot by shot (`at` on `fullbleed`).
- **A margin from the edges** of about 3 to 4% of the width (this skill's opinion): the stores round their cards'
  corners and, for panoramas, draw gaps.
- **Light or dark:** the store's own background follows the shopper's setting, so a set should hold up on both. No
  data says which converts better; choose by the brand and by contrast.
