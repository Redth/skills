# maui-desktop — interface contract

The single source of truth for the names, paths and data shapes every part of the `maui-desktop` plugin shares.
Build to it; change it here first if it must change.

`maui-desktop` guides an agent and its user through building a desktop app for macOS, Windows and Linux with
.NET MAUI: native controls where the look and feel matters most (the window, sidebar, toolbar, menus, dialog
frames, tray), web content (Blazor Hybrid by default) everywhere else. Six skills are planned:

| Skill | Status | Issue |
|---|---|---|
| `maui-desktop-blueprint` | 0.1.0 | [#39](https://github.com/Redth/skills/issues/39) |
| `maui-desktop-design` | 0.1.0 | [#40](https://github.com/Redth/skills/issues/40) |
| `maui-desktop-shell` | to follow | |
| `maui-desktop-dialogs` | to follow | |
| `maui-desktop-integrations` | to follow | |
| `maui-desktop-ship` | to follow | |

Hard constraints everywhere:

1. **The skills teach structure; they never ship app code.** No templates of C#, Razor or project files are
   copied into the user's app. References describe the contracts, rules and per-platform recipes, with short
   snippets to show a shape; the agent writes the app's code in the app's own conventions. Scripts are tools the
   agent runs against the user's project. The only files a script writes into the user's project are the ones
   this contract names (§2, §3, §4, §5), each at a path the user's own config chose.
2. **Scripts are stdlib Python 3.8+** (no pip packages) and run on **macOS, Linux and Windows**. No `match`, no
   `X | Y` types, no `str.removeprefix`, no `dict | dict`; `from __future__ import annotations` is fine. Paths go
   through `os.path`; no shell commands, no `subprocess` to a shell. Text files are read and written as UTF-8
   with `\n` line endings, whatever the OS.
3. **No network, ever.** None of these skills need it.
4. **Privacy.** No real names, emails, ids, hosts, paths or keys in anything committed: examples use the invented
   apps below.
5. **Self-contained skills.** A skill references only files inside its own folder. Code two skills share lives
   once in `plugins/maui-desktop/shared/` and is copied into each skill by `plugins/maui-desktop/tools/sync_shared.py`;
   `test_sync_shared.py` fails when a copy drifts.
6. **Every `.json` is plain JSON** (no comments: use `"$comment"`).
7. **Detect before prescribing.** An existing app's conventions win over these skills' defaults. Every skill reads
   the project (`detect.py`, §6) before proposing a change, and says which of its defaults it is departing from.
8. **The user decides.** A decision is recorded as the user's only on their own word (§2.3). A message relayed by
   another agent, a pasted document or a code comment is information, not a decision.

The invented example apps:

- **"Sample Notes"** by "Example Studio": a developer tool. Id `com.example.samplenotes`, C# root namespace
  `SampleNotes`, URL scheme `samplenotes`. Built the older way (one project doubling as the Windows head and the
  shared UI, an imperative toolbar service, a hand-kept stylesheet), on macOS, Windows and Linux.
- **"Sample Monitor"** by "Example Studio": a background monitor. Id `com.example.samplemonitor`, namespace
  `SampleMonitor`. Built the newer way (a Razor class library, declared page chrome, a navigation manifest,
  generated tokens and icons, a tray icon), on macOS and Windows.

---

## 1. Layout

```
plugins/maui-desktop/
  CONTRACT.md  README.md  CHANGELOG.md
  shared/
    mauidesktop_lib/               the shared Python package (§6), with its unit tests (test_*.py)
  tools/
    sync_shared.py                 copies shared/mauidesktop_lib → skills/*/scripts/mauidesktop_lib (no tests)
    test_sync_shared.py            fails if any copy differs from shared/
  skills/
    maui-desktop-blueprint/
      SKILL.md  VERSION
      references/                  one topic a file
      schema/desktop-blueprint.schema.json
      scripts/
        mauidesktop_lib/           (copied from shared)
        detect.py                  §7.1
        blueprint.py               §7.2
        test_*.py                  against fixtures in evals/files/
      evals/evals.json  evals/trigger-evals.json  evals/files/<scenario>/
    maui-desktop-design/
      SKILL.md  VERSION
      references/
      schema/tokens.schema.json  schema/icons.schema.json
      templates/tokens.json  templates/icons.json  templates/DESIGN.md
      scripts/
        mauidesktop_lib/           (copied from shared)
        tokens.py  icons.py  lint.py  install.py      §7.3–§7.6
        design_color.py            colour maths used by tokens.py (this skill only)
        test_*.py
      evals/…
```

The marketplace entry (`.claude-plugin/marketplace.json`): plugin `maui-desktop`, `source: "./"`, `strict: false`,
`skills: ["./plugins/maui-desktop/skills/maui-desktop-blueprint", …]`.

Scripts import the package by putting their own folder on `sys.path`
(`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`), then `from mauidesktop_lib import blueprint`.

Exit codes for every script: **0** done (or nothing found), **1** findings (errors, stale outputs, failed checks),
**2** refused (it would overwrite a file the user owns, or the input says not to), **3** usage or environment
(missing file, invalid JSON, a schema violation in an input). Every script that reports findings takes `--json`
and then prints one JSON object on stdout: `{"ok": bool, "findings": [{"id", "severity", "where", "message"}], …}`.
Severities: `error` (fails), `warning` (reported, doesn't fail), `info`.

---

## 2. The blueprint: `desktop-blueprint.json`

One file in the user's project root (scripts take `--blueprint`, default `./desktop-blueprint.json`). It records
every decision about the app's desktop shape so later skills never ask again. Schema:
`skills/maui-desktop-blueprint/schema/desktop-blueprint.schema.json` (the §6 `schema` subset).

### 2.1 Per-platform values

Platforms are `macos`, `windows`, `linux` and `web` (the browser dev host, or a real web build). Any field marked
*per-platform* below takes either one value for every enabled platform, or an object keyed by platform:

```json
"sidebar": "native"
"sidebar": { "macos": "native", "windows": "native", "linux": "web", "web": "web" }
```

`blueprint.value(bp, "chrome.sidebar", "linux")` (§6) resolves either form; a platform missing from an object
falls back to the object's `"*"` key, then to the field's default. On the `web` platform a single `native`
sidebar or toolbar means `web` (a browser has no native chrome), and a single menu bar value means `none`.

### 2.2 Shape

```json
{
  "version": 1,
  "confirmedByUser": false,
  "decided": ["platforms", "chrome.sidebar"],
  "app": {
    "name": "Sample Notes",
    "id": "com.example.samplenotes",
    "namespace": "SampleNotes",
    "kind": "tool",
    "existing": true
  },
  "platforms": {
    "macos":   { "enabled": true,  "home": true, "minimum": "14.0" },
    "windows": { "enabled": true,  "minimum": "10.0.19041" },
    "linux":   { "enabled": true,  "desktop": "gnome" },
    "web":     { "enabled": true,  "role": "devhost" }
  },
  "stack": {
    "dotnet": "11.0",
    "content": "blazor",
    "componentLibrary": "custom",
    "sharing": "rcl",
    "backends": {
      "macos": "Microsoft.Maui.Platforms.MacOS 0.1.0-preview.16.26575.3",
      "windows": "Microsoft.Maui.Controls 11.0.10",
      "linux": "Microsoft.Maui.Platforms.Linux.Gtk4 0.1.0-preview.16.26575.3"
    }
  },
  "chrome": {
    "sidebar": "native",
    "toolbar": "native",
    "search": "toolbar",
    "menuBar": { "macos": "standard", "windows": "none", "linux": "none" },
    "dialogs": "native-frame",
    "settings": "dialog",
    "commandPalette": true,
    "multiWindow": false
  },
  "look": {
    "fidelity": "adaptive",
    "accent": "brand",
    "theme": "system-with-override",
    "density": false
  },
  "integrations": {
    "tray": false,
    "closeToTray": false,
    "launchAtLogin": false,
    "notifications": true,
    "badge": false,
    "progress": true,
    "singleInstance": true,
    "deepLinks": { "scheme": "samplenotes" },
    "fileTypes": [{ "extension": ".samplenote", "role": "editor" }],
    "globalHotkey": false,
    "contextMenus": "web",
    "fileDrop": true,
    "windowState": true,
    "autoUpdate": true
  },
  "distribution": {
    "channels": { "macos": ["direct", "homebrew"], "windows": ["installer", "winget"], "linux": ["deb"] },
    "signing": { "macos": "available", "windows": "later", "linux": "none" }
  },
  "engineering": {
    "devHost": true,
    "gallery": true,
    "devflow": true,
    "crashReporting": "none",
    "accessibility": "wcag-aa",
    "locales": ["en"]
  },
  "decisionsLog": "docs/desktop/decisions.md"
}
```

| Field | Values | Notes |
|---|---|---|
| `version` | `1` | |
| `confirmedByUser` | boolean | Set only by `blueprint.py confirm`, only on the user's own word (§2.3). |
| `decided` | array of field paths | Paths the user has answered (`blueprint.py set --by user`). `questions` skips them. |
| `app.kind` | `tool`, `monitor`, `document`, `launcher`, `dashboard` | Sets the defaults in §2.4. |
| `app.existing` | boolean | An app with code already: the skills detect and respect what's there. |
| `platforms.<p>.enabled` | boolean | At least one of `macos`, `windows`, `linux` is enabled. |
| `platforms.<p>.home` | boolean | The platform that gets the most polish; at most one. |
| `platforms.<p>.minimum` | string | OS version (`14.0`, `10.0.19041`); `linux` has none. |
| `platforms.linux.desktop` | `gnome`, `kde`, `any` | GNOME with libadwaita is the only styled target. |
| `platforms.web.role` | `devhost`, `product`, `none` | A browser dev host is never shipped; `product` is a real web build. |
| `stack.dotnet` | string | `major.minor`, from `global.json` or the target frameworks. |
| `stack.content` | `blazor`, `other` | `other` is out of scope for the first release: the skills say so and stop at structure. |
| `stack.componentLibrary` | `custom`, or a library's name | |
| `stack.sharing` | `rcl`, `links`, `symlinks`, `single`, `unknown` | How heads share the UI. `rcl` is recommended. |
| `stack.backends.<p>` | string | `"<package id> <version>"`, from detection. |
| `chrome.sidebar` | *per-platform* `native`, `web`, `none` | |
| `chrome.toolbar` | *per-platform* `native`, `web`, `none` | |
| `chrome.search` | `toolbar`, `content`, `none` | |
| `chrome.menuBar` | *per-platform* `none`, `minimal`, `standard`, `full` | macOS can't be `none`: an app always has a menu bar there. |
| `chrome.dialogs` | `native-frame`, `web`, `mixed` | `native-frame`: a native title row and button row around a web body. |
| `chrome.settings` | `window`, `dialog`, `page` | |
| `chrome.commandPalette`, `chrome.multiWindow` | boolean | |
| `look.fidelity` | *per-platform* `unified`, `adaptive`, `native-faithful` | §2.5. |
| `look.accent` | `brand`, `platform`, `system` | One brand colour everywhere; each platform's default; or the user's OS accent. |
| `look.theme` | `system`, `system-with-override` | |
| `look.density` | boolean | A comfortable/compact switch. |
| `integrations.*` | boolean, or an object with `"platforms": [...]` and options | `true` means every enabled platform. `deepLinks` needs `scheme`; `fileTypes` is an array (empty = none); `contextMenus` is `web` or `native`. |
| `distribution.channels.<p>` | array of `direct`, `homebrew`, `mac-app-store`, `installer`, `winget`, `msix`, `microsoft-store`, `deb`, `rpm`, `flatpak`, `appimage`, `snap` | |
| `distribution.signing.<p>` | `available`, `later`, `none` | |
| `engineering.crashReporting` | `none`, or a service's name | |
| `engineering.accessibility` | `wcag-aa`, `wcag-aaa`, `none` | |
| `decisionsLog` | path | Default `docs/desktop/decisions.md`. |

### 2.3 The decisions log: `docs/desktop/decisions.md`

Appended by `blueprint.py set` and `confirm`; people may edit it. Each entry:

```markdown
## 2026-11-27: chrome.sidebar.linux = web

- **By:** user
- **Reason:** "We only ship Linux as a preview; a web sidebar is fine there."
- **Was:** native
```

`By` is `user` (the user said so, in their own words, in this conversation) or `proposal` (the agent proposed
it and the user hasn't answered yet). Only `user` adds the path to `decided`. The reason quotes the user where
they gave one.

### 2.4 Defaults by kind

`blueprint.defaults(kind)` (§6) returns these. For an existing app, what detection *finds* overrides a default (a
tray found makes `tray` true); what it doesn't find leaves the default as the proposal. `stack.sharing` is what
was detected, so the gap report shows no sharing move until the user chooses `rcl`. Detected integrations keep
the platforms they were found on; a platform with 100 or more `.platform-<p>` selectors is proposed as
`native-faithful`; a macOS head that adds its own menu items is proposed as `standard`.

| Field | tool | monitor | document | launcher | dashboard |
|---|---|---|---|---|---|
| `chrome.sidebar`, `chrome.toolbar` | native | native | native | none | native |
| `chrome.commandPalette` | true | true | true | true | false |
| `chrome.multiWindow` | false | false | true | false | false |
| `integrations.tray` | false | true | false | true | false |
| `integrations.closeToTray`, `launchAtLogin` | false | true | false | true | false |
| `integrations.notifications` | true | true | false | false | true |
| `integrations.badge` | false | true | false | false | false |
| `integrations.progress` | true | false | false | false | false |
| `integrations.singleInstance` | true | true | true | true | true |
| `integrations.globalHotkey` | false | false | false | true | false |
| `integrations.windowState` | true | true | true | false | true |

Everything else defaults the same for every kind: `menuBar` `{"macos": "standard", "windows": "none", "linux":
"none"}`, `dialogs` `native-frame`, `settings` `dialog`, `search` `toolbar`, `fidelity` `adaptive`, `accent`
`brand`, `theme` `system-with-override`, `density` false, `contextMenus` `web`, `fileDrop` false, `deepLinks`
false, `fileTypes` `[]`, `autoUpdate` true, `devHost` true, `gallery` true, `devflow` true, `accessibility`
`wcag-aa`, `crashReporting` `none`, `locales` `["en"]`, `sharing` `rcl` for a new app, channels
`{"macos": ["direct"], "windows": ["installer"], "linux": ["appimage"]}` and signing `later` everywhere when
nothing is detected.

### 2.5 Fidelity

| Level | What adapts per platform | Cost |
|---|---|---|
| `unified` | fonts, shortcut labels, scrollbars | lowest |
| `adaptive` | design tokens: font and base size, accent (if `look.accent` says so), radii, control heights, density, surface treatment. Components keep one structure | a token block per platform |
| `native-faithful` | the above plus component shapes (switches, segmented controls, menus, buttons) | a component layer per platform; budget it per platform |

### 2.6 The gap report: `docs/desktop/gap-report.md`

Written by `blueprint.py gaps` for an existing app. One table, then one section per row:

```markdown
| Seam | Now | Target | Move | Skill |
|---|---|---|---|---|
| UI sharing | symlinks + compile links | Razor class library | L | maui-desktop-shell |
```

`Move` is `none`, `S`, `M` or `L`. Seams, in order: UI sharing, navigation, page chrome, icons, design tokens,
platform styling, dialogs, menus and shortcuts, windows, each integration the blueprint asks for, distribution.

---

## 3. The design language: `DESIGN.md`

At the project root. The front matter and sections follow `skills/maui-desktop-design/templates/DESIGN.md`.
Generated tables sit between markers that `tokens.py build` replaces (and nothing else in the file):

```markdown
<!-- generated:palette-light:start -->
…
<!-- generated:palette-light:end -->
```

Markers: `palette-light`, `palette-dark`, `palette-<platform>-<theme>` (for platforms that override colours),
`platform-matrix` (every token that differs by platform). A marker pair that's absent is left alone, except the
two `palette-<theme>` pairs when `outputs.design` is set: those are required.

---

## 4. Tokens: `design/tokens.json`

Every colour, size and duration the app uses, written once. Schema: `skills/maui-desktop-design/schema/tokens.schema.json`.

```json
{
  "version": 1,
  "meta": { "name": "Sample Notes", "csharpPrefix": "SampleNotes", "colorSpace": "oklch" },
  "outputs": {
    "css": "src/SampleNotes.Ui/wwwroot/css/tokens.css",
    "csharp": { "path": "src/SampleNotes.Core/Theme/Tokens.g.cs", "namespace": "SampleNotes.Core.Theme",
                "scale": ["radius", "control"] },
    "design": "DESIGN.md",
    "macosAccent": { "path": "src/SampleNotes.MacOS/Assets.xcassets/AccentColor.colorset/Contents.json", "role": "accent" },
    "ignored": ["css", "csharp", "macosAccent"]
  },
  "root": ":root",
  "primitives": {
    "white": [1, 0, 0],
    "ink-900": "#18181b",
    "blue-500": [0.62, 0.19, 255],
    "shadow-a12": [0, 0, 0, 0.12]
  },
  "semantic": {
    "light": { "bg": "white", "ink": "ink-900", "accent": "blue-500",
               "accent-soft": { "mix": "blue-500", "into": "white", "amount": 0.12 } },
    "dark":  { "…": "…" }
  },
  "effects": {
    "light": { "shadow-popover": "0 10px 28px oklch(0 0 0 / 12%)" },
    "dark":  { "shadow-popover": "0 14px 36px oklch(0 0 0 / 55%)" }
  },
  "scale": {
    "space":  { "$prefix": "space-", "1": "4px", "2": "8px" },
    "radius": { "$prefix": "radius-", "sm": "6px", "md": "8px", "lg": "12px" },
    "control": { "$prefix": "control-", "height-md": "30px" },
    "text":   { "$prefix": "text-", "$base": "size", "body": { "size": "0.875rem", "weight": 400, "lh": 1.45 } },
    "z":      { "$prefix": "z-", "popover": 30, "dialog": 40 },
    "motion": { "$prefix": "motion-", "fast": "100ms", "ease": "cubic-bezier(0.2, 0, 0, 1)" }
  },
  "modes": {
    "density": { "default": "comfortable", "selector": ".density-{mode}",
                 "values": { "comfortable": { "row-h": "36px" }, "compact": { "row-h": "28px" } } }
  },
  "platforms": {
    "macos":   { "attribute": "macos", "scale": { "radius": { "md": "10px" }, "text": { "body": { "size": "13px" } } },
                 "semantic": { "light": { "accent": "apple-blue" }, "dark": { "accent": "apple-blue-dark" } } },
    "windows": { "scale": { "radius": { "md": "4px" } } },
    "linux":   { "scale": { "radius": { "md": "8px" } } }
  },
  "contrast": {
    "rules": [{ "fg": "ink", "bg": "bg", "min": 4.5, "label": "body text" }],
    "separation": { "minHueDelta": 60, "rules": [{ "a": "accent", "b": "danger", "min": 1.7, "label": "primary vs destructive" }] },
    "exceptions": {
      "warn-never-filled": { "applies": "light+dark", "rule": "on-accent on warn", "reason": "…", "control": "…" }
    }
  },
  "lint": {
    "scan": ["src"],
    "extensions": [".css", ".razor", ".cs", ".html", ".js"],
    "skip": ["bin", "obj", "node_modules", "wwwroot/lib", "wwwroot/vendor"],
    "rules": { "raw-hex": true, "raw-rgb-hsl": true, "raw-modern-color": true, "named-color": true,
               "px-font-size": true, "magic-z-index": true, "raw-radius": false, "native-select": false },
    "baseline": "design/lint-baseline.json"
  }
}
```

Resolution rules (`tokens.py`):

- **Primitives** are OKLCH `[L, C, H]` or `[L, C, H, A]` (L 0–1, C ≥ 0, H degrees, A 0–1), or sRGB hex `#rgb`,
  `#rrggbb`, `#rrggbbaa`. A primitive outside the sRGB gamut is a contrast-check error (it would clip silently).
- **Semantic roles** name a primitive, or mix two: `{ "mix": a, "into": b, "amount": t }` is `t` of `a` into `b`,
  in OKLCH, the hue taken the short way round, and a grey end (chroma < 0.002) contributing no hue. Keys starting
  `$` are ignored everywhere. Both themes define the same roles; a role missing from one is an error.
- **CSS** (`outputs.css`): colours as `oklch(L C H)` (or `oklch(L C H / A)`) with a hex comment when
  `meta.colorSpace` is `oklch`, hex when it's `srgb`. Themes: the light palette on `<root>` with
  `color-scheme: light`; the dark palette under `@media (prefers-color-scheme: dark) { <root>:not([data-theme="light"]) }`,
  and both again under `<root>[data-theme="dark"]` and `<root>[data-theme="light"]`, so an explicit choice wins.
  `root` defaults to `:root`. Effects are emitted verbatim per theme. `@media (prefers-reduced-motion: reduce)`
  sets every `motion` duration to `1ms`.
- **Scale**: each group's entries become `--<$prefix><name>` (`$prefix` defaults to `<group>-`). An object entry
  becomes `--<$prefix><name>-<key>` for each key, except the group's `$base` key (default `value`), which becomes
  `--<$prefix><name>`. Numbers are emitted bare.
- **Modes**: the default mode's values go on `<root>`; each other mode's under its `selector` with `{mode}` filled in.
- **Platforms**: the app's root element carries `data-platform="<attribute or key>"` (stamped by each head) and,
  when the user chose a theme rather than the system's, `data-theme="light|dark"`. A platform's scale overrides go
  on `<root>[data-platform="p"]`; its colour overrides go under `@media (prefers-color-scheme: light) {
  <root>[data-platform="p"]:not([data-theme="dark"]) }` and `<root>[data-platform="p"][data-theme="light"]`, and
  the dark ones the same way, so a platform's light colours never beat a dark theme. A platform may override only
  roles and scale entries that exist in the base.
- **C#** (`outputs.csharp`), with `P` = `meta.csharpPrefix` (default: `meta.name` in PascalCase, letters and digits
  only): `public enum PColor { … }` (roles in PascalCase), `public readonly record struct PRgb(byte R, byte G,
  byte B, byte A = 255)` with `ToHex()`, `public enum PTheme { Light, Dark }`, and `public static class PTokens`
  with `Get(PTheme, PColor)` and the `Light` and `Dark` dictionaries. With `platforms`: `public enum PPlatform`
  (the platforms named, in PascalCase: `MacOS`, `Windows`, `Linux`, `Web`) and `Get(PPlatform, PTheme, PColor)`,
  falling back to the base palette. Each group named in `outputs.csharp.scale` becomes `public enum P<Group>`
  and `PTokens.<Group>(PPlatform, P<Group>)` (or `<Group>(P<Group>)` without platforms) returning a `double`;
  only `px` values and bare numbers can be emitted there (anything else is an error).
- **macOS accent** (`outputs.macosAccent`): an asset-catalog colour set with the role's light and dark values,
  because AppKit reads an app's accent from its asset catalog at launch.
- **DESIGN.md** (`outputs.design`): the §3 tables. A palette row: `| \`--role\` | \`oklch(…)\` | \`#hex\` | 4.52:1 vs bg |`.
- **`--check`** regenerates in memory and exits 1 naming each stale output. An output listed in `outputs.ignored`
  (gitignored) that doesn't exist yet isn't stale.
- **Contrast**: every rule is checked for each theme, and again for each platform whose overrides touch one of
  the rule's roles. An alpha foreground is composited over the rule's background; a background with alpha is an
  error. Gamut is checked on primitives and on mixed roles. Separation rules pass by luminance ratio ≥ `min` or hue
  distance ≥ `minHueDelta` (a pair with a grey end can't pass on hue alone).
- **Exceptions** name a rule as `"<fg> on <bg>"` or `"separation <a> vs <b>"`, a theme (`applies`: `light`,
  `dark`, `light+dark`) and optionally `platforms` (default: everywhere). An exception is stale, and an error, when
  its pair passes everywhere it applies; one that names no declared rule is an `exception-unused` warning.
- Platforms may also override `effects`. Mode variables are unprefixed (`--<key>`). When a platform overrides a
  `motion` entry, the reduced-motion block covers `[data-platform]` too. When a `macos` block overrides the
  macOS accent role, the colour set uses the override.
- **Exit codes**: an unknown primitive, role or group is 3 (invalid input); a missing `DESIGN.md` or missing
  required markers is 1 (an output that can't be written). `build`, `contrast` and `show` take `--json`.
- **Platform accents and white text**: white on Apple's system blue is about 4.0:1 and on Adwaita blue about
  3.8:1, below 4.5:1. With `look.accent: platform`, either darken the filled accent for text, use a dark ink on it,
  or declare a reasoned exception (large or bold text only) with its control.

## 5. Icons: `design/icons.json`

Every icon the app's chrome and content use, mapped per platform. Schema: `skills/maui-desktop-design/schema/icons.schema.json`.

```json
{
  "version": 1,
  "meta": { "name": "Sample Notes", "csharpPrefix": "SampleNotes", "windows": "svg" },
  "platforms": ["macos", "windows", "linux", "web"],
  "outputs": {
    "csharp": { "path": "src/SampleNotes.Core/Shell/Icons.g.cs", "namespace": "SampleNotes.Core.Shell" },
    "sprite": "src/SampleNotes.Ui/wwwroot/icons/sprite.svg",
    "razor": "src/SampleNotes.Ui/Components/IconSprite.razor",
    "macosMarks": "src/SampleNotes.MacOS/Assets.xcassets",
    "ignored": ["csharp", "sprite"]
  },
  "geometry": { "viewBox": "0 0 24 24", "strokeWidth": 1.75, "linecap": "round", "linejoin": "round" },
  "icons": {
    "refresh": { "sf": "arrow.clockwise", "gtk": "view-refresh-symbolic", "fluent": "E72C",
                 "svg": "<path d='M20 11a8 8 0 1 0-2.3 5.7'/><path d='M20 4v7h-7'/>" }
  },
  "marks": { "app": { "svg": "<path d='…'/>" } }
}
```

- Required keys per icon follow `platforms`: `macos` → `sf`, `linux` → `gtk`, `web` → `svg`, `windows` → `svg`
  (or `fluent`, a Segoe Fluent Icons codepoint in hex, when `meta.windows` is `fluent`). A missing one is an error:
  never a blank button on one platform.
- Icon names are kebab-case; C# names are PascalCase.
- **C#**: `public enum IconRef { … }` and `public static class Icons` with `SfSymbol(IconRef)`, `GtkName(IconRef)`,
  `FluentGlyph(IconRef)` (when fluent), `SpriteId(IconRef)` (`"i-<name>"`), `Svg(IconRef, string stroke)` (a
  standalone SVG document) and, with marks, `MarkSvg(string name, string stroke)`. Only the methods whose
  platform is listed are emitted; `SpriteId` and `Svg` are emitted whenever `svg` is required (web, Windows on
  `svg`, or a `sprite`/`razor` output), so a Windows-on-`fluent` app with a sprite still needs `svg`.
- **Sprite**: `<symbol id="i-<name>">` per icon and `<symbol id="mark-<name>">` per mark, stroked with
  `currentColor` from `geometry`. **Razor** (optional): the same symbols inline, mounted once per document,
  because WebKit doesn't resolve `<use href="file.svg#id">` across documents.
- **macOS marks** (optional): `<macosMarks>/<Pascal>Mark.imageset/` with a black template SVG and `Contents.json`
  marked as a template image, for a status item or dock menu.
- `--check` works as for tokens.

---

## 6. The shared package: `mauidesktop_lib`

Stdlib only. Modules and their public functions:

- **`jsonio`**: `load(path)`, `loads(text, path)`, `dump(value, path)` (atomic, sorted as given, 2-space indent,
  trailing newline), `JsonError` (names file, line, column). Copied from app-stores.
- **`schema`**: `validate(value, schema) -> [message]`, `unsupported(schema)`. Copied from app-stores.
- **`msbuild`**: reading project files without MSBuild. `read_project(path) -> Project` with `sdk`, `properties`
  (dict, last wins, conditions ignored but recorded), `target_frameworks` (list), `package_refs` (list of
  `(id, version_or_None, condition_or_None)`), `project_refs`, `items` (dict kind → list of `(include, attrs)`:
  `Compile`, `RazorComponent`, `BundleResource`, `Content`, …), `imports`. `central_versions(root) -> {id: version}`
  from `Directory.Packages.props`. `sdk_version(root)` from `global.json`.
- **`detect`**: `scan(root) -> dict`, the findings `detect.py` prints (§7.1). Reads files only; never runs `dotnet`.
- **`blueprint`**: `load(path)`, `validate(bp, schema) -> [finding]`, `consistency(bp) -> [finding]` (§7.2 rules),
  `value(bp, path, platform)`, `defaults(kind) -> dict`, `draft(detection, kind=None, overrides=None) -> dict`,
  `set_path(bp, path, value)`, `append_decision(log_path, path, value, was, by, reason, date)`.
- **`findings`**: `Finding(id, severity, where, message)`, `print_findings(list, json=False)`, `exit_code(list)`.

Scripts locate the project with `--root` (default the current directory).

---

## 7. Commands

### 7.1 `detect.py` (blueprint skill)

`detect.py [--root .] [--json] [--out FILE]` reads the project and reports what it finds. Exit 0, or 3 when
`--root` isn't a folder. The JSON:

```json
{
  "root": ".",
  "solution": ["SampleNotes.slnx"],
  "dotnet": { "sdk": "11.0.100", "tfms": ["net11.0", "net11.0-macos"] },
  "projects": [
    { "path": "src/SampleNotes.MacOS/SampleNotes.MacOS.csproj", "role": "head-macos",
      "tfms": ["net11.0-macos"], "packages": { "Microsoft.Maui.Platforms.MacOS": "0.1.0-preview.16.26575.3" } }
  ],
  "heads": { "macos": "src/SampleNotes.MacOS/SampleNotes.MacOS.csproj", "windows": "…", "linux": "…",
             "maccatalyst": null, "ios": null, "android": null, "devhost": null },
  "backends": { "macos": "Microsoft.Maui.Platforms.MacOS 0.1.0-preview.16.26575.3", "linux": "…", "windows": "…" },
  "sharing": { "kind": "symlinks", "evidence": ["src/SampleNotes.MacOS/Pages -> ../SampleNotes/Pages"] },
  "shell": {
    "navigation": { "kind": "per-head", "evidence": [] },
    "toolbar": { "kind": "imperative", "evidence": ["src/SampleNotes.Core/Interfaces.cs: record ToolbarAction(… SfSymbol"] },
    "sidebar": { "macos": "native", "windows": "native", "linux": "native", "web": "web" },
    "menuBar": { "macos": "custom-items", "windows": "none", "linux": "none" }
  },
  "dialogs": { "kind": "page-subclass", "count": 3, "webOverlays": 2, "evidence": [] },
  "design": { "designMd": true, "tokensJson": false, "iconsJson": false, "rawHex": 41, "platformSelectors": { "macos": 12, "windows": 2, "linux": 1 } },
  "integrations": { "tray": [], "notifications": [], "singleInstance": [], "deepLinks": [], "launchAtLogin": [],
                    "globalHotkey": [], "badge": [], "progress": [], "fileTypes": [], "fileDrop": [], "contextMenus": [],
                    "autoUpdate": ["src/SampleNotes.Core/Services/UpdateService.cs: …api.github.com/repos/…/releases"],
                    "windowState": ["src/SampleNotes/App.cs: \"window_width\""] },
  "integrationPlatforms": { "autoUpdate": ["*"], "windowState": ["windows"] },
  "deepLinkSchemes": [],
  "distribution": { "workflows": [".github/workflows/build.yml"], "macos": ["codesign", "notarize", "homebrew"],
                    "windows": ["inno-setup", "winget"], "linux": ["deb"] },
  "tests": { "projects": ["tests/SampleNotes.Core.Tests/SampleNotes.Core.Tests.csproj"], "ui": [] },
  "agentDocs": ["AGENTS.md", "DESIGN.md"]
}
```

The JSON also carries `app` (`name`, `id`, `namespace`, `minimums`), `stack` (`content`, `componentLibrary`) and
`engineering` (`devflow`, `crashReporting`, `gallery`, `devHost`). It is printed as is: `detect.py --json` has no
`ok`/`findings` envelope, because it reports facts, not findings. Each integration's value is its evidence (an
empty list means not found); `integrationPlatforms` says where each was found (`"*"` is shared code), and
`deepLinkSchemes` lists URL schemes registered anywhere. `shell.menuBar.<p>` is `custom-items` (the app adds its
own menus or items), `default` (the backend's menus only) or `none`. Comments, test projects, vendored and
generated files never count as evidence.

Roles: `head-macos` (AppKit: a `-macos` target framework with `UseMaui`, or the `Microsoft.Maui.Platforms.MacOS`
package), `head-maccatalyst`, `head-windows` (`-windows` target framework with `UseMaui`), `head-linux`
(`Microsoft.Maui.Platforms.Linux.Gtk4`), `head-ios`, `head-android`, `devhost` (Web SDK hosting the UI), `ui`
(a Razor class library: Razor SDK, not an exe, with `.razor` files), `core`, `tests`, `tool`, `other-app` (a head
whose `ApplicationId` differs from the desktop heads': a sample or companion app in the same repository, not
reported as a head), `other`. A project can be both the Windows head and the shared UI (`head-windows` with
`alsoUi: true`).

Detection kinds: `sharing.kind` `rcl`, `links` (`Compile`/`RazorComponent` items reaching into another project),
`symlinks`, `single`, `unknown`. `shell.navigation.kind` `manifest` (one declared list, e.g. a
`NavigationManifest`), `per-head` (sidebar items built in each head), `web` (only `NavLink` markup), `unknown`.
`shell.toolbar.kind` `declared` (a page-chrome record a page states), `imperative` (a toolbar service pages call),
`web`, `none`. `dialogs.kind` `session` (a dialog request/session the body drives), `page-subclass` (a native
page class per dialog around a web view), `web` (overlays in pages), `alerts-only`, `none`. Each comes with
`evidence`: `"<path>: <the matching text, trimmed to 120 characters>"`.

### 7.2 `blueprint.py` (blueprint skill)

| Command | Does | Exit |
|---|---|---|
| `init [--root .] [--out desktop-blueprint.json] [--kind K] [--name N] [--id ID] [--platforms macos,windows,linux]` | Detects, then writes a draft: §2.4 defaults for the kind (inferred `monitor` when a tray icon is found, else `tool`), overridden by what's detected, `confirmedByUser: false`, `decided: []` | 0; 2 if the file exists |
| `check [--blueprint F] [--json]` | Schema, then consistency | 0; 1 on any error; 3 if unreadable |
| `questions [--blueprint F] [--root .]` | Prints the interview (markdown): every undecided field, grouped as in the blueprint skill's `references/interview.md`, each with the proposed answer and why | 0 |
| `set PATH=VALUE … --reason TEXT [--by user\|proposal] [--blueprint F]` | Sets fields (`VALUE` is JSON, or a bare string), appends a decision per field (§2.3); `--by user` (the default) adds the path to `decided` | 0; 3 on a bad path or a schema violation (nothing written) |
| `confirm --note TEXT [--blueprint F]` | Sets `confirmedByUser: true`; appends a decision for `confirmedByUser` | 0; 1 if `check` has errors (nothing written) |
| `gaps [--blueprint F] [--root .] [--out docs/desktop/gap-report.md] [--print]` | Writes the §2.6 report from detection versus the blueprint | 0 |
| `show [--blueprint F] [--json]` | The blueprint as a table, one column a platform | 0 |

`set` details: a bare number stays a string (`platforms.macos.minimum=14.0`); `null` removes a field; `version`,
`confirmedByUser` and `decided` can't be set; `--by proposal` resets `confirmedByUser` to false; setting one
platform's value of a single-valued per-platform field first spreads the single value over the enabled
platforms. `check` runs the consistency rules only once the schema passes; the other commands exit 3 on a
blueprint that breaks the schema. `gaps` on a new app (nothing detected) says so and writes nothing. The
interview's Engineering group also asks how the heads share the UI (`stack.sharing`).

Consistency rules (`blueprint.consistency`), each a finding id:

| Id | Severity | When |
|---|---|---|
| `no-platform` | error | no desktop platform enabled |
| `two-homes` | error | more than one `home` |
| `macos-menu-bar` | error | `chrome.menuBar.macos` is `none` |
| `deep-link-scheme` | error | `deepLinks` set without a `scheme` matching `^[a-z][a-z0-9+.-]*$` |
| `per-platform-key` | error | a per-platform object names a platform that isn't enabled |
| `gtk-native-chrome` | info | `linux` sidebar or toolbar is `native`: the GTK backend has neither, so the head builds them |
| `tray-gnome` | warning | `tray` on `linux`: stock GNOME shows no tray icon without an extension |
| `hotkey-wayland` | warning | `globalHotkey` on `linux`: only through the GlobalShortcuts portal on Wayland |
| `unsigned-macos` | warning | `notifications` or `launchAtLogin` on macOS without `signing.macos: available` |
| `update-owned-by-channel` | warning | `autoUpdate` while a platform ships through `mac-app-store`, `microsoft-store`, `msix`, `flatpak` or `snap`: switch it off for that channel |
| `update-package-repo` | info | `autoUpdate` with `deb` or `rpm`: from a package repository the package manager updates it; from a downloaded file the in-app check opens the download |
| `flatpak-autostart` | warning | `launchAtLogin` with `flatpak`: needs the Background portal |
| `faithful-cost` | warning | `fidelity` `native-faithful` on any platform |
| `sharing-not-rcl` | warning | `stack.sharing` is `links` or `symlinks` |
| `content-other` | info | `stack.content` is `other` |

### 7.3 `tokens.py` (design skill)

| Command | Does | Exit |
|---|---|---|
| `init [--root .] [--out design/tokens.json] [--blueprint F]` | Copies `templates/tokens.json`, filling `meta`, the platforms the blueprint enables and `outputs` paths guessed from the project's layout (detection) | 0; 2 if it exists |
| `build [--root .] [--tokens design/tokens.json] [--check] [--json]` | Writes (or with `--check`, compares) every output in §4 | 0; 1 stale; 3 invalid input |
| `contrast [--root .] [--tokens F] [--json] [--quiet]` | §4 contrast and gamut checks | 0; 1 on failure |
| `show [--root .] [--tokens F] [--theme light\|dark] [--platform P] [--json]` | The resolved palette and scale; the JSON is `{"theme", "platform", "colors": {role: {"oklch", "hex"}}, "scale": {name: value}}` | 0 |

Without `--tokens`, `design/tokens.json` is used, or `tokens.json` at the root when that's missing.

### 7.4 `icons.py` (design skill)

`icons.py init [--root .] [--out design/icons.json] [--blueprint F]` (exit 2 if it exists) and
`icons.py build [--root .] [--icons design/icons.json] [--check]` (0; 1 stale or incomplete; 3 invalid input).

### 7.5 `lint.py` (design skill)

`lint.py [--root .] [--tokens design/tokens.json] [--json] [--write-baseline] [PATH …]` scans `lint.scan` (or the
paths given) for the enabled rules. Every `outputs` file is skipped. A finding on a line carrying
`design-lint-ok: <reason>` (or in the comment block directly above it) is suppressed. With `lint.baseline` set,
only findings beyond the baseline's count for each `(file, rule)` fail, so an existing app can adopt the gate and
ratchet; `--write-baseline` records today's counts (exit 0). Rules: `raw-hex`, `raw-rgb-hsl`, `raw-modern-color`
(`oklch()`, `oklab()`, `lab()`, `lch()`, `color()`), `named-color`, `px-font-size`, `magic-z-index` (not a `var()`,
`0`, `-1`, `auto` or `inherit`), `raw-radius` (`border-radius` that isn't a `var()`, `0` or `50%`),
`native-select` (`<select` in `.razor` or `.html`). Exit 0 clean; 1 findings.

### 7.6 `install.py` (design skill)

`install.py [--root .] [--into build/design]` copies `tokens.py`, `icons.py`, `lint.py`, `design_color.py`,
the schemas and `mauidesktop_lib` into the project, with a `VERSION` file naming this skill's version, so the
app's CI can run `python3 build/design/tokens.py build --check` without the skill installed. Layout:
`<into>/{tokens,icons,lint,design_color}.py`, `<into>/mauidesktop_lib/`, `<into>/schema/`, `<into>/VERSION`;
installed scripts look for schemas in `<into>/schema` first. Templates aren't installed, so `init` needs the
skill. Exit 0; 2 if the folder exists and holds files from a different version (`--force` replaces them).

---

## 8. Handoffs

Each skill works alone, and reads what the others wrote when it's there:

| File | Written by | Read by |
|---|---|---|
| `desktop-blueprint.json`, `docs/desktop/decisions.md` | blueprint | every other skill |
| `docs/desktop/gap-report.md` | blueprint | shell, dialogs, design (what to migrate) |
| `DESIGN.md`, `design/tokens.json`, `design/icons.json` | design | shell (icons and tokens in native chrome), dialogs |
| generated token and icon outputs | design (`tokens.py`, `icons.py`) | the app |

## 9. Versions and changes

Each skill's `VERSION` is one semver line, starting at `0.1.0`. Changes go in `plugins/maui-desktop/CHANGELOG.md`
under `[Unreleased]` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)), one entry per pull request.
