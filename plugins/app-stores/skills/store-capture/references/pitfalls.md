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
  `screencap -d`) a capture fails or takes the wrong screen.

## Pixels

- **Alpha.** `simctl … --mask=alpha` (transparent corners), Mac window captures (corners and shadow), a web
  capture with a transparent background, an engine's transparent background, design tools exporting RGBA even when
  every pixel is opaque. Apple rejects alpha; a strict checker sees colour type, not pixels. The drivers flatten it
  (`flatten`, black by default) and report `alpha-flattened`; fix the source if it keeps happening. Simulator
  screenshots carry an alpha channel even with `--mask=ignored` (iOS 27.2, seen 2026-11-14), and so do some
  emulators' `screencap`s, so expect `alpha-flattened` on those every time: it's harmless when every pixel is opaque.
- **Colour profiles.** Simulators of P3 devices and Mac captures can be tagged with the display's profile; Android's
  `--preserve-display-colors` keeps the panel's. Keep captures sRGB (or untagged sRGB), 8 bits a channel, so the
  stores' pages show what was reviewed. Conversions are reported (`converted-to-srgb`, `16-bit-to-8-bit`).
- **The Dynamic Island and rounded corners.** Rectangular captures show content under the corners and an empty
  space where the island is. That's what the stores expect; keep important content in the safe area, and draw the
  island in a frame, not into the shot.

## The status bar

- **Overrides that don't take.** `simctl status_bar` was reported broken on iOS 16 and 17 runtimes, silently. The
  report's `statusBar` says whether it was verified; look at every picture's top edge.
- **Lost on reboot or erase.** A locale change that reboots the simulator drops the override: apply it after every
  boot (the drivers do).
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
- **The keyboard.** Typing into a field leaves the keyboard up and a caret blinking: `back` or tap away unless the
  shot is about typing.
- **Waits too short on a cold start.** The first launch after install is slow (and slower on CI); wait for an
  element, not a fixed time.

## Devices and machines

- **A person's own simulator erased.** Capturing on "the booted simulator" erased someone's working state. The
  drivers create `appstores-<device id>` devices and use the user's own only when the plan names it.
- **`booted` with two booted.** `simctl` "will choose one". Pass a UDID; pass `-s <serial>` to `adb`.
- **A device left changed.** A run killed half-way left an emulator at 1080×1920 in German with demo mode on.
  Reset by hand, and tell the user what was left: `wm size reset`, `wm density reset`, demo mode `exit`,
  `simctl status_bar … clear`, locale and appearance back.
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
- **The port.** On Android the agent's port may need `adb forward`; on a device several apps' agents can take
  neighbouring ports. Use the agent's own discovery (its broker or `list` command) rather than guessing.

## Video

- Simulator recordings are HEVC and variable frame rate; Android's are silent and capped at 180 s on older
  versions; Apple wants a constant 30 fps or less and (reportedly) an audio track; Vision Pro's 4K doesn't fit H.264
  Level 4.0. `video.py encode` and `check` handle each ([video.md](video.md)).
- **Android demo mode isn't perfectly clean on every image.** `datatype none` still showed a "3G" label on an API 35
  emulator image (seen 2026-11-14). Look at the status bar in the picture; turn mobile data off in demo mode
  (`-e mobile hide`) or use an image without it.
