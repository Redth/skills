# Matching Windows

What adaptive fidelity matches on Windows 11. The shell is WinUI 3 (Windows App SDK), the web engine WebView2,
which is evergreen Chromium.

## Tokens (adaptive)

| Token | Windows | Why |
|---|---|---|
| Font | `"Segoe UI Variable", "Segoe UI", system-ui`; mono `"Cascadia Code", "Cascadia Mono", Consolas` | Windows 11's type |
| Base size | 14px | Fluent's body size |
| Radii | Fluent 2: 4px for controls, 8px for cards, dialogs and flyouts | Windows 11's geometry; much squarer than macOS |
| Control height | about 32px | WinUI's standard control height |
| Row padding | about 10–12px × 16px | |
| Accent | the brand, or the Windows default; with `system`, the user's accent from `UISettings` | |
| Surfaces | light canvas slightly grey (`#f3f3f3`-ish) with white cards; dark canvas near `#202020` with lifted cards | WinUI's layering, so cards read against Mica or a solid window |
| Borders | visible 1px control borders, a slightly stronger bottom edge on inputs | Fluent's controls are outlined |

## Native-faithful (optional)

Fluent's toggle switch, the accent-underlined focused text box, a `NavigationView`-style selection pill, and
flyouts with acrylic. Most apps don't need it: tokens plus real WinUI chrome read as Windows.

## Chrome

- `NavigationView` around the web view for the sidebar; the title bar hosting back, title, search and commands.
  Keep the system caption buttons so Snap Layouts keep working.
- Mica behind the window with a transparent WebView2 lets the material show through the content's canvas; then
  `--bg` is transparent on Windows and cards carry the surface.
- Icon glyphs as `FontIcon` from Segoe Fluent Icons stay sharp at high DPI; rasterised images don't.

## Facts to push at run time

- The caption and title-bar height the content clears, when the content extends into the title bar.
- With `look.accent: system`, the accent from `UISettings`.
- Contrast themes arrive in CSS as `forced-colors: active`; let the system colours win there.
- Text scaling (Settings > Accessibility > Text size) through the root font size.

## Watch for

- WebView2's browser accelerator keys (F5, Ctrl+R, Ctrl+F, Ctrl+P), pinch zoom, swipe navigation, default context
  menus and dev tools are on unless the head turns them off.
- Its user data folder must be writable: move it under the user's local app data when the app is installed to a
  read-only folder.
- WebView2 supports newer CSS than WKWebView and WebKitGTK; don't let "it works on Windows" pass for "it works".
