# Changelog: app-stores

All notable changes to the `app-stores` plugin's skills. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); each skill's `VERSION` follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- `store-screenshots`: start from the current set (CONTRACT.md 8.7 step 0). `sheet.py --current <folder>` lays out
  the listing's current screenshots (pulled to `existing/<store>/screenshots/<locale>/<slot>/`, or any folder such as
  `assets/screenshots/<device>/`) by store and device in order, writes a skeleton `design/current.json` (schema
  `$defs/current`: each shot's screen, caption, layout, traits and the user's keep/change/drop, and the summary's
  look: keep, evolve or replace) and shows each shot beside its analysis; the storyboard starts from the shots kept
  and the inspiration board shows the set as one example. A batched first turn for users who ask for directions up
  front, its sheet headed as drafts (`sheet.py --directions ... --draft`). `sheet.py --styles` renders every starting
  style on one made-up app (`samples.py`, nothing committed) to pick by eye. A style role's `stores` gives it another
  layout or frame on one store; the app starting styles' hero is real UI on Google Play, so shot 1 no longer trips
  Play's UI-first warning.
- `store-listings`: start from what's live. `push.py pull apple|google` reads the live listing (read-only, like
  `plan`; on Google an edit opened to read and deleted) into `existing/<store>/`: `listing.json` in the contract's
  vocabulary, every screenshot and preview downloaded per locale and slot, and a `README.md` summary. App Review's
  contact is never written. `pull apple --public` needs no key: Apple's public iTunes Lookup API, per storefront
  country, for the name, description, release notes, categories, seller and screenshots, saying what isn't public
  (subtitle, keywords, promotional text…). Downloads reach only the stores' own hosts (`itunes.apple.com`,
  `*.mzstatic.com`, Play's image hosts), redirects included.
- `listing.py import --from live existing/`: the pulled listing as the draft config (merging, never overwriting;
  screenshots into the layout with ids from the uploaded file names; a field empty on the store kept empty with
  `""`), with a summary of what's live.
- `listing.py diff [--existing existing/]`: the config's resolved words and picture counts against what's live, per
  store, locale and field (unchanged, changed before → after, only live, only ours), as text or `--json`.
- `references/existing.md`; SKILL.md's first step is now "Start from what's live"; four evals for it.
- `appstores_lib.web.REDIRECT_ALLOWED`: a guard on which URLs a GET's redirect may follow.
- `stores.apple.platforms.<P>.locales`: the App Store locales one platform gets (an Apple TV version in fewer
  languages); check, build, diff and plan keep to them.
- `stores.<store>.keep`: slots whose pictures stay as the store has them (checked and previewed, never sent).
- The live import round-trips: pull → import → build → plan against the same store plans nothing. The copyright is
  kept as live (its © too), each platform's languages and the kept slots are set, and the pull records each
  platform's App Review notes.

### Fixed
- `pattern` rules skip `""` (a field cleared on purpose): Play's `video: ""` no longer fails the YouTube rule.
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
