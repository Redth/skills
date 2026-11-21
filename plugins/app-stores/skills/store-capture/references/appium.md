# Appium

Appium drives iOS, Android, Mac and Windows apps of any stack through the platforms' own automation (XCUITest,
UiAutomator2, Mac2, Windows), behind one W3C WebDriver API. Use it when the project already has an Appium suite, or
when many platforms must be reached the same way and the app can't change. The `appium` driver speaks WebDriver
JSON over HTTP to a **local** Appium server with the standard library: no client library, no Selenium.

## Setup (the user's machine)

```sh
npm install -g appium                       # Appium 2 or 3; needs Node
appium driver install xcuitest              # iOS, iPadOS, tvOS (and Xcode)
appium driver install uiautomator2          # Android (and the Android SDK, ANDROID_HOME)
appium driver install mac2                  # Mac apps
appium driver install windows               # Windows apps (on Windows)
appium driver list --installed
appium --address 127.0.0.1 --port 4723      # the server, on this machine only
```

`appium driver doctor <driver>` says what a driver is missing. Docs: https://appium.io/docs/en/latest/ and each
driver's README (`appium/appium-xcuitest-driver`, `appium-uiautomator2-driver`, `appium-mac2-driver`,
`appium-windows-driver` on GitHub). **The first XCUITest session builds WebDriverAgent, which takes minutes**: the
driver allows 600 s for it; later sessions are quick. Appium 2 and 3 serve at the root
(`http://127.0.0.1:4723/`), not Appium 1's `/wd/hub`; a server started with `--base-path` needs it in the plan.

## The plan's target

```json
{ "id": "android-phone", "platform": "android", "kind": "phone", "driver": "appium", "width": 1080, "height": 1920,
  "target": { "systemImage": "system-images;android-36;google_apis;arm64-v8a", "profile": "medium_phone",
              "server": "http://127.0.0.1:4723",
              "capabilities": { "appium:autoGrantPermissions": true } } }
```

- `server`: the Appium server, default `http://127.0.0.1:4723`. **It must be this machine**; the driver never
  starts a server or reaches a remote one (a device cloud or grid is out of scope). Start it yourself.
- `capabilities`: added to the session as they are (anything the platform's Appium driver takes). On a simulator
  the driver already sets `"appium:isHeadless": true`: the capture comes from `simctl io`, so no Simulator window
  is needed, and since Xcode 27 the XCUITest driver can't open Simulator.app where it looks ("The file
  /Applications/Xcode.app/Contents/Developer/Applications/Simulator.app does not exist"). `false` here turns it off.
  `"appium:wdaLaunchTimeout": 600000` gives a first WebDriverAgent build the time it needs. On a simulator the
  driver also gives the device its own `appium:wdaLocalPort` and `appium:mjpegServerPort`
  ([below](#beside-other-appium-servers)); a port set here is kept as it is.
- **The device has a host**, as for the in-app agents: `simctl` for Apple simulators, `adb` for Android, none for
  Mac and Windows apps (`target.host` overrides). The host creates or finds the dedicated device, boots it,
  installs the app, sets the device's locale, appearance and clean status bar, and resets them after; so the
  host's fields (`deviceType`, `runtime`, `udid`, `avd`, `serial`, `wmSize`, …) go in the same `target`
  ([simctl.md](simctl.md), [adb.md](adb.md)).

**A failed session** is reported with its own error (with what to do, for the causes seen before), never with
what it left behind: the XCUITest driver can shut the simulator down when a session fails, so before the next
screen the driver boots it again (and reapplies the status bar), and a session that fails is tried once more
after that. Without `--keep-going` the run stops at the first one anyway.

**One session a locale** (the language is a session capability). The driver's `POST /session` (`{
"capabilities": { "alwaysMatch": {…}, "firstMatch": [ {} ] } }`, answered with `value.sessionId`) carries
`platformName` and `appium:automationName` (XCUITest, UiAutomator2, Mac2, Windows), the host's device as
`appium:udid`, the app from the plan's `app` (`appium:bundleId`, `appium:appPackage` + `appium:appActivity`, or
`appium:app`), `appium:language` and `appium:locale` (Mac2: `appium:appLocale`), the seed as a launch argument
(`appium:processArguments` on iOS, `appium:optionalIntentArguments` on Android, `appium:arguments` on a Mac) and
`appium:noReset`; then `target.capabilities`. `DELETE /session/<s>` when the device is reset. Per platform:

| Platform | Capabilities |
|---|---|
| iOS (tvOS: `platformName: tvOS`) | `platformName: iOS`, `appium:automationName: XCUITest`, `appium:udid`, `appium:bundleId` or `appium:app`, `appium:language: de`, `appium:locale: de_DE`, `appium:processArguments: { args: [...], env: {...} }`; on a simulator `appium:isHeadless: true`, `appium:wdaLocalPort` (8130-8199) and `appium:mjpegServerPort` (9130-9199) |
| Android | `UiAutomator2`, `appium:udid` (the serial), `appium:appPackage` + `appium:appActivity` (or `appium:app`), `appium:language: de` with `appium:locale: DE` (a locale needs its language), `appium:optionalIntentArguments` (`am start` style: `--es Key "value"`), `appium:autoGrantPermissions` |
| Mac | `platformName: mac`, `Mac2`, `appium:bundleId` or `appium:appPath`, `appium:arguments` (an array), `appium:environment`, `appium:appLocale: { locale: "fr_FR", language: "fr" }` |
| Windows | `platformName: Windows`, `appium:automationName: Windows`, `appium:app`, `appium:appArguments` |

## Beside other Appium servers

XCUITest's driver starts WebDriverAgent (the agent inside the simulator that does the taps) on port 8100 of this
machine unless told otherwise, and Appium talks to whatever answers there. In a real trial another project's
Appium server had a session on 8100 for its own simulator: our session's `POST /session` went to that
WebDriverAgent, the next command failed with "invalid session id: Session does not exist", and the app launch
and terminate commands landed on the other simulator, which is someone else's (rule 1).

So on a simulator every session asks for this device's own ports:

- `appium:wdaLocalPort`, from 8130-8199, and `appium:mjpegServerPort` (XCUITest's screenshot stream, default
  9100), from 9130-9199: the same offset in both, derived from the plan's device id (a CRC-32, so the same on every
  run and machine), never 8100 or 9100. Two devices can map to the same port; a run takes devices one at a time.
- Before the first session the driver checks whether something already listens on 127.0.0.1 there. For the WDA
  port it asks `GET /status`: a WebDriverAgent whose reply names this device's simulator (its UDID) is ours and
  kept; another simulator's, one that doesn't say which simulator it serves (WebDriverAgent's own reply doesn't),
  or any other program is passed over for the next free port in the range, and the log and the report's device
  `warnings` say which and why. The MJPEG port is passed over when anything listens on it.
- The ports are chosen once a run and kept for every locale's session, so our own WebDriverAgent from the last
  session isn't mistaken for someone else's. `--dry-run` prints them (without checking); the report's `devices`
  entry has them as `source.wdaPort` and `source.mjpegPort`.
- A port the plan sets in `target.capabilities` is used as it is, never checked; with `appium:webDriverAgentUrl`
  (a WebDriverAgent the plan runs itself) the driver sets no WDA port.

**Simulator windows close.** When a session starts, XCUITest's driver closes Simulator.app's windows, headless or
not: the user's own simulators stay booted, but the windows they had open go. Say so to the user before the first
Appium run on iOS (they can reopen them from Simulator.app's File > Open Simulator).

## What the driver sends

All JSON over HTTP to the local server; `<s>` is the session id.

| Step | WebDriver call |
|---|---|
| `launch` | iOS and Mac: `mobile: launchApp` (`bundleId`, `arguments`, `environment`); Android: `mobile: startActivity` (`component: "pkg/.Activity"`, `extras: [["s", "key", "value"], ["z", "flag", "true"]]`, `stop`, `wait`), all through `POST /session/<s>/execute/sync` `{ "script": "mobile: …", "args": [ {…} ] }` |
| `deepLink` | `mobile: deepLink` (`url` and `bundleId`, or `url`, `package`, `waitForLaunch`) |
| `tap` | find (`POST /session/<s>/element`, the element under the key `element-6066-11e4-a52e-4f735466cecf`; 404 `no such element` when it isn't there), then `POST /session/<s>/element/<e>/click` |
| `type` | `POST /session/<s>/element/<e>/value` `{ "text": … }`, or into `GET /session/<s>/element/active` |
| `wait` | find until it appears |
| `scroll` | iOS `mobile: swipe` the finger's way (the opposite of the scroll's; `elementId` for `in`), never `mobile: scroll` with a direction ([below](#scrolling-on-ios)); Android `mobile: scrollGesture` (`left`, `top`, `width`, `height` or `elementId`, `direction`, `percent`); a Mac `mobile: scroll`; `to` an element: scroll until it's found, down then up, each way until the page source stops changing |
| `swipe` | `mobile: swipe` (iOS), `mobile: swipeGesture` (Android), or `POST /session/<s>/actions` (a touch pointer; `DELETE …/actions` after) sized from `GET /session/<s>/window/rect` |
| `back` | `POST /session/<s>/back` (on iOS that's navigation: never a way to close the keyboard) |
| `hideKeyboard` | `mobile: isKeyboardShown`, then `mobile: hideKeyboard` (iOS: `keys` Done, Return, Go, Search, Next: the keyboard's own key), then the plan's `done` or, on iOS, a button named Done, Close, Hide keyboard or Dismiss keyboard (the app's own: a number pad has no key that closes it, so `mobile: hideKeyboard` always fails there), then a `scroll`, then last a `tap` ([config.md](config.md#the-keyboard-focus-and-forms)) |
| `unfocus` | the host's (adb's Escape on Android); on iOS give it a `tap` (the keyboard closing usually takes the focus with it) |
| `posture` | the host's ([simctl.md](simctl.md#the-iphone-duo), [adb.md](adb.md#foldables)) |
| screenshot | the host's (below), else `GET /session/<s>/screenshot` (a base64 PNG) |

**Finding elements:** `id` is `accessibility id` (on iOS the accessibility identifier; on Windows the
`AutomationId`); on Android it's tried as `id` (the resource id) first, then `accessibility id` (the content
description). On Android a resource id without its package gets the app's. `text` and `label` are tried as every
driver matches them: exactly, then ignoring case and surrounding space, then contained. On iOS three predicates
(`label == "…" OR value == "…" OR name == "…"`, then `==[c]`, then `CONTAINS[c]`; a Mac's use `title`), on Android
and Windows three XPaths (`@text=…`, then `translate(normalize-space(@text), …)=…`, then `contains(translate(@text,
…), …)`; `@Name` on Windows). `xpath` is passed as it is (the platform driver's full XPath 1.0). The keyboard's
state for `verify` is `mobile: isKeyboardShown`. `.NET MAUI`'s `AutomationId`, React Native's `testID`, SwiftUI's `.accessibilityIdentifier`, Compose's
`testTag` (with `testTagsAsResourceId`) all end up as one of these.

## Capturing

With a host, the picture is the host's: `simctl io … screenshot --mask=ignored` or `adb exec-out screencap -p`, the
device's whole framebuffer at its native size, once Appium has reached the screen. For a Mac or Windows app (no
host), it's Appium's `GET /session/<s>/screenshot`. The size is checked either way.

Wait for scroll bars to fade after a scroll (`settle`) and put the keyboard away (`hideKeyboard`, never `back` on
iOS) before the shot. Appium never sets the status bar: the host does.

## Scrolling on iOS

XCUITest's `mobile: scroll` with only a direction (no element) **presses for half a second** at a quarter of the
window's width and height before it drags, slowly. When that point is a text field, the press focuses it: the
number pad that `hideKeyboard` just closed comes back, and the page doesn't move. On a large iPhone the point may
miss the fields by luck; on a small display (the iPhone Duo's cover) it landed in one. So the driver scrolls iOS
with a quick `mobile: swipe` the finger's way (`up` content is a `down` swipe), on the window or the `in` element,
with no hold: a form's scroll back to the top after typing (`fill`'s `scrollTo`, `scroll {"to": "top"}`) leaves the
keyboard down. By hand, the same: `mobile: swipe` or a W3C pointer drag with no pause, never a direction-only
`mobile: scroll` after typing.

## Stacks

- **.NET MAUI:** Microsoft's sample runs Appium from NUnit; elements by `AutomationId`. Launch arguments reach the app
  as `NSUserDefaults` / intent extras ([screenshot-mode.md](screenshot-mode.md#net-maui)). If the app has DevFlow,
  [devflow.md](devflow.md) is simpler.
- **React Native:** `testID` → accessibility identifier (iOS) / resource id or content description (Android).
- **Flutter:** Flutter's widgets aren't native views; Appium's Flutter drivers (`flutter-integration`) or
  `Semantics(identifier: …)` labels exposed to accessibility make them findable. A screenshot mode is usually less
  work.
- **An existing suite:** run it as a `script` step (`{ "script": "dotnet test --filter StoreShots" }`) when it saves
  its own screenshots, then import its folder ([importing.md](importing.md)); or point the plan's steps at the same
  ids it uses. **A suite that signs in to a real account or resets a server account** (a seeder that needs a
  test user's password and writes to the production API) isn't one to run: reuse its fixture data through a seed
  and its element ids in the plan's steps, under a guest mode, a debug bypass or a demo account named by
  environment variables ([staging.md](staging.md)).
- **Reading the tree to write steps:** `capture.py --inspect` saves each screen's page source (`GET
  /session/<s>/source`) to `<out>/.inspect/`; an unnamed button (no accessibility id or label) is reached by xpath
  (`//XCUIElementTypeNavigationBar/XCUIElementTypeButton[not(@name)]`), better by an id added to the app.
