# Layouts

Each shot names a `layout`; a target or a store can override it. The examples name famous apps whose live App
Store sets used the pattern on 2026-11-14: a picture of what's current, not of what converts.

## How one design fits every size

- **Units:** everything is in `--u`, 1% of the slot's width, so a caption at `sizePct: 8` is 8% of the width on a
  1320-px iPhone shot (105.6 px) and on a 1080-px Play shot (86.4 px) alike.
- **Aspect classes:** each layout has rules per class, picked from the slot's width over its height:

  | Class | w/h | Typical slots |
  |---|---|---|
  | `tall` | under 0.6 | iPhone (0.46), Play phone 9:16 (0.56) |
  | `mid` | 0.6 to 0.85 | iPad (0.75), iPhone Duo (0.69 to 0.70) |
  | `square` | 0.85 to 1.2 | Wear OS (1:1) |
  | `wide` | over 1.2 | landscape phones and tablets, Mac 16:10, TV 16:9, XR 8:5 |

- **Overrides,** most specific first: a target's `layouts` entry for the shot, then the target's
  `layout`/`frame`/`caption`, then `stores.<store>`, then the shot, then the theme. So "framed-bleed on Apple, band on Play" is one shot with `"stores": { "google": { "frame":
  "none" } }`, and a shot that won't read on a tablet can change layout for that target alone.

## The layouts

### `fullbleed`

The capture fills the slot; a caption plate sits over it, at the top or bottom (`at`).

- **Use for** games, photo and camera apps, maps: anything whose capture is a picture rather than a list.
  Play-safe.
- **Options:** `at`: `top` | `bottom`. Choose the side where the app's own UI isn't: words over a button or the
  board read as clutter, and Apple's 2.3.3 says overlays mustn't obscure the app's primary function.
- **Examples:** Candy Crush, Royal Match, Stardew Valley (a caption band at the bottom).

### `band`

A caption band, the capture below it, no frame.

- **Use for** a distinctive UI that reads at small sizes, and Play sets (frameless by default). It gives the UI
  more of the slot than a frame does.
- **Examples:** Duolingo (a short caption in a coloured pill, the UI filling the rest), Lightroom.

### `framed`

The capture whole in a drawn frame, the caption above.

- **Use for** utilities, productivity and finance apps, where the frame says "this is an app" and the caption
  carries the benefit; and the only layout for a user's own Apple bezel (as it is: [frames.md](frames.md)).
- **Cost:** the frame shrinks the UI to about 70 to 80% of the slot's width.
- **Examples:** Notion, Uber (phones on a flat field).

### `framed-bleed`

Framed and cut off by the bottom edge.

- **Use for** most apps: the UI can be bigger, the caption gets the top third, and the bottom of an app (the tab
  bar) is rarely what sells it. The commonest app pattern observed (about 10 of 13).
- **Never** with Apple's own bezel (cropping it is forbidden); the drawn frames are fine.
- **Examples:** Headspace, Calm, Strava, Airbnb, Revolut, Spotify, Todoist.

### `tilt`

Framed and rotated in 3D (CSS `perspective` with presets), with a soft shadow.

- **Use as an accent:** one shot in a set at most, often the hero, to break a run of identical frames.
- **Options:** `tilt`: `left` | `right`, or an object with its `side` and angles in degrees (`y` the turn, `x` the
  lean back, `z` the roll) and `perspective` (u). The theme's `tilt` sets the angles for the whole set, so a style can
  match a measured set's angles; a shot's own object varies one shot. Defaults by aspect class are in `tilt.css`
  (tall: y 20, x 6, z 6, perspective 260).
- **Cost:** perspective shrinks and skews the UI, which hurts reading at thumbnail size; Play asks that images not
  be "skewed". Never with Apple's own bezel.
- **Examples:** Calm, Spotify (shots 2 and 3), Todoist and Flighty (one shot each).

### `pair`

Two framed captures at their true relative scale (a phone and a watch, a phone and a tablet, two screens of a
flow).

- **Use for** a companion app, a widget beside the app, or a before and after.
- **Options:** `pair`: the second capture's screen id.
- **Watch:** on the App Store, no other platform's device; on Play, no device imagery at all by default. Apple's
  own bezels need correct relative scale and nothing on top of them.
- **Examples:** Strava (a watch over a phone), Flighty (a lock screen beside the app).

### `callout`

`framed-bleed` plus a clipped, enlarged copy of part of the capture, lifted out with a shadow.

- **Use for** small UI that matters and would be unreadable at thumbnail size: a chart's number, a chip, a card.
- **Options:** `callout`: `{ "rect": [x, y, w, h], "scale": 1.35 }`, the rectangle as fractions of the capture
  (0 to 1 from its top left), and how much to enlarge it.
- **Rules:** it must be the app's own UI, enlarged, never redrawn. Never out of Apple's own bezel ("graphic
  elements that appear to enter or come out of the product screen" are forbidden).
- **Examples:** MyFitnessPal (food cards and chips floating past the frame), Todoist (task cards lifted out).

### `hero`

The brand and its claim large, a `proof` line, and real UI: on a tall or mid slot, the app rising from the bottom
edge under the words; on a wide or square slot (an iPhone Duo's inner display, a landscape tablet), the words in a
column at the start side and the app beside them, so the shot still shows the app in use rather than a sliver.

- **Use for** shot 1 of a brand visitors already know, or a set whose UI doesn't explain itself.
- **Options:** `caption` (the claim), `proof` (a short, true, verifiable line), `kicker` (a small line above). The
  brand mark on top is `theme.hero.logo` (`fit`: `wide` draws a wordmark or a logo with words at its own shape, no
  tile; `tile` as an icon; `widthPct` its widest in u) or else `theme.icon` (a rounded tile). A target's `hero`
  overrides it key by key (a tall, stacked logo smaller on a landscape slot).
- **Sharing the height:** the mark, the words and the app share the slot. When the block (mark, kicker, claim,
  proof) is taller than its room (beside the app, the slot less its margins; above it, enough to leave 30% of the
  slot for the app), the mark shrinks first, to 4u at the least, then the claim, never below its floor. Words or a
  mark that still leave the slot don't fit: the report says which (`caption.outside`), render.py exits 1 and
  `check.py` errors (`design.caption.outside`).
- **Rules:** Apple 2.3.3 wants the app in use, not "merely the title art": the sliver of UI is why the layout has
  one, and more than half the set must still be the app in use (`check.py` counts a `hero` as in use only when
  its real UI covers 30% of the slot or more, the report's `uiShare`: a side-by-side hero usually does). On Play, `check.py` warns about a `hero` among the first three shots: Google asks for UI first there; a
  style's role can give the hero another layout on Play (`roles.hero.stores.google`, as the starting styles do). `proof` is where unverifiable claims, rankings and
  awards creep in: the check reads it like a caption. Brand art without UI belongs in iOS 27's header or search
  asset, which Apple sanctions for it.
- **Examples:** Notion ("Your life, beautifully organized."), Headspace and Calm (logo and claim), Uber.

### `fold`

A foldable's inner display shown partly folded: the capture split at the hinge, each half on a panel of the device
turned about the hinge in 3D, so the halves meet at the seam as one screen. The panels have thickness, a drawn
generic hinge sits behind the fold, and shading darkens the crease and the far panel. It reads at a glance as "made
for the foldable".

- **Use for** the shot (or two) of a foldable set that shows the app spread across the inner display: an iPhone
  Duo's inner display, an Android book foldable's. Either fold that shot on the foldable's target alone and keep
  its layout elsewhere (`targets.<id>.layouts: {"<shot id>": "fold"}`: one shot id, one entry in
  `store-listing.json`), or give a fold-only shot `targets` for those devices.
- **Options:** `fold` (or `theme.fold` for the set): `hinge` (`auto`: vertical, left and right halves, unless the
  capture is clearly portrait, under 0.8, when it folds across; or `vertical` | `horizontal`), `angle` (the angle
  between the halves: 120 by default, 180 flat), `turn` and `pitch` (the view, degrees), and `outer`: the outer
  display's capture (a screen id on the same capture device, or `{"capture", "device"}`), shown on the back of a
  lifted panel; for that the angle must be under 90 (70 by default) so the back faces the viewer, and the inner
  display shows past it.
- **Every aspect class:** the words above, the device under them, fitted by its projected size and centred like
  `framed`; never cut by the slot. The report's frame gives the projected box and `fold` (`hinge`, `angle`, `pose`:
  `open` | `cover`, `outer`'s box).
- **Rules:** a drawn frame only (a `foldable-inner` class by default): a maker's art can't be folded. `check.py`
  warns on a fold of a capture that isn't a foldable's inner display (longer than 1.6:1), and on the outer display
  at an angle of 90 or more. On Play it's device imagery like any frame: the starting styles' `foldable` role shows
  the capture flat there.
- **Examples:** the makers' own foldable marketing (a device half open on its hinge); few app listings use it yet,
  which is why it stands out in a foldable's slot.

### `gameplay`

The capture full-bleed, no words, no frame.

- **Use for** games' sets where the play speaks for itself, Play's TV slot (at least one unaltered shot), Wear OS,
  and anywhere a store wants no words.
- **Examples:** Clash Royale (four wordless arena shots after a key-art poster), Call of Duty, Alto's Odyssey.

## Choosing

- **Apps:** `framed-bleed` as the system, `hero` or a strong UI shot first, one `tilt` or `callout` as an accent.
  On Play, the same captions with `band` or `fullbleed` (no frame).
- **Games:** `fullbleed` with a 1 to 4 word caption, or `gameplay` with none ([games.md](games.md)).
- **Keep one system:** one caption style and place, one frame, one palette across the set. Change one thing per
  shot at most.
