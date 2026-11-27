# Reading an existing app

`detect.py` reads project files and source text; it never builds or runs anything. Its findings are evidence,
not verdicts: read the evidence lines, open the files they point at when a finding matters, and ask the user when
the code and the docs disagree.

## What it reads

| Area | From | Tells you |
|---|---|---|
| Heads | each `.csproj`: target frameworks, `UseMaui`, the backend packages | which platforms exist, AppKit versus Mac Catalyst, mobile targets too |
| Backends | package versions (with `Directory.Packages.props`), `global.json` | the .NET major and preview train; later skills' recipes are version-specific |
| UI sharing | project references to a Razor class library; `Compile`/`RazorComponent` items reaching into another project; symlinked folders | how pages and components reach each head |
| Navigation | a navigation manifest type; sidebar items built in a head; `NavLink` markup | whether the sidebar is declared once or per head |
| Toolbar | a page-chrome record pages declare; a toolbar service pages call | declared or imperative |
| Dialogs | a dialog request/session type; native page subclasses around a web view; web overlays in pages | which dialog generation, and how many dialogs a migration touches |
| Design | `DESIGN.md`, `design/tokens.json`, `design/icons.json`; raw hex counts; `.platform-*` selectors | how mature the design system is, and the fidelity in practice |
| Integrations | the API names in the integrations table | what's already there, per platform |
| Distribution | workflow files: signing, notarisation, installers, package formats | what shipping already looks like |

## The two generations

Apps built this way so far fall into two shapes. Name which one the app is when you report.

**Older: per-head chrome.** One project doubles as the Windows head and the shared UI; the macOS and Linux heads
pull its files in by links or symlinks, so the same code compiles three times with many `#if` blocks. Pages call
an imperative toolbar service whose records carry SF Symbol names, so each head keeps a translation table. The
sidebar is built in each head and again as web markup. Each dialog is a native page subclass plus a routed web
component, joined by a shared bridge object. Colours are written by hand in CSS and again in native code.

**Newer: declared chrome.** A Razor class library holds every page and component, and heads reference it. One
navigation manifest feeds every sidebar. Pages declare their chrome (title, search, actions, filters, menus) as a
value with equality; heads project it and rebuild only when its shape changes. Icons are a semantic enum
generated from one file with every platform's name. Dialogs are a request and a session: the body states its
title and buttons, the head draws them natively. Tokens are generated into both CSS and C# from one file.

The newer shape is the target. An app in the older shape has working, proven chrome: migrate seam by seam,
smallest risk first, and keep it shipping between steps (the gap report orders the moves).

## Versions

The AppKit and GTK4 backends are previews (`0.1.0-preview.N`); behaviour and workarounds change between them.
Record the versions in `stack.backends`; later skills check them before applying a recipe and say when a
workaround is no longer needed. Don't assume an app is on the latest .NET: one reference app is on .NET 11, the
other on .NET 10.

## When detection is wrong

- **A layout it doesn't know** (heads in unusual folders, a custom SDK): tell the user what was found and ask.
- **Mid-migration** (both a toolbar service and page chrome): report both; ask which is the direction.
- **Docs disagree with code** (a README advertising a package CI doesn't build): trust the code for "now", ask
  the user for "target", and mention the stale doc.
