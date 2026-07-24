# Vendoring skill-reflect into your plugin

This is the deep reference for vendored installs. Start with the canonical author
guide first: **[AUTHORS.md](../AUTHORS.md)**.

Vendoring means you ship `skill-reflect` inside your plugin, scoped to your
skills and routed to your repository. It is the reliable baseline for authors who
want coverage without depending on a separate user install.

The privacy model is unchanged:

- explicit reviews return chat findings by default;
- local writes and remote sends require separate authorization, with an exact
  outbound-body preview before every send;
- PII, secrets, absolute/private paths and URLs, machine names, and verbatim
  transcript excerpts must never appear in output;
- the hooks do no AI and no network work.

## Preferred author workflow

Use the dev-time **`skill-reflect-maintainer`** skill, not this directory's
fallback script, for normal adoption and maintenance.

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py adopt \
  --to <your-plugin> \
  --from <redth-skills-checkout> \
  --scope skill-a,skill-b \
  --destination you/your-repo
```

Per `docs/CONTRACT.md` §11.3, `adopt`:

- copies `skills/skill-reflect/` to `<to>/skills/skill-reflect/` by default;
- copies `hooks/stage_pending.py` and `hooks/nudge_start.py` to `<to>/hooks/`;
- merges SessionStart/SessionEnd commands into `<to>/hooks/hooks.json` without
  clobbering existing hooks;
- optionally copies `integrations/copilot-cli/skill-reflect-auto/` when
  `--with-auto` is used;
- writes `.skill-reflect-vendor.json` with version, source, targets, hash, scope,
  and destination;
- scaffolds `skill-reflect.config.json` only if absent.

The maintainer skill also appends the Improve This Skill block from
`skills/skill-reflect/templates/improve-this-skill.md` to each in-scope skill.

## Vendored layout

A typical target plugin after adoption:

```text
my-plugin/
├── .skill-reflect-vendor.json
├── skill-reflect.config.json
├── hooks/
│   ├── hooks.json
│   ├── nudge_start.py
│   └── stage_pending.py
├── skills/
│   ├── my-skill-a/
│   │   └── SKILL.md
│   ├── my-skill-b/
│   │   └── SKILL.md
│   └── skill-reflect/
│       ├── SKILL.md
│       ├── references/
│       ├── scripts/
│       └── templates/
└── extensions/
    └── skill-reflect-auto/        # optional, copied with --with-auto
        ├── attribution.mjs
        ├── extension.mjs
        └── extension.json
```

## Pin file

The maintainer engine writes `.skill-reflect-vendor.json` at the parent of the
vendored skill directory. The binding shape is defined in `docs/CONTRACT.md`
§11.2 and includes:

- `schema`;
- `upstreamVersion` from `skills/skill-reflect/VERSION`;
- `sourceRepo` and `sourceRef`;
- `vendoredAt`;
- `targets.skill`, `targets.hooks`, and `targets.autoExtension`;
- `contentHash` for drift detection;
- `scope`;
- `destinationRepo`.

Do not hand-edit the hash. Re-run the maintainer engine when you intentionally
adopt or update.

## Config

`skill-reflect.config.json` lives at the root of your plugin. In vendored mode,
use an explicit scope and destination repo:

```json
{
  "version": 1,
  "mode": "vendored",
  "scope": {
    "skills": ["my-skill-a", "my-skill-b"],
    "excludeSkills": ["skill-reflect", "skill-reflect-auto"]
  },
  "destination": {
    "mode": "ask",
    "repo": "your-org/your-repo"
  },
  "privacy": {
    "extraScrubPatterns": [],
    "redactionPreview": true,
    "allowTranscriptExcerpts": false
  }
}
```

`mode: "vendored"` plus `destination.repo` gives confirmed routing to your repo.
`destination.mode: "ask"` preserves destination-specific remote authorization:
users see the exact strict body and approve before sending.

Schema reference: `skill-reflect.config.schema.json` in the Redth/skills repo
root. Example: `vendoring/skill-reflect.config.vendored.example.json`.

## Hooks

Vendored Claude Code support uses the marketplace hook scripts:

- `hooks/stage_pending.py` for SessionEnd;
- `hooks/nudge_start.py` for SessionStart.

The maintainer engine merges the command entries from `hooks/hooks.json` into
your plugin's `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}` paths and preserves
your other hooks. The fallback script copies `hooks/hooks.json` only when you do
not already have one; otherwise you must merge those entries manually.

## Improve This Skill blocks

Each covered skill should include the block from:

```text
skills/skill-reflect/templates/improve-this-skill.md
```

This block is only an authorization-first nudge. To add a skill later, add it to
`scope.skills` and insert the block, or ask the maintainer skill to:

> wire reflection into <skill>

## Keeping current

Updates are manual and author-approved. There is no CI requirement and no
scheduled network check in v1.

The SessionStart update-check hook compares your local `.skill-reflect-vendor.json`
`upstreamVersion` to the installed plugin's `skills/skill-reflect/VERSION`. If
you are behind, it prints one throttled nudge. Nothing changes until you ask the
maintainer skill to update.

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py update --to <your-plugin>
```

`update` preserves `skill-reflect.config.json`, preserves your own skills' nudge
wording, re-merges hooks, and refuses with exit `3` on local drift unless forced.
Read `CHANGELOG.md`, review the diff, and approve manually.

For diagnostics:

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py doctor --to <your-plugin>
```

`doctor` exits `0` healthy/current, `10` update available, `11` drift, or `12`
for config/hooks/nudge problems.

## Minimal fallback: sync_vendor.sh

`vendoring/sync_vendor.sh` is intentionally basic:

```sh
vendoring/sync_vendor.sh \
  --from <redth-skills-checkout> \
  --to <your-plugin> \
  --with-auto
```

It copies the current source layout:

| Source | Target |
|---|---|
| `skills/skill-reflect/` | `<your-plugin>/skills/skill-reflect/` |
| `hooks/stage_pending.py` | `<your-plugin>/hooks/stage_pending.py` |
| `hooks/nudge_start.py` | `<your-plugin>/hooks/nudge_start.py` |
| `hooks/hooks.json` | `<your-plugin>/hooks/hooks.json` only if absent |
| `integrations/copilot-cli/skill-reflect-auto/` | `<your-plugin>/extensions/skill-reflect-auto/` with `--with-auto` |

It never overwrites an existing `skill-reflect.config.json`. It does not create a
pin file, detect drift, run `doctor`, or stamp nudge blocks.

## Double-fire / dedupe

If a user has a central install and your vendored copy active, review nudges
dedupe by skill name across both. The maintainer update-check is author-only and
per `.skill-reflect-vendor.json` pin, so it does not double-nudge end users.
