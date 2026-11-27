# OS integrations: what each costs

Neither the macOS nor the GTK backend provides any of these today; Windows provides some through the Windows App
SDK. Each is a small interface in shared code, one implementation per platform, and a stated fallback. Tell the
user the cost once, plainly. Read 2026-11-27; library versions and platform behaviour change, so check before
building (`maui-desktop-integrations`, to follow, has the recipes).

| Integration | macOS | Windows | Linux | Watch out for |
|---|---|---|---|---|
| **Web view hardening** (always) | turn off back/forward gestures and magnification; inspector off in Release | turn off browser accelerator keys, pinch zoom, swipe navigation, default context menus, dev tools | zoom and developer extras; the web view is reached by walking the widget tree | an unhandled file drop navigates WKWebView away from the app |
| **Window state** | frame autosave: nearly free | `AppWindow` position, size, presenter state | size only: Wayland doesn't allow positioning | restore onto a display that still exists |
| **Single instance, deep links, file types** | single instance by default; URL and document types in `Info.plist` | redirect activation in a custom `Main` before the UI starts; register the scheme and types | the app's `Gtk.Application` activates the first instance but forwards no arguments; the `.desktop` file needs `MimeType` | needed for sign-in callbacks and CLI hand-off |
| **Notifications** | `UNUserNotificationCenter`: asks permission; needs a signed app | `AppNotificationManager` (packaged or not) | `Gio` notifications: need an installed `.desktop` file matching the app id | actions route back into the running app |
| **Accent, contrast, transparency, text size** | read from AppKit | read from `UISettings` | the settings portal | CSS covers colour scheme, reduced motion and contrast; reduced transparency and the real OS accent need a native bridge |
| **Tray or menu-bar icon** | `NSStatusItem` with a menu or a popover | `Shell_NotifyIcon` | StatusNotifierItem over D-Bus | stock GNOME shows no tray without an extension (Ubuntu ships one); Linux trays are menu-only. A GTK 3 tray library can't share a process with GTK 4 |
| **Close to tray, start at login** | keep running after the last window; `SMAppService` (signed apps) | hide on close; a `Run` key or a startup task | `Gio.Application.Hold`; an autostart `.desktop` or the Background portal | Flatpak can't write the autostart folder |
| **Badge, progress, keep awake** | dock tile badge, attention request; an activity assertion | taskbar progress and overlay icon; execution state | launcher entry (Ubuntu Dock, KDE; not stock GNOME); inhibit | low cost; pairs with notifications |
| **Auto-update** | Sparkle, or Velopack | Velopack, WinSparkle | AppImage only | verify what's downloaded; switch it off where a store, package manager or Flatpak owns updates |
| **Native context menus** | the page reports the click; the head pops an `NSMenu` | `ContextMenuRequested` → `MenuFlyout` | the web view's signal → a popover menu | keep the engine's own menu in text fields |
| **File drop** | register the web view's container for file URLs | external drop on the WebView2 controller | a drop target | HTML drop events give contents, not paths; dragging out is custom everywhere |
| **Global hotkey** | Carbon hot keys: no permission needed | `RegisterHotKey` | X11 grabs; on Wayland only the GlobalShortcuts portal, which some desktops lack | always ship a tray or menu fallback |

## What to suggest, by kind

- Every app: web view hardening, window state, single instance.
- **tool**: notifications and progress for long work; file types and drop for files it understands; deep links
  if anything signs in through a browser.
- **monitor**: tray, close to tray, start at login, notifications, badge.
- **document**: file types, drop, window state per document, recent documents.
- **launcher**: global hotkey, tray, start at login.
- **dashboard**: notifications, deep links into a view.

Skip Spotlight and Windows Search indexing, the Services menu, Handoff and the Touch Bar unless the user asks.
