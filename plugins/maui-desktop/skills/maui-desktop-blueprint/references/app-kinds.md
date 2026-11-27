# Kinds of app

The kind sets most defaults (`blueprint.defaults(kind)`; the table is in the contract, §2.4). Ask it first.

| Kind | Looks like | The window | Background presence | Typical integrations |
|---|---|---|---|---|
| **tool** | a developer or admin utility: lists of things, long operations, settings | sidebar + toolbar + content | none | notifications and taskbar progress for long work, single instance, file types it understands |
| **monitor** | watches something and reacts: containers, builds, devices, servers | sidebar + toolbar + content, often closed | a tray or menu-bar icon, keeps running, starts at login | notifications, badge, single instance, live updates |
| **document** | opens and edits files | one window per document, maybe tabs | none | file associations, recent documents, window state per document, drop |
| **launcher** | summoned, used for seconds, dismissed | a small borderless panel | always running | global hotkey, tray, start at login |
| **dashboard** | shows a live picture of something remote | content-first, a light sidebar | none | notifications, deep links into a view |

## Signs in an existing app

- A tray or status item (`NSStatusItem`, `Shell_NotifyIcon`) → monitor or launcher.
- File-type registrations or "open recent" → document.
- A global hotkey and a borderless panel → launcher.
- Lots of long-running operations with progress UI → tool.

## How the kind changes the rest

- **Lifecycle.** A monitor or launcher keeps running with no window: closing the window hides it, quitting is a
  menu item. Decide what "quit" means on each platform (⌘Q on macOS; the tray menu on Windows and Linux).
- **Updates.** A monitor that's always running needs a quiet update path (download in the background, apply on
  next launch); a tool can ask.
- **Notifications.** For a tool, only when work finishes while the app is in the background. For a monitor,
  they are the product; let the user choose which.
- **Window state.** Everyone but a launcher should restore size, position and display.
