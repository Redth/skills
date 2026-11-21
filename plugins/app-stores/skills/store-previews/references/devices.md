# Devices and sizes

## Sizes

| Slot (App Store Connect) | Preview size | Notes |
|---|---|---|
| iPhone 6.9", 6.7", 6.5", 6.3", 6.1" (Face ID, Dynamic Island) | 886×1920 or 1920×886 | one preview serves the family; record on the largest |
| iPhone Duo (two-screen) | 886×1920 or 1920×886 | the same size as any iPhone; see foldables below |
| iPad (every current size) | 1200×1600 or 1600×1200 | record on a 13" iPad |
| Mac, Apple TV | 1920×1080 | landscape only |

`video.py encode --slot <slot>` picks the size from the rules data; `--size WxH` for any other. Compose at the
preview's size: the stage (`width`, `height`) is the video.

## Frames per device class

The edit's `footage.frame` draws store-screenshots' device classes: no maker's details, buttons or camera cutout,
just a metal band, a dark bezel and the screen, its corners clipped with `clip-path` so they hold through every
move.

| frame | bezel | screen radius | for |
|---|---|---|---|
| `phone` | 3.4% | 12% | modern phones (18:9 and taller) |
| `phone-classic` | 4% | 4.5% | 16:9 phones |
| `foldable-outer` | 3.6% | 10% | a foldable's cover display |
| `foldable-inner` | 2.8% | 5% | a foldable's open display (about square) |
| `tablet` | 4.5% | 3% | iPads and Android tablets |
| `none` | 0 | 0 | the screen alone |

Percentages are of the screen's short side. Keep the store-screenshots set and the preview on the same class.

## iPhone

Dump at the stage's width (`--width 886`); the footage is 886 wide and about 1920 tall. Floating at 0.62 to 0.66
leaves room for a two-line headline above; `full` 0.8 keeps the device whole pushed in.

## iPad

A 1200×1600 stage. Dump at 1200 wide; float at about 0.6, `full` about 0.82. Headlines can be a little larger
(`headSize` 96 to 110); look at the stills.

## Foldables (iPhone Duo, Android foldables)

The store shows one size, so one video carries **both postures**: folded on the cover display, then open.

- **Folded:** the cover display's take as the main footage, `frame: "foldable-outer"`.
- **Open:** the open display's take as a second footage (`footages.inner`, `frame: "foldable-inner"`, `pan: true`):
  too wide for a portrait stage at a readable scale, so it floats at about 1.0 and the `pan` keys show one pane,
  then slide across to the other (`[[0, -357], ["@pane", -357], ["@pane+1.1", 357]]` for a 1430-wide footage).
- **Between them:** a slide (`{"slide": 1.0}`), the open device arriving from the right.
- A two-screen simulator's open display records rotated; dump it with `video.py frames --size <its landscape
  WxH>` (e.g. 1430x1006) or it comes out squeezed.
- Fold and unfold animations are the device's, not the app's: don't film or fake them; show each posture's
  screens.
