# The edit file

`edit.json`, checked against `schema/preview-edit.schema.json` by `compose.py`. Paths are relative to the edit.
Times are seconds from the start (negative: already under way at the first frame) or a mark (`@name`,
`@name+s`, `@name-s`). Positions on the footage (touch points, a spotlight's rect) are the dumped frames' pixels.
`examples/sample-edit.json` is a complete one.

## Top level

| Field | Required | What it is |
|---|---|---|
| `name` | yes | names the output: `<out>/<name>/` (the frames) and `<out>/<name>-master.mp4` |
| `width`, `height` | yes | the stage, the video's size: 886×1920 for an iPhone or iPhone Duo preview ([devices.md](devices.md)) |
| `fps` | | the output rate; 30 (the default and Apple's maximum) |
| `framePattern` | | a take's frame files, printf style; default `frame-%05d.jpg` (`video.py frames`) |
| `style` | | a locked `screenshot-style.json` from `store-screenshots`: its palette (`background`, `background2`, `ink`, `accent`), first font and image background |
| `styleRoot` | | where the style's relative paths are, when not beside it (usually the screenshots config's folder) |
| `theme` | | over the style, or instead of one: `background`, `background2` (the gradient's top and bottom), `ink`, `accent`, `font`, `fontSrc`, `fontWeight`, `backgroundImage` |
| `background` | | an image for the background, over the theme's |
| `headSize` | | the largest headline size, px (default 90); every headline gets the largest size at which all their lines fit |
| `headTop` | | headlines' top, px (default 232) |
| `slideShift` | | how far a slide moves the screens, px (default 720) |
| `footage` | yes | the main footage ([below](#footage)) |
| `footages` | | more footages by name, e.g. `inner` for a foldable's open display |
| `segments` | yes | the timeline ([below](#segments)) |
| `camera` | | `[time, k]` keys: 0 floating, 1 pushed in; default `[[0, 0]]` ([motion.md](motion.md)) |
| `pan` | | `[time, x]` keys (stage px) for a footage with `pan` |
| `overlays` | | headlines, touches and spotlights ([below](#overlays)) |
| `endOut` | | when the screen sinks away for the end card |
| `end` | | the end card ([below](#the-end-card)) |

## Footage

| Field | What it is |
|---|---|
| `w`, `h` | the dumped frames' size (required) |
| `frame` | the drawn device frame: `phone` (default), `phone-classic`, `foldable-outer`, `foldable-inner`, `tablet`, or `none` |
| `full` | the scale pushed in (camera 1); keep the whole device on the stage, about 0.8 for a phone at the stage's width |
| `float` | `scale` and `cy` (the centre's height on the stage) floating (camera 0); default 0.64 and 62% down |
| `pan` | a wide screen shown a pane at a time: it stays floating, moved by the `pan` keys; no spotlight on it |

The frame's bezel and the screen's corner radius are store-screenshots' device classes (fractions of the screen's
short side), so the video's device matches the screenshots'.

## Segments

A list, in order, of:

- **frames:** `{"frames": "<folder>", "footage": "<name>"?, "ops": [...]}`; ops are `["hold", frame, seconds]`,
  `["play", first, last]`, `["play", first, last, step]` and `["mark", name]` ([editing.md](editing.md)).
- **a dissolve:** `{"dissolve": seconds}`: the next segment fades in over the last seconds of the one before.
- **a slide:** `{"slide": seconds, "shift": px?}`: the outgoing screen holds its last frame and leaves left, the
  next arrives from the right. Between footages (cover to open display), use a slide.

A transition overlaps: the edit is shorter by its length.

## Overlays

| kind | Fields |
|---|---|
| `headline` | `lines` (1 to 3; `[words]` in the accent colour), `in`, `out`, `top` (px) |
| `touch` | `at` `[x, y]`, `in`, `press`, `hold` (s, default 0.2), `out`; a drag adds `to`, `moveIn` (default `press`), `moveFor` (s, default 0.9) |
| `spotlight` | `rect` `[x, y, w, h]`, `r` (the element's corner radius), `pad` (an even margin), `dim` (0 to 1, default 0.5), `in`, `out` |

`out` must come after `in`. Touches and spotlights are on the main footage.

## The end card

| Field | What it is |
|---|---|
| `in` | when it starts building (required) |
| `name` | the app's name (required) |
| `mark` | the app's icon or mark (an image) |
| `by` | who makes it |
| `tagLines` | one to three short lines, `[words]` accented |
| `fine` | the disclosure: an account requirement, what a subscription adds |
| `top` | the mark's top, px (default 520); the rest stacks below it |
