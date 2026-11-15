# The design config: `store-screenshots.json`

One plain-JSON file in the user's project, usually beside `store-listing.json` (the scripts take `--config`,
default `./store-screenshots.json`). Paths inside it are relative to the config's own folder. The schema is the
skill's `schema/store-screenshots.schema.json`; every script validates against it first. Comments go in
`"$comment"` keys: JSON has none.

The examples use the invented app "Sample Recipes" by Example Studio.

## A whole config

```json
{
  "$schema": "./store-screenshots.schema.json",
  "version": 1,
  "captures": "captures",
  "out": "screenshots",
  "primaryLocale": "en-US",
  "locales": ["en-US", "de-DE"],
  "theme": {
    "fonts": [ { "family": "Brand Sans", "src": "fonts/BrandSans.woff2", "weight": "400 900", "style": "normal" } ],
    "palette": { "background": "#0E3B2E", "ink": "#FFFFFF", "accent": "#FFC94D" },
    "background": { "kind": "color" },
    "caption": { "placement": "top", "align": "center", "maxLines": 2, "weight": 800, "sizePct": 8.0,
                 "floorPct": 6.0, "font": "Brand Sans" },
    "frame": "phone"
  },
  "targets": {
    "iphone":        { "store": "apple",  "width": 1320, "height": 2868, "capture": "iphone-6.9" },
    "iphone-medium": { "store": "apple",  "width": 1206, "height": 2622, "capture": "iphone-6.3" },
    "ipad":          { "store": "apple",  "width": 2064, "height": 2752, "capture": "ipad-13", "frame": "tablet" },
    "android-phone": { "store": "google", "width": 1080, "height": 1920, "capture": "android-phone" }
  },
  "shots": [
    { "id": "plan",   "capture": "plan",   "layout": "hero",         "caption": "cap.plan", "proof": "cap.proof" },
    { "id": "recipe", "capture": "recipe", "layout": "framed-bleed", "caption": "cap.recipe",
      "callout": { "rect": [0.08, 0.42, 0.84, 0.12], "scale": 1.35 } },
    { "id": "shop",   "capture": "shopping", "layout": "tilt", "tilt": "left", "caption": "cap.shop",
      "targets": ["iphone", "iphone-medium", "ipad"] }
  ],
  "panorama": null,
  "stores": { "google": { "frame": "none" }, "apple": {} },
  "strings": {
    "en-US": { "cap.plan": "Plan a week of meals in minutes", "cap.recipe": "Every recipe, step by step",
               "cap.shop": "Your list, sorted by aisle", "cap.proof": "Loved by home cooks" },
    "de-DE": { "cap.plan": "Eine Woche Essen in Minuten planen" }
  }
}
```

## Top level

| Field | Type | Meaning |
|---|---|---|
| `$schema` | string | `"./store-screenshots.schema.json"` if a copy sits beside it |
| `version` | `1` | the format's version |
| `captures` | path | the captures' folder (below) |
| `out` | path | where the rendered files go; make it `store-listing.json`'s `screenshots.folder` |
| `primaryLocale` | BCP 47 | the locale every other falls back to, string by string and capture by capture |
| `locales` | list | the locales to render, the primary among them |
| `theme` | object | the look shared by every shot (below); with a style, what the style doesn't set |
| `style` | path | a `screenshot-style.json` whose theme and stores win over these, and whose roles give shots their layouts ([style.md](style.md)) |
| `design` | path | the design folder: inspiration, directions, explorations, `decisions.md`, the baseline (default `design`; [baseline.md](baseline.md)) |
| `targets` | object | the output screens, by id (below) |
| `shots` | list | the set, in the order the stores show it (below) |
| `panorama` | object or `null` | shots that share one canvas ([panoramas.md](panoramas.md)) |
| `stores` | object | per-store overrides (below) |
| `strings` | object | the words, per locale (below) |

## Captures

`<captures>/<locale>/<capture device id>/<capture screen id>.png`: the layout `store-capture` writes; any tool's
PNGs work renamed into it. A target's `capture` names the device folder, a shot's `capture` the file.

- A locale with no capture of its own uses the primary locale's, reported as `captureFallback`.
- A capture must be at least the size its target shows it at. It's never upscaled past 1.0: the report's
  `captureScale` says how it was drawn, and the check reports one that would be enlarged. Capture on a bigger device
  rather than resizing.
- Captures from a design tool (a screen mocked up in a design app) work the same way; they must still be the app's
  real UI.

## `theme`

- `fonts`: each `{ family, src, weight, style }`, as CSS `@font-face` takes them; `src` a font file in the project
  (WOFF2, WOFF, TTF or OTF), `weight` a single weight or a range (`"400 900"`). Nothing is fetched: a font must be a
  file, and one the user may use. Add one covering every locale's script ([localisation.md](localisation.md)).
- `palette`: `background` (the field behind the shots), `ink` (the captions), `accent` (highlights, plates). Hex
  colours.
- `background`: `{ "kind": "color" }` is the palette's flat background; the schema lists the other kinds it takes.
- `caption`:
  - `placement`: `top` | `bottom`, where captions sit on layouts that have a caption area.
  - `align`: how the lines align, `center` in the example (the schema lists the others; in right-to-left locales
    the start is the right edge).
  - `maxLines`: 2. More is an error in the check.
  - `weight`: the font weight (heavy reads best small).
  - `sizePct`: the font size it starts at, as a percentage of the slot's width.
  - `floorPct`: the smallest it may shrink to. A caption that won't fit `maxLines` at the floor fails the render.
  - `font`: the family, from `fonts`.
  - `case`: `upper` or `lower` draws the words in that case (the strings stay as written); default as written.
  Sizing: [legibility.md](legibility.md). The defaults are `sizePct` 9.5 and `floorPct` 7 (the size that reads in
  Apple's search row, and about 12 pt on the product page).
- `frame`: a drawn frame (`phone`, `phone-landscape`, `tablet`, `tablet-landscape`, `laptop`, `desktop`, `tv`,
  `watch`), `"none"`, or a frame file of the user's own ([frames.md](frames.md)).

## `targets`

Each target is one output screen: one set of files per locale.

| Field | Meaning |
|---|---|
| id (the key) | **the `screens` name in `store-listing.json`** (`iphone`, `android-phone`): the folder the files land in |
| `store` | whose rules apply: `apple` or `google` |
| `width`, `height` | its exact pixels: one of the sizes the store takes for that device ([store-rules.md](store-rules.md)) |
| `capture` | the capture device id whose captures feed it |
| `frame`, `layout`, `caption` (optional) | overrides for this target alone: e.g. `"frame": "tablet"` on an iPad, `"caption": false` on Play's tablets |

Which store slot a file fills is decided later by `store-listings`: Apple's by the pixel size, Play's by
`stores.google.slots`. Two Apple targets at sizes in the same display type would compete for one slot.

## `shots`

The set, in order. Each:

| Field | Meaning |
|---|---|
| `id` | **the shot id in `store-listing.json`'s `screenshots.shots`**: the file's name |
| `capture` | the capture screen id (the file name in each device's folder) |
| `role` | with a style: one of its roles (`hero`, `feature`, `detail`, `accent`...), which gives the layout when the shot gives none |
| `layout` | `fullbleed`, `band`, `framed`, `framed-bleed`, `tilt`, `pair`, `callout`, `hero`, `gameplay` ([layouts.md](layouts.md)); beats the role's |
| `caption`, `kicker`, `proof` | string keys in `strings` (the caption, a small line above it, a proof line under a hero) |
| `targets` | the target ids it's made for; `null` or absent: all |
| `tilt` | `left` \| `right`, for `tilt` |
| `callout` | `{ "rect": [x, y, w, h], "scale": s }`: the part of the capture to enlarge, as fractions of it, and by how much |
| `pair` | a second capture screen id, for `pair` |
| `at` | `top` \| `bottom`, where `fullbleed`'s plate sits |

## `style`

`"style": "screenshot-style.json"` names the look ([style.md](style.md)). The config's `theme` and `stores` are
merged under the style's, key by key: the style wins. Once a baseline is approved the style is locked: keep the
look in the style and out of the config's `theme` (a contradicting key is a check error), and give shots roles rather
than layouts. `render.py --style FILE --out design/explore/<name>` renders with another style for an exploration
without touching the set.

## `stores`

Overrides for every target of a store, over the theme and each shot: `frame`, `layout`, `caption` (`false` for no
words, for a store or slot that wants none). Play's default is `{ "frame": "none" }`; keep it unless the user
chooses frames knowing Google's guidance. A target's own overrides win over its store's.

## `strings`

`strings.<locale>.<key>`: the words, per locale. A key missing in a locale falls back to the primary locale's, and
the report marks the file `stringFallback` (`check.py` lists each). No placeholders. Words are checked against each
target store's caption rules (prices, rankings, awards, other platforms): write them for the strictest store a shot
goes to, or give a store its own key through a separate shot.

## Output

- `<out>/<locale>/<target id>/<shot id>.png`: opaque RGB at the target's exact size. Exactly the layout
  `store-listings` reads.
- `<out>/render-report.json`: what each file is and how it came out (the caption's size, lines and fit, its share of
  the picture, the frame's box, fallbacks, seams, a hash). The check and the sheets read it. Rendering is cached on
  the hash of each file's inputs; `render.py --force` renders everything again.
- `<out>/sheets/*.png` (from `sheet.py --png`): the mock-ups and the contact sheet; `compare-<target>.png` from
  `sheet.py --compare`.
- The report also records the `style` used (path, name, hash, traits), `configSha256`, and per file its `role`,
  `tilt` and `background` (`kind`, `colours`), for the baseline's drift check.
- `<design>/`: the inspiration, directions, explorations, `decisions.md` and `baseline/` ([baseline.md](baseline.md)).

`store-listings` reads only the locales and screens its own config names, so the report and the sheets beside them
are left alone. Don't hand-edit rendered files: change the config and render again.

## Connecting it to `store-listing.json`

| `store-screenshots.json` | `store-listing.json` |
|---|---|
| `out` | `screenshots.folder` |
| each target id | a key in `screens` (with its `kind`) |
| each shot `id`, in order | `screenshots.shots[].id`, in the same order |
| a shot's `targets` | that shot's `screens` filter |
| `locales` | the locales the stores get (`stores.<store>.locales`) |
