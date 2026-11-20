# Panoramas

A picture that runs across several screenshots, so a swipe reveals the rest of it.

## When

- **Allowed:** Play says "Stylized screenshots that break UI across multiple uploaded images are allowed"
  (https://support.google.com/googleplay/android-developer/answer/9866151); App Review's 2.3.3 reference treats a
  panorama across screenshots as fine.
- **Rare in practice:** 1 of 13 top apps observed (MyFitnessPal: one photo across shots 1 and 2); many more share
  one colour field across the set without a continuous picture, which gets most of the effect with none of the
  risk.
- **Only where shot 1 still stands alone.** Few people swipe, and search shows shots 1 to 3 side by side with gaps
  between them. If shot 1 doesn't sell the app without shot 2, it isn't a panorama, it's a puzzle.
- **The "+30% for panoramas" figure** that circulates traces back to vendor posts with no study behind it. Test it
  ([evidence.md](evidence.md)).

## How it renders

```json
"panorama": { "shots": ["plan", "recipe", "shop"], "background": "art/kitchen.jpg", "seam": 6 }
```

- `shots`: the shots, in order, that share one canvas N slots wide. They should be consecutive in `shots`.
- `background`: an image (path relative to the config) or `null` for the theme's background.
- `seam`: a keep-out margin either side of each seam, in `--u` (1% of a slot's width).

The page lays the canvas out once; `render.py` shoots slot *i* with the canvas shifted by *i* slot widths, so the
picture lines up exactly across files. Each target gets its own panorama at its own size: a phone's and a tablet's
are different pictures. The render report lists each file's `seams`, and `check.py` fails a caption, frame or
callout box that falls within the seam margin. `sheet.py`'s contact sheet shows seams as gutters, as the stores draw
them.

## Rules of thumb

- **Nothing that matters within the seam margin:** words, a device, a face, a button. The stores draw a gap
  between cards (its width isn't published) and round their corners, so anything across a seam is cut and looks
  broken. A phone straddling two slots looked broken once a gutter was added, in a trial render.
- **Each slot readable alone,** with its own caption, at search size.
- **Removing or reordering a shot breaks the strip.** Re-render the whole panorama after any change to its shots.
- **Per store:** a Play set's panorama is still frameless; keep the UI first in the first three shots.
- **Right-to-left storefronts:** whether the App Store's carousel starts from the right there (which would reverse
  the picture) is **unverified**; sources disagree. Check in an Arabic or Hebrew storefront before shipping a
  right-to-left panorama, or keep the right-to-left locales' shots independent.
