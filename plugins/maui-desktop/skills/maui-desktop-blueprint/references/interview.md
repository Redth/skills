# The interview

Ask in one message, not ten. Read the project first and propose an answer for every question, so the user only
corrects what's wrong. `blueprint.py questions` prints the undecided questions with their proposals; this file
says how to turn that into a message worth reading.

## Before asking

1. `detect.py` and the agent docs (`AGENTS.md`, `CLAUDE.md`, `DESIGN.md`, `docs/`). Note what's already decided
   in code: an app with a tray icon is a monitor; an app with `HybridFormPage` dialogs already chose native frames.
2. `blueprint.py init` (once), and for an existing app `blueprint.py gaps --print`.
3. What the user already said in this conversation counts. "We're building a menu-bar utility" answers the kind,
   the tray and probably the sidebar. Record those with `set` before printing the questions.

## The message

Lead with two or three lines on what you found ("Three heads on .NET 11, sharing the UI by symlinks; native
sidebar and toolbar on every platform; no tray, notifications or deep links"). Then the questions, grouped,
each a line with the proposal in bold and the reason after it. Put the two or three that matter most first and
say so. Offer the options only where the user is likely to want another. End by saying what happens next ("Once
you've answered, I'll record these and we'll do the design language").

Keep it to one screen where possible. A question whose answer follows from another ("start at login" for an app
with no tray) can be folded into it.

## The questions

| Group | Question | Field | Options |
|---|---|---|---|
| Product | What kind of app is it? | `app.kind` | tool, monitor, document, launcher, dashboard ([app-kinds.md](app-kinds.md)) |
| | Which platforms, and which gets the most polish? | `platforms.*.enabled`, `platforms.*.home` | macOS, Windows, Linux; plus a browser dev host |
| | Minimum OS versions? | `platforms.*.minimum` | macOS 14 is the usual floor for the AppKit backend; Windows 10 19041 |
| | New app or existing? | `app.existing` | usually detected |
| Chrome | Sidebar: native, web or none? | `chrome.sidebar` (per platform) | |
| | Toolbar: native or web? Where does search live? | `chrome.toolbar`, `chrome.search` | |
| | Menu bar: none, minimal, standard or full? | `chrome.menuBar` (per platform) | macOS can't be none |
| | Dialogs: a native frame around a web body, web only, or mixed? | `chrome.dialogs` | |
| | Settings: a window, a dialog or a page? | `chrome.settings` | |
| | A command palette? More than one window? | `chrome.commandPalette`, `chrome.multiWindow` | |
| Look | How platform-specific should the content look? | `look.fidelity` (per platform) | unified, adaptive, native-faithful |
| | Accent: one brand colour, each platform's default, or the user's OS accent? | `look.accent` | brand, platform, system |
| | Theme: follow the system, with or without a manual override? Density setting? | `look.theme`, `look.density` | |
| Background | A tray or menu-bar icon; keep running when the window closes; start at login? | `integrations.tray`, `closeToTray`, `launchAtLogin` | |
| | OS notifications; a dock or taskbar badge and progress? | `integrations.notifications`, `badge`, `progress` | |
| | Single instance; deep links (which scheme?); file types? | `integrations.singleInstance`, `deepLinks`, `fileTypes` | |
| | A global hotkey? | `integrations.globalHotkey` | |
| | Native context menus; file drop; remember window size and position? | `integrations.contextMenus`, `fileDrop`, `windowState` | |
| | Auto-update? | `integrations.autoUpdate` | |
| Distribution | Channels per OS? | `distribution.channels` | direct, Homebrew, Mac App Store; installer, winget, MSIX, Microsoft Store; deb, rpm, Flatpak, AppImage, Snap |
| | Signing identities available? | `distribution.signing` | available, later, none |
| Engineering | Content technology and component library? | `stack.content`, `stack.componentLibrary` | Blazor and custom components on tokens are the default |
| | A browser dev host and component gallery? DevFlow for agent-driven inspection? | `engineering.devHost`, `gallery`, `devflow` | |
| | Crash reporting? Accessibility target and locales? | `engineering.crashReporting`, `accessibility`, `locales` | |

## Explaining the three hard ones

**Fidelity.** Most apps want *adaptive*: the same components everywhere, with each platform's font, size, accent
(if chosen), corner radii, control heights and density. *Unified* suits a brand-led app where looking the same
everywhere is the point. *Native-faithful* reshapes components per platform (switches, segmented controls,
menus); it is expensive, so offer it per platform, usually only for the home one.

**Accent.** *Brand* is one colour everywhere and pushed into the native chrome too. *Platform* uses each
platform's own default (blue on macOS and GNOME, the Windows default). *System* follows the colour the user
picked in their OS settings, which needs a small bridge from the native side because the web engines don't
reliably expose it.

**Dialogs.** A native frame (title row and button row drawn by the platform, the body in web content) gets the
platform's button order, Return and Escape, sheets on macOS and focus handling for free. Web-only dialogs are
cheaper to start but get all of those slightly wrong on every platform. *Mixed* is legitimate when some dialogs
are really inline pickers.

## Recording answers

```sh
python3 <skill>/scripts/blueprint.py set app.kind=monitor platforms.linux.enabled=false \
  --reason "It's a menu-bar monitor; Linux later."
python3 <skill>/scripts/blueprint.py set 'chrome.sidebar={"macos":"native","windows":"native"}' \
  --reason "Native where we ship."
python3 <skill>/scripts/blueprint.py set integrations.autoUpdate=true --by proposal --reason "Proposed; not answered yet."
```

Quote the user in `--reason` when they gave one. An answer to a bundle ("yes to all of those") is an answer to
each field in it; record them together with the same reason.

## A worked message

> I've read the project: three heads on .NET 11 (AppKit, WinUI, GTK4), sharing the UI by symlinks and file links;
> native sidebar and toolbar on all three; 50 dialogs as native sheets around Blazor bodies; no tray,
> notifications or deep links. A few questions, with what I'd suggest:
>
> **Most important**
> - **Kind:** a developer *tool* (long operations, no background presence). Right?
> - **Look:** **adaptive** — same components, each platform's font, radii and density. Your macOS styling goes
>   further than that today; keep it there, or bring it back to tokens?
> - **Accent:** **each platform's default** (what you have). Or follow the user's OS accent?
>
> **Chrome:** native sidebar and toolbar everywhere (as now); a **standard** macOS menu bar with real shortcuts
> (today it's one item); no menu bar on Windows and Linux.
>
> **Integrations** worth adding for a tool: **notifications and taskbar progress** for long installs;
> **single instance** (two copies can open the same vault today); **file types** for the files you already
> understand. Not suggested: tray, start at login, global hotkey.
>
> **Distribution** stays as is (zip, Homebrew, installer, winget, deb).
>
> Once you've answered I'll record it and write the gap report.
