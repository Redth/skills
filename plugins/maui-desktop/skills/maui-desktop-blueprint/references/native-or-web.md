# Native or web

A hybrid desktop app wins when native controls go where the platform owns the behaviour or users operate by
habit, and web content goes where the content is the app's own. Users don't notice "native" or "web". They
notice the seams: a colour mismatch at the border, a white flash as a window opens, a context menu that says
"Reload", a dialog whose buttons are in the wrong order.

## By surface

| Surface | Default | Why |
|---|---|---|
| Window frame and title bar | native | Free, and correct: snap layouts, traffic lights, full screen, window menus |
| Alerts, confirmations, file and folder pickers | native | Cheap and familiar; keyboard behaviour exactly right |
| Menu bar | native on macOS (always there); optional on Windows and Linux | Shortcuts and discoverability; one projection of the app's commands |
| Sidebar | native on macOS and Windows; native or web on Linux | The source list is the most recognisable part of a Mac window; NavigationView on Windows |
| Toolbar | native | It shares the title bar, which web content can't reach |
| Dialog frame and buttons | native, with a web body | Sheets on macOS, the platform's button order, Return and Escape, focus |
| Tray, notifications, dock and taskbar | native | They live outside the window |
| Context menus | web by default, native as an option | Native escapes the web view's bounds and matches the OS; it costs a bridge per platform |
| Lists, forms, dashboards, logs, editors, inspectors | web | One implementation, fast iteration, rich layout |
| Dropdowns, popovers, tooltips inside content | web | They belong to the control they came from |

## The rules that make it work

1. **Declare once, project many times.** Navigation, page chrome (title, search, actions), commands, dialogs,
   icons and design tokens are each declared once in shared code; each platform's head projects them onto its
   own controls. Shared code never names a widget.
2. **Every native surface has a web fallback drawn from the same declaration.** That gives a browser dev host
   and a component gallery for free, a way to ship a platform before its native chrome is done, and turns "native
   or web sidebar on Linux?" into configuration.
3. **Don't fake native.** In the chrome, use the real control with its default styling, so it follows the OS's
   next redesign for free (macOS 26 gave standard toolbars and sidebars Liquid Glass with no code). In web
   content, never draw an imitation title bar, traffic lights or a native-looking window frame.
4. **Match the platform at the token level by default.** Font, size, accent, radii, density and control heights
   adapt; component structure stays shared. Component-level imitation is a budgeted choice (`look.fidelity`).
5. **Chrome code knows nothing about features.** A head receives declarations and a small shell bridge. If the
   toolbar needs a list of accounts, the page supplies the items; the head renders them.

## The seam

What has to match across the native/web boundary, whichever split is chosen:

- The window's background colour and the web view's (or a transparent web view over the native window).
- No first paint before the content is ready: a native placeholder, and a timeout so a startup error is never a
  blank window.
- The theme, on every web view (main window, each dialog, each extra window), before first paint.
- Fonts and sizes the platform uses; the accent where the chrome shows it.
- Browser behaviours switched off: reload keys, pinch zoom, the default context menu, link and image dragging,
  text selection outside inputs and code.

`maui-desktop-design` turns these into tokens and checks; `maui-desktop-shell` into per-platform recipes.

## Where the backends stand

The macOS AppKit backend (`Microsoft.Maui.Platforms.MacOS`) gives a native sidebar, a rich toolbar (search,
menus, segmented groups, custom views), a menu bar with keyboard accelerators, context menus, and sheet, overlay
or window modals. The GTK4 backend (`Microsoft.Maui.Platforms.Linux.Gtk4`) gives none of the desktop chrome: no
header bar, no libadwaita, toolbar items as plain text buttons. "Native" on Linux therefore means the head
builds the header bar and sidebar itself with GTK. Windows (WinUI) has `NavigationView`, a customisable title
bar and `ContentDialog`. Both preview backends change between releases; check the versions `detect.py` found.
