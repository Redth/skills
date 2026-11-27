# The blueprint file

`desktop-blueprint.json` at the project root, schema `schema/desktop-blueprint.schema.json`. Every later skill
reads it, so it holds decisions, not notes. The full contract is the plugin's `CONTRACT.md` §2; this is the
working summary.

## Shape

```json
{
  "version": 1,
  "confirmedByUser": false,
  "decided": ["app.kind", "platforms", "chrome.sidebar"],
  "app": { "name": "Sample Notes", "id": "com.example.samplenotes", "namespace": "SampleNotes", "kind": "tool", "existing": true },
  "platforms": {
    "macos":   { "enabled": true, "home": true, "minimum": "14.0" },
    "windows": { "enabled": true, "minimum": "10.0.19041" },
    "linux":   { "enabled": true, "desktop": "gnome" },
    "web":     { "enabled": true, "role": "devhost" }
  },
  "stack": { "dotnet": "11.0", "content": "blazor", "componentLibrary": "custom", "sharing": "rcl", "backends": {} },
  "chrome": { "sidebar": "native", "toolbar": "native", "search": "toolbar",
              "menuBar": { "macos": "standard", "windows": "none", "linux": "none" },
              "dialogs": "native-frame", "settings": "dialog", "commandPalette": true, "multiWindow": false },
  "look": { "fidelity": "adaptive", "accent": "brand", "theme": "system-with-override", "density": false },
  "integrations": { "tray": false, "notifications": true, "singleInstance": true,
                    "deepLinks": { "scheme": "samplenotes" }, "fileTypes": [], "windowState": true, "autoUpdate": true },
  "distribution": { "channels": { "macos": ["direct", "homebrew"], "windows": ["installer", "winget"], "linux": ["deb"] },
                    "signing": { "macos": "available", "windows": "later", "linux": "none" } },
  "engineering": { "devHost": true, "gallery": true, "devflow": true, "crashReporting": "none",
                   "accessibility": "wcag-aa", "locales": ["en"] },
  "decisionsLog": "docs/desktop/decisions.md"
}
```

## Per-platform values

Fields that differ by platform (`chrome.sidebar`, `toolbar`, `menuBar`, `look.fidelity`) take one value for
every platform or an object keyed by `macos`, `windows`, `linux`, `web`, with `"*"` as the fallback:

```json
"sidebar": { "*": "native", "linux": "web" }
```

An integration is `true` (every enabled platform), `false`, or an object with `"platforms": ["macos", "windows"]`
and its options.

## Who writes what

| Field | Set by |
|---|---|
| everything, as a draft | `blueprint.py init` (detection plus the kind's defaults) |
| a field the user answered | `blueprint.py set PATH=VALUE --reason "…"` (adds it to `decided`) |
| a proposal still waiting for an answer | `blueprint.py set … --by proposal` (not added to `decided`) |
| `confirmedByUser` | `blueprint.py confirm --note "…"`, only after the user says the blueprint is right |

Edit the file by hand only to fix something the scripts can't express; then run `check`.

## The decisions log

`docs/desktop/decisions.md`, one dated entry per change: the field, the new value, who decided (`user` or
`proposal`), the reason in the user's words, and what it was. It's the history a later reader needs: why Linux
has a web sidebar, why there's no tray.

## The gap report

`docs/desktop/gap-report.md`, from `blueprint.py gaps`: for each seam (UI sharing, navigation, page chrome, icons,
tokens, platform styling, dialogs, menus and shortcuts, windows, each integration asked for, distribution), what
the app does now, the target, the size of the move (none, S, M, L) and which skill makes it. Regenerate it after
each move; don't edit it by hand.
