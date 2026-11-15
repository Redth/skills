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

## The caption-size rule (about 9% of the slot's width)

iOS's minimum text size is 11 pt and its default 17 pt
(https://developer.apple.com/design/human-interface-guidelines/typography). For a caption in the search row to read
as 11 pt, its font size must be about **9 to 10% of the slot's width** on a portrait phone shot (about 120 to 130 px
on a 1320-px shot). A single landscape shot needs about 3%. Top apps' captions measure 5 to 9% by eye: readable on the
product page, marginal in search.

**How the config expresses it:** `theme.caption.sizePct` is the font size it starts at and `floorPct` the smallest it
may shrink to, both as a percentage of the slot's width. The caption shrinks from one toward the other until it fits
in `maxLines` (2).

**How to check it:**

1. In `<out>/render-report.json`, each file's `caption.fontPx` over its `width` is the size it rendered at (`105.6 /
   1320` is 8%); `atFloor: true` means it shrank all the way.
2. `sheet.py --png` draws shots 1 to 3 in the search row at its real width and prints each caption's size in points.
   Open `<out>/sheets/` and read them there: 11 pt or more for shots 1 to 3 is the aim.
3. Under 11 pt in search: fewer words (so it fits bigger), a bigger `sizePct` for the first shots, or a layout that
   gives the caption more width. Never a lower floor to make a long caption fit.

The floor the check enforces is the least legible a caption may be anywhere, not a target. The example config's 8%
start and 6% floor read well on the product page; shots 1 to 3 of a portrait phone set want 9% or more.

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
