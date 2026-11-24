# Apple simulators: `simctl`

The `simctl` driver captures iOS, iPadOS, tvOS, watchOS and visionOS simulators with Xcode's own command-line
tool. It reaches screens by launch arguments, environment and deep links; it can't tap (pair it with a screenshot
mode, or use `devflow`, `ailoha`, `appium` or `xcuitest` for screens that need taps: their steps are `skipped`
here). Commands below are from `xcrun simctl help` in current Xcode; `<udid>` is always a device's UDID, never
`booted` (with two booted, "simctl will choose one").

## The plan's target

```json
{ "id": "iphone-6.9", "platform": "ios", "driver": "simctl", "width": 1320, "height": 2868,
  "target": { "deviceType": "iPhone 17 Pro Max", "runtime": "latest" } }
```

- `deviceType`: the name or identifier from `xcrun simctl list devicetypes` (e.g.
  `com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max`). The JSON list has no screen sizes: they're in
  [sizes.md](sizes.md), and `capture.py` checks every capture against `width`×`height` anyway.
- `runtime`: `latest`, a name (`iOS 27.2`), a version (`27.2`) or an identifier from `xcrun simctl list runtimes`.
- `udid` (optional): use an existing device. **Only when the user names it.** It's never deleted, and its device
  language is never changed (the app gets the locale through its launch arguments). Otherwise the driver creates
  and owns `appstores-<device id>`, reuses it on later runs, and deletes it only with `capture.py --cleanup`.
- `localeScope: "app"` (optional): give the app the locale by launch arguments only, skipping the device language
  and its reboot, when no system UI shows.
- `display` (optional): a screen id from `simctl io <udid> enumerate`, for devices with more than one screen. By
  default the driver captures the screen a posture change made active, else the built-in screen whose pixel size is
  the device's `width`×`height` (either way round). The iPhone Duo refuses a capture without one ("Invalid
  argument").
- `hingeAngle`, `foldCli`: a foldable's half-open angle (default 90) and the fold control's command (default
  `["maui", "devflow"]`): [The iPhone Duo](#the-iphone-duo).

`script` steps get the simulator as `APPSTORES_UDID` (`xcrun simctl get_app_container "$APPSTORES_UDID" <bundle>
data` finds the app's data), with `APPSTORES_DEVICE`, `APPSTORES_PLATFORM`, `APPSTORES_APP_ID`, `APPSTORES_LOCALE`
and `APPSTORES_SCREEN`. When something shuts the simulator down under the driver (a failed UI-test session can),
it's booted again before the next locale change rather than failing with "device is not booted".

## Lifecycle

| Step | Command |
|---|---|
| Create a dedicated device | `xcrun simctl create appstores-iphone-6.9 <device type> <runtime>` |
| Boot and wait | `xcrun simctl boot <udid>` then `xcrun simctl bootstatus <udid> -b` (blocks until booted) |
| Clean slate | `xcrun simctl shutdown <udid>` then `xcrun simctl erase <udid>` (data, permissions and status bar overrides go) |
| Install | `xcrun simctl install <udid> build/SampleRecipes.app` |
| Grant permissions first (`staging.permissions.ios`) | `xcrun simctl privacy <udid> grant photos com.example.samplerecipes` (also `location`, `contacts`, `calendar`, `microphone`, `motion`, …), after install, revoked in reset; a change may terminate the app. Notifications can't be granted this way: the app's screenshot mode skips asking |
| Launch with arguments | `xcrun simctl launch --terminate-running-process <udid> com.example.samplerecipes -ScreenshotScreen plan -ScreenshotSeed demo` |
| Environment | prefix variables with `SIMCTL_CHILD_` in the caller's environment: `SIMCTL_CHILD_SCREENSHOT_MODE=1` reaches the app as `SCREENSHOT_MODE=1` |
| Deep link | `xcrun simctl openurl <udid> 'samplerecipes://recipe/demo'` |
| Seed data without app code | a file into the app's data (`appFile`, or `staging.seed` `file`): `xcrun simctl get_app_container <udid> com.example.samplerecipes data` is the folder (`Library/Caches/…`, `Library/…`, `Documents/…`), the app terminated first; an Xcode project's `.xcappdata` with `xcrun simctl install_app_data <udid> Seed.xcappdata`; `simctl addmedia` (photos, videos, contacts), `simctl keychain`, `simctl pbcopy` |
| Location, a notification | `xcrun simctl location <udid> set 48.8584,2.2945`; `xcrun simctl push <udid> com.example.samplerecipes payload.json` |
| Appearance | `xcrun simctl ui <udid> appearance dark` (also `increase_contrast`, `content_size large`) |
| Shut down, delete | `xcrun simctl shutdown <udid>`; the dedicated device can be kept for the next run or `simctl delete`d |

## Locale

- **The app only:** launch with `-AppleLanguages '(de)' -AppleLocale de_DE` (Foundation's argument domain); the
  driver adds these to every `launch`. Enough when no system UI shows.
- **The whole device** (alerts, the keyboard, the share sheet, the status bar's date on iPad follow only this):
  `xcrun simctl spawn <udid> defaults write -g AppleLanguages -array de-DE` and `… -g AppleLocale de_DE`, then
  reboot the device. The driver does this on its own simulators when the locale changes (and reapplies the
  status bar after the reboot); check the first capture of each locale.
- XCUITest: `xcodebuild test -testLanguage de -testRegion DE`.

## Status bar

```sh
xcrun simctl status_bar <udid> override --time 9:41 \
  --dataNetwork wifi --wifiMode active --wifiBars 3 \
  --cellularMode active --cellularBars 4 --operatorName '' \
  --batteryState charged --batteryLevel 100
xcrun simctl status_bar <udid> list      # what's overridden
xcrun simctl status_bar <udid> clear     # afterwards
```

- Apply it **after** `bootstatus`, and again after any reboot or erase (both lose it).
- `--time` takes a time or an ISO date (which also sets the date shown on iPad).
- **It has silently not worked on some runtimes** (reported on iOS 16 and 17). The driver reads the override back
  with `status_bar list` and records `statusBar` as `verified` (the list shows the time) or `unverified` (the
  override failed, or the list doesn't show it: it can't be confirmed, so look and retake). Neither looks at the
  pixels: look at the top of every picture either way.
- The 360×780@3x "mini" simulators have shown a red `rdar://…` banner in the status bar on recent Xcodes; no mini
  is a required size: don't capture on them.
- tvOS and visionOS have no status bar; a watch shows only the time.

## Capturing

```sh
xcrun simctl io <udid> screenshot --type=png --mask=ignored out.png
```

- The framebuffer at the device's native pixels, portrait unless the app's scene is rotated.
- **Always `--mask=ignored`.** `--mask=alpha` makes the rounded corners transparent (Apple rejects alpha);
  `black` paints them black.
- **Two displays** (the iPhone Duo simulator): `--display <id>` is required; capture each as its own device in the
  plan ([The iPhone Duo](#the-iphone-duo)).
- The Dynamic Island isn't in the framebuffer: the status bar shows split around an empty area. That's what the
  store expects; a frame added later draws the island.
- Landscape: rotate in the app (its screenshot mode, or XCUITest's `XCUIDevice.shared.orientation`); `simctl` has
  no rotate command. Check the PNG's size; never assume.
- `simctl io <udid> screenConfig geometry` can change a screen's geometry within its mode, but don't use it to turn
  one device into another class: pick the right device type.

## The iPhone Duo

The iPhone Duo simulator has two built-in screens (`simctl io <udid> enumerate`, "Connected Screens"):

| Screen | Id | Pixels captured | In use |
|---|---|---|---|
| LCD (the cover, outer) | 1 | 1398×2034, portrait | folded (how it boots) |
| LCD-1 (inner) | 3 | **2853×2007, landscape** (it's listed as 2007×2853) | open |

`simctl` has no hinge command, and Xcode opens the simulator only from its Device Hub (a click). What opens it from
a script is **DevFlow's fold control**, part of the `Microsoft.Maui.Cli` .NET tool (`dotnet tool install -g
Microsoft.Maui.Cli --prerelease`): it needs no agent in the app, so it works whatever the app is built with and
whichever driver captures it:

```sh
maui devflow device fold get --udid <udid> --experimental --json            # mode, hinge angle, which display is active
maui devflow device fold set unfolded --udid <udid> --experimental --timeout 60 --json
maui devflow device fold set folded --udid <udid> --experimental --timeout 60 --json
maui devflow device fold set partially-folded --angle 90 --udid <udid> --experimental --timeout 60 --json
```

It's **experimental**: it drives private Simulator APIs (Apple silicon, Xcode 27.1 or later), never a real device.
The `simctl` driver (and every driver it hosts: Appium, DevFlow, Ailoha, Maestro, XCUITest) uses it for a device's
`posture` (`folded`, `open`, `half-open`) or a `posture` step, captures the display it reports active, and folds
the simulator back in `reset`. Seen 2026-11-19 (Xcode 27.2, iOS 27.2): folded and unfolded switch in about 5 s and
are confirmed; `partially-folded` settled at 85° for 90° and wasn't confirmed, so a half-open hinge within 10° is
accepted with a warning, and anything further off misses the shot. After a change, the app's scene takes a moment to move to the other display (a launch
straight after the unfold drew a blank page that `settle` took as still): the driver waits `target.postureSettle`
seconds (default 3) before the steps; wait for an element after the launch rather than a fixed time. A posture the
simulator is already in isn't set again, nor put back. Ailoha has no fold control of its own: the
`simctl` host still uses DevFlow's CLI. Without it, open the simulator by hand in Xcode's Device Hub and leave
`posture` out (the inner display is captured as long as it's the one in use).

App Store slots: `IPHONE_DUO_OUTER` (1398×2034) and `IPHONE_DUO_INNER`, captured landscape (2853×2007: `width`
2853, `height` 2007; don't try to rotate it). Both are Apple's one Duo set (`APP_IPHONE_DUO`). [sizes.md](sizes.md).

## CoreSimulator hiccups

A transient CoreSimulator failure ("Mach error -308 - (ipc/mig) server died", an interrupted connection) can fail
one `simctl install`, `boot`, `launch` or `io … screenshot`. The driver tries such a command once more after 5 s
(and says so in the report); any other failure, or a second one, is reported as it is.

## Apple TV, Vision Pro, Watch

- **Apple TV:** "Apple TV 4K" device types render 3840×2160, "… (at 1080p)" 1920×1080; both are accepted. Focus
  drives the UI: a screenshot mode that sets focus on a meaningful item, or XCUITest's
  `XCUIRemote.shared.press(.right)`. The focus effect (lift, parallax) is in the framebuffer.
- **Vision Pro:** the store wants 3840×2160; whether the simulator's capture is exactly that with the window
  composited into the environment varies: check the size.
- **Watch:** one size per watch family, the same across locales (Apple asks for that). `--mask=ignored`.

## Reset (always, in `finally`)

`status_bar clear`; the appearance back; a foldable's posture back; the app stopped; a simulator the driver booted
shut down; with `--cleanup`, its own simulators deleted. A person's own simulator named by the plan is never erased, deleted or
given another device language.
