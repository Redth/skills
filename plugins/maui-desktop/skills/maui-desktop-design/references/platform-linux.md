# Matching Linux

The styled target is GNOME with libadwaita conventions; other desktops work but aren't styled for. The shell is
GTK 4 (`Microsoft.Maui.Platforms.Linux.Gtk4`), the web engine WebKitGTK 6.0, whose version varies by
distribution.

## Tokens (adaptive)

| Token | Linux | Why |
|---|---|---|
| Font | `system-ui` (the desktop's interface font: Adwaita Sans, Cantarell, Ubuntu); mono `"Adwaita Mono", monospace` | recent WebKitGTK no longer maps `-apple-system`; use `system-ui` |
| Base size | 14px | |
| Radii | libadwaita: about 6px for controls, 12px for cards and dialogs | |
| Control height | about 34px | GNOME's buttons and entries are taller |
| Row padding | about 12px × 16px | libadwaita's boxed lists |
| Accent | Adwaita blue, or the brand; with `system`, the accent from the settings portal | GNOME 47+ lets users pick an accent |
| Surfaces | boxed lists on a light grey canvas (light); `#242424`-ish canvas with lifted cards (dark) | |

## What the GTK backend doesn't give

No header bar, no libadwaita widgets, toolbar items as plain text buttons. A native look on Linux means the head
builds a `Gtk.HeaderBar` with icon buttons, a search entry and menu buttons, and a sidebar list itself. If that's
not worth it for the app's Linux users, the blueprint can choose the web sidebar and toolbar on Linux; the tokens
still give the content GNOME's type, radii and density.

## Facts to push at run time

- Colour scheme and accent from the settings portal (`org.freedesktop.appearance`); GTK's own notification of a
  theme change is unreliable on Wayland.
- The window background the head paints, as `--bg`.

## Watch for

- WebKitGTK versions differ: Ubuntu 24.04's updates and 26.04 ship 2.52, Fedora 43 and 44 ship 2.54 (read
  2026-11-27). Use `@supports` for anything newer than the table in [webview-css.md](webview-css.md).
- On NVIDIA hardware, and in virtual machines with software rendering, blur and heavy animation are slow; provide
  a reduced-effects choice (opaque popovers, no backdrop blur). Some NVIDIA setups need the DMA-BUF renderer
  turned off.
- Fonts render with FreeType hinting: don't rely on pixel-exact line heights matching macOS.
