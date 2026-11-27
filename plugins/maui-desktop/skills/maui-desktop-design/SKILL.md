---
name: maui-desktop-design
description: >
  Use this skill to create or revise the design language of a .NET MAUI desktop app whose content is Blazor
  Hybrid (or other web content) inside native chrome on macOS, Windows and Linux: a DESIGN.md spec, one
  design/tokens.json generating the CSS custom properties and the C# constants native chrome uses, one
  design/icons.json mapping each icon to SF Symbols, Adwaita names, Segoe Fluent and an SVG sprite, per-platform
  differences (fonts, sizes, accent, radii, density) and seam rules so web content and native chrome look like
  one surface in light and dark mode. Checks contrast and gamut, lints raw colours and sizes, and ratchets an
  existing app onto tokens. Use for "design system for our MAUI app", "make it feel native on each platform",
  "dark mode looks off next to the toolbar", "tokens for CSS and native", "icons per platform". Do not use for
  deciding which parts are native (maui-desktop-blueprint), web-only sites, or mobile apps.
license: MIT
---

# maui-desktop-design

A design language for a hybrid desktop app: written down in `DESIGN.md`, made executable in `design/tokens.json`
and `design/icons.json`, generated into the CSS and the C# the native chrome reads, and kept honest by contrast
and lint gates. Platform differences live in tokens, not in pages.

## Purpose

- **One source for every colour, size and duration.** `tokens.py build` writes the CSS custom properties, a C#
  palette and scale for native chrome, the macOS accent colour set, and the palette tables in `DESIGN.md`. Native
  and web can't disagree because neither is written by hand.
- **Platform-adaptive by default.** Each platform gets its font, base size, radii, control heights and, if the
  blueprint says so, accent; components keep one structure. Facts only the OS knows (the real window colour, the
  toolbar inset, the user's accent) arrive at run time from the head.
- **One icon vocabulary.** Shared code names an icon; each platform resolves it. A missing mapping fails the
  build instead of leaving a blank button on one platform.
- **Seams that don't show.** The checklist of what must match across the native/web boundary, and the CSS that
  works in all three web engines.

## Non-goals

- Deciding which surfaces are native or web, or which platforms ship (`maui-desktop-blueprint`).
- Building the native chrome, dialogs or integrations (`maui-desktop-shell`, `maui-desktop-dialogs`, to follow).
- General visual design craft (brand, illustration, layout taste). If a general design skill is installed, it
  sets the direction; this skill makes it platform-adaptive and executable.
- Shipping components or templates. The skill describes the primitives an app needs; the agent builds them in the
  app's own conventions.

## When to use

- A new app needs its design language, after the blueprint.
- An existing app has colours written by hand in CSS and native code, or per-page styles, or per-platform hacks.
- "It looks wrong next to the native toolbar", "dark mode has a seam", "the Windows accent doesn't match".
- Adding a platform, changing the accent strategy, adding icons, or putting the design gates in CI.

## Inputs

| Input | Where | Notes |
|---|---|---|
| `desktop-blueprint.json` | the project root | Platforms, `look.fidelity`, `look.accent`, `look.theme`, `look.density`. Without one, ask those four things first |
| `design/tokens.json` | `--tokens` | Created by `tokens.py init`. Every field: [tokens.md](references/tokens.md) |
| `design/icons.json` | `--icons` | Created by `icons.py init`. [icons.md](references/icons.md) |
| `DESIGN.md` | the project root | From `templates/DESIGN.md`. [design-md.md](references/design-md.md) |
| The app's CSS and Razor | `lint.scan` | Read by `lint.py`; never rewritten by a script |

Prerequisites: Python 3.8+ (stdlib only), on macOS, Linux or Windows.

## Workflow

The scripts are in this skill's `scripts/` folder; run them with `python3`, from the user's project.

1. **Read what's there.** The blueprint, `DESIGN.md`, any token or icon files, the main stylesheet and two or
   three pages. For an existing app, run `lint.py` first: the counts show how far the app is from tokens
   ([adopting.md](references/adopting.md)).
2. **Agree the direction with the user** before writing tokens: the character in a sentence ("calm, dense,
   precise"), the neutrals (pure grey or tinted), the accent strategy and colour, density, and how far each
   platform adapts. Show the platform matrix you propose ([platform-macos.md](references/platform-macos.md),
   [platform-windows.md](references/platform-windows.md), [platform-linux.md](references/platform-linux.md)).
   **Stop for agreement.**
3. **Write the tokens.** `tokens.py init --blueprint desktop-blueprint.json` starts from a neutral, accessible
   template with the enabled platforms filled in; then edit it to the agreed direction. Keep roles semantic
   (`surface-card`, `ink-muted`, `accent`), never visual (`grey-2`).
4. **Generate and check.** `tokens.py build`, then `tokens.py contrast`. A failing pair means changing the token,
   or a reasoned exception with the control that compensates, never lowering the rule
   ([gates.md](references/gates.md)).
5. **Icons.** `icons.py init`, trim to what the app uses, add the rest, `icons.py build`. Check SF Symbol and
   Adwaita names exist; the template's are best-effort.
6. **Write `DESIGN.md`** from the template: the overview, the rules, the platform matrix and seam table
   (generated tables go between markers), the primitives the app uses, and the inventory of every page, dialog
   and window ([design-md.md](references/design-md.md), [primitives.md](references/primitives.md)).
7. **Wire the seams.** Tell the user (or the shell skill) what each head must do: stamp `data-platform` and
   `data-theme` on the web view's root before first paint, match the window background, push run-time overrides,
   read native colours from the generated C#. Check against [seams.md](references/seams.md) and the engine
   matrix in [webview-css.md](references/webview-css.md).
8. **Gate it.** `install.py` copies the generators into the project so CI can run `tokens.py build --check`,
   `icons.py build --check`, `tokens.py contrast` and `lint.py`. For an existing app, `lint.py --write-baseline`
   first, so only new raw values fail.
9. **Look.** In both themes, on every platform the app ships, at the seams: toolbar to content, sidebar to
   content, dialog frame to body, a popover over a card. Report what you see.

## Agent rules

The short form; the reasons are in [agent-rules.md](references/agent-rules.md).

1. Taste is the user's. Propose a direction with reasons; stop for agreement before writing tokens.
2. Every colour, size and duration comes from `design/tokens.json`. Never hand-write a value a generator owns.
3. Fix the token, not the gate. Contrast rules change only with the user, and exceptions name their control.
4. Platform differences live in tokens and in each head's run-time overrides, never in page styles.
5. Use the real platform control in chrome; never imitate native chrome in web content.
6. An existing app adopts by ratchet: baseline first, then fewer raw values each change. No big-bang restyle.
7. Validate in light and dark, on every platform the app ships, at the seams.
8. Don't commit unless asked. Say what's ready: the token and icon sources, `DESIGN.md`, generated outputs
   that are tracked.

## Validation

- `tokens.py build --check` and `icons.py build --check` exit 0.
- `tokens.py contrast` exits 0; every exception has a reason and a control.
- `lint.py` exits 0 (with the baseline, for an existing app).
- `DESIGN.md` has the generated tables between their markers, the platform matrix, the seam table and the
  surface inventory.
- Each head stamps `data-platform` and `data-theme` and matches the window background (checked by looking, in
  both themes).

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `contrast`: out of gamut | an OKLCH primitive can't be shown in sRGB and would clip | lower its chroma, or adjust lightness |
| `contrast`: exception now passes | the token changed and the exception is stale | delete the exception |
| `build --check`: stale | someone edited tokens without regenerating, or edited a generated file | run `build`; never edit generated files |
| `icons.py`: missing `gtk` | an icon has no Linux name | add one; the build refuses blank buttons |
| A light seam in dark mode around the web view | the web view paints its own background, or the head's isn't the token's | make the web view transparent or set its blank-page colour; push the window colour as a run-time override |
| Colours right in pages, wrong in a dialog | each web view is its own document | stamp `data-theme`/`data-platform` and load the tokens in every web view |
| A token change has no effect on one platform | a page or platform block overrides it | `lint.py`; move the override into the platform block of `tokens.json` |
| `corner-shape` or `backdrop-filter` does nothing | the engine doesn't support it yet | [webview-css.md](references/webview-css.md): treat it as an enhancement with a fallback |

## References

| File | What's in it |
|---|---|
| [tokens.md](references/tokens.md) | `tokens.json` field by field, what each output contains, how heads and pages use it |
| [icons.md](references/icons.md) | `icons.json`, the generated C#, sprite and template images, naming per platform |
| [design-md.md](references/design-md.md) | the sections of `DESIGN.md`, the generated tables, the inventory |
| [platform-macos.md](references/platform-macos.md) | matching AppKit: type, accent, radii, sheets, Liquid Glass |
| [platform-windows.md](references/platform-windows.md) | matching WinUI 3 and Fluent 2: type, accent, radii, Mica |
| [platform-linux.md](references/platform-linux.md) | matching GNOME and libadwaita; what the GTK backend lacks |
| [webview-css.md](references/webview-css.md) | CSS that works in WKWebView, WebView2 and WebKitGTK; fallbacks |
| [seams.md](references/seams.md) | the checklist for native and web to read as one surface |
| [primitives.md](references/primitives.md) | the components every app needs, and the rules for each |
| [gates.md](references/gates.md) | contrast, gamut, lint, baselines and CI |
| [adopting.md](references/adopting.md) | moving an existing app onto tokens without a big-bang restyle |
| [agent-rules.md](references/agent-rules.md) | the agent's rules with their reasons |
