# The style file: `screenshot-style.json`

A style is the look a set keeps across updates: the theme (palette, background, caption, frame), the roles shots play,
store overrides, rules for the words, and how far a later render may drift from the approved baseline. It's separate
from `store-screenshots.json` so the look can be explored, compared, approved and locked on its own, while the config
keeps what changes every release (targets, shots, strings, captures). The schema is
`schema/screenshot-style.schema.json`; the traits vocabulary lives there once, in `$defs` (`trait-*`), and
`design/inspiration/inspiration.json` uses the same words.

## The file

```json
{
  "version": 1,
  "name": "Brand-colour bold",
  "locked": false,
  "traits": { "captionPosition": "top", "captionSize": "standard", "captionWeight": "heavy",
              "emphasis": "accent-word", "device": "realistic", "devicePlacement": "bleed-bottom",
              "background": "brand-colour", "density": "standard", "mood": "bold" },
  "theme": {
    "palette": { "background": "#1E4FD6", "ink": "#FFFFFF", "accent": "#FFD24D" },
    "background": { "kind": "color" },
    "caption": { "placement": "top", "align": "center", "maxLines": 2, "weight": 800, "sizePct": 9.5, "floorPct": 7.0 },
    "frame": "phone"
  },
  "roles": { "hero": { "layout": "hero" }, "feature": { "layout": "framed-bleed" }, "whole": { "layout": "framed" },
             "detail": { "layout": "callout" }, "accent": { "layout": "tilt", "maxPerSet": 1 } },
  "stores": { "google": { "frame": "none" } },
  "copy": { "maxWords": 5, "maxLines": 2, "case": "sentence", "emphasis": "one accent word at most" },
  "drift": { "captionSize": 0.05, "captionPosition": 0.005, "deviceBox": 0.01, "textShare": 0.03, "colour": 2 }
}
```

| Field | Meaning |
|---|---|
| `name` | what the user calls it ("the bold blue one") |
| `locked` | set by `baseline.py approve`, cleared only by `baseline.py unlock --reason` ([baseline.md](baseline.md)) |
| `traits` | the look in the fixed vocabulary below; for people and the sheets, not the renderer |
| `theme` | the same object as the config's `theme` ([config.md](config.md)); the renderer uses it |
| `roles` | `{role: {layout, frame?, tilt?, at?, maxPerSet?}}`: the layout each kind of shot gets |
| `stores` | per-store overrides, as the config's |
| `copy` | `maxWords`, `maxLines`, `case` (`sentence`, `title`, `upper`, `lower`, `any`): `check.py` warns on captions that break them; `emphasis` is guidance in words |
| `drift` | tolerances against the baseline: `captionSize` relative (0.05 = 5%), `captionPosition` and `deviceBox` as fractions of the slot's width (0.01 = 1u), `textShare` an absolute share, `colour` a CIE76 delta E |

## How it joins the config

- The config names it: `"style": "screenshot-style.json"` (relative to the config). `render.py --style FILE` uses
  another for one run (an exploration, with `--out design/explore/<name>`).
- **The style wins.** The config's `theme` and `stores` are merged under the style's, key by key (into `palette`,
  `caption`, `background`); anything the style doesn't set comes from the config.
- **Roles.** A shot may give `"role": "feature"` instead of a `layout`; the style's roles give it the layout (and
  `frame`, `tilt`, `at` where the shot has none). A shot's own `layout` still wins over its role, and store and target
  overrides beat both (target, then store, then shot, then theme, as before). A role the style lacks is a usage error.
- **Locked.** Once a baseline is approved the style is locked: a config `theme` key that contradicts it is a check
  error, a shot whose own layout none of the roles use is a warning, and a change to the style itself is an error until
  a new baseline is approved with the user.
- `caption.case` (`upper` or `lower`) draws the words in that case without changing the strings.

## The traits vocabulary

From the screenshot-craft measurements (19 sets measured shot by shot, the generators' source, and 26 sets surveyed
before). Each trait has a closed set of values; an example may list two.

| Trait | Values | What it maps to |
|---|---|---|
| `captionPosition` | `top` · `bottom-band` · `bottom-plate` · `side` · `over-shot` · `none` | the layout and `caption.placement` (`band`, `fullbleed` with `at`, `gameplay`) |
| `captionAlign` | `center` · `start` | `caption.align` |
| `captionSize` | `quiet` (7u or less) · `standard` (8-10u) · `loud` (11u or more) | `caption.sizePct` |
| `captionWeight` | `regular` · `medium` · `bold` · `heavy` | `caption.weight` (400, 500, 700, 800-900) |
| `captionCase` | `sentence` · `title` · `upper` · `lower` | `caption.case`, `copy.case` |
| `emphasis` | `none` · `accent-word` · `bold-lead` · `lead-and-grey` · `hand-drawn-mark` · `highlighter` | `*word*` in the strings (accent-word); the others are art the templates don't draw |
| `lines` | `one` · `two` · `three-with-subtitle` | `caption.maxLines`, `copy.maxLines`, a `proof` line |
| `support` | `none` · `eyebrow` · `tag-pill` · `icon-above` · `subtitle` | a shot's `kicker` and `proof`, `theme.icon` on the hero |
| `device` | `none` · `frameless` · `outline` · `realistic` · `panel` | `frame` (`none` draws a bare rounded screen; `phone` the drawn device) |
| `devicePlacement` | `whole` · `bleed-bottom` · `bleed-top` · `bleed-side` · `tilted` · `pair` · `callout` | the layout (`framed`, `framed-bleed`, `tilt`, `pair`, `callout`) |
| `deviceSize` | `small` (74u or less) · `standard` (75-86u) · `big` (87u or more) | the layout's device width |
| `background` | `light` · `brand-colour` · `colour-per-shot` · `gradient` · `dark` · `photo` · `illustration` · `continuous` | `theme.background` and the palette; `continuous` is a panorama |
| `colour` | `monochrome-brand` · `one-accent` · `rotating` · `photographic` · `dark-neon` | the palette |
| `density` | `airy` (caption top 19u or lower, a gap of 20u or more) · `standard` · `packed` (badges, chips, fine print) | spacing |
| `decoration` | `none` · `shapes` · `hand-drawn` · `mascot` · `chips` · `awards-hero` | art the user owns (the templates draw none) |
| `mood` | `calm` · `premium` · `technical` · `playful` · `bold` · `warm` · `editorial` | what the others add up to |
| `story` | `feature-a-shot` · `parallel` · `problem-answer` · `strip` | how the captions run (copy guidance) |

Describe an example by what it does, in these words, never by copying it: its marks, illustrations, characters and
trade dress are its owner's.

## The starting points (`styles/`)

Eight named directions, each a style file to copy into `design/directions/<name>/screenshot-style.json` and adapt
(the brand's colours and font in `theme`; keep the sizes unless the eye says otherwise). Each file's `$comment` says
who it suits. The public apps named are where the pattern was seen on 2026-11-14, described and never copied.

| File | Direction | Suits | Seen in |
|---|---|---|---|
| `brand-bold.json` | Heavy caption at the top, one accent word, a drawn phone bleeding about 12% off the bottom, the brand's flat colour | most utilities, productivity and consumer apps with a strong colour: the safest default | Things, Crouton, Bears Gratitude, Monzo, CARROT Weather |
| `minimal-editorial.json` | Left-aligned bold words on warm off-white, frameless screens, one accent at most, airy | design-led and premium brands with clean UI | Notion, Airbnb |
| `dark-pro.json` | Near-black gradient, white words, one bright accent, the device whole | cameras, finance, developer and pro tools, dark-UI apps | Halide, Revolut, Superlist, Flighty |
| `playful-saturated.json` | Loud heavy words with a colour word, a saturated glow, frameless screens | consumer, education, wellness, apps with a mascot | Headspace, Duolingo |
| `photo-lifestyle.json` | A photo behind (ships with a gradient: add the user's photo), medium words, the device bleeding or tilted | travel, wellness, fitness, finance cards | Calm, Monzo's later shots |
| `panoramic-strip.json` | One background running across shots 2-3 (the config's `panorama`), each slot still a whole ad | a story across shots when shot 1 stands alone | Calm's shots 3-4, MyFitnessPal |
| `game-key-art.json` | Key art first (one short line on a scrim), then full-bleed gameplay with no words | games whose play reads at a glance; Steam always | Clash Royale, Alto's Odyssey, Stardew Valley |
| `game-banner.json` | Full-bleed gameplay with a band of the brand's colour at the foot, heavy capitals, imperative verbs | mobile games where one line of action sells each shot | Royal Match, Monopoly GO |

The app styles share role names (`hero`, `feature`, `whole`, `detail`, `accent`, `pair`), so one config's shots render
in any of them; the game styles use `key-art`, `gameplay` and `banner`.

## The numbers behind the defaults

The templates' geometry comes from the same measurements (medians on a tall slot): side margin about 8u, caption top
12u with the caption centred a little high in the room above the device, gap to the device 9u or more, the device
86u wide bleeding about 12% of its height (76u when whole), leading 1.08, tracking -0.015em, two lines reserved so
every shot puts its device in the same place. Sources: the measured listings (`https://apps.apple.com/us/app/id<id>`),
goldie (https://github.com/software-mansion-labs/goldie/blob/699578c/src/layouts.ts), the ParthJadhav skill
(https://github.com/ParthJadhav/app-store-screenshots/blob/e889033/skills/app-store-screenshots/SKILL.md), Koubou
(https://github.com/bitomule/koubou/blob/11c5a12/skills/koubou/design-guide.md) and fastlane frameit
(https://docs.fastlane.tools/actions/frameit/).
