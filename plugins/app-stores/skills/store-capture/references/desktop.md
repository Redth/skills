# Desktop: the Mac App Store, Windows apps, Steam and itch.io

## Mac App Store

**Sizes are 16:10 only:** 1280×800, 1440×900, 2560×1600, 2880×1800 (Apple's screenshot specifications). Today's
notched MacBook displays aren't 16:10, so a full-screen capture of the built-in display usually isn't an accepted
size. Three ways, best first:

1. **The app renders its own window at the size** in its screenshot mode: the content view drawn to a bitmap at
   exactly 2880×1800 (or the window sized to 1440×900 points on a Retina display). Most reproducible; needs no
   Screen Recording permission. Import the folder it writes, or have the `macos` driver launch it.
2. **A window sized and captured** by the `macos` driver: the window set to `width/scale` × `height/scale` points
   (a 2880×1800 device on a Retina display is a 1440×900-point window), then `screencapture -x -o -l <window id>`.
   The picture is the whole window, title bar and rounded corners included (the corners flattened): right for a
   designed shot that `store-screenshots` puts on a background, less so for a full-bleed one. Details in
   [ui-automation.md](ui-automation.md#macos-accessibility-macos-driver).
3. **An external 16:10 display** at a scaled resolution of 1440×900 (2880×1800 pixels), the app full screen,
   `screencapture -x -D <display>`. Works, but borrows a person's display setup: only when they offer it.

Notes:

- `screencapture` needs **Screen Recording** permission for the terminal (or the host app). A first run without it
  captures only the desktop wallpaper, silently. Accessibility (for clicks and keystrokes) is a separate
  permission.
- Window captures have **transparent rounded corners** (and a shadow unless `-o`): the driver flattens alpha and
  says so. A full-bleed store shot shouldn't show the window's corners at all: capture the content.
- Mac Catalyst and MAUI-on-Mac apps are Mac apps here; the DevFlow and Ailoha agents may also reach them (see their
  references).
- The Mac's preview video is 1920×1080 (16:9) while its screenshots are 16:10: record a 16:9 window separately
  rather than cropping ([video.md](video.md)).

## Windows apps (WinUI, WPF, WinForms)

There's no Windows store in this plugin's rules yet; Steam and itch.io take Windows apps' and games' shots.

- **Reaching screens:** the Ailoha agent (WinUI 3, WPF), Appium's Windows driver (WinAppDriver-style automation by
  `AutomationId`), or the app's screenshot mode.
- **Capturing:** the app's own render at the size (WPF's `RenderTargetBitmap`, WinUI's `RenderTargetBitmap`) is
  the most reproducible; a window capture through the agent or Appium works when the window is sized exactly.
  Stdlib Python has no Windows capture of its own.

## Steam and itch.io

- Both take 16:9 screenshots; 1920×1080 is the usual size (the store-listings rules' checklists say what each
  needs). Games render their own (see [engines.md](engines.md)); apps: a window or full-screen capture on a 1080p
  or 4K display, or the app's own render.
- Neither has a listing API: the captures go up by hand (store-listings' checklist).
