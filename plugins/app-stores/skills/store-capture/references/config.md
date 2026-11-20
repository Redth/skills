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
| `staging` | object | | how the app is signed in, seeded and set up for the screens, agreed with the user ([staging.md](staging.md)); below |
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
| `adb` | `systemImage` and `profile` (an AVD of the skill's own, `appstores-<id>`), `avd` (an AVD by name; `readOnly`, `window`, `port`, `emulatorArgs`), `serial` (a connected device: only one the user names), `wmSize` (default the device's `width`x`height`; `null` leaves it), `density`, `deviceLocale`, `display`, `animations` (`off` by default), `navigation` (`gesture`, `threebutton`), `statusBarMobile`, `statusBarCheck`; the tools' paths `adb`, `emulator`, `avdmanager` ([adb.md](adb.md)) |
| `uiautomator` | `serial`, or `avd` already running: it changes nothing on the device (no size, locale, demo mode, install or launch) |
| `chrome` | `scale` (device scale factor, default 1; the page is `width/scale` × `height/scale` CSS px), or `viewport` (`[w, h]` CSS px, which sets the scale); `mobile`; `reducedMotion` |
| `macos` | `scale` (the display's backing scale, default 2: the window is sized to `width/scale` × `height/scale` points), `position` (default `[0, 40]`) |
| `devflow`, `ailoha` | the host's fields (as `simctl` or `adb`), plus `agentPort` (by hand, checked), `agentPlatform`, `appName`, `agentTimeout`, `cli`, `host`, `screenshot`: [devflow.md](devflow.md), [ailoha.md](ailoha.md) |
| `appium` | the host's fields, plus `server` (default `http://127.0.0.1:4723`, this machine only), `capabilities` (on a simulator `appium:isHeadless` is already `true`) and `pointScale`: [appium.md](appium.md) |
| `xcuitest` | `scheme` (required), `project` or `workspace`, `testPlan`, `configuration`, `xctestrun`, `destination`, `testTimeout`, plus the host's: [ui-automation.md](ui-automation.md) |
| `maestro` | `maestro` (the command), `env`, `flowTimeout`, plus the host's: [ui-automation.md](ui-automation.md) |

Each driver's reference is the authority for its `target`; unknown fields are reported, not guessed at.

## `screens[]`

| Field | Type | Meaning |
|---|---|---|
| `id` | `[a-z0-9][a-z0-9_.-]*` | the file name; what `store-screenshots` calls the capture screen |
| `state` | string | what the screen must show, in plain words; in `staging.md`, the report and a wrong state's reason |
| `steps` | array | how to reach it, run in order; then the screenshot |
| `verify` | an element, or a list | must be on screen before the shot (`timeout`, default 5 s), else the shot is `missed` ("wrong state"); the report's `stateCheck` |
| `staging` | `false` | leave the staging's seed and launch values out of this screen |
| `devices` | array of device ids | only these devices (default: all) |
| `platforms` | array of platforms | only devices of these platforms |
| `locales` | array | only these of the device's locales |
| `appearance`, `clock`, `statusBar`, `seed`, `flatten` | | this screen's settings |
| `overrides` | object | keyed by a device id or a platform: `steps`, `state`, `verify` or settings that differ there. A device id's entry wins over its platform's |

## `staging`

Agreed with the user before the plan runs; [staging.md](staging.md) has the questions and the reasons.
`capture.py --write-staging` writes it readable as `staging.md` beside the plan, and a run warns when that file no
longer matches.

| Field | Meaning |
|---|---|
| `account` | `kind`: `none`, `guest`, `bypass` (a debug sign-in bypass), `demo` (a demo account: never a real person's); `env`: the **names** of the environment variables holding a demo account's sign-in (checked before a run, usable in launch values as `${NAME}`, masked in every log and report); `how` |
| `seed` | `kind`: `command` (`run`, a `script` before each screen's steps; `timeout`), `file` (`file` copied into the app's data at `into`, a path or one per platform, as an `appFile` step), `launch` (the app seeds itself: put the switch in `launch.args`), `backend`, `none`; `when`: `each-screen` (default) or `once` (before each device's first screen); `how` |
| `launch` | `args` and `env` added to every `launch` step (the step's own win) |
| `skip` | what's skipped and how: strings or `{ "what", "how" }` |
| `permissions` | by platform: granted after install, before launch, revoked in reset (simctl privacy services; Android permission names) |
| `flags` | feature flags: strings or `{ "name", "value", "how" }` |
| `clock` | the app's own "now": `now`, `how` (the status bar's is the plan's `clock`) |
| `network` | `kind`: `offline`, `mock`, `staging`, `live`; `how` |
| `confirmed` | `{ "screen", "device", "on" }`: the user saw this screen captured with this staging and agreed. Until it's set, a run captures one screen only |
| `doc` | the readable copy's file name (default `staging.md`) |

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
| `script` | a string (split like a shell would, not run by one), an argument list, or `{ "run": …, "timeout": s }` | a command the user provides, run as is from the plan's folder, with the variables below |
| `appFile` | `{ "file": "seed/app.db", "into": "Library/Caches/app.db" }` (`into` may be `{ "ios": …, "android": … }`) | copies a file into the app's own data, the app stopped first and the old file (and a database's `-wal`/`-shm`) removed: the simulator's data container, Android's `/data/data/<package>` through `run-as` (debug builds). Done by the `simctl` and `adb` drivers, and through them by the agents and Appium |
| `settle` | `true` or `{ "timeout": s, "ignore": [[x, y, w, h], …] }` | waits until two screenshots in a row are identical (outside the `ignore` rectangles, in the picture's pixels: an illustration that never stops moving); a screen that never settles is a warning |

A `script` step's environment:

| Variable | Value |
|---|---|
| `APPSTORES_DEVICE` | the plan's device id |
| `APPSTORES_LOCALE`, `APPSTORES_SCREEN` | the locale and screen being captured |
| `APPSTORES_PLATFORM` | the device's platform (`ios`, `android`, …) |
| `APPSTORES_APP_ID` | the app's bundle id or package |
| `APPSTORES_UDID` | the simulator's UDID (`simctl`, and drivers it hosts) |
| `ANDROID_SERIAL`, `APPSTORES_SERIAL` | the adb serial (`adb`, and drivers it hosts; adb honours `ANDROID_SERIAL`) |

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
| `statusBar` | `verified` (iOS: `simctl status_bar list` shows the override; Android: the status bar's pixels changed with demo mode's clock and came back), `overridden` (applied and not checked: `target.statusBarCheck: false`), `unverified` (the override failed or couldn't be confirmed, or an imported picture whose tool didn't say), `none` (no status bar, or `as-is`). The icons are still for a person to look at |
| `state`, `stateCheck` | the screen's `state` words; its `verify`: `passed`, `failed` (the shot is `missed`, "wrong state"), `unchecked` (the driver can't see elements: look) |
| `fixes` | lossless repairs made: `alpha-flattened`, `converted-to-srgb`, `16-bit-to-8-bit`. Never a resize. Simulators and emulators write an alpha channel that's all opaque: those are flattened quietly (still in `fixes`) and counted once in the report's `notes`; see-through pixels get a warning |
| `warnings` | what a person should look at (a screen that didn't settle, a wait that couldn't see elements) |
| `source` | what produced it (device type and runtime, AVD and API level, browser) |

Each PNG is exactly its device's `width`×`height`, 8-bit RGB (no alpha, no `tRNS`), sRGB, not interlaced. Files are
written to a temporary folder and moved into place at the end, so a failed run never leaves a mix.

The report also has `devices` (each device's source and warnings) and `notes` (said once a run, like the count of
quietly flattened pictures).

## Options outside the plan

- `capture.py --cleanup`: delete the simulators and AVDs the skill created for itself (`appstores-<device id>`) after the
  run. It never deletes one the plan names by UDID, serial or AVD name.
- `capture.py --inspect`: also save each screen's UI tree (after its steps, or where they stopped) to
  `<out>/.inspect/<locale>/<device>/<screen>.txt`, for writing steps and `verify`.
- `capture.py --write-staging`: write `staging.md` from the plan, and stop.
- `capture.py --current [folder]`: list the current store screenshots (`existing/<store>/screenshots/`,
  `store-screenshots.json`'s shots, `design/current.json`, or the folder), to start the screens from; and stop.
