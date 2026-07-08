---
name: skill-reflect-maintainer
description: >
  Use this skill when a plugin or skill author wants to add or adopt skill-reflect into
  their plugin, keep vendored skill-reflect updated, wire reflection into a skill,
  check my skill-reflect copy, doctor a vendored skill-reflect install, or update
  skill-reflect after an author-approved review.
license: MIT
---

# skill-reflect-maintainer

**Dev-time tooling for plugin authors only. Do not redistribute this skill to end users.**
It vendors and maintains `skill-reflect` inside an author's plugin repository, and it is
**always excluded from reflection**.

This skill is intentionally thin: it orchestrates `tools/adopt.py` and edits author-owned
`SKILL.md` files. Do not re-implement the deterministic adopt/update/doctor engine in the
conversation.

## Flows

### Adopt `skill-reflect` into this plugin

Use when the author asks to add/adopt/vendor `skill-reflect`.
Follow `references/adopt-workflow.md`: choose `--to`, `--scope`, `--destination`, optional
`--with-auto`, then run:

```bash
python3 plugins/skill-reflect-maintainer/tools/adopt.py adopt --to <plugin-dir> --from <redth-skills-checkout> --scope <a,b> --destination <owner/repo>
```

After adoption, append the exact reference block from
`skills/skill-reflect/templates/improve-this-skill.md` to each in-scope author `SKILL.md`.

### Check for updates / doctor

Use when the author asks whether their copy is current or healthy. Follow
`references/update-workflow.md` and run:

```bash
python3 plugins/skill-reflect-maintainer/tools/adopt.py doctor --to <plugin-dir>
```

Only perform a live GitHub check if the author explicitly asks.

### Update `skill-reflect`

Use when the author approves an update. Summarize the `CHANGELOG.md` delta, surface drift,
and run:

```bash
python3 plugins/skill-reflect-maintainer/tools/adopt.py update --to <plugin-dir> --from <redth-skills-checkout>
```

If drift blocks the update, report it. Use `--force` only after explicit author approval.

### Wire reflection into `<skill>`

Use when the author asks to add reflection nudges to a particular skill. Follow
`references/wiring-references.md`: append the exact Improve This Skill block, replace the
placeholder skill identity if needed, and add the skill name to `skill-reflect.config.json`
`scope.skills` plus `.skill-reflect-vendor.json` `scope` when appropriate.

## Reference files

- `references/adopt-workflow.md` — author adoption procedure.
- `references/update-workflow.md` — doctor and manual update procedure.
- `references/wiring-references.md` — how to inject the reference block and scope a skill.
- `references/troubleshooting.md` — exit codes and common recovery steps.
