# Android emulators and devices: `adb`

The `adb` driver captures Android phones, tablets, TV, Wear OS and Fire OS devices, emulated or real, with the SDK's
platform-tools. It reaches screens by intent extras and deep links, and can tap, type, swipe and go back through
`input`, finding elements in a `uiautomator dump` (the `uiautomator` driver is the same element finding on its
own). Always `-s <serial>`: with two devices attached, a bare `adb` fails or picks the wrong one.

## The plan's target

```json
{ "id": "android-phone", "platform": "android", "driver": "adb", "width": 1080, "height": 1920,
  "target": { "avd": "appstores-android-phone", "profile": "medium_phone",
              "systemImage": "system-images;android-36;google_apis;arm64-v8a",
              "wmSize": "1080x1920", "density": 420 } }
```

- `systemImage` (and `profile`, a device definition such as `medium_phone`): an AVD of the skill's own,
  `appstores-<device id>`, created with `avdmanager` when it isn't there and deleted with `capture.py --cleanup`.
- `avd`: an emulator by AVD name: one already running is used as it is, otherwise it's started headless and stopped
  after (`readOnly: true` adds `-read-only`, so the AVD's disk is never written). A person's own AVD only when the
  plan names it.
- `serial`: a device or emulator already connected (`adb devices`). **Only when the user names it.** It's the
  person's: never stopped or deleted, and everything changed on it is put back.
- `wmSize`: the size the device lays out and renders at. **By default the device's own `width`x`height`**, so a
  1080×1920 device gets `wm size 1080x1920`; `null` leaves the display alone. `density` sets `wm density`. Both are
  reset after.
- `deviceLocale: true`: set the device's language as well as the app's (the default is the app's only, Android 13
  and later).
- `display`: a display id for `screencap -d` (foldables, desktop modes).
- `navigation`: `gesture` or `threebutton` (or `twobutton`): the navigation mode, through SystemUI's navigation bar
  overlays (`cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.gestural`), put back
  after. Gesture navigation leaves a thin handle over the bottom of the content instead of a bar of buttons; the
  handle itself can't be hidden from adb on stock images, so keep important content clear of the bottom 24 dp, or
  let the design step crop nothing and frame it.
- `statusBarMobile: true`: show a full mobile signal in demo mode (hidden by default: an emulator without a SIM
  draws an empty triangle). `statusBarCheck: false`: skip the pixel check below (the report then says
  `overridden`).
- `adb`, `emulator`, `avdmanager`: the tools' paths, when they aren't where the driver looks: `$ANDROID_HOME` (or
  `$ANDROID_SDK_ROOT`)'s `platform-tools/adb`, `emulator/emulator` and `cmdline-tools/latest/bin/avdmanager`, then
  the newest versioned `cmdline-tools/<version>/bin/avdmanager` (an SDK Manager install often has no `latest`), then
  `tools/bin`, then `PATH`.

`script` steps get the device as `ANDROID_SERIAL` (which adb honours, so a script's bare `adb` reaches only this
device) and `APPSTORES_SERIAL`, with `APPSTORES_DEVICE`, `APPSTORES_PLATFORM`, `APPSTORES_APP_ID`,
`APPSTORES_LOCALE` and `APPSTORES_SCREEN`.

## Lifecycle

| Step | Command |
|---|---|
| Create an AVD | `avdmanager create avd -n appstores-android-phone -k "system-images;android-36;google_apis;arm64-v8a" -d medium_phone` |
| Start headless, wait | `emulator -avd appstores-android-phone -no-window -no-audio -no-boot-anim -no-snapshot`, then `adb -s <serial> wait-for-device shell 'while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 1; done'` |
| Install | `adb -s <serial> install -r build/app.apk` (a .NET MAUI Debug APK needs `-p:EmbedAssembliesIntoApk=true` at build: a Fast Deployment APK has no assemblies in it and crashes on start; the driver warns) |
| Clear data (`launch.clean`) | `adb -s <serial> shell pm clear com.example.samplerecipes` |
| Grant permissions (`staging.permissions.android`) | `adb -s <serial> shell pm grant com.example.samplerecipes android.permission.POST_NOTIFICATIONS` after install, `pm revoke` in reset (`appops set` for special ones, by hand) |
| A file into the app's data (`appFile`) | `adb -s <serial> push app.db /data/local/tmp/appstores-app.db`, then `adb -s <serial> shell run-as com.example.samplerecipes sh -c 'mkdir -p cache && rm -f cache/app.db* && cp /data/local/tmp/appstores-app.db cache/app.db'`: `run-as` works only for a debuggable build; paths are relative to `/data/data/<package>` (`files/`, `cache/`, `databases/`) |
| Launch with extras | `adb -s <serial> shell am start -W -S -n com.example.samplerecipes/.MainActivity --es ScreenshotScreen plan --es ScreenshotSeed demo` (`-S` stops it first; the driver types each value: `--es` strings, `--ez` booleans, `--ei` integers, `--ef` floats) |
| Deep link | `adb -s <serial> shell am start -W -a android.intent.action.VIEW -d 'samplerecipes://recipe/demo' com.example.samplerecipes` |
| Tap, type, swipe, back | `input tap <x> <y>`, `input text 'pasta'` (spaces as `%s`), `input swipe x1 y1 x2 y2 300`, `input keyevent KEYCODE_BACK` |
| Find an element | `uiautomator dump /sdcard/ui.xml` then `adb exec-out cat /sdcard/ui.xml`: match `resource-id`, `text` or `content-desc`, tap the centre of its `bounds` |
| D-pad (TV) | `input keyevent KEYCODE_DPAD_RIGHT`, `KEYCODE_DPAD_CENTER` |

A `.NET MAUI` `AutomationId`, a Compose `Modifier.testTag` (with `testTagsAsResourceId = true`) and a View's
`android:id` all show up as `resource-id`. A plan's `{ "id": "search" }` matches a `resource-id` ending in
`search` (`com.example.samplerecipes:id/search`).

## Exact size: `wm size`

```sh
adb -s <serial> shell wm size 1080x1920
adb -s <serial> shell wm density 420
# … capture …
adb -s <serial> shell wm size reset
adb -s <serial> shell wm density reset
```

The app lays out and renders at the size set, so the capture is that size without scaling.

- **Every current phone emulator profile is taller than Play's 2:1 limit:** `medium_phone` 1080×2400 (2.22),
  `pixel_10` 1080×2424, `pixel_10_pro_xl` 1344×2992. A full-screen capture from any is rejected ("the maximum
  dimension can't be more than twice the minimum"). Set `wm size 1080x1920` (9:16, Play's recommended size). Don't
  crop instead: the app wasn't laid out for it and the bars are lost.
- Tablets: `medium_tablet` and `pixel_tablet` are 2560×1600 (16:10). The rules data takes 16:9 or 9:16 for Play's
  tablet slots: `wm size 2560x1440` (or `1920x1080` on `small_tablet`).
- Pick a density that keeps the layout's density class the app was designed for (e.g. 420 on a phone at
  1080×1920); a very different density changes which layout and assets load.
- Restore in `finally`. A device left at 1080×1920 looks broken to its owner.

## Status bar: SystemUI demo mode

```sh
adb -s <serial> shell settings put global sysui_demo_allowed 1
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command enter
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command clock -e hhmm 0941
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command battery -e level 100 -e plugged false
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command network -e wifi show -e level 4 -e fully true
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command network -e mobile hide
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command notifications -e visible false
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command status -e bluetooth hide -e volume hide -e alarm hide \
  -e location hide -e sync hide -e mute hide -e speakerphone hide -e zen hide -e eri hide -e tty hide -e cast hide -e hotspot hide
# afterwards
adb -s <serial> shell am broadcast -a com.android.systemui.demo -e command exit
```

- **`-e fully true` on Wi-Fi**, or some images (API 36 emulators, seen 2026-11-14) draw the Wi-Fi icon with a "!"
  (connected, no internet).
- **Two passes the first time.** The first demo-mode pass after a boot left the real Wi-Fi icon beside demo
  mode's (two Wi-Fi icons on an API 36 image, seen 2026-11-14); after `command exit` and the same broadcasts again
  there's one. The driver does that the first time on each device.
- **The mobile icon hidden** by default: an emulator without a SIM draws an empty signal triangle and a "3G" label
  that `-e datatype none`, `-e level 4` and `-e fully true` didn't fill on that image. `target.statusBarMobile:
  true` shows it full instead (`-e mobile show -e datatype none -e level 4 -e fully true`), for a real device with a
  SIM.

**Checked in the pixels.** Demo mode can't be read back, and the broadcasts are answered whether SystemUI honours
them or not. So after them the driver captures the status bar's strip (24 dp at the density), moves demo mode's
clock to another time, captures it again, puts the clock back, and captures it a third time: the report says
`verified` only when the strip changed with the clock and came back; `unverified` (with a warning) when it didn't
change (demo mode ignored: some makers' skins) or kept changing (an animation behind it). That proves demo mode is
drawing the bar and its clock; the icons are still for a person to look at in every picture.

Play's own guidance: no carrier names or notifications; battery, Wi-Fi and signal full. Since Android 15 apps draw
edge to edge, so the bars sit over the app's content and show more. Gesture navigation's handle looks cleaner than
three buttons (`target.navigation: "gesture"`). TV, Wear OS and Automotive have no phone status bar.

## Locale, appearance, animations

| What | Command |
|---|---|
| The app's language (Android 13+) | `adb shell cmd locale set-app-locales com.example.samplerecipes --locales de-DE` |
| The device's language (`target.deviceLocale: true`) | `adb shell cmd locale set-device-locale de-DE` (recent images); older emulators: `setprop persist.sys.locale` and a SystemUI restart |
| Dark mode | `adb shell cmd uimode night yes` (`no` after) |
| Animations off | `adb shell settings put global window_animation_scale 0` (and `transition_animation_scale`, `animator_duration_scale`) |
| No touch dots | `adb shell settings put system show_touches 0`; `pointer_location 0` |
| Font scale | `adb shell settings put system font_scale 1.0` |

The driver records each value before changing it and puts it back.

## Capturing

```sh
adb -s <serial> exec-out screencap -p > out.png
```

- `exec-out`, not `shell`: `shell` can mangle binary output.
- Foldables and desktop modes have several displays: `screencap -d <display id>` (ids from
  `dumpsys SurfaceFlinger --display-id`) or `-a` for all.
- Leave `--preserve-display-colors` off, so the output is the system's sRGB-processed picture.
- Real devices: check the size, and that the device's own status bar honours demo mode (some makers' skins don't).

## TV, Wear, Fire

- Android TV: `tv_1080p` (1920×1080) or `tv_4k` (3840×2160) profiles; at least one TV screenshot is needed to
  publish to TV, and the listing also needs a 1280×720 banner without alpha. Drive with D-pad keyevents.
- Wear OS: `wearos_*` profiles give a square framebuffer; Play wants 1:1, at least 384×384, no mask, no
  transparency.
- Fire TV and Fire tablets: adb works the same on Fire OS devices.

## Reset (always, in `finally`)

Demo mode `exit`; the display size and density back; dark mode, language and animation scales back to what they
were; the app stopped; an emulator the driver started stopped; with `--cleanup`, its own AVD deleted. A person's own
device is never wiped.
