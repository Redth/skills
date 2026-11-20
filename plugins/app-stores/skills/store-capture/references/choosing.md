# Choosing a technique

Reaching a screen is the hard, stack-specific part of capturing; taking the picture is easy once the app is
there. The technique decides how the app gets to each screen, and with what data. Choose per device; one plan can
mix them.

## Questions to ask first

Read the project before asking; ask only what it doesn't say.

1. **Which stores, devices and locales?** From `store-listing.json`'s screens if there is one. Each device's size
   comes from the stores' rules ([sizes.md](sizes.md)).
2. **Does something already make captures?** A `Snapfile` or `Screengrabfile` (fastlane), a `.maestro/` folder,
   Detox or Playwright screenshot tests, Flutter `integration_test` with `takeScreenshot`, an Appium suite, a game's
   capture command. If it works, import its output ([importing.md](importing.md)). If running it needs a real
   account, credentials or writes to a live server, it doesn't count as working for an agent: reuse its fixture
   data and element ids instead ([staging.md](staging.md)).
3. **Can the app change?** If the user can add a few lines, a screenshot mode makes every later capture cheap and
   stack-neutral ([screenshot-mode.md](screenshot-mode.md)). If it can't (a client's app, a frozen release), drive
   it from outside.
4. **What's already in the app?** `AddMauiDevFlowAgent` in `MauiProgram.cs` (DevFlow); an Ailoha package
   (`Ailoha.Agent.Maui`, `com.ailoha:ailoha-android-agent`, `ailoha_agent`, `@ailoha/react-native`); accessibility
   identifiers or automation ids on the controls the screens need (any outside driver finds them).
5. **What's installed?** Xcode (macOS only), the Android SDK, Node (Appium, the Ailoha CLI), Java (Maestro),
   .NET (the DevFlow CLI), Chrome.

## The decision table

First match wins, per device. Say which row matched and why.

| # | The app | Technique | Driver | Strengths | Costs |
|---|---|---|---|---|---|
| 0 | An existing pipeline makes captures but needs a real account, secrets, or writes to a live server (an Appium suite that resets a server account) | don't run it: reuse its data (its fixtures, written by a seed) and its element ids, under a guest mode, a debug bypass or a demo account named by env vars; then go on down the table | (the row below that fits) | keeps what the team built without anyone's account | a seed or bypass to set up ([staging.md](staging.md)) |
| 1 | Another tool already makes good captures | import them, mapped into the layout | `import` | no new work; keeps a pipeline the team knows | the other tool's sizes and status bar are what they are: check them |
| 2 | The user can change the app | a **screenshot mode**: launch argument or deep link opens a named screen with seeded demo data and a fixed clock | `simctl`, `adb`, `chrome`, `macos` | fastest, most repeatable, no taps, no element ids, any stack | a code change in the app (debug or screenshot builds only) |
| 3 | .NET MAUI with the DevFlow agent in its debug build | the agent's visual tree and actions over loopback | `devflow` | reaches controls with an `AutomationId` (or text); no Appium, no test project | debug build; on iOS its taps are semantic, not touches: a gesture on an unnamed parent, point taps (without `EnableSyntheticTouch`) and native menus are out of reach, so such screens need `appium` ([devflow.md](devflow.md#what-it-cant-reach)) |
| 4 | Has the Ailoha agent | the agent's UI tree and actions over loopback | `ailoha` | one protocol across MAUI, Android, Flutter, React Native/Expo, WinUI, WPF | debug build; the agent package in the app |
| 5 | An Appium suite exists, or many platforms must be reached the same way | WebDriver to a local Appium server | `appium` | iOS, Android, Mac and Windows from one plan; no app change | a server and drivers to install; slower; scroll bars and keyboards to wait out |
| 6 | XCUITest screenshot tests or Maestro flows exist (or Android UI tests) | run them as a `flow`; Android instrumented tests run as the project does, then imported | `xcuitest`, `maestro` (`import`) | reuses tests the team keeps working | their names map to screens; locale and status bar set by the host, outside the flow |
| 7 | Every screen is reachable by launch arguments or deep links already | the command-line tools alone | `simctl`, `adb` | nothing to install beyond Xcode or platform-tools | `simctl` can't tap: a screen needing a tap is `skipped` |
| 8 | A web app or PWA | headless Chrome at viewport × scale | `chrome` | any size exactly; locale, time zone, colour scheme per context | no system bars (fine for designed shots) |
| 9 | A Mac or Windows desktop app | Accessibility and window capture, or the app's own render | `macos`, `appium` | the real window | Mac App Store takes 16:10 only; window corners need flattening |
| 10 | A game (Unity, Godot, Unreal) | the engine renders each picture at its exact size; import the folder | `import` | supersampled, deterministic, no status bar | an engine-side command or test to write |

Rows 2 and 3/4 combine well: the agent reaches a screen the screenshot mode doesn't name; the screenshot mode
seeds the data the agent can't.

## When the app can't change and nothing drives it

Say so. Offer, in order: a screenshot mode (the smallest change), accessibility ids on the controls the screens
need (so Appium, Maestro or UI Automator can find them), an in-app agent in debug builds. Don't fall back to
tapping coordinates: they break on the next layout change and differ per device size.

## Per stack, the usual choice

| Stack | Usually | Also |
|---|---|---|
| Swift / SwiftUI / UIKit | screenshot mode + `simctl`; XCUITest if tests exist | Appium (XCUITest driver), Maestro |
| Kotlin / Jetpack Compose / Views | screenshot mode + `adb`; UI Automator or screengrab if tests exist | Ailoha, Appium (UiAutomator2), Maestro |
| .NET MAUI | DevFlow if it's in the debug build; screenshot mode + `simctl`/`adb` | Ailoha, Appium (`AutomationId`) |
| Flutter | screenshot mode + `simctl`/`adb`; Ailoha | `integration_test` import, Maestro, Appium (Flutter driver) |
| React Native / Expo | screenshot mode (launch args or a deep link) + `simctl`/`adb`; Ailoha | Maestro, Detox import, Appium |
| Kotlin / Compose Multiplatform | as Android and Swift for each side | Maestro for both |
| Capacitor, Ionic, Cordova | as native for the shell, `chrome` for the web layer | Appium |
| WinUI, WPF | Ailoha; Appium (Windows driver) | the app's own render |
| Web, PWA | `chrome` | Playwright import |
| Mac (AppKit, SwiftUI, Catalyst) | screenshot mode + `macos` | Appium (Mac2), XCUITest for macOS |
| Unity, Godot, Unreal | the engine's own render at the size, then `import` | `simctl`/`adb` on a build (no supersampling) |

## What each driver can do

A screen with a step its device's driver can't do is `skipped` without running anything; the report says which.

| Driver | Steps | Finds elements by | The device |
|---|---|---|---|
| `simctl` | `launch`, `deepLink`, `url`, `wait` (time only), `settle`, `script` | none | creates or uses the simulator |
| `adb` | `launch`, `deepLink`, `url`, `tap`, `type`, `wait`, `scroll`, `back`, `swipe`, `settle`, `script` | `id`, `text`, `label`, `xpath` | creates or uses the emulator, `wm size` |
| `uiautomator` | `tap`, `type`, `wait`, `scroll`, `back`, `swipe`, `settle`, `script` | `id`, `text`, `label`, `xpath` | a running one, changed in nothing |
| `chrome` | `launch`, `url`, `deepLink`, `tap`, `type`, `wait`, `scroll`, `back`, `settle`, `script` | `css`, `id`, `text`, `label`, `xpath` | a headless browser |
| `macos` | `launch`, `tap`, `type`, `wait`, `settle`, `script` | `id`, `text`, `label` | the Mac; the app's window |
| `devflow`, `ailoha` | `launch`, `deepLink`, `url`, `tap`, `type`, `wait`, `scroll`, `back`, `swipe`, `settle`, `script` | `id`, `text`, `css`, `xpath` | its host (`simctl`, `adb`) |
| `appium` | `launch`, `deepLink`, `tap`, `type`, `wait`, `scroll`, `back`, `swipe`, `settle`, `script` | `id`, `text`, `label`, `xpath` | its host |
| `xcuitest` | `flow` | (the test's own) | its host (`simctl`) |
| `maestro` | `flow`, `launch`, `deepLink`, `url`, `tap`, `type`, `wait`, `scroll`, `back`, `swipe`, `settle` | `id`, `text`, `label` | its host |

## Mixing techniques in one plan

A device's captures live under its `id` (`<out>/<locale>/<device id>/`): change its `driver` (devflow to appium,
say) in place and keep the `id`, and the folder, the report's earlier entries and `store-screenshots`' references
stay the same.

`driver` is per device. A typical cross-platform plan: iPhone and iPad by `simctl` with a screenshot mode,
Android by `adb` with `wmSize`, a Mac window by `macos`, and one screen only Appium reaches, limited to the
devices it needs with `screens[].devices`. Every device still uses the same `seed`, `clock` and locales, so the
sets tell the same story.
