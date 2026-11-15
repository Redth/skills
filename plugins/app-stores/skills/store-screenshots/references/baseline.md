# Taste, directions and the baseline

How a set gets its look from the user's taste, and keeps it across updates. Five steps; every file lives in the
user's project beside the config, under `design/` (or the folder the config's `"design"` names).

```
design/
  inspiration/           the user's examples (images) and inspiration.json
  directions/<name>/     screenshot-style.json: each candidate look
  explore/<name>/        each candidate rendered (render.py --style ... --out ...)
  sheets/                inspiration.png, directions.png
  decisions.md           what the user decided, in their words, dated
  baseline/              the approved set: baseline.json, render-report.json, screenshot-style.json, the PNGs
    history/<date>/      earlier baselines
```

## 1. Inspiration

Ask the user for 3 to 6 sets they like and 1 or 2 they don't: screenshots they saved, of any app or game. Put them
in `design/inspiration/` and describe each in `inspiration.json`:

```json
{
  "version": 1,
  "examples": [
    { "file": "liked-1.png", "source": "a to-do app's App Store listing", "likes": ["one bold line"],
      "dislikes": [], "traits": { "captionWeight": "heavy", "background": "brand-colour" } },
    { "file": "not-this.png", "source": "a game's listing", "verdict": "dislike",
      "likes": [], "dislikes": ["badges everywhere"], "traits": { "density": "packed" } }
  ],
  "summary": { "traits": { "captionWeight": "heavy", "density": "standard", "mood": "bold" },
               "notes": "Bold and plain, one stressed word, never busy.", "confirmedByUser": false }
}
```

`traits` use the vocabulary in [style.md](style.md). `sheet.py --inspiration --png` lays the examples out with their
notes (`design/sheets/inspiration.png`); show it, and set `confirmedByUser` only when the user agrees the summary.
Examples inform the style only: never their marks, illustrations, characters or trade dress. No script fetches
anything: the user brings the pictures.

## 2. Directions

Propose 2 to 4 candidate looks, each a style in `design/directions/<name>/screenshot-style.json`, from the starting
points in the skill's `styles/` or written fresh from the summary. Render only the first shots of each, on one target:

```sh
render.py --style design/directions/bold/screenshot-style.json --out design/explore/bold --shots plan,recipe,shop --targets iphone
sheet.py --directions design/explore/bold,design/explore/calm,design/explore/dark --png
```

`design/sheets/directions.png` shows each direction's first three shots in Apple's search row (each caption's size
in points) and at the product page's size, with its name and traits. The user picks; offer to mix ("the bold one's
words with the calm one's background").

## 3. Iterate

Copy the chosen style to `screenshot-style.json` beside the config and name it there (`"style"`); move the theme
out of the config (the style holds it now). One change a round: render, then `sheet.py --compare <previous out>` for
before and after. Each decision the user makes goes in `design/decisions.md`, dated, in their words:

```markdown
## 2026-11-14: captions a little smaller

"The big words crowd the phone." Caption 10.5u to 9.5u; still 11.2 pt in search.
```

## 4. Approve the baseline

When the user approves the set (all targets and locales rendered, `check.py` without errors):

```sh
baseline.py approve --note "the user's words"
```

It refuses (exit 2) unless the render report is current for the config and style: every file the config asks for
rendered from the inputs it has now (the same `inputsSha256`), unchanged on disk, and no `check.py` errors; and
unless the config's theme agrees with the style. Then it moves any previous baseline to
`design/baseline/history/<date>/`, copies the files, the report and the style into `design/baseline/`, writes
`baseline.json` (`version`, `approvedAt`, `note`, `style`, `styleSha256`, `configSha256`, `inputsSha256`, `report`,
`files`), sets the style's `"locked": true` and adds the approval to `decisions.md`.

`styleSha256` is the style's canonical JSON without `locked`, so locking and unlocking aren't changes.

## 5. Updates

A new capture, a new caption, a new locale: render as usual (the locked style is used), then

```sh
check.py                                   # uses design/baseline by itself when it's there, and says so
sheet.py --compare design/baseline --png   # <out>/sheets/compare-<target>.png: baseline left, now right
baseline.py status                         # style or config changed? report current? shots without a baseline?
```

Show the user the compare sheets every time. `--no-baseline` skips the comparison; `--baseline DIR` names another.

### What the check measures

Each file is paired with its baseline counterpart: the same locale, target and shot; else the primary locale's;
else, for a shot new since the baseline, one of the same target with the same role, else the same layout (named in
the notes). Then, against the style's `drift` tolerances:

| Measure | From the report | Default tolerance |
|---|---|---|
| caption size | `caption.fontPx` / width (u) | 5% |
| caption top and height | `caption.box` y and h (u; height only when the line count is the same and the size didn't drift) | 0.5u |
| line count | `caption.lines` | any change |
| device box | `frame.box` x, y, width, height (u) | 1u |
| frame | `frame.name`, `frame.tilted`, the shot's `tilt` | any change |
| text share | `caption.textShare` | 3 points |
| caption ink and accent | `caption.ink`, `caption.accent` | delta E 2 |
| background | `background.kind`, `colours`, `image` | any change of kind; delta E 2 a colour |
| layout | `layout` | any change |

Drift is a **warning**: the user decides whether it's fine (a longer German caption that shrank) or a fix (a caption
that ran to three lines). A changed capture changes only the pixels inside the device's screen, so it isn't drift.

Errors: **the locked style changed** since the baseline (approve a new baseline with the user, or put it back:
`design/baseline/screenshot-style.json` is the approved one), and a config `theme` key contradicting a locked style.
Warnings: a shot's own layout outside the locked style's roles, a role used more often than its `maxPerSet`, and the
style's `copy` rules (`maxWords`, `maxLines`, `case`), checked whether or not a baseline exists.

### What the tolerances mean

They're the research's "between releases" numbers: well-made sets hold the device's box to 0.1u and the caption's top
to 0.5u shot to shot, so 1u and 0.5u between releases say "the layout moved", and a headline 5% smaller is the eye's
threshold for "the type changed". Loosen one in the style's `drift` only with the user (for a set whose captions shrink
by design in long locales, `captionSize` 0.2).

### Changing the look

Never edit a locked style unasked. When the user wants a new look, it's a new approval: they say why,
`baseline.py unlock --reason "their words"` logs it, explore and iterate as above, and approve again (the old
baseline moves to `history/`).

## Exit codes

`baseline.py`: 0 done; 1 (`status`) the locked style changed; 2 refused (no current report, check errors, no style,
the theme contradicts the style); 3 usage (no config, no `--reason`).
