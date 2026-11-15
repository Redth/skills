# `capture-plan.json`: every field

The plan says which devices capture which screens in which locales, and how each screen is reached. Its schema is
`schema/capture-plan.schema.json` (`capture.py` validates the plan against it before anything runs). Paths in it
are relative to the plan's own folder. Plain JSON: comments go in `"$comment"` fields, which are allowed
everywhere.

```json
{
  "$schema": "./capture-plan.schema.json",
  "version": 1,
  "out": "captures",
  "app": { "ios": { "bundleId": "com.example.samplerecipes", "app": "build/SampleRecipes.app" },
           "android": { "package": "com.example.samplerecipes", "activity": ".MainActivity", "apk": "build/app.apk" },
           "web": { "url": "http://localhost:8080" } },
  "locales": ["en-US", "de-DE"],
  "appearance": "light",
  "clock": "09:41",
  "statusBar": "clean",
  "seed": "demo",
  "devices": [
    { "id": "iphone-6.9", "platform": "ios", "kind": "phone", "driver": "simctl", "width": 1320, "height": 2868,
      "target": { "deviceType": "iPhone 17 Pro Max", "runtime": "latest" } },
    { "id": "ipad-13", "platform": "ipados", "kind": "tablet", "driver": "simctl", "width": 2064, "height": 2752,
      "target": { "deviceType": "iPad Pro 13-inch (M5)" } },
    { "id": "android-phone", "platform": "android", "kind": "phone", "driver": "adb", "width": 1080, "height": 1920,
      "target": { "avd": "appstores-android-phone", "profile": "medium_phone", "wmSize": "1080x1920", "density": 420 } }
  ],
  "screens": [
    { "id": "plan", "steps": [ { "launch": { "args": { "ScreenshotScreen": "plan" }, "clean": true } },
                               { "wait": { "id": "plan-title" } }, { "settle": true } ] },
    { "id": "recipe", "steps": [ { "deepLink": "samplerecipes://recipe/demo" }, { "wait": { "id": "recipe-title" } } ] },
    { "id": "search", "devices": ["iphone-6.9", "android-phone"],
      "steps": [ { "launch": {} }, { "tap": { "id": "search" } }, { "type": { "text": "pasta" } },
                 { "wait": { "ms": 800 } } ],
      "overrides": { "android": { "appearance": "dark" } } }
  ]
}
```

## Top level

| Field | Type | Default | Meaning |
|---|---|---|---|
| `$schema` | string | | the schema's path, for editors |
| `version` | `1` | required | the plan format's version |
| `out` | string | `captures` | the captures' folder: `<out>/<locale>/<device id>/<screen id>.png` and `<out>/capture-report.json` |
| `app` | object | | the app on each platform (below) |
| `locales` | array of BCP 47 | `["en-US"]` | captured in this order; each store's own codes are `store-listings`' job |
| `appearance` | `light` \| `dark` | the device's | system appearance during the screens |
| `clock` | `H:MM`, `HH:MM` or an ISO date-time | `09:41` | the status bar's time (an ISO date also sets the date on iPad) |
| `statusBar` | `clean` \| `as-is` | `clean` | `clean`: the clock, full battery and signal, no notifications or carrier; `as-is`: left alone |
| `seed` | string or integer | | passed to the app as `ScreenshotSeed` (a launch argument, an intent extra, a query parameter) |
| `flatten` | `#RRGGBB` | `#000000` | the colour a picture with alpha is flattened onto (black, as a device's masked corners are) |
| `devices` | array, at least 1 | required | below |
| `screens` | array, at least 1 | required | below |

Settings (`locales`, `appearance`, `clock`, `statusBar`, `seed`, `flatten`) resolve **plan, then device, then
screen, then the screen's `overrides` for the device's id or platform**; each later one wins.

## `app`

One entry a platform: `ios`, `ipados`, `tvos`, `watchos`, `visionos`, `macos`, `android`, `web`, `windows`, `linux`.
A device uses its platform's entry, else its family's (`ipados`, `tvos`, `watchos`, `visionos` fall back to `ios`),
merged with the device's own `app`.

| Platform | Fields |
|---|---|
| Apple (`ios` … `macos`) | `bundleId`; `app` (a built `.app` to install on a simulator, or open on the Mac); `processName` (macOS: the name System Events knows it by; default the `.app`'s name) |
| `android` | `package`; `activity` (`.MainActivity` or a full class name); `apk` (installed with `adb install -r` before the screens) |
| `web` | `url`: the app's address **on this machine** (`localhost`, `127.0.0.1`); `launch` opens it and `url` steps resolve against it |

Extra fields are passed to the driver (an agent's app name, for example).

## `devices[]`

| Field | Type | Meaning |
|---|---|---|
| `id` | `[a-z0-9][a-z0-9_.-]*`, ≤ 64 | the folder name, and what `store-screenshots` calls the capture device |
| `platform` | enum above | which `app` entry, and which `overrides` apply |
| `kind` | `phone`, `tablet`, `desktop`, `tv`, `watch`, `xr` | which store slot its pictures are for (`check_captures.py --rules`) |
| `driver` | `simctl`, `adb`, `uiautomator`, `chrome`, `macos`, `devflow`, `ailoha`, `appium`, `xcuitest`, `maestro` | the technique ([choosing.md](choosing.md)); `import` isn't run by `capture.py` ([importing.md](importing.md)) |
| `width`, `height` | integers | **the exact pixel size this device promises**, from the store's rules ([sizes.md](sizes.md)). Any other size is `failed`, never resized. Landscape is `width > height` |
| `target` | object | the driver's own settings (below) |
| `app` | object | merged over the plan's `app` entry for this platform |
| `locales`, `appearance`, `clock`, `statusBar`, `seed`, `flatten` | | this device's settings |

### `target`, per driver

| Driver | Fields |
|---|---|
| `simctl` | `deviceType` (name or identifier), `runtime` (`latest`, a name, a version or an id), `udid` (an existing device: only one the user names), `display` (a display id, two-screen devices), `localeScope` (`app`: no device language change) |
| `adb` | `systemImage` and `profile` (an AVD of the skill's own, `appstores-<id>`), `avd` (an AVD by name; `readOnly`), `serial` (a connected device: only one the user names), `wmSize` (default the device's `width`x`height`; `null` leaves it), `density`, `deviceLocale`, `display` |
| `uiautomator` | `serial`, or `avd` already running: it changes nothing on the device (no size, locale, demo mode, install or launch) |
| `chrome` | `scale` (device scale factor, default 1; the page is `width/scale` × `height/scale` CSS px), or `viewport` (`[w, h]` CSS px, which sets the scale); `mobile`; `reducedMotion` |
| `macos` | `scale` (the display's backing scale, default 2: the window is sized to `width/scale` × `height/scale` points), `position` (default `[0, 40]`) |
| `devflow`, `ailoha` | the host's fields (as `simctl` or `adb`), plus `agentPort`, `agentPlatform`, `appName`, `agentTimeout`, `cli`, `host`, `screenshot`: [devflow.md](devflow.md), [ailoha.md](ailoha.md) |
| `appium` | the host's fields, plus `server` (default `http://127.0.0.1:4723`, this machine only) and `capabilities`: [appium.md](appium.md) |
| `xcuitest` | `scheme` (required), `project` or `workspace`, `testPlan`, `configuration`, `xctestrun`, `destination`, `testTimeout`, plus the host's: [ui-automation.md](ui-automation.md) |
| `maestro` | `maestro` (the command), `env`, `flowTimeout`, plus the host's: [ui-automation.md](ui-automation.md) |

Each driver's reference is the authority for its `target`; unknown fields are reported, not guessed at.

## `screens[]`

| Field | Type | Meaning |
|---|---|---|
| `id` | `[a-z0-9][a-z0-9_.-]*` | the file name; what `store-screenshots` calls the capture screen |
| `steps` | array | how to reach it, run in order; then the screenshot |
| `devices` | array of device ids | only these devices (default: all) |
| `platforms` | array of platforms | only devices of these platforms |
| `locales` | array | only these of the device's locales |
| `appearance`, `clock`, `statusBar`, `seed`, `flatten` | | this screen's settings |
| `overrides` | object | keyed by a device id or a platform: `steps` or settings that differ there. A device id's entry wins over its platform's |

## Steps

One kind a step: `{ "<kind>": <value> }`.

| Step | Value | Notes |
|---|---|---|
| `launch` | `{ "args": {…}, "env": {…}, "clean": bool }` | `args` become launch arguments (iOS `-Key value`), intent extras (Android), query parameters (web); `env` the app's environment; `clean` reinstalls or clears its data first. `seed` is added as `ScreenshotSeed` |
| `deepLink` | a URL | `simctl openurl`, `am start -a VIEW -d`, or the agent's navigation |
| `url` | a URL or path | web: resolved against `app.web.url` |
| `tap` | an element, or `{ "x": …, "y": … }` | coordinates are a last resort: they differ per device size |
| `type` | `{ "text": "…", <finder> }` | types into the focused field, or one found by `id`, `label`, `xpath`, `css`, or `into` (its placeholder text) |
| `wait` | a number (ms), `{ "ms": … }`, or an element | an element waits for it to appear, up to its `timeout` (seconds, default 10). A driver that can't see elements waits and warns |
| `scroll` | `{ "to": <element> }` or `{ "direction": "up"\|"down"\|"left"\|"right", "times": n }` | wait for scroll bars to fade after (`settle`) |
| `back` | `true` | the system back (Android), the agent's or Appium's back |
| `swipe` | `{ "from": [x, y], "to": [x, y], "ms": … }` or `{ "direction": … }` | |
| `flow` | a string (a Maestro flow's path, a UI test's name) or the flow driver's own object | run by the driver that understands it |
| `script` | a string (split like a shell would, not run by one), an argument list, or `{ "run": …, "timeout": s }` | a command the user provides, run as is from the plan's folder, with `APPSTORES_DEVICE`, `APPSTORES_LOCALE` and `APPSTORES_SCREEN` set |
| `settle` | `true` or `{ "timeout": s }` | waits until two screenshots in a row are identical; a screen that never settles is a warning |

**Elements** are found by one of: `id` (accessibility identifier, `AutomationId`, resource id, test id: matches
the whole id or its last part, so `search` finds `com.example.samplerecipes:id/search`), `text` (exact, then
ignoring case, then contained), `label` (accessibility label or content description), `xpath`, `css` (web); with an
optional `timeout` in seconds. Prefer `id`: text changes with the locale. Each driver lists the step kinds and
finders it supports (`capabilities()`); a screen with a step it can't do is `skipped` without running anything.

## `capture-report.json`

Written to `<out>/capture-report.json` after every run.

```json
{ "version": 1, "startedAt": "2026-11-14T10:02:11Z", "plan": "capture-plan.json",
  "shots": [
    { "locale": "en-US", "device": "iphone-6.9", "screen": "plan", "status": "taken",
      "path": "en-US/iphone-6.9/plan.png", "width": 1320, "height": 2868, "sha256": "…",
      "driver": "simctl", "source": { "deviceType": "iPhone 17 Pro Max", "runtime": "iOS 27.2" },
      "statusBar": "verified", "fixes": [], "warnings": [] },
    { "locale": "de-DE", "device": "android-phone", "screen": "search", "status": "missed",
      "reason": "tap: id 'search' didn't appear in 10 s", "kept": "previous" }
  ] }
```

| Field | Meaning |
|---|---|
| `status` | `taken`; `missed` (not reached: `kept` is `previous` when the last run's picture stays, else `none`); `failed` (reached but unusable: the wrong size, a capture error); `skipped` (a step or device the driver can't do) |
| `reason` | why it isn't `taken` |
| `statusBar` | `verified` (the override was read back from the device: `simctl status_bar list` shows it), `overridden` (applied but not read back: Android's demo mode always, or a `list` that didn't show it), `unverified` (the override failed, or an imported picture whose tool didn't say), `none` (no status bar, or `as-is`). None is a look at the pixels: look at the picture |
| `fixes` | lossless repairs made: `alpha-flattened`, `converted-to-srgb`, `16-bit-to-8-bit`. Never a resize |
| `warnings` | what a person should look at (a screen that didn't settle, a wait that couldn't see elements) |
| `source` | what produced it (device type and runtime, AVD and API level, browser) |

Each PNG is exactly its device's `width`×`height`, 8-bit RGB (no alpha, no `tRNS`), sRGB, not interlaced. Files are
written to a temporary folder and moved into place at the end, so a failed run never leaves a mix.

## Options outside the plan

- `capture.py --cleanup`: delete the simulators and AVDs the skill created for itself (`appstores-<device id>`) after the
  run. It never deletes one the plan names by UDID, serial or AVD name.
