# maui-desktop

**Build a desktop app for macOS, Windows and Linux with .NET MAUI: native controls where the look and feel
matters most, web content (Blazor Hybrid) everywhere else, and no seams between them.** The skills interview you
about the app's shape, write the decisions down, turn the design language into tokens both the web content and
the native chrome read, and describe how to structure each part. They teach structure; they never paste
template code into your app.

- 🧭 **One blueprint** (`desktop-blueprint.json`, with a JSON Schema): platforms, which surfaces are native or web
  on each, dialogs, how platform-specific the content looks, the OS integrations the kind of app needs, and how it
  ships. Decided with you in one message, with a proposed answer for every question.
- 🔎 **Detect first:** an existing app's heads, backend versions, UI sharing, shell and dialog generation, design
  system, integrations and packaging are read before anything is proposed, and a gap report sizes each move.
- 🎨 **One design source:** `design/tokens.json` generates the CSS custom properties, a C# palette and scale for
  native chrome, the macOS accent colour set and the tables in `DESIGN.md`; `design/icons.json` maps every icon
  to SF Symbols, Adwaita, Segoe Fluent and an SVG sprite. Contrast, gamut and raw-value gates run offline and in CI.
- 🔌 **No dependencies:** stdlib Python 3.8+ on macOS, Linux and Windows. No network.

## The skills

| Skill | Status | What it does | Issue |
|---|---|---|---|
| [`maui-desktop-blueprint`](./skills/maui-desktop-blueprint/) | 0.1.0 | reads the project (`detect.py`), drafts a blueprint from defaults for the kind of app (tool, monitor, document, launcher, dashboard), interviews the user in one message, records answers with reasons in a dated decisions log, checks consistency (macOS always has a menu bar; a tray on stock GNOME; an in-app updater on a store build), and writes a gap report for an existing app | [#39](https://github.com/Redth/skills/issues/39) |
| `maui-desktop-design` | next | the design language: `DESIGN.md` from a template, tokens with per-platform blocks and run-time overrides, generated CSS and C#, icons per platform, the seam checklist, CSS that works in WKWebView, WebView2 and WebKitGTK, contrast and lint gates with a baseline ratchet for existing apps | [#40](https://github.com/Redth/skills/issues/40) |
| `maui-desktop-shell` | to follow | solution layout, navigation manifest, declared page chrome, commands projected to menus, shortcuts and a palette, windows, per-backend recipes | |
| `maui-desktop-dialogs` | to follow | native frames around web bodies: a session the body drives, typed header and footer controls, presentation per platform | |
| `maui-desktop-integrations` | to follow | tray, notifications, single instance, deep links, file types, window state, updates, per platform | |
| `maui-desktop-ship` | to follow | packaging, signing, notarisation, installers and release automation per platform | |

Each works alone, and reads what the others wrote: the blueprint's decisions, the design's tokens and icons.

## For consumers: using it

**Claude Code:**

```text
/plugin marketplace add Redth/skills
/plugin install maui-desktop@redth-skills
```

**Any agent:** ask in your own words:

> We're starting a desktop app with MAUI and Blazor for Mac, Windows and Linux. How should we structure it?
>
> Review our MAUI desktop app's architecture: what should be native, what should be web?
>
> Should we add a tray icon and notifications? What does it cost on Linux?
>
> Add Linux to our Mac and Windows MAUI app: what do we need to decide?

The usual flow:

```sh
python3 <blueprint>/scripts/detect.py                          # what's there: heads, versions, shell, dialogs, design
python3 <blueprint>/scripts/blueprint.py init --kind tool      # a draft from detection and the kind's defaults
python3 <blueprint>/scripts/blueprint.py questions             # the interview, with a proposed answer for each
python3 <blueprint>/scripts/blueprint.py set chrome.sidebar.linux=web --reason "the user's words"
python3 <blueprint>/scripts/blueprint.py check                 # contradictions and costs
python3 <blueprint>/scripts/blueprint.py gaps                  # existing app: docs/desktop/gap-report.md
python3 <blueprint>/scripts/blueprint.py confirm --note "the user's words"
```

### Prerequisites

- **Python 3.8+** (stdlib only), on macOS, Linux or Windows.
- A .NET MAUI desktop app, or the intention of one: the macOS head on AppKit (`Microsoft.Maui.Platforms.MacOS`),
  Windows on WinUI, Linux on GTK 4 (`Microsoft.Maui.Platforms.Linux.Gtk4`). The skills read the project; they
  don't build or run it.

## For authors

The plugin's names, file shapes and commands are in [CONTRACT.md](./CONTRACT.md). Code two skills share lives in
`shared/mauidesktop_lib` and is copied into each skill by `tools/sync_shared.py` (`--check` in the tests). Changes
go in [CHANGELOG.md](./CHANGELOG.md).

The architecture these skills describe was distilled from two shipping apps built this way, one a developer tool
on all three platforms and one a background monitor on macOS and Windows.
