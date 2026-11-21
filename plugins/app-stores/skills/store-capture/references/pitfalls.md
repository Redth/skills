# Pitfalls

What has gone wrong when capturing store screenshots and previews, and how to avoid it. Each is written so it can
happen to any app.

## Sizes

- **A device's size class isn't its pixel size.** A set captured on the iPhone 11 simulator (listed in Apple's 6.5"
  class) came out 828×1792, a size the App Store doesn't take. Read every PNG's header; choose devices from
  [sizes.md](sizes.md), and check the first capture of any device not in it.
- **Play's 2:1 limit and modern phones.** Every current phone emulator profile is about 2.2:1, so a full-screen
  capture is rejected. `wm size 1080x1920` lays the app out at 9:16; cropping instead cuts off the bars and shows a
  layout that wasn't made for it.
- **Upscaling and stretching.** The stores ask against "blurry, distorted or pixelated" and "stretched" images, and
  Apple scales the largest set down itself. Never scale a smaller capture up or another aspect across; a wrong size
  is a capture to redo.
- **Landscape assumed.** Whether a capture comes out landscape depends on the app's scene, not the device: check
  the size.
- **Two screens.** Foldables and the iPhone Duo have more than one display; without choosing one (`--display`,
  `screencap -d`) a capture fails ("Invalid argument" on the Duo; on Android a warning printed before the PNG) or
  takes the screen that's off. The drivers pick the one in use; `target.display` names one.
- **The iPhone Duo's inner display is landscape**: it captures 2853×2007, though it's listed 2007×2853. Write the
  device that way round; don't rotate.

## Foldables

- **Folding locks the screen** (an Android emulator), and the next launch lands behind the keyguard. The `adb`
  driver wakes and unlocks it after every posture change; a script that folds by itself has to as well (`input
  keyevent KEYCODE_WAKEUP`, `wm dismiss-keyguard`).
- **`wm size` is per physical display.** Set while open, it never reaches the cover display; the fold then
  captures the cover display at its own 1080×2424 and the shot fails. The driver sets it again after each posture
  change and puts each display's back.
- **Demo mode after a fold** showed a stray icon beside 9:41 until applied again; the driver re-applies it.
- **No way to fold from a script** was the trial's first blocker. Use the plan's `posture` (the emulator's
  console; DevFlow's fold control for the iPhone Duo) rather than a `script` step per device.
- **A layout that changes with the posture**: an open foldable may show two screens side by side and drop the tab
  bar, so a tap meant for a tab lands on something else (`verify` catches it). Patch the steps for that layout
  (`stepsPatch`, a device `layout`), or `omit` the screen there.

## Pixels

- **Alpha.** `simctl … --mask=alpha` (transparent corners), Mac window captures (corners and shadow), a web
  capture with a transparent background, an engine's transparent background, design tools exporting RGBA even when
  every pixel is opaque. Apple rejects alpha; a strict checker sees colour type, not pixels. The drivers flatten it
  (`flatten`, black by default) and report `alpha-flattened`; fix the source if it keeps happening. Simulator
  screenshots carry an alpha channel even with `--mask=ignored` (iOS 27.2, seen 2026-11-14), and so do some
  emulators' `screencap`s: when every pixel is opaque it's harmless, so it stays in `fixes` but isn't shown per
  shot, and the report's `notes` count it once. See-through pixels are a warning on the shot.
- **Colour profiles.** Simulators of P3 devices and Mac captures can be tagged with the display's profile; Android's
  `--preserve-display-colors` keeps the panel's. Keep captures sRGB (or untagged sRGB), 8 bits a channel, so the
  stores' pages show what was reviewed. Conversions are reported (`converted-to-srgb`, `16-bit-to-8-bit`).
- **The app's own rendering bugs pass every check.** On a newer build one platform drew a value and its "1 day
  ago" over each other in a two-column form; the other platform was fine. `verify` passed (the elements were
  there), the size, alpha and status-bar checks passed, and only looking at the picture at full size caught it.
  No automated check here sees overlapping, clipped or truncated text ("Ingredi…"), a label cut by its
  container, or a broken layout: look for them in every picture, and report them to the user as the app's bugs,
  with the shot's path and what's wrong. Don't hide them (a different screen, a shorter seed value, a crop) and
  don't hand the picture on: it isn't shippable until the app is fixed, and the user decides what to do meanwhile.
- **The Dynamic Island and rounded corners.** Rectangular captures show content under the corners and an empty
  space where the island is. That's what the stores expect; keep important content in the safe area, and draw the
  island in a frame, not into the shot.

## The status bar

- **Overrides that don't take.** `simctl status_bar` was reported broken on iOS 16 and 17 runtimes, silently. The
  report's `statusBar` says whether it was verified; look at every picture's top edge.
- **Lost on reboot or erase.** A locale change that reboots the simulator drops the override: apply it after every
  boot (the drivers do).
- **Read back isn't seen.** A status bar reported fine while the picture showed a Wi-Fi "!" and "3G" beside an empty
  signal triangle (Android demo mode on an API 36 emulator, 2026-11-14): the broadcasts were all answered. The
  driver now sends Wi-Fi `fully` and hides the mobile icon, and calls the bar `verified` only when its pixels moved
  with demo mode's clock; anything it can't confirm is `unverified`. The icons are still a person's to check.
- **The mini simulators' red banner.** 360×780@3x simulators have shown a red `rdar://…` banner in the status bar
  on recent Xcodes. No mini is a required size: don't use them.
- **Demo mode ignored.** Some Android makers' system UIs ignore SystemUI demo mode on real devices; emulators honour
  it.
- **Different times on different devices.** One `clock` for the whole plan.

## Locale

- **Half translated.** The app's language set by a launch argument, but the alert, keyboard and share sheet still
  in the system's: set the device language when system UI shows.
- **Demo data in one language.** English content in every locale's shots. Translate the fixtures.
- **Text that finds elements.** A step `{ "tap": { "text": "Search" } }` misses in German. Find by `id`.

## Reaching screens

- **Steps that silently stop working.** A screen reached through five taps broke when a button moved, and the set
  shipped with last month's picture. The report says `missed` and `kept: previous`: say so to the user, every time.
  A screenshot mode by name breaks less often than taps.
- **Coordinates.** Taps at `x`,`y` land elsewhere on another size or locale. Use elements.
- **Scroll bars.** They appear after a scroll and fade a moment later; `settle` after scrolling.
- **The keyboard.** Typing into a field leaves the keyboard up and a caret blinking. Tapping a label near the end
  of the steps didn't close it on iOS; the keyboard's own Done key did. End the steps with `hideKeyboard` and add
  `{ "keyboard": "hidden" }` to `verify` (a screen that types nothing is checked without asking): a `verify`
  element the keyboard doesn't cover passed with the keyboard up. On iOS, `back` is navigation, never a way to
  close the keyboard.
- **Per-device copies of the steps go stale.** A device override that copies the whole step list doesn't get a
  later fix to the base steps (the keyboard's Done reached the phone but not the open Duo's copy, whose shot came
  out with the keyboard up). Name the steps and patch only what differs (`stepsPatch`).
- **Text that matches on one platform and not another.** `verify {text: "Cooking time"}` must find a label drawn
  "COOKING TIME", and "Lemon" one that reads "  Lemon Pasta for 4 people": every driver matches exactly,
  then ignoring case and surrounding space, then contained. Cross-platform xpaths name both platforms' attributes
  (`@text` and `@label`).
- **Waits too short on a cold start.** The first launch after install is slow (and slower on CI); wait for an
  element, not a fixed time.
- **The right screen in the wrong state.** Reached by its taps, but signed out, empty, or under a what's-new sheet:
  the picture looks like a capture and isn't one. Give each screen a `verify` element only its intended state shows
  (a seeded item's name), and agree the staging with the user on one screen first ([staging.md](staging.md)).
- **An animation that never stops** (a gently moving illustration, a live clock) keeps `settle` from finishing;
  the warning is right and the picture is usually fine. `settle: { "ignore": [[x, y, w, h]] }` leaves that region
  out of the comparison.
- **Writing steps blind.** An unnamed button (no id, no label) needs an xpath; `capture.py --inspect` saves each
  screen's tree, so read it rather than opening a session by hand.
- **"No name" that isn't.** `//XCUIElementTypeButton[not(@name)]` found a menu button until a newer build gave it
  `name=" "`. Match it with `normalize-space(@name)=''`, or better, ask for an id.
- **A value on a chip, platform by platform.** iOS puts "24" on the chip itself (`label`), Android on a child
  (`text`): a cross-platform xpath for it names both attributes and a descendant. Write
  `{ "id": "amount", "contains": "24" }` instead ([config.md](config.md#steps)).
- **A newer app breaks steps written for the old one.** Two months of commits later two steps broke: a redesign turned a
  typed field into chips that open a number sheet, and an unnamed button's `not(@name)` stopped matching. `verify`
  caught both as `missed` instead of shooting the wrong screen. Before recapturing, run `capture.py --changes`, show
  the user what changed and which screens it touches, and repair the steps (a `stepsPatch` for one device or
  layout), never the check ([staging.md](staging.md#7-updating-when-the-app-changed)).
- **A set that doesn't look in use.** Every check passed and the user turned the set down: a data-entry form
  was blank, its fields showing only their placeholders. Staging had covered the data, sign-in and skips, but not
  what each screen looks like with someone using it. Ask it per screen (`inUse`), fill forms with believable values
  (`fill`, nothing saved), record the user's rule in `staging.inUse` so later screens get the same, and look at
  every picture asking "does this look in use?" ([staging.md](staging.md#looking-in-use)).
- **A form that typing scrolled.** After typing into a long form the shot started mid-form, the title under the
  navigation bar. `fill`'s `"scrollTo": "top"` (or a `scroll {"to": "top"}` after the keyboard's down).
- **A number pad that won't close.** On a small display `mobile: hideKeyboard` couldn't close a number pad ("did
  not know how to dismiss the keyboard": it has no Done or Return key), and a scroll back up opened it again: a
  direction-only `mobile: scroll` presses for half a second at a quarter of the window before dragging, and that
  point was a field, so the press focused it. What closed it was the app's own Done button beside the pad; what
  scrolled back without reopening it was a quick `mobile: swipe`. The driver now tries a button named Done, Close or
  Hide keyboard after the keyboard's keys, scrolls iOS by swipes, and tries a tap outside the field only last (many
  apps don't close the keyboard for it). Still up after every try, the step fails saying so: find the app's Done
  (`--inspect`), and only when there's none tell the user it's the app's to fix; never ship the keyboard or drop
  that device's typing quietly ([appium.md](appium.md#scrolling-on-ios)).
- **A caret after the keyboard closed.** On Android, back closed the keyboard but the field kept its focus, and
  the caret blinked into some shots and not others (`settle` saw two identical frames either way). `unfocus` (a
  `fill` does it) presses Escape while a field has the focus and checks the screen didn't go back.
- **The other pane scrolled.** On an open foldable the form was the right pane; a `scroll {direction}` swiped the
  screen's middle (the list), and `scroll {to}` only looked down, so a field above was never found and the form
  never went back to its top. `scroll {"in": {"id": <the pane>}}` (and `fill`'s `in`); `scroll {to}` now looks
  both ways.
- **A patch per field.** Typing a form on Android needed, for every field, the keyboard closed (it covers the next
  field), the field scrolled into view (the dump lists only what's on screen) and then the typing. One `fill` does
  that for every field on every driver.
- **A landscape keyboard swallowing a tap.** On an open foldable, text entry put the keyboard full screen; the
  number sheet's Done tap landed on the keyboard, and the next `hideKeyboard` closed only the keyboard. The drivers
  now close a full-screen keyboard before a tap on Android ([adb.md](adb.md#the-keyboard)).

## Builds

- **Stale build output after updating the app.** The first iOS build of a .NET MAUI app after pulling two months
  of commits failed to link from stale `obj/`; a clean build fixed it. Build clean before the first capture after
  an update (.NET: delete the target framework's `obj/` and `bin/`; Xcode: Product ▸ Clean Build Folder or
  `xcodebuild clean`; Gradle: `./gradlew clean`; Flutter: `flutter clean`).

## Devices and machines

- **A person's own simulator erased.** Capturing on "the booted simulator" erased someone's working state. The
  drivers create `appstores-<device id>` devices and use the user's own only when the plan names it.
- **`booted` with two booted.** `simctl` "will choose one". Pass a UDID; pass `-s <serial>` to `adb`.
- **A device left changed.** A run killed half-way left an emulator at 1080×1920 in German with demo mode on.
  Reset by hand, and tell the user what was left: `wm size reset`, `wm density reset`, demo mode `exit`,
  `simctl status_bar … clear`, locale and appearance back.
- **The user's own app driven instead of ours.** With the developer's own simulators running the same debug build,
  an in-app agent's CLI picked whichever agent it found first. The drivers now pin the agent of the plan's app on
  the dedicated device (its UDID or serial, the bundle id, the process) and refuse when they can't tell
  ([devflow.md](devflow.md#which-agent-pinned-to-the-app-on-the-device-it-owns)). A build-time port
  (`-p:MauiDevFlowPort`) isn't honoured while DevFlow's broker runs.
- **Port forwards on the user's phone.** A CLI that sets up `adb forward`/`adb reverse` without a serial changes
  whichever device adb picks. The agents get `--device <serial>` and `ANDROID_SERIAL`; a forward that another
  device holds is never taken (`--no-rebind`).
- **Real accounts in an existing pipeline.** A screenshot suite that signs in to a real test account and resets
  it on the production server isn't safe for an agent to run: reuse its data and ids under a demo account or a
  bypass ([staging.md](staging.md)).
- **CoreSimulator hiccups.** "Mach error -308 - (ipc/mig) server died" failed an install once and every screen
  of that device was reported missed; a retry a few seconds later worked. The `simctl` driver tries such a command
  once more by itself.
- **SDK tools in versioned folders.** An SDK Manager install may have `cmdline-tools/19.0/`, `23.0/` and no
  `latest/`: the driver takes the newest; `target.avdmanager` names one.
- **Permissions for the tools.** macOS needs Screen Recording for `screencapture` (without it, only the wallpaper is
  captured) and Accessibility for clicks; Android needs `sysui_demo_allowed` for demo mode.
- **Commands that read stdin.** `ffmpeg` and `adb shell` read standard input, so a script that runs them inside
  a `while read` loop loses the rest of its input (it broke a validation script once). The drivers give external
  commands no stdin; when you run them by hand in a loop, use `ffmpeg -nostdin`, `adb shell -n` or `</dev/null`.
- **The editor or IDE holding the project** (game engines, some build tools): close it or work on a copy.
- **CI.** Emulators need hardware acceleration (KVM on Linux runners); simulators need macOS; engines need a GPU.
  Don't commit captures from CI without a person looking at them.

## In-app agents

- **An agent in a store build.** DevFlow, Ailoha and screenshot modes belong in debug or screenshot builds only;
  check the guard (`#if DEBUG`, `kDebugMode`, `__DEV__`, `debugImplementation` with the no-op artifact in release).
- **The agent's own screenshot isn't the whole screen.** An app-window capture can leave out the status bar; for a
  full-screen store shot, the drivers take the picture from the simulator or emulator once the agent has reached the
  screen. Check the size and the top edge.
- **A screenshot scaled down.** DevFlow's `ui screenshot` scales to 1× logical pixels unless asked for `--scale
  native`; an agent's or WebDriver picture is checked against the device's size like any other.
- **Stale element ids.** An agent's element ids belong to one reading of the tree: after the screen changes, find
  the element again.
- **The first Appium session on iOS takes minutes** while it builds WebDriverAgent; don't mistake it for a hang.
- **The CLI's default platform.** Both agents' CLIs default `--platform` to `maccatalyst`: name the platform (the
  drivers do, from the plan).
- **DevFlow's taps aren't touches** (iOS): a gesture on an unnamed parent answers `success: false`, point taps need
  `EnableSyntheticTouch`, native menus aren't in the tree. Switch that device to `appium`, or add `AutomationId`s.
- **One client at a time.** DevFlow's lease turns away a second client's changes; the drivers change the app only
  through the CLI, retry a command another client turned away, and say so when one holds the lease.
- **A .NET Debug APK that won't start.** Fast Deployment leaves the assemblies out of the APK; `adb install` then
  gives an app that crashes on start. Build with `-p:EmbedAssembliesIntoApk=true`.
- **Another Appium server's WebDriverAgent answered our session.** XCUITest's driver puts every session's
  WebDriverAgent on port 8100 unless told otherwise. In a real trial another project's Appium server held 8100 for
  its own simulator: our `POST /session` went to that WebDriverAgent, the next `mobile: terminateApp` failed with
  "invalid session id: Session does not exist", and our app commands were sent into someone else's simulator. The
  driver now gives each simulator device its own `appium:wdaLocalPort` (8130-8199) and `appium:mjpegServerPort`
  (9130-9199) from its id, and passes over a port another WebDriverAgent or program holds
  ([appium.md](appium.md#beside-other-appium-servers)). Setting them by hand in `target.capabilities` works too.
- **Appium closes the Simulator windows.** Starting an XCUITest session closes Simulator.app's windows, even with
  `appium:isHeadless`: the user's own simulators stay booted, but their windows close. Tell the user before the
  first Appium run on iOS; it isn't something to fix by touching their simulators.
- **Simulator.app moved** (Xcode 27): Appium's XCUITest driver failed to open it; `appium:isHeadless` (the default
  on simulators now) avoids it. A failed session also left the simulator shut down, and the next screens failed
  with "device is not booted": the driver now boots it again and reports the session's own error.
- **The port.** On Android the agent's port may need `adb forward`; on a device several apps' agents can take
  neighbouring ports. Use the agent's own discovery (its broker or `list` command) rather than guessing.

## Video

- Simulator recordings are HEVC and variable frame rate; Android's are silent and capped at 180 s on older
  versions; Apple wants a constant 30 fps or less and (reportedly) an audio track; Vision Pro's 4K doesn't fit H.264
  Level 4.0. `video.py encode` and `check` handle each ([video.md](video.md)).
- **Android demo mode isn't perfectly clean on every image.** `datatype none` still showed a "3G" label on API 35
  and 36 emulator images (seen 2026-11-14), and Wi-Fi a "!" without `-e fully true`. The driver hides the mobile
  icon by default (`target.statusBarMobile` shows it) and sends Wi-Fi fully connected; the first pass after a boot
  drew two Wi-Fi icons, so it enters demo mode twice the first time. Look at the status bar in every picture and
  video.
