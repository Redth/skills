# dotnet-maui vendored skill-reflect example

This directory shows the post-vendoring layout for the **`dotnet/maui-labs`** plugin —
a worked example of embedding `skill-reflect` inside an existing plugin repo so that
all feedback from MAUI-skill sessions is routed to the plugin's own issue tracker.

## Post-vendoring directory layout

```
maui-labs/                                 ← root of the host plugin repo
│
├── skill-reflect.config.json              ← vendored config (routes to dotnet/maui-labs)
│
├── skills/                                ← host plugin's own skills
│   ├── dotnet-maui-doctor/
│   │   └── SKILL.md
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
│   └── native-library-bindings/
│       └── SKILL.md
│
├── skill-reflect/                         ← vendored copy of skill-reflect core
│   │   # (vendored copy of skill-reflect/ — see repo root of redth/skill-reflect)
│   ├── SKILL.md
│   ├── assets/
│   ├── references/
│   │   ├── eval-format.md
│   │   ├── friction-rubric.md
│   │   ├── privacy-scrub.md
│   │   ├── provenance-routing.md
│   │   ├── registry-format.md
│   │   ├── reporting.md
│   │   ├── session-sources.md
│   │   └── skill-improvement-taxonomy.md
│   ├── scripts/
│   │   ├── resolve_provenance.py
│   │   ├── scrub.py
│   │   └── stamp_nudge.py
│   └── templates/
│       ├── github-issue.md
│       └── improve-this-skill.md
│
└── skill-reflect-auto/                    ← optional: vendored Copilot CLI automation
        # (vendored copy of skill-reflect-auto/ — see repo root of redth/skill-reflect)
    ├── extension.mjs
    └── extension.json
```

> **Content of vendored skill directories:** The `skill-reflect/` and
> `skill-reflect-auto/` entries above are **exact copies** of those directories from
> the `redth/skill-reflect` repository. They contain no host-specific content; only
> the `skill-reflect.config.json` at the repo root is host-specific. To update the
> vendored copy, run `vendoring/sync_vendor.sh` from the source repo — the config is
> never overwritten.

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

`destination.repo: "dotnet/maui-labs"` hardcodes feedback routing to this repo's issue
tracker. When provenance is resolved, the resolver returns **Confirmed** (Step 3 of
`provenance-routing.md`) — no SKILL.md frontmatter lookup or registry query is needed.

## How the "Improve This Skill" nudge references the vendored skill-reflect

Each host skill's `SKILL.md` should include the standard nudge block from
`skill-reflect/templates/improve-this-skill.md`, with `[skill-name]` filled in for
that skill and `[owner/repo]` set to `dotnet/maui-labs`. Example for
`dotnet-maui-doctor`:

```markdown
<!-- BEGIN skill-reflect nudge -->

## Improve This Skill

**For the agent:** If this skill was used during the session and you or the user
encountered friction, you may offer a brief skill-quality review at a natural stopping
point:

> "This session used **dotnet-maui-doctor**. Want me to capture privacy-safe feedback
> for the MAUI Labs team using `skill-reflect`?"

If the user says **yes**, invoke the `skill-reflect` skill:

    Run skill-reflect. Skill used this session: dotnet-maui-doctor
    (source repo: dotnet/maui-labs).

<!-- END skill-reflect nudge -->
```

The block in each skill's SKILL.md is static — it only nudges; the actual review work
(consent, scrub, artifact, issue filing) is done by `skill-reflect` on explicit user
approval.

## Sync

To bring the vendored copy up to date with a new skill-reflect release:

```sh
cd /path/to/skill-reflect-source
./vendoring/sync_vendor.sh \
  --from /path/to/skill-reflect-source \
  --to   /path/to/maui-labs \
  --with-auto
```

The script never overwrites `skill-reflect.config.json`. After syncing, review the
schema change notes in the skill-reflect release to check whether any new config fields
apply to your setup.
