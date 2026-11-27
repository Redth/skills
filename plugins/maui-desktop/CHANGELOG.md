# Changelog: maui-desktop

All notable changes to the `maui-desktop` plugin's skills. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); each skill's `VERSION` follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `maui-desktop-design` 0.1.0 (#40): the design language of a hybrid desktop app. `tokens.py` (init, build,
  contrast, show) generates from `design/tokens.json` (schema `schema/tokens.schema.json`: OKLCH or hex
  primitives, semantic roles per theme, mixes, effects, scales, modes, per-platform overrides, contrast rules and
  reasoned exceptions) the CSS custom properties (themes by `prefers-color-scheme` and `data-theme`, platforms by
  `data-platform`), a C# palette and scale for native chrome, the macOS accent colour set and `DESIGN.md`'s
  palette and platform-matrix tables; `contrast` checks every pair per theme and platform, gamut, separation by
  luminance or hue, and stale exceptions. `icons.py` generates from `design/icons.json` an `IconRef` enum with SF
  Symbol, Adwaita, Segoe Fluent and SVG lookups, an inline sprite component and macOS template images, refusing
  an icon without a mapping for a platform the app ships. `lint.py` finds raw colours, pixel font sizes, raw
  z-indexes (optionally raw radii and native `<select>`) with a per-file baseline ratchet; `install.py` copies the
  gates into an app for its CI. A port of a shipping app's Node generators, checked against their output.
  Templates: a neutral, accessible `tokens.json` with macOS, Windows and Linux blocks; 28 common icons;
  `DESIGN.md`. References: tokens, icons, DESIGN.md, matching macOS, Windows and Linux, CSS across WKWebView,
  WebView2 and WebKitGTK (read 2026-11-27), the seam checklist, primitives, gates, adopting tokens in an existing
  app, agent rules.
- The `maui-desktop` plugin: `CONTRACT.md` (the blueprint, design-language, token and icon file shapes, the shared
  package and every command), `README.md`, `shared/mauidesktop_lib` (JSON in and out and the JSON Schema subset,
  copied from app-stores; findings; reading MSBuild project files; project detection; the blueprint model) and
  `tools/sync_shared.py` with a drift test.
- `maui-desktop-blueprint` 0.1.0 (#39): plans a .NET MAUI desktop app's shape with its user.
  `detect.py` reads an existing project (heads and backend versions, UI sharing, navigation, toolbar and dialog
  generation, design system, integrations, packaging) with evidence lines. `blueprint.py` drafts
  `desktop-blueprint.json` (schema `schema/desktop-blueprint.schema.json`) from detection and defaults by kind of
  app, prints the interview with a proposed answer for every undecided question, records answers in a dated
  decisions log, checks consistency (fifteen rules, from "macOS always has a menu bar" to "an in-app updater on a
  store build"), confirms only on the user's word, and writes a gap report for an existing app. References: the
  interview, native or web per surface, kinds of app, OS integrations and their cost per platform (read
  2026-11-27), detection and the two generations of this architecture, the blueprint file, agent rules.
