---
name: store-capture
description: >
  Use this skill to take our app's App Store or Google Play screenshots on every iPhone, iPad, Android phone,
  tablet, TV or Mac size the stores need, in every language, with a clean status bar and demo data; capture
  from a simulator, emulator, device, browser, Mac window or game engine; drive the app there with its in-app
  agent (DevFlow for .NET MAUI, Ailoha), Appium, XCUITest, UI Automator, Maestro, simctl or adb; add a
  screenshot mode (a launch argument or deep link) to the app; import fastlane snapshot, screengrab, xcresult,
  Maestro, Flutter, Detox or Playwright screenshots; check captures' sizes; or record and encode an App Store
  preview video. Any stack. Do not use for designing, captioning or framing screenshots (store-screenshots),
  the listing's words or sending it to a store (store-listings), building, signing or uploading the app, or
  UI testing, test automation or videos that aren't for a store listing.
license: MIT
---

# store-capture

Captures an app's real screens, and records its preview videos, at exactly the pixel sizes the stores take, on
any stack. A `capture-plan.json` names the devices (each with the size it promises) and the screens (each reached
by steps); `capture.py` runs a driver per device and writes a folder of clean PNGs and a report saying what was
taken, missed, failed or skipped. The folder is what `store-screenshots` designs from and what `store-listings`
sends as it is.

## Purpose

- **The right technique for the app.** A screenshot mode in the app, the in-app agent it already has (DevFlow,
  Ailoha), Appium, the platform's UI automation (XCUITest, UI Automator, Maestro, macOS Accessibility), the
  command-line tools alone (`simctl`, `adb`), headless Chrome for the web, or importing what another tool already
  makes. The decision table is below and in [references/choosing.md](references/choosing.md).
- **Exact sizes from the device, never from resizing.** Each device is chosen (or set with `wm size`, a viewport,
  an engine's render size) so its framebuffer *is* a store size. A capture of any other size is `failed`.
- **Clean, repeatable state:** demo data from a seed, a fixed clock, a clean status bar, one locale and appearance
  at a time, everything changed put back afterwards.
- **An honest report:** `capture-report.json` marks every shot `taken`, `missed` (the previous picture kept, or
  none), `failed` or `skipped`, with the reason.

## Non-goals

- **Design.** Captions, frames, backgrounds and layouts are `store-screenshots`. This skill hands it raw captures.
- **The listing.** Words, the stores' checks of the whole listing and sending are `store-listings`.
- **Resizing to fit.** A wrong size is a failure to fix at the device, never a resize. Only lossless repairs are
  made (flattening alpha, 16-bit to 8-bit, converting to sRGB), and each is reported.
- **Building, signing or uploading the app.** The plan points at a build the user made.
- **General UI testing.** The drivers reach screens for the stores; they don't assert behaviour or replace a test
  suite. An existing suite is a way in (`flow`), not something to rewrite.

## When to use

- "Take screenshots of our app on every iPhone and iPad size", "capture the Play screenshots from the emulator".
- "Do it in German, Japanese and Arabic too", "light and dark", "with 9:41 and a full battery".
- "Our MAUI app has DevFlow: get the store screens", "use our Appium tests / Maestro flows for the screenshots".
- "Add a screenshot mode to the app so we can capture without tapping through it."
- "Import our fastlane snapshot / screengrab / Maestro / Detox / Playwright screenshots."
- "These screenshots were rejected for their size", "Play says our screenshots are too tall."
- "Record an App Store preview video", "make this recording fit Apple's preview spec."

## Inputs

| Input | Where | Notes |
|---|---|---|
| The app's stack and how it can be driven | the project | a screenshot mode? an in-app agent? UI tests? Appium? fastlane? Ask what isn't in the code |
| The stores and devices | `store-listing.json`'s screens, or ask | each device's size from the stores' rules (`rules/apple.json`, `rules/google.json`): [references/sizes.md](references/sizes.md) |
| A build of the app | the plan's `app` (`.app`, `.apk`, a local URL, an installed bundle id) | a debug or screenshot build, made by the user; never a store build with debug tools in it |
| `capture-plan.json` | the user's project (`--plan`, default `./capture-plan.json`) | every field: [references/config.md](references/config.md); schema `schema/capture-plan.schema.json` |
| Demo data | the app's own fixtures, seeded by `seed` | fictional people and places only: [references/clean-state.md](references/clean-state.md) |

Prerequisites: Python 3.8+ (stdlib only), and the tools of the technique chosen: Xcode for `simctl` and
`xcuitest`, the Android SDK's platform-tools (and emulator) for `adb` and `uiautomator`, the DevFlow or Ailoha CLI
for those agents, an Appium 2/3 server and its drivers, the Maestro CLI. Google Chrome or Chromium (`CHROME`
overrides where it's found) for web apps, and to redraw a picture that needs a lossless fix (alpha, 16 bits, a
colour profile). `ffmpeg` and `ffprobe` for video. Each is looked for at run time, never bundled, and its absence
is explained, not worked around.

## Workflow

The scripts are in this skill's `scripts/` folder; run them with `python3`, from the user's project.

1. **Find out, then choose a technique.** Read the project: its stack (Swift/SwiftUI, Kotlin/Compose, .NET MAUI,
   Flutter, React Native/Expo, web, a Mac app, a game engine), whether it already has a screenshot mode, an in-app
   agent (`AddMauiDevFlowAgent`, an Ailoha package), UI tests (XCUITest, Espresso/UI Automator, Maestro flows,
   Appium, Detox, Flutter `integration_test`, Playwright) or a fastlane `Snapfile`/`Screengrabfile`. Ask which
   stores, devices and locales are needed if `store-listing.json` doesn't say, and take each device's size from
   the stores' rules ([references/sizes.md](references/sizes.md)). Then choose, first match wins, and say why:

   | The app | Technique | Driver | Reference |
   |---|---|---|---|
   | Another tool already makes good captures (fastlane snapshot or screengrab, Maestro, Detox, Playwright, Flutter, an engine) | import them; don't rebuild what works | `import` | [importing.md](references/importing.md) |
   | The user can change the app | add (or use) a **screenshot mode**: a launch argument or deep link opens a named screen with demo data | `simctl`, `adb`, `chrome`, `macos` | [screenshot-mode.md](references/screenshot-mode.md) |
   | .NET MAUI with the DevFlow agent in its debug build | the agent's visual tree and actions | `devflow` | [devflow.md](references/devflow.md) |
   | Has the Ailoha agent (MAUI, Android, Flutter, React Native/Expo, WinUI, WPF and others) | the agent's UI tree and actions | `ailoha` | [ailoha.md](references/ailoha.md) |
   | Has an Appium suite, or many platforms (iOS, Android, Mac, Windows) to reach the same way | WebDriver to a local Appium server | `appium` | [appium.md](references/appium.md) |
   | Has XCUITest screenshot tests or Maestro flows (or Android UI tests) | run them as a `flow` (Android tests: run them, then import) | `xcuitest`, `maestro`, `import` | [ui-automation.md](references/ui-automation.md) |
   | Reaches every screen by launch arguments or deep links already | the command-line tools alone | `simctl`, `adb` | [simctl.md](references/simctl.md), [adb.md](references/adb.md) |
   | A web app or PWA | headless Chrome at the device's viewport × scale | `chrome` | [web.md](references/web.md) |
   | A Mac (or Windows) desktop app | Accessibility and window capture, or the app's own render | `macos`, `appium` | [desktop.md](references/desktop.md) |
   | A game (Unity, Godot, Unreal) | the engine renders each picture at the exact size; import its folder | `import` | [engines.md](references/engines.md) |

   Techniques mix: one device by `devflow`, another by `adb`. Where none fits and the app can't change, say so and
   offer the screenshot mode as the change that makes it possible.
2. **Clean state.** Decide with the user what each screen shows: demo data (a seed, fictional names, `example.com`),
   a fixed "now" that matches the status bar's time, a clean status bar (`9:41`, full signal and battery, no
   notifications), the locale and the appearance. Grant permissions before launch so no prompt shows; turn off
   animations, debug banners and touch indicators. Detail: [references/clean-state.md](references/clean-state.md).
3. **Write `capture-plan.json`.** The devices, each with the exact `width`×`height` a store takes and the
   `driver` and `target` that produce it natively ([references/sizes.md](references/sizes.md)); the screens, each
   reached by steps; `locales`, `appearance`, `clock`, `statusBar`, `seed`. Every field:
   [references/config.md](references/config.md). Name dedicated devices (`appstores-<device id>`), never the
   user's own, unless they ask.
4. **Dry run, then run.** `capture.py --dry-run` prints each device's preparation and every step as its driver
   would run it, running nothing. Read it with the user (which simulators get created, what's erased, which
   settings change and are put back). Then `capture.py` (`--devices`, `--screens`, `--locales` to narrow; a
   partial run keeps the report's other entries). It stops at the first shot missed or failed unless
   `--keep-going`; `--cleanup` deletes the simulators and emulators it created when done.
5. **Check.** `check_captures.py --plan capture-plan.json --rules apple,google` reads every PNG's header against the plan and the stores'
   accepted sizes: size, bit depth, alpha, colour profile, interlacing. A wrong size goes back to step 3 with a
   device that renders the right one, never to a resize.
6. **Look at every capture at full size.** An exit code of 0 can't see a toast, a keyboard, a spinner, a
   permission prompt, a debug banner or FPS counter, a scroll bar, a text caret, a half-finished animation, real
   personal data, the wrong locale (the app's, or the system's in an alert or the keyboard), a status bar that
   wasn't overridden, or a Dynamic Island area that looks broken. Report what you see, screen by screen; retake
   what's wrong.
7. **Hand on.** Say which shots were taken, which were missed (and whether the previous picture was kept, so it's
   stale), which failed and why. Captures to design: `store-screenshots` reads `<out>/<locale>/<device>/<screen>.png`
   as its captures. Captures to send as they are: name the plan's devices as `store-listing.json`'s screens and
   its screens as the shots, and the folder is the listing's screenshots folder; `listing.py check`
   (`store-listings`) is next.
8. **Video (when asked).** `video.py record --from simctl|adb|chrome` on the dedicated device with the status bar
   clean, `video.py encode … --slot <display type>` to that slot's preview size (constant 30 fps, H.264, a silent
   stereo track when there's none, trimmed with `--start`/`--end`), and `video.py check` against the rules. Then
   watch it through. Detail: [references/video.md](references/video.md).

Exit codes: 0; 1 (a shot failed, or was missed or skipped with no previous picture kept; for `check_captures.py`
and `video.py check`, a problem found); 2 (`capture.py` refused: another capture is writing to the same folder);
3 (usage, an invalid plan, or a tool that's needed isn't there).

## Agent rules

1. **Never touch the user's own simulators, emulators or devices** unless the plan names them. Create and own
   dedicated ones (`appstores-<device id>`). *Why:* erasing a simulator or changing a phone's language or display
   size wrecks someone's working setup.
2. **Put back everything changed:** the status bar, demo mode, `wm size` and density, locale, appearance,
   animation scales, permissions. The drivers do it in `finally`; if a run is killed, reset by hand
   ([references/pitfalls.md](references/pitfalls.md#devices-and-machines)) and say what may still be changed.
3. **Never resize, crop or stretch a capture to make it fit.** Choose the device that renders the size
   ([references/sizes.md](references/sizes.md)). *Why:* a resized shot is blurry or distorted, and the stores ask
   for the app as it looks.
4. **Report what was missed, honestly.** A screen not reached keeps its previous picture only when there is one,
   and the report and your reply say it's stale. Never present a missed or failed shot as taken.
5. **No real personal data.** Demo data is fictional: invented names, `example.com` addresses, 555-01xx numbers,
   generated avatars; never a real account, the user's contacts or photos, or a tester's name.
6. **Local only.** Drivers talk to this machine: simulators, emulators, devices over adb, a local Appium server,
   in-app agents on loopback ports, the app on `localhost`. Nothing is sent anywhere.
7. **Look at every picture at full size** before calling a set done, and **watch every video through**.
8. **Debug tools stay out of store builds.** An in-app agent or screenshot mode belongs to debug or screenshot
   builds only (`#if DEBUG`, `kDebugMode`, `__DEV__`, `debugImplementation`); flag one that could ship.
9. **Change the app only with the user.** Adding a screenshot mode, accessibility ids or an agent package is a
   code change: propose it, show it, let them decide.
10. **Don't commit unless asked.** Say what's ready: the plan, any app changes, the captures folder if they keep
    captures in the repository.

## Validation

- `capture.py --dry-run` was read before the first real run, and named no device the user didn't agree to.
- `capture.py` exited 0, or every `missed`, `failed` and `skipped` shot in `capture-report.json` was reported with
  its reason, and whether a previous picture was kept.
- `check_captures.py --rules …` exits 0: every PNG is exactly its device's size, 8-bit RGB, no alpha, sRGB.
- Every `statusBar` in the report is `verified` (read back from the device) or `overridden` (applied, not read
  back), or `none` where there's no status bar; and the status bar was looked at in every picture, since none of
  these is a check of the pixels. An `unverified` one is retaken.
- Every capture was opened at full size and what was seen is reported.
- `simctl status_bar … list`, `adb shell wm size`, the locale and appearance are back as they were (the drivers'
  reset log says so).
- Videos: `video.py check` exits 0 and the video was watched through.

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `failed`: wrong size (e.g. 828×1792) | the device type doesn't render a store size, whatever class it's listed in | pick a device from [sizes.md](references/sizes.md) that renders it natively; never resize |
| Play rejects a phone shot as too tall | modern phone emulators are about 2.2:1; Play allows 2:1 | `target.wmSize: "1080x1920"` so the app lays out at 9:16 ([adb.md](references/adb.md)) |
| Status bar shows the real time or carrier | the override wasn't honoured on this runtime, or was lost on a reboot | the report says `unverified`; reapply after boot, retake, or tell the user ([pitfalls.md](references/pitfalls.md)) |
| `missed`: an element wasn't found | the screen changed, the id is missing, the locale's text differs | find by `id`, not `text`; add an accessibility id (with the user); the previous picture is kept and reported stale |
| A toast, keyboard, spinner or prompt in the shot | the screen hadn't settled, or a permission wasn't granted | `settle` or `wait` for an element; grant permissions before launch ([clean-state.md](references/clean-state.md)) |
| Alpha in a PNG | `--mask=alpha`, a window capture's corners, a transparent background | the drivers flatten it and list `alpha-flattened`; fix the source if it recurs |
| The agent isn't found (DevFlow, Ailoha) | a release build, the port not forwarded, the broker not running | a debug build; the agent's status command; `adb forward` on Android ([devflow.md](references/devflow.md), [ailoha.md](references/ailoha.md)) |
| Appium: session won't start | server not running, driver not installed, wrong capabilities | `appium driver list --installed`; capabilities in [appium.md](references/appium.md) |
| `skipped`: a step the driver can't do | e.g. a `tap` on the `simctl` driver | use a driver that taps (agent, Appium, XCUITest), or reach the screen by launch argument |
| Half the screen in another language | the app's language was set but the system's wasn't (alerts, keyboard) | set the device language too ([clean-state.md](references/clean-state.md)) |
| Video rejected: frame rate or audio | variable or 60 fps; no audio track | `video.py encode` (constant 30 fps, silent stereo AAC) |
| Exit 3: a tool not found | Xcode, platform-tools, Chrome, ffmpeg, a CLI isn't installed or on `PATH` | install it, or choose another technique |

## References

| File | What's in it |
|---|---|
| [choosing.md](references/choosing.md) | the decision table in full, the questions to ask, mixing techniques |
| [screenshot-mode.md](references/screenshot-mode.md) | adding a launch-argument / deep-link screenshot mode: SwiftUI, UIKit, Compose, .NET MAUI, Flutter, React Native, web |
| [devflow.md](references/devflow.md) | .NET MAUI's DevFlow agent: setup, the CLI, finding elements, capturing |
| [ailoha.md](references/ailoha.md) | the Ailoha agent on each stack: setup, the CLI, ports, capturing |
| [appium.md](references/appium.md) | Appium 2/3: drivers, capabilities, the WebDriver calls the driver makes |
| [ui-automation.md](references/ui-automation.md) | XCUITest, UI Automator, Maestro, macOS Accessibility |
| [simctl.md](references/simctl.md) | iOS, iPadOS, tvOS, watchOS, visionOS simulators: lifecycle, launch, status bar, capture |
| [adb.md](references/adb.md) | Android emulators and devices: launch, `wm size`, demo mode, capture |
| [web.md](references/web.md) | web apps and PWAs in headless Chrome |
| [desktop.md](references/desktop.md) | Mac App Store windows, Windows apps, Steam and itch.io |
| [engines.md](references/engines.md) | Unity, Godot, Unreal: rendering each picture at its exact size |
| [importing.md](references/importing.md) | fastlane snapshot and screengrab, xcresult, Maestro, Flutter, Detox, Playwright, a folder |
| [video.md](references/video.md) | recording, trimming, encoding and checking preview videos |
| [clean-state.md](references/clean-state.md) | demo data, the clock, the status bar, locale, appearance, transient UI |
| [sizes.md](references/sizes.md) | which simulator, emulator or viewport renders which store size natively |
| [pitfalls.md](references/pitfalls.md) | what went wrong before, and how to avoid it |
| [config.md](references/config.md) | every field of `capture-plan.json` and `capture-report.json` |
