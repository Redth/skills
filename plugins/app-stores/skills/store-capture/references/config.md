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
| `posture` | `folded`, `open` (or `unfolded`), `half-open` | as it is | a foldable's posture before the steps (below, [Foldables](#foldables)) |
| `staging` | object | | how the app is signed in, seeded and set up for the screens, agreed with the user ([staging.md](staging.md)); below |
| `appSource` | `{ "repo": "…", "paths": […] }` | `repo`: the plan's folder | the app's git checkout (`repo`, relative to the plan) and the folders and files that draw the staged screens (`paths`, relative to `repo`): the report records the revision each shot was taken at, and `capture.py --changes` lists what changed there since ([Updating](staging.md#7-updating-when-the-app-changed)) |
| `devices` | array, at least 1 | required | below |
| `screens` | array, at least 1 | required | below |

Settings (`locales`, `appearance`, `clock`, `statusBar`, `seed`, `flatten`, `posture`) resolve **plan, then
device, then screen, then the screen's `overrides` for the device's platform, then its `layout`, then its id**;
each later one wins.

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
| `layout` | an id (`wide`, `split`, `cover`) | how the app lays out here, when it differs: screens' `overrides` keyed by it apply to every device with it (after the platform's, before the device id's) |
| `posture` | `folded`, `open`, `half-open` | a foldable's posture: each posture captured is its own device here, with its own id and size ([Foldables](#foldables)) |
| `locales`, `appearance`, `clock`, `statusBar`, `seed`, `flatten` | | this device's settings |

### `target`, per driver

| Driver | Fields |
|---|---|
| `simctl` | `deviceType` (name or identifier), `runtime` (`latest`, a name, a version or an id), `udid` (an existing device: only one the user names), `display` (a screen id from `simctl io <udid> enumerate`; by default the active one after a posture change, or the one the device's size), `localeScope` (`app`: no device language change), `hingeAngle` (`half-open`, default 90), `foldCli` (the fold control's command, default `["maui", "devflow"]`), `postureSettle` (seconds after a posture change, default 3) |
| `adb` | `systemImage` and `profile` (an AVD of the skill's own, `appstores-<id>`; with `avd` named `appstores-…` too, that AVD, so two postures can share one), `avd` (an AVD by name; `readOnly`, `window`, `port`, `emulatorArgs`), `serial` (a connected device: only one the user names), `wmSize` (default the device's `width`x`height`; `null` leaves it), `density`, `deviceLocale`, `display` (SurfaceFlinger's long id; by default the display in use on a device with more than one), `hingeAngle` (`half-open`, default 90), `animations` (`off` by default), `navigation` (`gesture`, `threebutton`), `statusBarMobile`, `statusBarCheck`; the tools' paths `adb`, `emulator`, `avdmanager` ([adb.md](adb.md)) |
| `uiautomator` | `serial`, or `avd` already running: it changes nothing on the device (no size, locale, demo mode, install or launch) |
| `chrome` | `scale` (device scale factor, default 1; the page is `width/scale` × `height/scale` CSS px), or `viewport` (`[w, h]` CSS px, which sets the scale); `mobile`; `reducedMotion` |
| `macos` | `scale` (the display's backing scale, default 2: the window is sized to `width/scale` × `height/scale` points), `position` (default `[0, 40]`) |
| `devflow`, `ailoha` | the host's fields (as `simctl` or `adb`), plus `agentPort` (by hand, checked), `agentPlatform`, `appName`, `agentTimeout`, `cli`, `host`, `screenshot`: [devflow.md](devflow.md), [ailoha.md](ailoha.md) |
| `appium` | the host's fields, plus `server` (default `http://127.0.0.1:4723`, this machine only), `capabilities` (on a simulator `appium:isHeadless` is already `true`, and `appium:wdaLocalPort` and `appium:mjpegServerPort` are the device's own unless set here: [appium.md](appium.md#beside-other-appium-servers)) and `pointScale`: [appium.md](appium.md) |
| `xcuitest` | `scheme` (required), `project` or `workspace`, `testPlan`, `configuration`, `xctestrun`, `destination`, `testTimeout`, plus the host's: [ui-automation.md](ui-automation.md) |
| `maestro` | `maestro` (the command), `env`, `flowTimeout`, plus the host's: [ui-automation.md](ui-automation.md) |

Each driver's reference is the authority for its `target`; unknown fields are reported, not guessed at.

## `screens[]`

| Field | Type | Meaning |
|---|---|---|
| `id` | `[a-z0-9][a-z0-9_.-]*` | the file name; what `store-screenshots` calls the capture screen |
| `state` | string | what the screen must show, in plain words; in `staging.md`, the report and a wrong state's reason |
| `inUse` | string | what it looks like in use, in plain words (the form part-filled with which values, the list's entries; or why it's empty on purpose): agreed with the user ([staging.md](staging.md#looking-in-use)); in `staging.md` beside the values its `fill` and `type` steps enter. With `staging.inUse` set, a screen without it is warned about |
| `steps` | array | how to reach it, run in order; then the screenshot |
| `verify` | an element (with `contains`, optionally), `{ "keyboard": … }`, or a list | must be so before the shot (`timeout`, default 5 s), else the shot is `missed` ("wrong state"); the report's `stateCheck`. `contains` and the keyboard: below |
| `sources` | array of paths | the app's files (or folders, or globs) that draw this screen, relative to `appSource.repo`: `capture.py --changes` names the screen when one changed |
| `staging` | `false` | leave the staging's seed and launch values out of this screen |
| `devices` | array of device ids | only these devices (default: all) |
| `platforms` | array of platforms | only devices of these platforms |
| `locales` | array | only these of the device's locales |
| `appearance`, `clock`, `statusBar`, `seed`, `flatten`, `posture` | | this screen's settings |
| `overrides` | object | keyed by a platform, a device `layout` or a device id (applied in that order): `stepsPatch`, `steps`, `omit`, `state`, `inUse`, `verify` or settings that differ there (below) |

### Overrides: when a device's layout differs

A screen's steps are written once. Where a device lays the app out differently (no tab bar on an open foldable or
a tablet, the menu button outside the navigation bar on a cover display), an override changes only what differs:

```json
{ "id": "servings",
  "steps": [ { "launch": {} },
             { "tap": { "xpath": "//XCUIElementTypeNavigationBar/XCUIElementTypeButton[normalize-space(@name)='']" }, "name": "menu" },
             { "tap": { "text": "Scale servings" } },
             { "type": { "id": "servings-field", "text": "12" } },
             { "hideKeyboard": true } ],
  "verify": [ { "id": "ingredients" }, { "keyboard": "hidden" } ],
  "overrides": {
    "android":   { "stepsPatch": [ { "replace": "menu", "with": [ { "tap": { "label": "Open navigation drawer" } } ] } ] },
    "duo-outer": { "stepsPatch": [ { "replace": "menu", "with": [ { "tap": { "xpath": "//XCUIElementTypeButton[normalize-space(@name)='']" } } ] } ] } } },
{ "id": "history",
  "steps": [ { "launch": {} }, { "tap": { "id": "tab-history" }, "name": "open-tab" }, { "wait": { "id": "history-list" } } ],
  "overrides": { "wide": { "stepsPatch": [ { "remove": "open-tab" } ] },
                 "duo-inner": { "omit": "the open Duo shows the history beside the plan" } } }
```

- **`stepsPatch`** (prefer it): changes to the steps before it, in order: `{ "prepend": [steps] }`,
  `{ "append": [steps] }`, `{ "remove": <ref> }`, `{ "replace": <ref>, "with": [steps] }`,
  `{ "before": <ref>, "insert": [steps] }`, `{ "after": <ref>, "insert": [steps] }`. A ref is a step's **`name`**
  (any step may carry one) or a 1-based position in the steps as they are when that entry runs (names survive
  edits; positions don't). A fix to the base steps (a `hideKeyboard` added later) reaches every patched device. A
  ref to a step that's gone (renamed, removed) is an error when the plan loads, never a silent no-op.
- **`steps`**: a whole replacement. It doesn't follow later fixes to the base steps (a copy goes stale): keep it for
  a device whose way in has nothing in common with the others'.
- **`omit`**: `true`, or why: the screen isn't captured on that device (logged, not reported as missed). When a
  device shows two screens as one picture (an open foldable's split view), omit one there and leave that shot out
  of the device's set in `store-screenshots` (the shot's `targets`).
- **Device `layout`**: devices that lay out alike (`"layout": "wide"` on an open iPhone Duo and an unfolded Pixel
  Fold) share one override keyed by the layout.
- **An unnamed button** (a hamburger menu with no accessibility label): match "no name" with
  `normalize-space(@name)=''`, never `not(@name)`. A newer build that gives it a name of one space (`name=" "`)
  breaks `not(@name)`; `normalize-space` covers both. Better: ask the user to give it an id (`AutomationId`,
  `accessibilityIdentifier`), which no redesign of its label moves.

### Foldables

Each posture captured is its own device in the plan (its own id, its own `width`×`height`, its own folder):

```json
{ "id": "fold-outer", "platform": "android", "kind": "phone", "driver": "adb", "width": 1080, "height": 1920,
  "posture": "folded", "target": { "avd": "appstores-fold", "systemImage": "system-images;android-36;google_apis;arm64-v8a",
                                   "profile": "pixel_9_pro_fold", "wmSize": "1080x1920", "density": 420 } },
{ "id": "fold-inner", "platform": "android", "kind": "tablet", "driver": "adb", "width": 1920, "height": 1080,
  "posture": "open", "layout": "wide",
  "target": { "avd": "appstores-fold", "systemImage": "system-images;android-36;google_apis;arm64-v8a",
              "profile": "pixel_9_pro_fold", "wmSize": "1920x1080", "density": 320 } },
{ "id": "duo-outer", "platform": "ios", "kind": "phone", "driver": "appium", "width": 1398, "height": 2034,
  "posture": "folded", "target": { "deviceType": "iPhone Duo" } },
{ "id": "duo-inner", "platform": "ios", "kind": "phone", "driver": "appium", "width": 2853, "height": 2007,
  "posture": "open", "layout": "wide", "target": { "deviceType": "iPhone Duo" } }
```

- `folded` is the cover display, `open` (or `unfolded`) the inner one, `half-open` the hinge part-way
  (`target.hingeAngle`, default 90: tabletop held landscape, book held portrait).
- **Android** ([adb.md](adb.md#foldables)): the emulator's console (`adb emu fold`, `emu unfold`, `emu posture 2`),
  or a real foldable's `cmd device_state state`; then the screen is woken and unlocked (a fold locks it), the
  display in use found again, `wm size` and `wm density` set again on it (each physical display keeps its own) and
  demo mode applied again. Captured from the display in use (`screencap -d`).
- **iPhone Duo** ([simctl.md](simctl.md#the-iphone-duo)): `simctl` can't fold a simulator; the driver uses
  DevFlow's fold control (`maui devflow device fold set …`, experimental: no agent needed, any app) and captures the
  display it made active. The inner display is landscape: **2853×2007**, `width` 2853 and `height` 2007.
- A `posture` step folds in the middle of a screen's steps. Drivers with a host (the agents, Appium, Maestro,
  XCUITest) fold through it.

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
| `inUse` | how the screens look in use, app-wide, as the user put it: `rule` (their words), `by` (who and when), `values` (what's believable here), `save` (`false`, the default: forms are captured filled, before they're saved). In `staging.md`; a run warns about each screen without its own `inUse` ([staging.md](staging.md#looking-in-use)) |
| `notes` | house rules that fit no other field (strings), in `staging.md` |
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
| `type` | `{ "text": "…", <finder>, "rate"? }` | types into the focused field, or one found by `id`, `label`, `xpath`, `css`, or `into` (its placeholder text); `rate` (keys a second) types key by key, for a recording ([below](#typing-at-a-persons-pace)) |
| `wait` | a number (ms), `{ "ms": … }`, or an element (with `contains`, optionally) | an element waits for it to appear (and, with `contains`, to show that text), up to its `timeout` (seconds, default 10). A driver that can't see elements waits and warns |
| `scroll` | `{ "to": <element> \| "top" \| "bottom" }` or `{ "direction": "up"\|"down"\|"left"\|"right", "times": n }`, either with `"in": <element>` | `to` an element looks `direction` first (default down) until it's in view or the content stops moving, then the other way; `"top"`/`"bottom"` scroll until the content stops moving; `in` scrolls within that element (a pane, a list) rather than at the screen's middle (on a two-pane layout, the other pane): the scroll view itself or anything inside it (the pane's content, one of its fields), whose nearest scrolling ancestor is what's scrolled ([below](#scrolling-in-a-pane)). On iOS through Appium each scroll is a quick swipe ([appium.md](appium.md#scrolling-on-ios)). Wait for scroll bars to fade after (`settle`) |
| `back` | `true` | the system back (Android), the agent's or Appium's back |
| `swipe` | `{ "from": [x, y], "to": [x, y], "ms": …, "hold": … }` or `{ "direction": … }` | `ms` is how long the move takes; `hold` (ms, default 0) keeps the finger down at `from` before it moves, for a slider, a drag handle, a reorder or a custom pan gesture ([below](#dragging-a-slider-or-a-handle)) |
| `flow` | a string (a Maestro flow's path, a UI test's name) or the flow driver's own object | run by the driver that understands it |
| `script` | a string (split like a shell would, not run by one), an argument list, or `{ "run": …, "timeout": s }` | a command the user provides, run as is from the plan's folder, with the variables below |
| `appFile` | `{ "file": "seed/app.db", "into": "Library/Caches/app.db" }` (`into` may be `{ "ios": …, "android": … }`) | copies a file into the app's own data, the app stopped first and the old file (and a database's `-wal`/`-shm`) removed: the simulator's data container, Android's `/data/data/<package>` through `run-as` (debug builds). Done by the `simctl` and `adb` drivers, and through them by the agents and Appium |
| `settle` | `true` or `{ "timeout": s, "ignore": [[x, y, w, h], …] }` | waits until two screenshots in a row are identical (outside the `ignore` rectangles, in the picture's pixels: an illustration that never stops moving); a screen that never settles is a warning |
| `posture` | `"folded"`, `"open"`, `"half-open"` | folds the device in the middle of the steps ([Foldables](#foldables)); `simctl`, `adb`, and the drivers they host |
| `hideKeyboard` | `true`, or `{ "done", "tap", "scroll", "own" }` | closes the on-screen keyboard if it's up, trying each way until it's down ([below](#the-keyboard-focus-and-forms)); never a navigation back |
| `unfocus` | `true`, or `{ "tap": <element or {x, y}> }` | clears the text field's focus, so no caret blinks in the shot ([below](#the-keyboard-focus-and-forms)) |
| `fill` | a list of `{ "field": <element, or an id>, "text": "…", "rate"? }`, or `{ "fields": [...], "in", "keyboard", "unfocus", "scrollTo", "rate" }` | types a form's fields in one step, the same on every driver that types ([below](#the-keyboard-focus-and-forms)) |

Any step may carry a **`name`** (`{ "tap": { "id": "tab-history" }, "name": "open-tab" }`) for an override's
`stepsPatch` to refer to it; names are unique within a screen's steps.

### The keyboard, focus and forms

**`fill`** types into several fields at once, as a person filling the form would: for each `{ "field", "text" }`
(`field` an element, or a string that's an id), the field is brought into view (`scroll {"to": …}`, both ways,
within `in`: the pane, or anything in it, [below](#scrolling-in-a-pane)), then typed into (the driver's `type`); on
Android the keyboard is closed first (it covers the fields below the one just typed into, and `uiautomator` lists
only what's on screen). Then the keyboard is closed (`keyboard`: `true` by default, `"keep"` to leave it up, or
`hideKeyboard`'s object), the focus is cleared (`unfocus`, default `true` unless the keyboard's kept) and, with
`scrollTo` (`"top"`, `"bottom"` or an element), the form is scrolled back: typing into a long form scrolls it, and
the shot would start mid-form. Nothing is submitted (no Return, no Save). A field that can't be found fails the step
naming it ("field 2: id 'salt'"). Fields are typed into as they are: a field that already holds text gets the new
text after it.

```json
{ "fill": { "fields": [ { "field": "servings", "text": "12" }, { "field": "minutes", "text": "45" },
                        { "field": { "text": "Notes" }, "text": "extra lemon" } ],
            "in": { "id": "scale-form" }, "keyboard": { "done": { "label": "Done" } }, "scrollTo": "top" },
  "name": "fill" }
```

On `maestro` a `fill` becomes `scrollUntilVisible` (down only), `tapOn`, `inputText` and `hideKeyboard` per field; it
can't scroll within a pane (`in`). Give the step a `name` so a device's `stepsPatch` can change it.

#### Typing at a person's pace

A value goes in at once by default: right for a screenshot, wrong for a preview video, where a field jumps from
empty to full. **`rate`** (keys a second, above 0, at most 50) types key by key instead, so a recording shows each
key land: on a `type`, on a `fill` (every field), or on one `fill` field (it wins over the fill's).

```json
{ "fill": { "fields": [ { "field": "servings", "text": "12" }, { "field": "minutes", "text": "45" } ], "rate": 4 } }
```

| Driver | With a `rate` |
|---|---|
| `appium` (iOS, Android) | one `setValue` a key, which appends; paused `1/rate` between keys |
| `adb`, `uiautomator` | one `input text` a key; each call takes its own time on the device, so the pace is at most `rate` |
| `chrome` | one `Input.insertText` a key |
| an agent (DevFlow, Ailoha) | the host's own `type` gets the rate where it types into the focused field; its `fill` puts a value in at once, so the rate is left out, with a warning |
| `maestro`, `macos` | the value goes in at once; the rate is left out, with a warning |

Leave `rate` out of screenshot plans: it only slows the run.

**Verify only what the shot shows.** A `verify` (and its `contains`) is checked against what the driver sees when
the shot is taken, which is what's on screen (Android's dump lists nothing else). A field `fill` typed below the visible
part, out of sight once `scrollTo` has scrolled the form back, can't be checked there: its `verify` fails ("wrong
state"). `fill` warns when that's so ("fill typed into id 'notes', which is out of sight once the form is scrolled
back…"). Check the fields the shot shows (on a short display, maybe fewer than on a tall one: a device's
`overrides` may change its `verify`), or leave `scrollTo` out when the shot should show the lower fields.

**`hideKeyboard`** tries, in order, until the keyboard is down (the driver looks after each try, where it can):

1. the driver's own close (`"own": false` leaves it out): Android's back, only while `dumpsys input_method` says
   the keyboard is up (a full-screen landscape keyboard too: [adb.md](adb.md#the-keyboard)); Appium's `mobile:
   hideKeyboard` (on iOS the keyboard's Done, Return, Go, Search or Next key). **A number pad has none of those**,
   so on iOS this always fails for it ("did not know how to dismiss the keyboard");
2. the app's own Done: `done` (an element, or `{x, y}` for a round close button with no name); without one, Appium
   on iOS looks for a button named Done, Close, Hide keyboard or Dismiss keyboard (an input accessory's, or one
   floating beside the keyboard) by itself. For a number pad this is the way that works;
3. a scroll: `scroll` (`true` is `up`, or a direction, or `{ "direction", "in" }`): an interactive keyboard closes
   when its scroll view is dragged;
4. last, a tap on something neutral: `tap` (a title or label outside the field, or `{x, y}`). Many apps don't close
   the keyboard for a tap outside a field (iOS doesn't by itself), and a tap or press that lands on a field opens
   it again.

Still up after all of them, the step fails: "the keyboard is still up after …", naming each try and what's not
been tried yet. Look for the app's own Done first (`--inspect`'s tree; on iOS a button beside or above the number
pad); only when the app has no way to close it is it the app's to fix: tell the user, with the device and screen.
Don't capture it with the keyboard up, and don't drop the screen's typing on that device (a `stepsPatch` that
removes the `fill`) unless the user decides to, and then say so in its `inUse`. A driver that can't see the
keyboard (`simctl`, an agent on iOS) does the plan's `done` and `tap` once each; with neither, the step is
`skipped`.

**`unfocus`** clears the text field's focus after typing: closing the keyboard doesn't (Android's back closes the
keyboard and leaves the field focused, its caret blinking, and a shot lands with it on or off). With `tap`, that's
tapped first. Then the driver's own way: on Android (`adb`, `uiautomator`, and the agents and Appium on an adb host)
the dump is read and, only while a text field has the focus, the keyboard is closed and Escape pressed (newer
Android versions clear the focus on it); the dump is read again, and if the field is gone (Escape went back, as an
unhandled Escape does on older versions) the step fails saying to give `unfocus` a tap. On the web, the focused
element's `blur()`. Elsewhere (an iOS agent) give it a `tap`, or it warns. `settle` after typing with no `unfocus`
since warns when a field still has the focus (read from the dump or the page) or, where the driver can't tell, when
the settled screen changes again within a second (a caret's blink).

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
the whole id or its last part, so `search` finds `com.example.samplerecipes:id/search`), `text` and `label` (exact,
then ignoring case and surrounding space, then contained: the first that finds one wins), `xpath`, `css` (web);
with an optional `timeout` in seconds. Prefer `id`: text changes with the locale. Each driver lists the step kinds
and finders it supports (`capabilities()`); a screen with a step it can't do is `skipped` without running anything.

| Driver | `text` / `label` | `xpath` |
|---|---|---|
| `adb`, `uiautomator` | exact, ignoring case and space, contained (in the `uiautomator dump`) | XPath 1.0's everyday part over the dump (below) |
| `devflow`, `ailoha` | the agent's own query (exact), then the tree: ignoring case and space, contained | the agent's HTTP query, else the same XPath over the tree (elements named by type, fields as attributes) |
| `appium` | iOS and Mac predicates `==`, `==[c]`, `CONTAINS[c]` over label, value and name (title on a Mac); Android and Windows XPaths `@text=`, `translate()`, `contains()` | the platform driver's own XPath (full XPath 1.0) |
| `chrome` | exact, ignoring case, contained (visible text) | the browser's |
| `macos` | the whole of a name, description, title or value (AppleScript's `is` ignores case), then a part of one | no |
| `maestro` | Maestro's own text match (a regular expression of the whole text; this driver escapes it) | no |

**"This element shows this text": `contains`.** A `wait` or `verify` element may add `contains`: the element
`id` (or `text`, `label`, `xpath`, `css`) finds must show that text, itself or anything under it, ignoring case and
runs of space. `{ "id": "servings", "contains": "24" }` passes on iOS, where 24 is the chip's own label, and on
Android, where it's a child's text, with no hand-written xpath naming both platforms' attributes and a
descendant. When several elements match (a list of chips with one id), any one that shows it passes. A miss is
"wrong state: id 'servings' containing '24' wasn't on screen".

| Driver | What `contains` reads |
|---|---|
| `adb`, `uiautomator` | the dump: the element's and its descendants' `text` and `content-desc` |
| `devflow`, `ailoha` | the agent's tree: the element's and its children's text and value (`css`: the element's own) |
| `appium` | the page source, once: iOS's `label` and `value`, Android's `text` and `content-desc`, a Mac's `title`, Windows' `Name`, the element's and its descendants' |
| `chrome` | `innerText`, `textContent`, the value, `aria-label`, `title`, `alt` |
| `macos` | the name, description, title and value of the element and everything in it |
| `maestro` | can't: a `wait` with `contains` skips the screen (wait for the `text` itself); `verify` is `unchecked` on a flow driver anyway |

**XPath on the tree-reading drivers** (`adb`, `uiautomator`, the agents' tree): paths with `/` and `//`, `*`, `.`,
`..`, `@attr`, positions (`[2]`, `[last()]`, `(//node)[2]`), `=`, `!=`, `<`, `>`, `and`, `or`, and the functions
`contains`, `starts-with`, `ends-with`, `not`, `normalize-space`, `translate`, `lower-case`, `upper-case`, `string`,
`concat`, `string-length`, `text`, `name`, `position`, `last`. Attribute names differ by platform (Android's
`@text`, `@content-desc`, `@resource-id`; iOS's `@label`, `@name`, `@value`), so a cross-platform xpath names
both: `//*[contains(@text,'Lemon') or contains(@label,'Lemon')]`.

### Scrolling in a pane

`in` (a `scroll`'s, a `fill`'s, `hideKeyboard`'s `scroll`) names an element: the scroll view itself, or anything
inside it, often easier to name (an id on the pane's content, or one of the pane's own fields), so one
`{ "id": "servings" }` serves every device where the scroll view itself has no id. What's scrolled is the nearest
view that is that element or holds it and scrolls: in `adb`'s and `uiautomator`'s dump, and Appium's Android page
source, a node with `scrollable="true"`; in Appium's iOS or Mac page source, an `XCUIElementTypeScrollView`,
`Table`, `CollectionView` (or a Mac's `Outline`), found again by its path for its element id; in an agent's tree, a
`ScrollView`, `CollectionView`, `ListView`, `RecyclerView` or `ScrollViewer` (or a `scrollable` flag where the agent
gives one); on the web, the nearest element whose overflow scrolls (`overflow: auto` or `scroll`, with more content
than room). With nothing around it that scrolls, the element itself is scrolled, as named, **except a text field on
a driver that swipes** (`appium`, `adb`, `uiautomator`): a swipe on a field taps it and opens the keyboard (and a
`scroll {"to": "top"}` would repeat that until it gave up), so the screen is scrolled instead, with a warning ("it's
a text field, so the screen was scrolled instead"); name the pane's scroll view or something else in it that isn't
a field. The agents and `chrome` scroll without touching, so they scroll the field's pane as named. When what was scrolled
isn't the element named, the report's `panes` says so ("in id 'servings': scrolled its nearest scrolling ancestor,
android.widget.ScrollView [600,200][1080,1920]"); read it when a scroll moved the wrong thing. Once found on a
screen, the pane serves that screen's later scrolls when the element named has scrolled out of sight (a field at
the top of the form, once the fill's reached the bottom).

On iOS through Appium a `tap` on an element below the visible part scrolls it into view first (XCUITest does), so
a `scroll {"to": <element>}` before a `tap` of the same element isn't needed; on Android and the agents it is.

### Dragging a slider or a handle

A `swipe` from one point to another touches down and moves straight away: a scroll view takes that for a scroll or a
flick, and a control inside one that drags (a slider, a drag handle, a list's reorder grip, a custom control with
its own pan gesture) may not move at all, though the step succeeded. Give it a `hold`, the ms the finger stays down at
`from` before it moves, and a slower move (`ms`):

```json
{ "swipe": { "from": [180, 1240], "to": [900, 1240], "hold": 400, "ms": 1000 }, "name": "set-servings" }
```

400 ms is usually enough to read as a press; a control that waits for a long press (a reorder) may want its
platform's long-press time (about 500 ms). `hold` goes with `from` and `to`; with a `direction` it's left out with a
warning. How each driver holds: Appium, a W3C `pause` after `pointerDown` (iOS and Android); `adb` and
`uiautomator`, `input motionevent` DOWN, a `sleep`, a few MOVEs along the way and UP in one shell line, or on an
older Android whose `input` has no `motionevent`, a long press and then the swipe with the finger lifted between
(a warning: drive that device with Appium). Maestro, DevFlow and Ailoha can't hold before a swipe: they leave it
out and warn. Check the picture: a slider that didn't move is still a shot taken.

### `verify` and the keyboard

`verify` holds elements and, optionally, `{ "keyboard": "hidden" | "shown" | "any" }`. **A screen whose steps type
nothing is checked for `hidden` without asking**, where the driver can tell (`adb` and the agents on Android:
`dumpsys input_method`; Appium: `mobile: isKeyboardShown`); a keyboard left up makes the shot `missed`, "wrong
state", and says to end the steps with `hideKeyboard`. A screen that types isn't checked unless it asks, but a
keyboard left up is a warning in the report. `{ "keyboard": "any" }` turns the check off. A driver that can't see
the keyboard (`simctl`, an agent on iOS) reports an asked-for check as `unchecked`: look at the picture.

## `capture-report.json`

Written to `<out>/capture-report.json` after every run.

```json
{ "version": 1, "startedAt": "2026-11-14T10:02:11Z", "plan": "capture-plan.json",
  "shots": [
    { "locale": "en-US", "device": "iphone-6.9", "screen": "plan", "status": "taken",
      "path": "en-US/iphone-6.9/plan.png", "width": 1320, "height": 2868, "sha256": "…",
      "driver": "simctl", "source": { "deviceType": "iPhone 17 Pro Max", "runtime": "iOS 27.2" },
      "statusBar": "verified", "fixes": [], "warnings": [], "appRevision": "3f2c…" },
    { "locale": "de-DE", "device": "android-phone", "screen": "search", "status": "missed",
      "reason": "tap: id 'search' didn't appear in 10 s", "kept": "previous" }
  ],
  "app": { "revision": "3f2c…", "describe": "v2.1-14-g3f2c1a0", "committed": "2026-11-19T16:05:00+01:00",
           "dirty": false, "repo": ".", "builds": { "ios": { "version": "2.1", "build": "214" } } } }
```

| Field | Meaning |
|---|---|
| `status` | `taken`; `missed` (not reached: `kept` is `previous` when the last run's picture stays, else `none`); `failed` (reached but unusable: the wrong size, a capture error); `skipped` (a step or device the driver can't do) |
| `reason` | why it isn't `taken` |
| `statusBar` | `verified` (iOS: `simctl status_bar list` shows the override; Android: the status bar's pixels changed with demo mode's clock and came back), `overridden` (applied and not checked: `target.statusBarCheck: false`), `unverified` (the override failed or couldn't be confirmed, or an imported picture whose tool didn't say), `none` (no status bar, or `as-is`). The icons are still for a person to look at |
| `state`, `stateCheck` | the screen's `state` words; its `verify`: `passed`, `failed` (the shot is `missed`, "wrong state"), `unchecked` (the driver can't see elements: look) |
| `fixes` | lossless repairs made: `alpha-flattened`, `converted-to-srgb`, `16-bit-to-8-bit`. Never a resize. Simulators and emulators write an alpha channel that's all opaque: those are flattened quietly (still in `fixes`) and counted once in the report's `notes`; see-through pixels get a warning |
| `warnings` | what a person should look at (a screen that didn't settle, a wait that couldn't see elements, a field `fill` typed that's out of sight for its `verify`) |
| `panes` | what each scroll's `in` scrolled where it wasn't the element named: its nearest scrolling ancestor, or the element itself when nothing around it scrolls ([scrolling in a pane](#scrolling-in-a-pane)); left out when there's nothing to say |
| `source` | what produced it (device type and runtime, AVD and API level, browser) |
| `recording` | with `capture.py --record`, the screen's steps recorded: `path` (`<locale>/<device>/<screen>.mov` from a simulator, `.mp4` from Android, beside the picture), `seconds` (from its start to the stop), `by` (`simctl recordVideo`, `adb screenrecord`), `from` (the step it started at: the first `launch`), `display` (when the device has more than one), `flush` (`{"by": "status bar battery 99%", "at": 21.4}`: the moment's change that flushed a simulator's last frames, that many seconds in: `video.py encode … --end 21.4`; `null` on Android, or where there's no status bar). Left out without `--record`, and when the shot isn't taken |
| `appRevision` | the app's commit when this shot was taken (a taken shot, when the app is in a git checkout): what `--changes` starts from |

Each PNG is exactly its device's `width`×`height`, 8-bit RGB (no alpha, no `tRNS`), sRGB, not interlaced. Files are
written to a temporary folder and moved into place at the end, so a failed run never leaves a mix.

The report also has `app`, the app this run captured: git's `revision`, `describe`, `committed`, `dirty` (the
screens' paths had changes not committed), `repo`, and `builds` (an iOS-family `.app`'s version and build number
from its `Info.plist`); `devices` (each device's source and warnings; an Appium simulator's source also has the
`wdaPort` and `mjpegPort` its sessions used) and `notes` (said once a run, like the count of
quietly flattened pictures). A run keeps earlier entries for what it didn't run this time (`--screens`,
`--devices`, `--locales`), and drops those the plan no longer has (a screen, device or locale removed, or omitted
on a device), naming them in `notes`.

## Options outside the plan

- `capture.py --cleanup`: delete the simulators and AVDs the skill created for itself (`appstores-<device id>`) after the
  run. It never deletes one the plan names by UDID, serial or AVD name.
- `capture.py --inspect`: also save each screen's UI tree (after its steps, or where they stopped) to
  `<out>/.inspect/<locale>/<device>/<screen>.txt`, for writing steps and `verify`.
- `capture.py --record`: also record each screen's steps, for a preview video: from just before its first `launch`
  (after the device is prepared, any seed, and any reboot a locale change needs) until a second after its last
  step, stopped before its `verify`, the screenshot and the reset, to `<out>/<locale>/<device>/<screen>.mov`
  (simulators: `simctl io recordVideo` on the display the screenshots take, its last frames flushed by a moment's
  status bar change) or `.mp4` (Android: `screenrecord`, pulled after; 180 s at most). Devices whose driver has no
  simulator or Android device under it (`chrome`, `macos`, a Mac or Windows app, `target.host: "none"`) are refused
  before anything runs (exit 3). The report's `recording` says where, how long and where to trim
  ([video.md](video.md#recording-a-screens-steps-capturepy---record)).
- `capture.py --write-staging`: write `staging.md` from the plan, and stop.
- `capture.py --changes [revision]`: what changed in the app since the last capture (the oldest `appRevision` the
  report keeps, or `revision`: a commit, tag or branch), in `appSource.paths` and the screens' `sources`
  (uncommitted changes included): the commits, the files, and the screens to re-check, each with why (its
  `sources` changed; a step's or `verify`'s id or text is on a changed line, or was removed). Exit 3 when the app
  isn't in a git checkout or no revision is known. A run warns when the app moved since the shots it keeps.
- `capture.py --current [folder]`: list the current store screenshots (`existing/<store>/screenshots/`,
  `store-screenshots.json`'s shots, `design/current.json`, or the folder), to start the screens from; and stop.
  `design/current.json`'s shots come by group (store, locale and slot: App Store and phones first), in order, each
  with what it shows, the capture screen it maps to (or "not mapped yet") and its caption.
