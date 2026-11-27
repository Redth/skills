---
name: maui-desktop-blueprint
description: >
  Use this skill to plan a .NET MAUI desktop app for macOS, Windows and Linux, or to bring an existing MAUI or
  Blazor Hybrid desktop app onto a native-chrome architecture: which platforms, native or web sidebar and
  toolbar, a menu bar, native dialogs around web content, a tray or menu-bar icon, notifications, single
  instance, deep links, auto-update, how platform-specific the content should look, and how it ships. It reads
  the project first, interviews the user in one message with a proposed answer for every question, and records
  the decisions in desktop-blueprint.json with a dated decisions log and, for an existing app, a gap report.
  Use when someone says "start a cross-platform desktop app with MAUI", "should this be native or web",
  "plan our Mac, Windows and Linux app", "what desktop features should we add", "review our MAUI desktop
  architecture". Do not use for the design language or tokens (maui-desktop-design), mobile-only MAUI apps,
  Electron or Tauri apps, or fixing a specific build error.
license: MIT
---

# maui-desktop-blueprint

The front door of the `maui-desktop` plugin. Reads what's there, asks the user what they want in one message,
and writes the answers down so no later step asks again: `desktop-blueprint.json`, `docs/desktop/decisions.md`
and, for an existing app, `docs/desktop/gap-report.md`.

## Purpose

- **Decide the app's desktop shape with its user:** platforms and the home one; which parts of the window are
  native and which are web, per platform; dialogs; how platform-specific the content looks; the background and
  OS integrations the kind of app needs; distribution.
- **Respect what exists.** For an existing app, `detect.py` reads the project (heads, backends and versions, how
  the UI is shared, the shell and dialog generation, the design system, integrations, packaging) and every
  proposal starts from it.
- **Record decisions durably:** one schema-backed file, a decisions log in the user's words, and a gap report that
  sizes each move and names the skill that makes it.

## Non-goals

- The design language, tokens, icons and per-platform styling (`maui-desktop-design`).
- Building the shell, dialogs, integrations or release pipeline (`maui-desktop-shell`, `maui-desktop-dialogs`,
  `maui-desktop-integrations`, `maui-desktop-ship`, to follow). This skill decides; they build.
- Writing app code. These skills describe structure; the agent writes code in the app's own conventions.
- Mobile-only MAUI apps, Mac Catalyst as the macOS target, Electron, Tauri or other shells.

## When to use

- Starting a desktop app with .NET MAUI and a web UI (Blazor Hybrid by default).
- Adopting this architecture in an existing app, or reviewing one: "what's native, what's web, what should be?"
- Adding a platform, a tray icon, notifications or another OS integration, when it isn't yet clear it belongs.
- Before `maui-desktop-design` or any later skill, when there's no `desktop-blueprint.json` yet.

## Inputs

| Input | Where | Notes |
|---|---|---|
| The project | `--root` (default the current folder) | Read only. Nothing is built or run |
| `desktop-blueprint.json` | the project root (`--blueprint`) | Created by `init`. Every field: [blueprint-file.md](references/blueprint-file.md) |
| `docs/desktop/decisions.md` | the blueprint's `decisionsLog` | Appended by `set` and `confirm` |
| Agent docs | `AGENTS.md`, `CLAUDE.md`, `DESIGN.md`, `docs/` | Read before proposing: they hold decisions the code doesn't show |

Prerequisites: Python 3.8+ (stdlib only), on macOS, Linux or Windows.

## Workflow

The scripts are in this skill's `scripts/` folder; run them with `python3`, from the user's project.

1. **Read the project.** `detect.py` (add `--json` for the full findings), then the agent docs. Note the target
   frameworks and backend versions: recipes in later skills depend on them, and an existing app's choices win
   over this skill's defaults ([detection.md](references/detection.md)).
2. **Draft.** `blueprint.py init` writes a draft from the detected facts and the defaults for the kind of app
   ([app-kinds.md](references/app-kinds.md)). Pass `--kind` when the kind is obvious from what the user said.
   For an existing app, run `blueprint.py gaps` now too: the gap report shapes what to ask.
3. **Ask, in one message.** `blueprint.py questions` prints every undecided question with a proposed answer and
   the reason. Turn it into one message: lead with what you found, group the questions, say why each proposal
   fits this app, mark the ones that matter most, and keep each to a line or two
   ([interview.md](references/interview.md)). Explain native versus web where the user is choosing between them
   ([native-or-web.md](references/native-or-web.md)) and what each integration costs on each platform
   ([integrations.md](references/integrations.md)). **Stop for the answers.**
4. **Record.** For each answer: `blueprint.py set chrome.sidebar.linux=web --reason "<the user's words>"`. A
   proposal the user hasn't answered stays `--by proposal` (or unset). Ask a follow-up only where an answer
   conflicts with another or with the platform (step 5).
5. **Check.** `blueprint.py check`. Errors are contradictions to resolve with the user (macOS without a menu bar,
   a deep link with no scheme). Warnings are costs to tell them about once (a tray icon on stock GNOME, an
   in-app updater on a store build).
6. **Show and confirm.** `blueprint.py show` and, for an existing app, the gap report. When the user says the
   blueprint is right, `blueprint.py confirm --note "<their words>"`. Never confirm on their behalf.
7. **Hand off.** Say which skill comes next and why: usually `maui-desktop-design` (the design language), then
   the shell. For an existing app, list the gap report's moves in the order the user wants them, smallest
   risk first.

## Agent rules

The short form; the reasons are in [agent-rules.md](references/agent-rules.md).

1. Read first. Run `detect.py` and read the agent docs before proposing anything.
2. Ask in one message, with a proposed answer for every question. Never ten messages; never a blank form.
3. The user decides. `set --by user` and `confirm` only on the user's own words in this conversation.
4. An existing app's conventions win. Say when a proposal departs from what's there, and what the move costs.
5. Native where the platform owns the behaviour; web where the content is the app's own. Explain the trade, don't
   preach it.
6. Every integration has a cost on some platform. Say it once, plainly, with the fallback.
7. Don't write app code from this skill. Decide, record, hand off.
8. Don't commit unless asked. Say what's ready: the blueprint, the decisions log, the gap report.

## Validation

- `blueprint.py check` exits 0 (warnings read out to the user once).
- Every question `questions` printed was either answered by the user or explicitly left as a proposal.
- `decided` lists only paths the user answered; `confirmedByUser` is true only after their confirmation.
- For an existing app, `docs/desktop/gap-report.md` exists and its "Now" column matches what `detect.py` found.
- `--json` on `check` gives machine-readable findings (`id`, `severity`, `where`, `message`).

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `init` exits 2 | a blueprint already exists | read it; continue with `questions` and `set`. Never delete it to start over |
| `detect.py` finds no heads | not a MAUI desktop app yet, or an unusual layout | treat it as a new app; ask the user where the projects are if there's code |
| Detection disagrees with the agent docs | the docs are stale, or the code is mid-migration | ask the user which is true; record the answer |
| `check`: `macos-menu-bar` | macOS always has a menu bar | propose `minimal` (App, Edit, Window) |
| `check`: `per-platform-key` | an answer names a platform that isn't enabled | drop the key or enable the platform, as the user says |
| The user wants Mac Catalyst | out of scope: these skills target AppKit | say so; the blueprint still records platforms and choices |
| The user wants a non-Blazor web stack | `stack.content: other` | record it; later skills describe structure but their recipes assume Blazor |

## References

| File | What's in it |
|---|---|
| [interview.md](references/interview.md) | the questions, how to propose answers, a worked message |
| [native-or-web.md](references/native-or-web.md) | where native pays for itself, per surface; the seam |
| [app-kinds.md](references/app-kinds.md) | tool, monitor, document, launcher, dashboard: what each implies |
| [integrations.md](references/integrations.md) | each OS integration's cost and caveat per platform |
| [detection.md](references/detection.md) | what `detect.py` reads, the two generations of this architecture, versions |
| [blueprint-file.md](references/blueprint-file.md) | every field of `desktop-blueprint.json`, the log, the gap report |
| [agent-rules.md](references/agent-rules.md) | the agent's rules with their reasons |
