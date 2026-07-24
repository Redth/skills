# dotnet-maui vendored skill-reflect example

This directory shows the post-vendoring layout for the **`dotnet/maui-labs`**
plugin: `skill-reflect` is bundled, scoped to MAUI skills, and routed to the
plugin's issue tracker.

For the canonical author workflow, see [AUTHORS.md](../../../AUTHORS.md). Use
the dev-time `skill-reflect-maintainer` skill for adoption and manual updates.

## Post-vendoring directory layout

```text
maui-labs/                                 # root of the host plugin repo
├── .skill-reflect-vendor.json             # maintainer pin: version, hash, scope, destination
├── skill-reflect.config.json              # vendored config (routes to dotnet/maui-labs)
├── hooks/
│   ├── hooks.json                         # includes merged SessionStart/SessionEnd entries
│   ├── nudge_start.py
│   └── stage_pending.py
├── skills/                                # host plugin's own skills plus vendored core
│   ├── dotnet-maui-doctor/
│   │   └── SKILL.md                       # includes Improve This Skill block
│   ├── maui-app-lifecycle/
│   │   └── SKILL.md
│   ├── maui-data-binding/
│   │   └── SKILL.md
│   ├── maui-dependency-injection/
│   │   └── SKILL.md
│   ├── maui-safe-area/
│   │   └── SKILL.md
│   ├── maui-shell-navigation/
│   │   └── SKILL.md
│   ├── maui-collectionview/
│   │   └── SKILL.md
│   ├── maui-theming/
│   │   └── SKILL.md
│   ├── binlog-failure-analysis/
│   │   └── SKILL.md
│   ├── native-library-bindings/
│   │   └── SKILL.md
│   └── skill-reflect/                     # vendored copy from skills/skill-reflect/
│       ├── SKILL.md
│       ├── references/
│       ├── scripts/
│       └── templates/
└── extensions/
    └── skill-reflect-auto/                # optional Copilot CLI automation
        ├── attribution.mjs
        ├── extension.mjs
        └── extension.json
```

The vendored core is copied from `skills/skill-reflect/`. The optional Copilot
CLI extension is copied from `integrations/copilot-cli/skill-reflect-auto/` to
`extensions/skill-reflect-auto/`.

## Config at a glance

`skill-reflect.config.json` (see the full file in this directory):

```json
{
  "version": 1,
  "mode": "vendored",
  "scope": {
    "skills": ["dotnet-maui-doctor", "maui-app-lifecycle", "maui-data-binding", "..."],
    "excludeSkills": ["skill-reflect", "skill-reflect-auto"]
  },
  "destination": {
    "mode": "issue",
    "repo": "dotnet/maui-labs"
  }
}
```

`destination.repo: "dotnet/maui-labs"` hardcodes feedback routing to this repo's
issue tracker. The privacy and authorization guarantees are unchanged.

## Improve This Skill block

Each host skill's `SKILL.md` should include the standard block from
`skills/skill-reflect/templates/improve-this-skill.md`, with `[skill-name]` and
`[owner/repo]` filled in. Example for `dotnet-maui-doctor`:

```markdown
<!-- BEGIN skill-reflect nudge -->

## Improve This Skill

**For the agent:** If this skill was used during the session and you or the user
encountered friction, you may offer a brief skill-quality review at a natural
stopping point:

> "This session used **dotnet-maui-doctor** and encountered some friction. Want a
> privacy-safe review of how the skill performed?"

If the user says **yes**, invoke the `skill-reflect` skill:

    Run skill-reflect in analysis mode. Skill used this session: dotnet-maui-doctor
    (source repo: dotnet/maui-labs).

<!-- END skill-reflect nudge -->
```

## Sync and maintenance

Preferred maintenance is manual and author-approved through the maintainer skill:

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py doctor --to <maui-labs>
python3 skills/skill-reflect-maintainer/scripts/adopt.py update --to <maui-labs>
```

The SessionStart update-check hook checks only local files: the vendored pin's
`upstreamVersion` against the installed plugin's `skills/skill-reflect/VERSION`. It does not make
network calls and never updates automatically.

For a basic copy-only fallback:

```sh
vendoring/sync_vendor.sh \
  --from <redth-skills-checkout> \
  --to <maui-labs> \
  --with-auto
```

The fallback preserves `skill-reflect.config.json`; if `hooks/hooks.json` already
exists, merge the SessionStart/SessionEnd entries from the source `hooks/hooks.json`
manually.
