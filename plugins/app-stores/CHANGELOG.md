# Changelog: app-stores

All notable changes to the `app-stores` plugin's skills. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); each skill's `VERSION` follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `store-previews` 0.1.0 (#33): App Store previews (and portrait Play promo videos) composed from an app's real
  recordings. A storyboard agreed with the user first (three to five beats, one headline each, the poster frame,
  an end card with the account and subscription disclosure); an edit file (schema `schema/preview-edit.schema.json`)
  naming frames dumped by `store-capture`'s `video.py frames` (held, played, stepped, marked; times as `@mark±s`),
  dissolves and slides, camera keys (floating on the background or pushed in, never past the whole device), pan
  keys for a foldable's open display, headlines (masked line reveals), touch hotspots and a spotlight with an even,
  concentric margin; the look from a locked `screenshot-style.json` and store-screenshots' device frame classes,
  clipped with `clip-path`. `compose.py` works out each frame's footage, camera, pan and spotlight, draws it in
  headless Chrome (`templates/preview.html`, a pure function of the frame number) and encodes a master with ffmpeg
  (`--dry-run`, `--frames … --stills`). References: Apple's preview rules (read 2026-11-20), storyboard, motion,
  editing, the edit's fields, devices (iPhone, iPad, foldables folded and open), checking.
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
- `store-capture`: foldables. A device's (or screen's) `posture` (`folded`, `open`, `half-open`) and a `posture`
  step: `adb` folds an emulator through its console and a real foldable through `cmd device_state`, then wakes and
  unlocks it, finds the display in use, sets `wm size`/`wm density` again on it (each display's put back in its
  posture) and re-applies demo mode; `screencap -d` takes the display in use by itself. `simctl` opens the iPhone
  Duo simulator through DevFlow's fold control (experimental, no agent needed; `target.foldCli`, `hingeAngle`) and
  captures the screen it made active, or the one of the device's size. Each posture is its own device; two can share
  an AVD. sizes.md: the Duo's inner display captures landscape (2853x2007), and where foldable pictures go on Play.
- `store-capture`: per-layout steps that follow the base steps. A device's `layout`; screens' `overrides` keyed by
  platform, layout or device id; `stepsPatch` (prepend, append, remove, replace, insert before or after a step by its
  `name` or position; a ref that's gone is a plan error) instead of whole copies that go stale; `omit` a screen on a
  device that shows it inside another.
- `store-capture`: the keyboard. A `hideKeyboard` step (Android: back only while the keyboard is up; Appium:
  `mobile: hideKeyboard` with the iOS keyboard's Done or Return, then a Done button; `{"tap": …}` anywhere) and
  `verify`'s `{"keyboard": "hidden"|"shown"|"any"}`, checked for `hidden` by default on a screen that types nothing,
  so a shot with the keyboard up is a wrong state, not a pass.
- `store-capture`: the update path, for recapturing after the app changed. The report records the app's revision
  (`app`: git's commit, describe, date, uncommitted changes, an iOS build's version and build; each taken shot's
  `appRevision`); `capture.py --changes [revision]` lists the commits and files changed since the last capture in
  the plan's `appSource.paths` and each screen's `sources`, and the screens to re-check, each with why (its sources
  changed, a step's or verify's id or text is on a changed or removed line); a run warns when the app moved since
  the shots it keeps. SKILL.md's new step 2 and staging.md's "Updating: when the app changed": show the user what
  changed, build clean (stale build output can fail to link: .NET's `obj/` and `bin/`, Xcode, Gradle, Flutter),
  re-check the named screens one at a time, repair broken steps in the plan (a `stepsPatch` per device or layout),
  never the check. config.md recommends `normalize-space(@name)=''` (or an id) over `not(@name)` for an unnamed
  button.
- `store-capture`: `contains` in `wait` and `verify` (`{"id": "amount", "contains": "24"}`): the element found must
  show the text itself or on anything under it, ignoring case and runs of space, on `adb`/`uiautomator` (the dump),
  `devflow`/`ailoha` (the tree), `appium` (the page source), `chrome` and `macos`; `maestro` skips such a wait.
- `store-capture` (Android): a keyboard up full screen (landscape text entry on open foldables and tablets:
  `mIsFullscreen=true`) is closed with back before every tap (`adb`, and Appium and the agents on a device adb
  hosts), so a sheet's Done no longer lands on the keyboard; `hideKeyboard` handles it too; adb.md says how.
- `store-capture`: the app's own rendering bugs (text over text, clipped or truncated text, broken layouts) pass
  every automated check: SKILL.md's look-at-every-picture step and agent rules 9 and 13, the validation checklist
  and pitfalls say to look for them and report them to the user as the app's bugs, never ship or work around them.
  Three evals (an overlapping capture, an updated app, the landscape keyboard).
- `store-capture`: screens that look in use. Staging asks, for every screen, what it looks like with someone using
  it (forms partly filled with believable, fictional values; lists populated; no empty states or placeholder-only
  fields; nothing saved unless that's the point): each screen's `inUse`, and the user's rule for all of them in
  `staging.inUse` (`rule` in their words, `by`, `values`, `save`), rendered in `staging.md` (a "Looking in use"
  section and an In use column with the values each screen types) and warned about for any screen without one;
  `staging.notes` for house rules. SKILL.md's look-at-every-capture step, agent rule 13, validation and failure
  modes ask "does it look in use?".
- `store-capture`: the `fill` step: a form's fields typed in one step on every driver that types (a list of
  `{field, text}`, or `{fields, in, keyboard, unfocus, scrollTo}`): each field scrolled into view both ways within
  a pane, the keyboard closed before the next on Android, then the keyboard closed, the focus cleared and the form
  scrolled back (`scrollTo: "top"`); nothing submitted. Maestro writes it as a flow.
- `store-capture`: `scroll` takes `in` (scroll within a pane: on a two-pane layout a plain scroll swiped the other
  pane) and `to: "top"`/`"bottom"` (until the content stops moving), and `scroll {to}` looks the other way too when
  the first direction reaches its end (adb's only looked down). On iOS through Appium a scroll is a quick
  `mobile: swipe`: a direction-only `mobile: scroll` presses first at a quarter of the window, which on a small
  display focused a field and reopened the number pad.
- `store-capture`: `hideKeyboard` tries the driver's own close, the app's own Done (`done`; Appium on iOS looks
  for a button named Done, Close or Hide keyboard: a number pad has no key `mobile: hideKeyboard` can use), a
  `scroll`, and last a neutral `tap`, looking at the keyboard after each; still up, it fails naming each try and
  what's left, rather than shipping the keyboard or dropping the typing quietly.
- `store-capture`: the `unfocus` step (Android: Escape only while the dump shows a focused text field, then
  checked, failing if the screen went back instead; the web: `blur()`; a `tap` anywhere), since back closes the
  keyboard but leaves a caret blinking; `fill` ends with it, and `settle` after typing warns when a field kept the
  focus or the settled screen blinks. Three evals (a blank form caught at review, the in-use rule reused for a new
  screen, a number pad that won't close).
- `store-capture`: a `scroll`'s or `fill`'s `in` may name anything inside the pane (an id on its content, one of
  its own fields), not only the scroll view, which often has no id: what's scrolled is the nearest scrolling view
  that is it or holds it (`scrollable="true"` in Android's dump and Appium's Android source; a scroll view's,
  table's or collection view's type in Appium's iOS and Mac source, found again by its path, and in the in-app
  agents' trees; the page's overflow container on the web), else the element itself. The report's new `panes` says
  what was scrolled when it wasn't the element named, and a pane found once serves the screen's later scrolls after
  the element named has scrolled out of sight, so one `in` serves every device.
- `store-capture`: `fill` warns when a field it typed that the screen's `verify` names is out of sight once
  `scrollTo` has scrolled the form back (a `verify` sees only what's on screen); config.md and staging.md say to
  verify only what the shot shows.
- `store-capture`: a `swipe`'s `hold` (ms, default 0): the finger stays down at `from` before it moves, so a slider,
  a drag handle, a reorder or a custom pan gesture inside a scroll view drags instead of reading the touch as a scroll
  (in a real trial a `from`/`to` swipe returned 200 and the slider didn't move). Appium puts a W3C `pause` after
  `pointerDown` (iOS and Android); `adb` and `uiautomator` send `input motionevent` DOWN, a `sleep`, a few MOVEs and
  UP in one shell line, and on an `input` without `motionevent` long-press and then swipe, with a warning. Maestro,
  DevFlow and Ailoha leave it out with a warning, as does a `direction` swipe. config.md ("Dragging a slider or a
  handle"), appium.md, adb.md, a SKILL.md failure row, the schema and CONTRACT 10.2.
- `store-capture`: `capture.py --record` records a screen's steps for a preview video, from just before its first
  `launch` (after the device is prepared and any reboot a locale change needs) until a second after its last step,
  stopped before the `verify`, the screenshot and the reset, to `<out>/<locale>/<device>/<screen>.mov` (simulators,
  and the drivers they host: `simctl io recordVideo` on the display the screenshots take, so the iPhone Duo's cover
  or inner one) or `.mp4` (Android: `screenrecord` on the device, pulled after, warned about past its 180 s); other
  drivers are refused before anything runs. simctl holds a still screen's last frame back until the next change, so
  a moment's status bar change (the battery at 99 % for a second, then back) flushes it; the report's `recording`
  gives the file, its length, the step it started at, the display and the flush's time to trim at (`video.py
  encode --end`). In a real trial `video.py record --during "capture.py …"` ended as `capture.py` rebooted the
  simulator for its language, and its reset shut it down: video.md now says to use `--record`, why, how to trim the
  flush, and that the steps' `wait`s set the pacing; SKILL.md's step 9 and a failure mode say so too.
- `store-capture`: `video.py frames <video> <out-dir> [--width W | --size WxH] [--format jpg|png] [--quality N]`:
  every recorded frame, in order, numbered afresh, for an edit by frame index. A simulator recording's timestamps
  don't follow the wall clock and some clash, so seeking, `fps=` or `setpts` landed on the wrong frames and the
  image muxers dropped some in a real trial; `frames` decodes once to raw RGB with the timestamps passed through
  and pipes it into a second ffmpeg that numbers the frames. It prints the count and size, notes a stream frame
  count that differs, and notes a display-matrix rotation (written upright; `--size` forces the display's shape
  when the picture comes out squeezed, as a two-screen simulator's inner display did). video.md (editing by frame
  index, the rotated recording), SKILL.md (the video step, a failure-mode row) and CONTRACT say so.

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
- `store-screenshots`: frames that fit (`scripts/frames.py`). Drawn frames are drawn for each capture: the screen
  opening is its exact size (nothing letterboxed, stretched or cut), even bezels, and the screen's corners rounded by
  a device class (`phone`, `phone-classic` for 16:9, `foldable-outer`, `foldable-inner`, `tablet`, `watch`, `tv`,
  `laptop`, `desktop`; fractions of the short side, approximations), picked by the capture's shape, the target's
  words or its new `device`. The page reads each capture's corners and shrinks a radius that would cut content (a
  status bar's clock in the corner: the trial's ":41"); the report says what it did (`corners`). The frame object
  (`class`, `radius`, `bezel`, `buttons`, `cutout`: a neutral punch-hole or pill, `finish`); buttons and cutouts
  never on Apple targets. The old frame names keep working; `frames/*.svg` are gone.
- `store-screenshots`: a maker's device art the user brings (`frame: {"art": "...png", "maker": "apple"}`) has its
  see-through screen found from the PNG's alpha (`appstores_lib.png.decode_alpha`; `frames.py detect --write` saves
  it), the capture placed under it at the opening's size, the art never stretched and no shadow added; `check.py`
  warns when the capture is cut to fit, the art is upscaled or its corners hide content, and holds art of no said
  maker to Apple's terms on Apple targets. `references/frames.md` says where makers' art comes from and what it
  allows.
- `store-screenshots`: the `fold` layout: a foldable's inner display split at the hinge (vertical, or across for a
  portrait capture) and shown partly folded in CSS 3D (`fold.angle`, 120 by default), with panel edges, a drawn
  hinge, crease and depth shading, the halves continuous at the seam; `fold.outer` lifts one panel past upright with
  the outer display on its back. Fitted by its projected size in every aspect class, reported with its box and pose;
  `check.py` warns on a fold of a phone-shaped capture. The app starting styles gain a `foldable` role.
- `store-screenshots`: the hero beside its words on wide and square slots (real UI, not a sliver; `check.py` counts
  a hero as in use when its UI covers 30% of the slot, the report's `uiShare`); `theme.hero.logo` (`fit: wide` for a
  wordmark at its own shape, or `tile`); `theme.tilt` and a shot's tilt object (angles and perspective);
  `caption.maxWidthPct`; accents across a line break (`*whole week\nof meals*`).
- `store-screenshots`: `sheet.py --compare current` (or a folder of the live set's pictures, no render report):
  each new shot beside the live one it replaces, paired by the screen it shows (from `current.json`), else by place;
  `check.py --out` and `sheet.py --out` for an exploration (files resolve beside its report, its style used, its
  sheets beside it, counts left to the full set); targets and current-set groups ordered App Store first, iPhone
  before foldables, iPads and the rest; the report notes a role that takes another layout on Play.
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
- `store-capture`: `rate` on `type` and `fill` (the fill's, or one field's): keys a second, typed key by key so a
  recorded take shows each key land rather than the value appearing at once (Appium a `setValue` a key, `adb` and
  `uiautomator` an `input text` a key, Chrome an `insertText` a key; Maestro, the Mac and an agent's own fill put
  the value in at once and warn that the rate is left out). `references/video.md` says to use it for takes;
  `references/staging.md` says to seed again right before each capture session, as relative dates go stale.

### Fixed
- `store-capture`: a `scroll` `in` a text field with nothing that scrolls found around it no longer swipes the field
  on Appium, `adb` or `uiautomator` (each swipe tapped it and reopened the keyboard, and `scroll {"to": "top"}`
  repeated that until it gave up); the screen is scrolled instead, with a warning to name the pane. `config.md`
  notes that on iOS through Appium a `tap` scrolls its element into view, so a `scroll {to}` before it isn't needed.
- `store-screenshots`: an iOS simulator capture's black corner tip (its framebuffer's own few pure-black pixels) no
  longer squares every iPhone frame's screen corners: the corner check ignores the corner's tip, pure black near it
  and a few stray pixels; a radius the frame sets is always kept (what it cuts is reported, and `check.py` warns); a
  radius cut to under half is a warning (`design.frame.corners_squared`), not a note.
- `store-screenshots`: words or a hero's mark leaving the slot no longer report as fitting (`caption.outside`,
  render.py exits 1, `check.py` errors `design.caption.outside`); the hero's mark shrinks before its claim (never
  below the claim's floor) so mark, words and app share the height; a target's `hero` overrides `theme.hero`.
- `store-screenshots`: the render cache's hash covers every config value a file depends on (the target's frame,
  device and layouts, its store's overrides, the shots, the theme), so a target's frame change renders again.
- `store-screenshots`: `theme.hero.logo`'s `widthPct` (up to 60u) is honoured for a squarish mark, its height up to
  `maxHeightPct`; `caption.widthPct` sets the caption's box wider or narrower than the layout's; a target's
  `layouts` gives one shot another layout on that target alone (`{"plan": "fold"}` on a foldable).
- `store-screenshots`: `check.py` no longer guesses a Play slot for a target `store-listing.json`'s
  `stores.google.slots` leaves out (it isn't sent, so it's counted in no slot); a render report outside the config's
  `out` resolves its files beside itself.
- `store-screenshots`: captions on an Apple phone slot are sized as a phone's whatever its shape. An iPhone Duo's
  outer display (1398x2034) and inner display (2007x2853) and the 3.5-inch iPhone (640x960) are mid-shaped. They
  took the iPad's caption factor (0.64), so a locked style's 9.8u came out at 6.3u. That is about 7.4 to 8.3 pt in
  Apple's search row, where `check.py` already judged them as phones (three across) and warned. The new
  `scripts/slots.py` decides a slot's caption class for both scripts: its aspect class, but `tall` for an App Store
  target sized as an iPhone display type in portrait. `render.py` passes it to the page (the job's
  `slot.captionClass`, `body[data-caption-class]`, which now carries `--caption-factor`). The slot keeps its shape's
  margins and device sizes; only the words take the tall size. `check.py`'s first-shots size goes by the same
  class. A target's `captionClass` overrides it (schema, config.md), and the report gives each file's
  `captionClass` beside its `aspectClass`. **Visible change:** such targets render with bigger captions (9.8u
  where they were 6.3u), and with an approved baseline `check.py` reports the caption size and the class as drift.
  The class is always reported, whatever the style's tolerances. `"captionClass": "mid"` on the target keeps the
  old size. iPad, Play and other Apple targets are unchanged.

- `store-capture`: `text` and `label` match the same way on every driver, as config.md promised: exactly, then
  ignoring case and surrounding space, then contained (Appium's iOS and Mac predicates `==[c]` and `CONTAINS[c]`,
  its Android and Windows XPaths `translate()` and `contains()`, the in-app agents' trees, the Mac's AppleScript);
  the drivers that read a tree themselves evaluate XPath 1.0's everyday part (`contains()`, `not()`, `and`/`or`,
  `translate()`, positions), where ElementTree's subset failed a cross-platform xpath; a CoreSimulator hiccup
  ("server died") booting, installing, launching or capturing is tried once more; `capture.py --current` lists
  `design/current.json` by group and order with what each shot shows, its capture and caption (it printed "?");
  staging.md and SKILL.md: `staging.confirmed` only on the user's own answer, never a relayed one: stop and ask with
  the first picture attached. The report drops entries for screens, devices or locales the plan no longer has
  (removed or omitted), named in its `notes`; entries a filtered run didn't reach are still kept.
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
- `store-capture` (Appium): a session on a simulator could be answered by another Appium server's WebDriverAgent on
  the shared default port 8100, and our app's launch and terminate commands went into that server's simulator
  ("invalid session id" right after the session started). Each simulator device now gets its own
  `appium:wdaLocalPort` (8130-8199) and `appium:mjpegServerPort` (9130-9199) from its id, never 8100; a port
  something already listens on is passed over (a WebDriverAgent is kept only when its `/status` names our
  simulator) and the log and the device's warnings say so; a port the plan sets is kept. `--dry-run` prints the
  ports and the report's `devices` entry records them (`source.wdaPort`, `source.mjpegPort`); "invalid session id"
  on iOS says what it may be. appium.md (running beside other Appium servers) and pitfalls.md also say that
  XCUITest's driver closes Simulator.app's windows when a session starts, even headless: tell the user.
- `store-capture` (Appium): `appium:isHeadless` by default on simulators (Xcode 27 moved Simulator.app); a failed
  session reports its own cause, and the simulator it shut down is booted again (and the session retried) instead
  of later screens failing with "device is not booted".
- `store-capture` (Android): an AVD's `systemImage` missing from the SDK in use (`$ANDROID_HOME`, else
  `$ANDROID_SDK_ROOT`) fails the device once before `avdmanager` runs (and in `--dry-run`), naming that SDK, the
  other SDK folders that have the image (`$ANDROID_SDK_ROOT`, `$ANDROID_HOME`, Android Studio's and Homebrew's
  default places) and the `sdkmanager --sdk_root` that installs it, instead of avdmanager's "Package path is not
  valid. Valid system image paths are: null" on every screen; that avdmanager error is explained the same way when
  no variable names the SDK. The emulator gets `ANDROID_SDK_ROOT` when only `ANDROID_HOME` is set ("Cannot find AVD
  system path" otherwise); `base.spawn` logs the variables it adds.
- `store-capture` (Android foldables): the unlock after a posture change waits for `sys.boot_completed`, then tries
  wake and `wm dismiss-keyguard` up to four times with a longer wait each (adding `input keyevent 82`) before warning
  "the lock screen is still up": an emulator booted fresh and unfolded at once kept its lock screen over the first
  dismiss and the screen was missed. adb.md (The SDK, Foldables), pitfalls.md and SKILL.md say so.
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

### Changed

- `listing.py import`: shot ids come from the file names (`01-plan-iphone.jpg` -> `plan`), `shot-NN` only for a
  folder whose names don't each name a moment; a shot only some screens have lists them; Apple screens are named
  by device class (`iphone`, `ipad`, `mac`, `apple-tv`) unless a class has two display types; Play slots with
  byte-identical pictures share one screen (`android-tablet` for both tablet slots).
- `listing.py preview --png` renders each page whole (Mac, Apple TV and Vision pages were cut off above the
  description), shows descriptions in whole lines instead of a clamp that could cut a word, and gives Play's
  developer line as the copyright's holder, not the package name.
