# vendoring/

This directory supports authors who vendor `skill-reflect` into their own plugin.
The canonical entry point is **[AUTHORS.md](../AUTHORS.md)**.

## Contents

| File / Dir | Purpose |
|---|---|
| [`../AUTHORS.md`](../AUTHORS.md) | Start here: canonical author workflow. |
| [`vendor.md`](vendor.md) | Deep reference for vendored layout, config, hooks, and the minimal copy helper. |
| [`skill-reflect.config.vendored.example.json`](skill-reflect.config.vendored.example.json) | Config example. |
| [`sync_vendor.sh`](sync_vendor.sh) | Minimal POSIX copy helper. |
| [`examples/dotnet-maui/`](examples/dotnet-maui/) | Worked example of a vendored plugin layout. |

## Recommended path

Use the dev-time **`skill-reflect-maintainer`** skill and ask it to:

> adopt skill-reflect into this plugin

It runs `skills/skill-reflect-maintainer/scripts/adopt.py adopt`, writes the
`.skill-reflect-vendor.json` pin, merges SessionStart/SessionEnd hooks, scaffolds
vendored config if absent, and wires the Improve This Skill blocks into scoped
skills.

Equivalent CLI:

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py adopt \
  --to <your-plugin> \
  --from <redth-skills-checkout> \
  --scope skill-a,skill-b \
  --destination you/your-repo
```

## Manual updates, no CI

The `skill-reflect` plugin's SessionStart update-check hook performs a local-only
version check: `.skill-reflect-vendor.json` `upstreamVersion` versus the installed
plugin's `skills/skill-reflect/VERSION`. It makes no network calls and never updates anything by
itself. When it nudges, ask the maintainer skill to `update skill-reflect`, review
`CHANGELOG.md`, and approve the file changes manually.

## No-frills fallback

If you only need a basic copy, run:

```sh
vendoring/sync_vendor.sh \
  --from <redth-skills-checkout> \
  --to <your-plugin> \
  --with-auto
```

The fallback copies:

- `skills/skill-reflect/` to `<your-plugin>/skills/skill-reflect/`;
- `hooks/stage_pending.py` and `hooks/nudge_start.py` to `<your-plugin>/hooks/`;
- `hooks/hooks.json` only when the target has none;
- optionally `integrations/copilot-cli/skill-reflect-auto/` to
  `<your-plugin>/extensions/skill-reflect-auto/`.

It never overwrites an existing `<your-plugin>/skill-reflect.config.json`.
