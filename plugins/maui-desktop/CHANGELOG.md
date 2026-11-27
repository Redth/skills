# Changelog: maui-desktop

All notable changes to the `maui-desktop` plugin's skills. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); each skill's `VERSION` follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
