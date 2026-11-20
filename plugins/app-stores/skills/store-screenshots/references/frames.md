# Device frames

**This skill draws its own frames, fitted to each capture, and never ships, fetches or modifies anyone else's
device art.** The licensing
facts below were read 2026-11-14. They're a reading of public terms, not legal advice: when a user wants a maker's
art, tell them the terms and let them decide.

## The drawn frames: fitted to each capture

A drawn frame is drawn for the capture it holds (`scripts/frames.py`): **its screen opening is the capture's exact
size**, so nothing is letterboxed, stretched or cut, whatever the capture's shape. The bezel is the same thickness all
round (a laptop's chin aside), the body's corners follow the screen's, and the screen's corners are rounded by the
device class's radius. Pick one with `theme.frame`, a target's, a store's or a shot's `frame`; `"none"` for no frame.

| Name | Class (by the capture's shape where it says "auto") |
|---|---|
| `phone` (and the old `phone-landscape`) | auto: `phone` (the long side 1.85 times the short or more), `phone-classic` (1.6 to 1.85: 16:9), `foldable-outer` (1.3 to 1.6), `foldable-inner` (under 1.3); a target's id or capture device saying `inner`/`unfolded` or `outer`/`cover` (with `fold`, `duo` or `foldable`) picks the foldable's display |
| `tablet` (and `tablet-landscape`) | `tablet` |
| `watch`, `tv`, `laptop`, `desktop` | the class of that name |
| `phone-classic`, `foldable-outer`, `foldable-inner` | that class |

The orientation always follows the capture. A target's `device` (a class name) or the frame object's `class` says
which class when the shape can't (a foldable's outer display at 1.94:1 is a `phone` by shape).

**The classes' numbers** (`frames.py` `CLASSES`; `python3 scripts/frames.py classes` prints them), as fractions of
the screen's short side. They're approximations of each class's devices from 2024 to 2026, not any one device's
measurements:

| Class | Bezel | Screen corner radius | What it's for |
|---|---|---|---|
| `phone` | 0.034 | 0.12 | a modern phone (18:9 and taller): its display rounded at about an eighth of its width |
| `phone-classic` | 0.04 | 0.045 | a 16:9 phone: nearly square corners, so a status bar's clock in the very corner stays whole |
| `foldable-outer` | 0.036 | 0.10 | a foldable's outer (cover) display |
| `foldable-inner` | 0.028 | 0.05 | a foldable's inner display, unfolded (about square) |
| `tablet` | 0.045 | 0.03 | a tablet |
| `watch` | 0.12 | 0.24 | a smartwatch: a rounded case and strap stubs |
| `tv` | 0.014 | 0.004 | a television: a hairline bezel, two feet |
| `laptop` | 0.034 (a thicker chin) | 0.016 | a laptop's lid over a base |
| `desktop` | 0.028 | 0.008 | a monitor on a stand |

**A capture is never cut by the corners.** Before laying out, the page reads each capture's corners: where a
corner's curve would cut off content (a status bar's clock or icon in the very corner, as Android draws it), the
radius shrinks until nothing is cut. Two things don't count as content: the corner's very tip (pixels nearer the
corner than about 6% of the radius, at least 8 px), and pure-black pixels near it, which an iOS simulator's
framebuffer carries in its corners (the display's own mask: 15 or so at the top left), and a handful of stray pixels
relative to the radius. The report's frame says what happened (`corners.radiusFrom`, `reduced`, `clippedPx`);
`check.py` warns if anything is still cut, and warns when the radius was cut to under half (square corners inside a
rounded body look wrong): look at the capture's corners. **A radius the frame object sets always wins** (`radius`, 0
for square corners): the page keeps it and only reports what it cuts (`corners.radiusSet`), for the check to warn.

**The frame object** (instead of a name), for options:

```json
"frame": { "name": "phone", "class": "foldable-outer", "radius": 0.08, "bezel": 0.03,
           "buttons": true, "cutout": "punch-hole", "finish": "light" }
```

- `buttons`: generic side keys (a rocker and a key on the long edge) on phones and foldables.
- `cutout`: `punch-hole` or `pill`, a neutral black camera cutout centred over the status bar, for a capture whose
  status bar leaves room for one (an Android capture taken with the cutout hidden): it makes the gap look
  intentional. Off by default.
- `finish`: `dark` (default) or `light`.

They're generic on purpose: **no notch, Dynamic Island, Home button, camera bump or brand shape**, and on an Apple
target never side buttons or a cutout (render.py leaves them off and says so; `check.py` errors if a report shows
them). Apple's marketing guidelines say a generic device illustration must not carry "details that are unique to
Apple products, such as the iPhone Home button, sensor housing, Ring/Silent switch, or volume controls", and that
"any simulation of an Apple product" isn't permitted. A plain rounded slab simulates nobody's device, so it can be
tilted, cut off, folded and overlapped freely, and it doesn't date the set when a new phone comes out.

Configs that name the old frames (`phone`, `phone-landscape`, `tablet`, `tablet-landscape`, `laptop`, `desktop`,
`tv`, `watch`) keep working; they now draw fitted frames, so a set rendered again looks slightly different (the
render cache knows: everything renders afresh once).

## Per store

| Store | Frames | Source |
|---|---|---|
| Apple | drawn frames fine; Apple's own bezels only as they are (below) | https://developer.apple.com/app-store/marketing/guidelines/ |
| Google Play: phone, tablet, TV | discouraged: no device imagery ("can become obsolete quickly or alienate some users"). **The default is no frame**; `check.py` warns when one is used | https://support.google.com/googleplay/android-developer/answer/9866151 |
| Google Play: Wear OS | **none, required**: "do not use device frames", no backgrounds or masking | same |
| Steam, itch.io | none: gameplay, full-bleed | https://partner.steamgames.com/doc/store/assets/standard |

The rules files' `design` table holds this (`frames`, with `bySlot` for Wear OS, and `deviceArt`: Apple's
`ownAsIs`, Google's `none`); `check.py` reads it.

On Play, a user who wants frames anyway may keep them (some top apps do): it's their choice once they know Google
recommends against it and that the recommendation formats (large cards on Play's home) require the recommendations
to be met.

## The makers' device art

| Frames | Licence, as it reads | Ship them? | Can the user use them? |
|---|---|---|---|
| **Apple's product bezels** (Apple Design Resources: PSD, PNG, Keynote) | Apple Design Resources License: use "solely for creating mock-ups of user interfaces designed for use in software products that run only on Apple's macOS, iOS, watchOS, tvOS, and/or visionOS", including showing them in screenshots; no redistribution, no embedding in software, no modification or derivative works; recipients of mock-ups must be told the restrictions. https://developer.apple.com/design/resources/ and the licence, https://developer.apple.com/support/downloads/terms/apple-design-resources/Apple-Design-Resources-License-20230621-English.pdf | **No** | Yes, fetched themselves, for Apple-only apps, as they are |
| **Google's Device Art Generator** | "Do *not* use graphics created here in your feature image or screenshots for your Google Play store listing." https://developer.android.com/distribute/marketing-tools/device-art-generator | No | Not for Play listings |
| **Meta's device set** (where fastlane frameit's frames came from) | "may not be used for commercial purposes without express written permission"; for prototypes and mock-ups; device images may carry their makers' trademarks (read via a search summary, https://www.meta.com/design-at-meta/license/) | No | Doubtful for store listings |
| **fastlane `frameit-frames`** | Downloaded by frameit on first run; the repository states no licence (https://github.com/fastlane/frameit-frames) | No | At their own risk |
| **devices.css** | MIT, but its iPhone drawings copy Apple-only details | No (not the Apple ones) | Not the Apple ones |

## A maker's device art the user brings

A user may bring a maker's device art they downloaded themselves (below), and use it **as it is**. Point `frame`
at it, as a path (relative to the config) or an object:

```json
"frame": { "art": "art/bezels/phone-portrait.png", "maker": "apple" }
```

- **Its screen is found.** The PNG's see-through screen opening is the largest transparent region the art
  encloses (one not touching the picture's edge; the transparent background around the device does), read from its
  alpha with `appstores_lib.png`. The capture goes under the opening at its exact size, and the art is drawn over it
  at its own shape: never stretched, never redrawn, no shadow or reflection added. If the capture's shape differs
  from the opening, the capture is cut to fill it (never stretched) and `check.py` warns: use art for the device the
  capture came from. An art drawn larger than its own pixels is a warning too, and so is content its rounded corners
  hide.
- **Or give the screen.** For an SVG, or art the search gets wrong, put the screen in the object
  (`"screen": {"x", "y", "width", "height"}` in the art's pixels, and `screenRadius`) or in a JSON beside the art in
  the drawn frames' shape (`frames.py detect art.png --maker apple --write` writes one from what it finds, so a
  large art isn't searched on every render).
- **Say whose it is** (`maker`): the check holds it to that maker's terms. Art whose maker isn't said is held to
  Apple's on Apple targets.
- **As it is, on Apple:** the `framed` layout only (or `pair` at true relative scale). Never `tilt`, `fold` or
  `framed-bleed`, no `callout` out of it, no caption, plate or graphic over it. `check.py` fails an Apple bezel
  tilted, turned in 3D, cropped or overlapped. A `fold` with art draws a generic frame instead and says so.
- **Apple sets only** for Apple's art (Google's guidance, and an Apple device on Play is another platform's); any
  maker's art on Play is a warning (Play discourages device imagery).
- **Never committed by the agent, never copied into the skill,** never redistributed: the user keeps it where they
  put it.

### Where it comes from, and what it allows

| Art | Where | What its terms allow (as read 2026-11-19; not legal advice) |
|---|---|---|
| Apple's product bezels | Apple Design Resources, https://developer.apple.com/design/resources/ (PNG bezels per device and colour) | mock-ups of software that runs only on Apple's platforms, as they are: no tilt, crop, 3D or overlap; recipients told the restrictions. The latest generation of device |
| Google's Pixel device art | the Android developers' device art pages and Pixel press kits, where offered | the Device Art Generator's output is not for Play listings ("Do *not* use graphics created here in your feature image or screenshots"); read the page each image comes from |
| Samsung's device images | Samsung's newsroom and developer marketing pages | press and editorial use as each page states; read before using in a store listing |

When the user asks for Apple's bezel tilted, cut off or folded (common on live listings), explain that Apple's terms
forbid exactly that for its art, and offer the ways that work: the bezel whole in `framed`, or a drawn frame tilted,
cut off or folded as they like.

## What the stores' rules data says

`store-listings`' Apple rules carry an `unverified` warning (`apple.screenshots.device_frames`) reading the
marketing guidelines strictly: Apple's bezels only, unmodified. The guidelines are written for "marketing
materials", App Review's guidelines don't repeat them, and tilted, cut-off phones are common in live App Store
screenshots, so whether review enforces them on screenshots is unverified. Generic drawn frames are this skill's
answer; the warning is a reminder to the user, not a reason to block.
