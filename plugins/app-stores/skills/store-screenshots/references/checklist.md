# The pre-ship checklist

Run on the rendered files and the sheets before handing a set to `store-listings`. Each item says who decides it:

- **check.py**: decided by the script from the render report and the PNGs (an error or a warning).
- **sheet, then look**: the script measures or draws it; a person (or the agent, looking) decides.
- **look**: only a look at every file at full size can tell. `check.py` prints these as checklist items, never as
  errors; the agent goes through them and reports what it saw, file by file.

## Pixels and counts

1. **check.py.** Every file at its target's exact size, and that size one the store takes for the device; no alpha;
   PNG or JPEG; counts within each store's limits (Apple 1 to 10 a size; Play 2 to 8 a device type, at least 4 for
   tablets, and at least 4 for apps or 3 for games to be eligible for recommendations; Wear 1:1).
2. **check.py** (with `store-listings`' check). The required sizes are there: Apple's iPhone medium display and
   iPad 13" if the app runs on iPad, iPhone Duo once due; Play's tablets if the app supports them.

## Words

3. **check.py, then look.** Every caption fits without being cut, at or above its floor, in at most 2 lines (more is
   an error) and about 5 words (over 6 warns); no word broken but by hyphenation; every locale rendered. Look at
   the breaks in each language.
4. **check.py.** No forbidden words for the store in captions, kickers or proof lines (the rules' `words` rules that
   apply to `captions`): prices and price words, "#1" and rankings, Apple-designated awards, other platforms' names;
   on Play any award, testimonial, promotion or call to action. A word the check can't see (in the capture, in an
   image) is item 12's look.
5. **look** (typed in Play Console). Play alt text for every screenshot, per locale, 140 characters or fewer, not
   starting "photo of" or "image of". Draft it from each shot's message and what it shows.

## Legibility

6. **sheet, then look.** In the search-row mock, each caption is 11 pt or more, and shots 1 to 3 (or the one
   landscape shot) each say what the app is, on their own ([legibility.md](legibility.md)).
7. **check.py.** Caption contrast 4.5:1 or more against the actual pixels behind it.
8. **check.py, then look.** Nothing within a panorama's seam margin; shot 1 reads without shot 2 (look at the
   contact sheet's gutters).
9. **check.py, then look.** Play: words at most 20% of the image; no extra text on Play's tablet shots (look).
   Missing glyphs: none.

## Content (a look at full size)

10. **look.** Real UI from the current version on the latest OS; invented data and accounts; a clean status bar
    (full signal and battery, no carrier, no notifications); no debug overlays, toasts, banners, prompts or
    spinners; the right input UI for the device; captions not over the app's own UI where it matters.
11. **look.** Fit for all ages on Apple, every shot: no gore, no weapons aimed at a person or the viewer, nothing
    sexual. (Steam: at least 4 flagged for all ages.)
12. **look.** Nobody else's names, logos, characters, likenesses, photos or fonts without the rights; other
    platforms' devices, badges or button glyphs out of Apple's set and Apple's devices out of Play's. Flag every
    one to the user with who owns it.
13. **check.py, then look.** Frames: drawn ones, fitted to their captures, or the user's Apple bezel as it is (the
    check fails one tilted, folded, cropped or overlapped); none on Wear OS; Play frameless unless the user chose
    otherwise (a warning). At full size, each frame's corners: the status bar's clock and icons whole (the check
    warns where a corner still cuts content), a camera cutout only where the capture leaves room for one, and a
    fold's halves meeting at the seam.
14. **look.** Required fine print present and legible where the app needs it (finance, regional availability, a
    subscription). Version 1's config has no fine-print slot: if one is needed, raise it with the user.
15. **look.** One visual system across the set (caption style and place, frame, palette); a dark-mode shot if the
    app has dark mode.
16. **check.py, then look.** Fallbacks: every locale's caption and captures its own, or each fallback accepted by
    the user. Right-to-left locales captured in right-to-left; logos and clocks not mirrored; a panorama's order
    checked in the storefront.
17. **look.** Nothing dated or seasonal (a date, an event, a holiday) in a screenshot; seasonal messages go to
    swappable assets or a test.
18. **look.** A product page optimisation (Apple) or store listing experiment (Play) proposed for the first-shot
    choice, with the after-install measure named ([evidence.md](evidence.md)).

## Consistency and the baseline

19. **check.py, then look.** One system inside the set: the device in the same place on every non-hero shot of a
    layout (within 0.2u) and the caption's top too (0.5u); shots 1 to 3's captions at least 9.5u on a tall slot (6u
    mid, 4u wide). The hero may break the grid.
20. **check.py.** With a style: its copy rules (words, lines, case); with a locked style, no config theme key
    against it (an error), no layout outside its roles, roles within their `maxPerSet`.
21. **check.py, then look** (an update to an approved set). The locked style unchanged since the baseline (an error
    otherwise); each drift warning shown to the user with `sheet.py --compare design/baseline`, and accepted or
    fixed by them ([baseline.md](baseline.md)).
22. **look.** The user picked the direction and approved the set; `design/decisions.md` says so in their words.

Also checked, not numbered: captures never shown larger than they are (`captureScale` over 1.0 is a finding), and
every file's inputs unchanged since its render (`render.py --force` if in doubt).
