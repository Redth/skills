# Gates

Four checks keep the design language true after the first week. Run them locally while working and in CI on
every change.

| Gate | Command | Fails when |
|---|---|---|
| Generated files current | `tokens.py build --check`, `icons.py build --check` | a source changed without regenerating, or a generated file was edited |
| Contrast and gamut | `tokens.py contrast` | a declared pair is below its minimum, an OKLCH colour is outside sRGB, an exception is stale |
| Icon completeness | `icons.py build --check` | an icon lacks a mapping for a platform the app ships |
| Raw values | `lint.py` | a hand-written file has a raw colour, a pixel font size, a raw z-index (and, if enabled, a raw radius or a native `<select>`) |

## Contrast

- Declare the pairs that carry meaning: body and muted text on each surface, inks on their fills, accent on the
  canvas, status inks on their tints, the focus ring on the canvas. WCAG AA is 4.5:1 for text, 3:1 for large text
  and UI components.
- Rules are checked for each theme, and again for each platform that overrides colours.
- **Separation** rules keep two fills a user must never confuse apart (primary and destructive buttons): they
  pass by luminance ratio or by hue distance.
- An **exception** is a reasoned departure: which pair, which theme, why, and the control that compensates ("no
  filled warning button exists; warning is for icons and borders only"). An exception for a pair that now passes
  fails the check, so stale ones surface.

## Lint

- Suppress one line with a comment carrying `design-lint-ok: <reason>` on it or in the comment block directly
  above. The reason is required by convention; review it.
- Generated outputs and vendored folders are skipped.
- For an existing app, `lint.py --write-baseline` records today's counts per file and rule; afterwards only
  increases fail. Lower the baseline as files are cleaned ([adopting.md](adopting.md)).

## In the app's CI

`install.py --into build/design` copies the generators into the project with a `VERSION` file, so CI needs only
Python:

```sh
python3 build/design/tokens.py build --check
python3 build/design/icons.py build --check
python3 build/design/tokens.py contrast --quiet
python3 build/design/lint.py
```

When generated outputs are gitignored (listed in `outputs.ignored`), CI's build step runs `tokens.py build` before
compiling and the check step skips them when absent. Tracked outputs (`DESIGN.md`) are always checked.
