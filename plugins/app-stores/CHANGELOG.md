# Changelog: app-stores

All notable changes to the `app-stores` plugin's skills. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); each skill's `VERSION` follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `store-capture` 0.1.0 (#13): an app's real screens captured at exactly each store's sizes, on any stack.
  `capture-plan.json` (schema `schema/capture-plan.schema.json`: devices each promising a width and height, screens
  reached by steps, locales, appearance, clock, status bar, seed, per-device and per-screen overrides);
  `capture.py` (a driver per device, `--dry-run`, a dedicated `appstores-<device id>` simulator or emulator by
  default, everything changed put back, every picture checked: the wrong size `failed` and never resized, alpha
  flattened and reported; `capture-report.json` marking each shot taken, missed with the previous picture kept,
  failed or skipped); drivers for `simctl`, `adb`, `uiautomator`, `chrome`, `macos`, the DevFlow and Ailoha in-app
  agents, `appium`, `xcuitest` and `maestro`; `import_captures.py` (fastlane snapshot and screengrab, xcresult,
  Maestro, Flutter, Detox, Playwright, a folder, with a mapping); `check_captures.py`; `video.py` (record, encode
  to each store's preview spec with ffmpeg: constant frame rate, H.264 or ProRes, the exact size, a silent stereo
  track when there's none; check with ffprobe). The references choose a technique per app (a decision table), show
  how to add a screenshot mode on SwiftUI, UIKit, Compose, .NET MAUI, Flutter, React Native and the web, cover each
  driver, game engines, desktop, clean state and which simulator or emulator renders which store size natively
  (read 2026-11-14).
- `store-screenshots` 0.1.0 (#12): designed store screenshots from an app's real captures, one design for every
  store, size and locale. A brief and a storyboard agreed with the user before rendering; `store-screenshots.json`
  (theme, targets at each store's exact sizes, shots with their layouts and captions, per-store overrides,
  strings per locale, an optional panorama); `render.py` (HTML/CSS templates through headless Chrome, captions that
  shrink to a floor and fail there, a render report); `check.py` (sizes, alpha, counts, caption fit and words,
  Play's text share, frames per store, forbidden words in captions, missing glyphs, seams, contrast, upscaling,
  fallbacks, and the checklist a person judges); `sheet.py` (Apple's search row, the product page, Play's listing
  and a contact sheet, at real display size). Generic drawn device frames only; Play frameless by default. The
  references give each design principle its evidence grade, what each store allows (read 2026-11-14), the makers'
  device-art licences, localisation and legibility.
- `store-screenshots`: taste, directions and the baseline (CONTRACT.md 8.7). The user's examples described in a
  fixed traits vocabulary (`design/inspiration/inspiration.json`, `sheet.py --inspiration`); 2 to 4 directions
  rendered with `render.py --style ... --out ...` and laid side by side at search-row and product-page size
  (`sheet.py --directions`); `screenshot-style.json` (schema `schema/screenshot-style.schema.json`: traits, theme,
  roles, store overrides, copy rules, drift tolerances) merged over the config's theme, shots given a `role`;
  eight starting styles in `styles/` (brand-colour bold, minimal editorial, dark pro, playful saturated,
  photo/lifestyle, panoramic strip, game key art, game banner); `baseline.py approve | status | unlock` (a current
  render report required, history kept, the style locked, decisions logged in `design/decisions.md`);
  `check.py --baseline` (used by itself when a baseline exists): drift in caption size, position and lines, the
  device's box, frame and tilt, text share, colours and background, a changed locked style an error, a config theme
  against it an error, copy rules; `sheet.py --compare` (baseline and now, the drift under each pair). The render
  report gains `style`, `configSha256` and per file `role`, `tilt` and `background`.
- `store-screenshots`: template defaults from measured sets and the generators' source: captions start at 9.5u
  (floor 7u) on a tall slot (mid about 6u, wide about 4.6u), side margin 8u, caption top 12u, gap 9u, the device 86u
  bleeding 12% (76u whole), leading 1.08, two caption lines reserved so devices line up across a set; `caption.case`.
  `check.py` warns when shots 1 to 3's captions are under 9.5u (any store) and when a set's device moves more than
  0.2u or its caption top more than 0.5u.
- `store-listings` 0.1.0 (#11): one `store-listing.json` for the App Store and Google Play; the stores' rules as
  dated, sourced data (`rules/apple.json`, `rules/google.json`), checked offline; `listing.py` import (fastlane
  deliver and supply, Gradle Play Publisher, Expo), check, build (fastlane-compatible output) and preview;
  `push.py` plan and apply, refusing when the store changed since the plan.
- The shared `appstores_lib` package (PNG/JPEG reading, Chrome over the DevTools pipe, a JSON Schema subset,
  text counting, locale tables, the rules engine, requests with retries, JWT signing through openssl) and the
  sync tool that copies it into each skill.

### Added
- `store-listings`: per-platform Apple words: `locales.<loc>.apple.platforms.<IOS|MAC_OS|TV_OS|VISION_OS>`
  overrides a version's `description`, `keywords`, `promotionalText`, `whatsNew`, `marketingUrl` and `supportUrl`
  for one platform (App Store Connect keeps them per platform); the check runs each platform's words where they
  differ, and the build writes each platform's own into `listing.json` and fastlane's folders.
- `store-listings`: locales per store: `stores.<store>.locales` (default: every locale) and
  `stores.apple.primaryLocale`; a store's words fall back to its own primary (Play's `defaultLanguage`) before the
  config's. `check`, `build` and `push.py` see only each store's locales; a store's primary must be one of them.
- `listing.py import --platform` for a fastlane folder; a later Apple platform's differing words become its
  overrides; each store's `locales` and primary come from what its source had.
- `appstores_lib.chrome.Chrome.render(..., full_page=N)`: capture the whole page, up to N CSS px tall.

### Changed
- `listing.py import`: shot ids come from the file names (`01-plan-iphone.jpg` -> `plan`), `shot-NN` only for a
  folder whose names don't each name a moment; a shot only some screens have lists them; Apple screens are named
  by device class (`iphone`, `ipad`, `mac`, `apple-tv`) unless a class has two display types; Play slots with
  byte-identical pictures share one screen (`android-tablet` for both tablet slots).
- `listing.py preview --png` renders each page whole (Mac, Apple TV and Vision pages were cut off above the
  description), shows descriptions in whole lines instead of a clamp that could cut a word, and gives Play's
  developer line as the copyright's holder, not the package name.

### Fixed
- `listing.py import --from supply` (or Triple-T) after an App Store import whose primary language Play has no
  listing in no longer sets `stores.google.defaultLanguage` to that language: it's one of Play's own (the layout's
  default, the primary if Play has it, en-US, or the first).
- Play's icon check (`google.icon.transparency`) warns only on see-through pixels, not on the opaque alpha channel
  of the 32-bit PNG Play asks for. The rules gain a `format` key, `transparency`, and `appstores_lib.png` a
  `has_transparency(path)`.
