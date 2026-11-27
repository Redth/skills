# Adopting tokens in an existing app

An app with a hand-kept stylesheet, colours repeated in native code and per-page styles gets onto tokens by
ratchet, not by a big-bang restyle. Each step ships.

## Steps

1. **Measure.** `lint.py` with every rule on shows the raw colours, pixel font sizes and z-indexes per file.
   `detect.py` (blueprint skill) counts `.platform-*` selectors and hex values.
2. **Capture what exists.** Write `design/tokens.json` from the current stylesheet's custom properties: the same
   role names (add aliases later), the same values as hex primitives. Platform blocks come from the existing
   per-platform overrides. Generate, and diff the generated CSS against the hand-kept one: the variables should
   match before anything else changes.
3. **Swap the source.** Load the generated CSS instead of the hand-kept variable blocks; delete those blocks. The
   app looks identical.
4. **Native chrome.** Replace colour literals in native code (form themes, title-bar colours, dialog palettes)
   with the generated C#. This is where drift hides: compare each literal with the token it should be before
   replacing it, and fix the drift deliberately.
5. **Baseline.** `lint.py --write-baseline`, and add the gates to CI. From here, no file can get worse.
6. **Ratchet.** Clean a page or component at a time (literals to roles, per-page platform hacks into the platform
   blocks, page-level modal and dropdown styles into shared primitives); lower the baseline with each.
7. **Then improve.** With every value in one place, retune: OKLCH primitives, the surface ladder, contrast pairs.

## Things to expect

- **Palette drift** between the stylesheet and native code. A real example: a dialog separator `#EBEBEF` in native
  code while the design doc said `#e8e8ec`. Decide which is right; don't carry both.
- **Accents that disagree across the boundary** (a purple native title bar over a blue web accent). One source
  fixes it for good.
- **Per-platform selectors that grew page by page.** Move what's a token (sizes, radii, colours) into
  `platforms`; what's a component shape belongs to native-faithful fidelity and stays in the component's styles,
  scoped and documented.
- **Aliases.** Old variable names in many files can stay as aliases (`--bg-primary: var(--surface-canvas)`) in a
  small hand-written file the lint allows, removed as pages move over.
