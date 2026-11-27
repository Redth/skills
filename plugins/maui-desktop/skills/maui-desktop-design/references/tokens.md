# Tokens

`design/tokens.json` holds every colour, size and duration the app uses. `tokens.py build` generates the rest.
Nothing generated is edited by hand; everything hand-written uses the generated names. The full contract is the
plugin's `CONTRACT.md` §4.

## The layers

| Layer | Holds | Used by |
|---|---|---|
| `primitives` | raw colours: OKLCH `[L, C, H]` (or `[L, C, H, A]`) or hex | only `semantic`; never a component |
| `semantic.light` / `semantic.dark` | roles: `bg`, `surface-card`, `ink`, `ink-muted`, `accent`, `on-accent`, `danger`, … each a primitive or a mix of two | every component, page and native chrome |
| `effects` | per-theme values with alpha or composition: shadows, scrims | CSS only, verbatim |
| `scale` | space, radius, text, control sizes, z-index, motion | CSS; groups named in `outputs.csharp.scale` also reach C# |
| `modes` | alternate sets toggled by a class or attribute: density | CSS |
| `platforms` | per-platform overrides of scale entries and semantic roles | CSS (`[data-platform]`), C# (`Get(platform, …)`) |
| `contrast` | the pairs that must stay readable, separation rules, reasoned exceptions | `tokens.py contrast` |
| `lint` | what `lint.py` scans and which rules it applies | `lint.py` |

Author colours in OKLCH where you can: lightness is perceptual, so a ladder of surfaces steps evenly, and dark
themes are easier to tune. Hex primitives are fine for an existing palette.

## Naming

- Roles describe purpose, not appearance: `surface-well`, not `grey-200`; `ink-muted`, not `text-grey`.
- A surface ladder of four or five steps covers almost every app: `bg` (canvas), `surface-card`, `surface-well`
  (recessed), `surface-control` (inputs), `surface-popover` (overlays). Keep a separate `surface-console` for
  logs and terminals that must stay framed in both themes.
- Every filled role has its ink: `accent` / `on-accent`, `danger` / `on-danger`.
- Status colours come in four: `<status>-fg`, `-bg` (tint), `-border`, `-dot`.

## What the outputs contain

- **CSS** (`outputs.css`): custom properties for every role (light on the root; dark under
  `prefers-color-scheme` unless `data-theme="light"`; both again under explicit `data-theme`), every scale entry,
  the default mode, each platform's overrides under `[data-platform="…"]`, and reduced-motion durations.
- **C#** (`outputs.csharp`): `<P>Color` (every role), `<P>Rgb`, `<P>Theme`, `<P>Tokens.Get(theme, color)` and,
  with platforms, `<P>Platform` and `Get(platform, theme, color)`; scale groups you list become enums returning
  `double` pixel values per platform.
- **macOS accent** (`outputs.macosAccent`): an asset-catalog colour set. AppKit reads an app's accent from its
  asset catalog at launch, so a brand accent must reach it this way.
- **DESIGN.md**: the palette tables (with contrast against `bg`) and the platform matrix, between markers.

## How heads use it

Each head (the shell skill has the recipes):

1. **Stamps the root of every web view** before first paint: `data-platform="macos|windows|linux"` and, when the
   user picked a theme rather than "system", `data-theme="light|dark"`. With "system", leave `data-theme` off:
   `prefers-color-scheme` follows the OS and the CSS handles it.
2. **Paints native chrome from the generated C#**: window and dialog backgrounds, separators, native buttons'
   accent, a tray icon's tint. Never a hex literal in native code.
3. **Pushes run-time overrides** for facts only the OS knows: the actual window background (so a transparent web
   view sits on it exactly), separator colour, the toolbar or title-bar height content must clear, and, with
   `look.accent: system`, the user's accent. Set them as inline custom properties on the root
   (`style="--accent: …"`), re-pushed when the OS appearance changes.

Pages and components use `var(--role)` and `var(--radius-md)`, never literals. A colour that's "a bit lighter
than the card" is `color-mix(in oklch, var(--surface-card), var(--bg) 40%)` or, better, a new role.

## Static platform blocks or run-time overrides?

| | Static (`platforms` in `tokens.json`) | Run-time (pushed by the head) |
|---|---|---|
| For | design decisions known when you build | facts only the OS knows |
| Examples | base font size, font stack, radius scale, control height, row padding, a platform accent | actual window colour, separator colour, title-bar inset, the user's accent, increased contrast |
| Checked by | `tokens.py contrast`, per platform | looking at it; keep a fallback in the static tokens |

Use both. Static blocks give each platform its character; run-time overrides close the last pixel of seam.

## Accent strategies

- **brand**: one `accent` in `semantic`, also written to `outputs.macosAccent` so AppKit controls (focus rings,
  default buttons, selected sidebar rows) use it. Windows takes it through the app's accent resources.
- **platform**: `accent` overridden per platform in `platforms.<p>.semantic` (Apple's blue, the Windows default,
  Adwaita's blue). White text on Apple's system blue is about 4.0:1 and on Adwaita blue about 3.8:1, below AA's
  4.5:1: use a slightly darker filled accent for buttons with text (keep the platform blue for focus and
  selection), a dark ink, or a reasoned exception limited to large or bold labels. `tokens.py contrast` will say
  which.
- **system**: a static fallback per platform plus a run-time override from the OS; contrast is checked on the
  fallback, so pick inks that hold for any reasonable accent (white on a mid-lightness accent), or derive
  `on-accent` at run time from the accent's luminance.

## Commands

```sh
python3 <skill>/scripts/tokens.py init --blueprint desktop-blueprint.json   # design/tokens.json from the template
python3 <skill>/scripts/tokens.py build                                     # write every output
python3 <skill>/scripts/tokens.py build --check                             # CI: exit 1 if any output is stale
python3 <skill>/scripts/tokens.py contrast                                  # every pair, per theme and platform
python3 <skill>/scripts/tokens.py show --theme dark --platform macos        # the resolved values
```
