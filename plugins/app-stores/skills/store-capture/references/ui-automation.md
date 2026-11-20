# The platforms' UI automation: XCUITest, UI Automator, Maestro, macOS Accessibility

When the app has UI tests or flows that reach its screens, run them for the screenshots rather than writing new
steps. The `xcuitest` and `maestro` drivers take a `flow` step (a test name or a flow file); the device's locale,
appearance and status bar are set by the device's host (`simctl`, `adb`) before the flow and reset after, because
the flows can't do it themselves. Android instrumented tests are run as the project runs them and imported.

## XCUITest (`xcuitest` driver)

For iOS, iPadOS, tvOS and macOS apps with a UI test target. The test reaches each screen and attaches a
screenshot; the driver runs it and exports the attachments.

The test (the user's, or one to propose):

```swift
final class StoreShots: XCTestCase {
    func testPlan() {
        let app = XCUIApplication()
        app.launchArguments += ["-ScreenshotScreen", "plan", "-ScreenshotSeed", "demo"]
        app.launch()
        XCTAssertTrue(app.staticTexts["plan-title"].waitForExistence(timeout: 10))
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())   // whole screen, status bar included
        shot.name = "plan"                                                    // the plan's screen id
        shot.lifetime = .keepAlways
        add(shot)
    }
}
```

The plan's step: `{ "flow": "SampleRecipesUITests/StoreShots/testPlan" }` (a test, a class or a whole target), or
`{ "flow": { "test": "SampleRecipesUITests/StoreShots", "attachment": "plan" } }`. The driver runs:

```sh
xcodebuild test -scheme SampleRecipes -destination 'platform=iOS Simulator,id=<udid>' \
  -testLanguage de -testRegion DE -resultBundlePath out.xcresult \
  -only-testing:SampleRecipesUITests/StoreShots/testPlan
xcrun xcresulttool export attachments --path out.xcresult --output-path shots/
```

- **One test run serves every screen that names it** (per locale and device); each screen takes the attachment
  named after it (or the flow's `attachment`). A test that fails (`xcodebuild` exit 65) but left the attachment is
  still `taken`, with a warning.
- `xcresulttool export attachments --path … --output-path … [--test-id …] [--filter '*.png'] [--only-failures]`
  writes the files and a `manifest.json`: per test, its `testIdentifier` and `attachments`, each with
  `exportedFileName`, `suggestedHumanReadableName` (`<attachment name>_<n>_<UUID>.<ext>`: the driver strips the
  `_<n>_<UUID>`), `configurationName`, `deviceName`, `deviceId`, `timestamp`, `isAssociatedWithFailure`
  (`--schema` prints the format).
- **The run's settings reach the test as environment variables** (xcodebuild passes `TEST_RUNNER_<NAME>` to the
  runner as `<NAME>`): `ScreenshotSeed`, `APPSTORES_LOCALE`, `APPSTORES_SCREEN`, `APPSTORES_DEVICE`. Pass them on
  to the app's `launchArguments` or `launchEnvironment`. The locale is also `-testLanguage`/`-testRegion`.
- `target`: `scheme` (required), `project` or `workspace`, `testPlan`, `configuration`, `xctestrun` (run
  `test-without-building` against a built `.xctestrun`), `destination` (instead of the host's simulator),
  `testTimeout` (seconds, default 1800), plus the host's (`deviceType`, `runtime`, …).
- The simulator is the `simctl` host's: created as `appstores-<device id>`, booted, the app installed, the
  appearance, device locale and clean status bar set before `xcodebuild` runs ([simctl.md](simctl.md)). A Mac
  target runs on `platform=macOS` with no host.
- `XCUIScreen.main.screenshot()` is the whole screen; `element.screenshot()` is only that element, not a store
  shot. On tvOS, `XCUIRemote.shared.press(.right)` moves focus. Landscape:
  `XCUIDevice.shared.orientation = .landscapeLeft`.

## UI Automator (`uiautomator` driver, and Android tests)

Two things go by the name:

- **The device's `uiautomator dump`** (the `uiautomator` driver): an XML of the screen's accessibility tree, read
  over adb; elements by `id` (resource id), `text`, `label` (content description) or `xpath`; actions by `adb shell
  input` (`tap`, `type`, `scroll`, `swipe`, `back`). No test code. **It changes nothing else on the device**: no
  display size, language, dark mode, demo mode (so the report's `statusBar` is `none`), install or launch. It
  connects to `target.serial`, or an emulator already running `target.avd`, and never starts one. Use it on a device
  the person has already set up; use the `adb` driver (the same element finding, plus everything else) for the rest
  ([adb.md](adb.md)).
- **An instrumented test** that reaches a screen (Espresso, Compose test, UI Automator's `UiDevice`) and saves a
  full-screen shot: `UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).takeScreenshot(file)`
  includes the status bar; Compose's `onRoot().captureToImage()` doesn't. No driver runs these as a `flow`: run
  them as the project does (Gradle's `connectedAndroidTest`, or a `script` step with `adb shell am instrument -w -e
  class com.example.samplerecipes.StoreShots com.example.samplerecipes.test/androidx.test.runner.AndroidJUnitRunner`),
  pull the files they wrote, and import the folder ([importing.md](importing.md)). fastlane screengrab
  (`Screengrab.screenshot("plan")`, `CleanStatusBar`) is the same from a test: import its output with
  `--from fastlane-screengrab`.

## Maestro (`maestro` driver)

A YAML flow runs the same on iOS simulators and Android (and web), black-box, finding elements by text or
accessibility id. Good when a stack has no UI-test story of its own.

```yaml
appId: com.example.samplerecipes
---
- launchApp:
    clearState: true
    permissions: { all: allow }
    arguments: { ScreenshotScreen: plan, ScreenshotSeed: "${ScreenshotSeed}" }
- assertVisible:
    id: "plan-title"
- takeScreenshot: plan           # the plan's screen id; a path without extension
```

- **A flow of the app's own:** `{ "flow": "flows/plan.yaml" }`, or `{ "flow": { "file": "flows/plan.yaml",
  "screenshot": "plan", "env": { … } } }`. The driver runs `maestro --device=<id> test --test-output-dir <tmp>
  -e KEY=VALUE … flows/plan.yaml` (`--udid` is the same option; `--test-output-dir` wins over a workspace config's
  `testOutputDir`); the flow must `takeScreenshot` the screen (by its id, or the flow's `screenshot`). The PNG is
  found in the `takeScreenshot` folder of the flow's artifacts, inside the run's timestamped folder; subfolders in
  the name are fine (`checkout/pay`), `..` is refused. One run serves every screen that names the same flow (per locale). The flow gets
  `ScreenshotSeed`, `APPSTORES_LOCALE`, `APPSTORES_SCREEN` and `APPSTORES_DEVICE` (use them as
  `${ScreenshotSeed}`; an undefined one silently becomes `undefined`).
- **Steps without a flow** (`launch`, `deepLink`, `tap`, `type`, `wait`, `scroll`, `swipe`, `back`, `settle`) are
  written as a flow (`launchApp`, `openLink`, `tapOn`, `inputText`, `extendedWaitUntil`, `scrollUntilVisible`,
  `swipe`, `back`, `waitForAnimationToEnd`; `appId:` first, or `url:` for the web) and run; the host then takes
  the screenshot (the whole framebuffer, status bar included). Maestro's text selectors are regular expressions:
  the driver escapes the text it's given. Maestro has no sleep, so a `wait` of some milliseconds becomes an
  optional `extendedWaitUntil` on an id that's never there. A `fill` becomes, per field, `scrollUntilVisible` (down
  only), `tapOn` and `inputText` (with `hideKeyboard` between fields on Android, and after the last), and
  `hideKeyboard` is Maestro's own; `scroll {"to": "top"}` is five swipes; a scroll or fill `in` a pane can't be
  written as a flow (the screen is `skipped`: use adb, Appium or the agent for that device). Docs:
  https://docs.maestro.dev.
- `launchApp.arguments` arrive as launch arguments on iOS and intent extras on Android; React Native and Flutter
  read them through a launch-arguments package ([screenshot-mode.md](screenshot-mode.md)).
- **Maestro can't set the locale or the status bar** (`--device-locale` is `maestro start-device`'s, not `maestro
  test`'s): the device's host (`simctl` or `adb`) does, with the dedicated device, its locale, appearance and
  clean status bar, before the flow and reset after.
- `target`: `maestro` (the command as a list), `env` (more `-e` values), `flowTimeout` (seconds, default 900), plus
  the host's.
- Needs Java and the Maestro CLI.

## macOS Accessibility (`macos` driver)

For Mac apps (AppKit, SwiftUI, Catalyst, Electron, MAUI on Mac Catalyst).

- **`launch`** opens the app (`open -a <app.app>`, or `open -b <bundleId>`) with arguments after `--args`:
  `-ScreenshotSeed`, the screen's `args` as `-Key value`, the locale (`-AppleLanguages (de-DE) -AppleLocale
  de_DE`) and the appearance (`-AppleInterfaceStyle Dark`), all for this app alone, never the person's Mac; `env`
  through `open --env`. A copy it launched is quit first.
- **The window is sized** so the capture is exactly the device's pixels: `width/scale` × `height/scale` points
  (`target.scale`, default 2, a Retina display's), at `target.position` (default `[0, 40]`).
- **`tap`, `type`, `wait`** through Accessibility (`osascript`, System Events): elements by `id` (`AXIdentifier`),
  `text` or `label` (name, description, title or value); `type` is `keystroke`.
- **The capture:** `screencapture -x -o -l <window id>` (no sound, no shadow, one window), the window found through
  CoreGraphics' window list. Its rounded corners come out transparent: flattened onto the plan's `flatten` colour
  (`fixes: alpha-flattened`).
- **Permissions:** the terminal (or the agent's host app) needs **Accessibility** (clicks, sizing) and **Screen
  Recording** (`screencapture`; without it the capture is only the desktop) in System Settings ▸ Privacy &
  Security.
- **If the app is already running when the run starts, it's the person's:** the driver refuses rather than touch
  it. Ask them to quit it.
- Store sizes, and composing a window onto a 16:10 picture: [desktop.md](desktop.md).
