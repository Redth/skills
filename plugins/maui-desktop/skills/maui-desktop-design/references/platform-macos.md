# Matching macOS

What adaptive fidelity matches on macOS, and what goes further. The shell is AppKit
(`Microsoft.Maui.Platforms.MacOS`), the web engine WKWebView, tied to the macOS version.

## Tokens (adaptive)

| Token | macOS | Why |
|---|---|---|
| Font | `system-ui` (resolves to SF Pro); mono `ui-monospace, "SF Mono", Menlo` | the system font tracks the OS |
| Base size | 13px | AppKit's body size; 14px looks oversized next to native controls |
| Radii | larger: about 6 / 8 / 10 / 16 / 20 px for xs–xl | macOS 26 controls and cards are rounder |
| Control height | about 28–30px regular, 22–24px small | matches `NSButton` regular and small |
| Row padding | about 8–10px × 12–14px | AppKit's source lists and tables are tight |
| Accent | Apple blue, or the brand pushed through the asset catalog | AppKit controls use the app's accent colour |
| Surfaces | content as soft tonal fills, few outlines; hairlines between rows | the macOS 26 content style |
| Canvas | transparent web view over the window | the window paints the ground; the sidebar's material shows through where it should |

## Native-faithful (optional)

Component shapes macOS users notice: the elongated capsule switch, a horizontal `⋯` overflow in a circle, segmented
controls with an elevated selected segment, popup buttons with a double chevron, translucent popovers and menus
with a blurred backdrop (`-webkit-backdrop-filter` plus `backdrop-filter`). Budget it: it's a component layer of
its own, and it must keep working in the light and dark appearances.

## Chrome the app gets for free

Built against the current SDK on macOS 26 or later, a standard `NSToolbar` and split-view sidebar take the Liquid
Glass material automatically. Apple's guidance is to remove custom backgrounds behind them, and to use the glass
effect view only sparingly for custom chrome. That is the "don't fake native" rule paying off: real controls with
default styling follow the OS.

## Facts to push at run time

- The window background (`NSColor.windowBackgroundColor`) as `--bg`, resolved inside the window's effective
  appearance (AppKit's dynamic colours resolve against the default light appearance outside a drawing context).
- The title-bar plus toolbar height the content must clear.
- With `look.accent: system`, `NSColor.controlAccentColor`.
- Reduce Transparency and Increase Contrast, which the web engine doesn't fully expose: switch popovers to opaque
  and borders to stronger tokens.

## Watch for

- `corner-shape: squircle` is not in a shipping WKWebView as of this writing; treat it as an enhancement.
- WKWebView has no `prefers-reduced-transparency`.
- Text selection, the default context menu, back/forward swipes and magnification are on unless the head turns
  them off.
- A sheet's body is a separate web view: it needs the tokens, `data-platform` and `data-theme` of its own.
