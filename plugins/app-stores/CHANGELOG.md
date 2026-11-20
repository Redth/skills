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
- `store-capture`: staging with the user before any plan runs (`references/staging.md`): which screens tell the
  story, starting from the current set (`capture.py --current`: the storyboard, `existing/<store>/screenshots/`, a
  folder), and how the app is signed in (guest, a debug bypass, or a demo account named only by environment
  variables, checked before a run and masked in every log and report; never a real person's account), seeded (a
  command or a file copied into the app's data), skipped, granted, flagged, clocked and networked. The plan's
  `staging` section (schema), each screen's `state` and `verify` (an element that must be on screen, else the shot
  is `missed`, "wrong state"; the report's `stateCheck`), `staging.md` written by `capture.py --write-staging`,
  `staging.confirmed` before a run of more than one screen, reuse on every later capture.
- `store-capture`: the `appFile` step (a file into the app's own data: the simulator's data container, Android's
  through `run-as`); `staging.permissions` granted before launch and revoked after (`simctl privacy`, `pm grant`);
  `capture.py --inspect` (each screen's UI tree in `<out>/.inspect/`); `settle.ignore` rectangles; `target.navigation`
  (gesture or button navigation), `statusBarMobile` and `statusBarCheck` on Android; `check_captures.py` notes a
  required App Store display type no device fills; script steps also get `APPSTORES_PLATFORM`, `APPSTORES_APP_ID`
  and `APPSTORES_SERIAL`.
- `store-capture`: decision-table row for an existing pipeline that needs a real account or secrets (reuse its data
  and ids, not its run); DevFlow's limits on iOS documented, with when to switch a device to Appium; a .NET MAUI
  section on seeding local data without a screenshot mode and `-p:EmbedAssembliesIntoApk=true` for Debug APKs.

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
- `store-listings`: `push.py pull apple --public` downloads the screenshots at the uploads' own size (the lookup's
  mzstatic address with a box bigger than any upload, which Apple serves at the upload's size, never enlarged)
  instead of the web page's 320x480 to 392x696 copies, checks each against the rules' App Store sizes
  (`storeSize`), falls back to the page's copy (noted) when the full size can't be had, and keeps the old behaviour
  with `--thumbnails`. The pictures are marked `reencoded` and the README says they're the App Store's re-encoded
  copies; `import --from live` copies those at a store size into the config and lists their slots in
  `stores.apple.keep`.
- `store-listings`: `listing.py check` no longer warns that a `rules.relax` id "isn't one of <store>'s rules" when
  it's a screenshot design rule (a rules file's `design` entry, e.g. `google.design.frames`, which
  `store-screenshots`' check honours): it lists it as relaxed for `store-screenshots` and warns only for ids the
  rules data has nowhere. `appstores_lib.rules`: `RuleSet.design_ids`, `.known()`, `relaxed_design`,
  `design_rule_id()` (which `store-screenshots`' check now uses for its design findings' ids).
- `store-listings`: `listing.py import --from live` with one store pulled names the other, how to read it, and what
  a listing there still needs before the check passes (from its rules: required fields and graphics, the least
  screenshots, screens for its slots), instead of leaving the check to report them all at once.
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
- `store-capture`: the `devflow` and `ailoha` drivers could drive another app's agent (the developer's own
  simulators): they now pin the agent of the plan's app on the dedicated device (status device id, the process's
  simulator folder, Android's `pidof`), pass `--agent-port` everywhere, find it again after each launch, and refuse
  when none or several match or a named `agentPort` is another device's. On Android they pass `--device <serial>`
  and `ANDROID_SERIAL`, never take a forward another device holds, and refuse without a serial when several devices
  are attached.
- `store-capture` (DevFlow): changes go only through the CLI, retried when another client's lease turns one away
  (then a clear error); `success: false` replies fail the step with advice; an xpath the HTTP query refuses (the
  preview.14 query takes only type, automationId, text, selector) and a native view's automationId the query misses
  are found in `ui tree`; taps wait for their element; `scroll --element` falls back to scrolling; back is
  `ui navigate ..`, the host's key, then HTTP.
- `store-capture` (Android): demo mode sends Wi-Fi `fully` and hides the mobile icon (an API 36 image drew "!" and
  "3G" while the report said `overridden`), and the first time on a device enters demo mode twice (the first pass
  after a boot drew two Wi-Fi icons); the status bar is `verified` only when its pixels follow demo mode's clock
  (each read steady), else `unverified`. A missing log folder is no longer reported as a missing emulator. iOS: a `status_bar list` without the override is `unverified`, not `overridden`.
- `store-capture` (Appium): `appium:isHeadless` by default on simulators (Xcode 27 moved Simulator.app); a failed
  session reports its own cause, and the simulator it shut down is booted again (and the session retried) instead
  of later screens failing with "device is not booted".
- `store-capture`: `avdmanager` found in a versioned `cmdline-tools/<version>/` when there's no `latest`; a .NET
  Fast Deployment APK is warned about; the dry run shows the `wm size` a real run sets; no env warning on Android
  for keys `args` also carries; an opaque alpha channel no longer lists `alpha-flattened` on every shot (counted
  once in the report's `notes`); tests write only into temp folders, and every test module checks nothing was left
  beside the scripts.
- `listing.py import --from supply` (or Triple-T) after an App Store import whose primary language Play has no
  listing in no longer sets `stores.google.defaultLanguage` to that language: it's one of Play's own (the layout's
  default, the primary if Play has it, en-US, or the first).
- Play's icon check (`google.icon.transparency`) warns only on see-through pixels, not on the opaque alpha channel
  of the 32-bit PNG Play asks for. The rules gain a `format` key, `transparency`, and `appstores_lib.png` a
  `has_transparency(path)`.
