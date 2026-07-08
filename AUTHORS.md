# Add skill-reflect feedback collection to your plugin

This is the canonical author guide for adopting `skill-reflect` in your own
Claude Code plugin or cross-agent skill bundle.

Two guarantees come first:

1. **Nothing leaves the user's machine without explicit consent.** Feedback is
   reviewed locally first; filing or sending anywhere requires a second approval.
2. **No PII or secrets ever.** Reports must not contain names, emails,
   credentials, tokens, private URLs, file paths, machine names, or verbatim
   transcript excerpts. Values are paraphrased and scrubbed.

By adopting `skill-reflect`, you are adopting a privacy-first feedback loop for
improving skills from real session friction.

## Choose an adoption model

### A. Central install

The end user installs `skill-reflect` once from this marketplace. It can review
any distributed skill and route feedback by provenance.

- **Least author work.** You do not vendor or maintain a copy.
- **Depends on the user having it installed.** Coverage is not guaranteed.
- **Routing depends on provenance.** Your skill metadata or registry entries need
  to resolve cleanly.

### B. Vendored copy — recommended baseline

You bundle a copy inside your plugin, pre-scoped to your skills, with routing
hardcoded to your repository.

- **Reliable coverage.** Users who install your plugin get the feedback loop.
- **Best default for this workstream.** It is the vendoring-first path defined by
  `docs/CONTRACT.md` §11.
- **You own maintenance.** Updates are manual and author-approved.

### C. Dependency declaration

Where a host supports plugin dependencies, you may declare `skill-reflect` as a
dependency instead of vendoring it.

- **Best-effort only.** Dependency support is not universal across agents/hosts.
- **Use when available, but do not rely on it as the only path.** Vendoring is the
  reliable baseline.

## Vendoring, the easy way

Install the **`skill-reflect`** plugin in your development environment; it
bundles the dev-time **`skill-reflect-maintainer`** skill. The `adopt` engine
copies only the review skill and its hooks into your plugin, so the maintainer
skill and its update-check hook never reach your end users. Then ask your
agent:

> adopt skill-reflect into this plugin

The maintainer skill is a conversational wrapper over the deterministic engine:

```text
skills/skill-reflect-maintainer/scripts/adopt.py
```

For adoption it runs `adopt`, then:

- copies `skills/skill-reflect/` into your plugin;
- copies `hooks/stage_pending.py` and `hooks/nudge_start.py`;
- merges the `SessionStart` / `SessionEnd` entries into your `hooks/hooks.json`
  without clobbering your other hooks;
- writes `.skill-reflect-vendor.json` with the upstream version, source ref,
  content hash, scope, and destination repo;
- scaffolds `skill-reflect.config.json` in vendored mode if absent;
- appends the **Improve This Skill** reference block to each in-scope `SKILL.md`.

Equivalent manual CLI:

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py adopt \
  --to <your-plugin> \
  --from <redth-skills-checkout> \
  --scope skill-a,skill-b \
  --destination you/your-repo
```

The no-frills fallback is `vendoring/sync_vendor.sh`. It copies the current
layout and preserves your config, but it does not write the pin, detect drift, or
merge hooks intelligently.

## Keeping the copy up to date

Updates are **manual in v1**. There is **no CI requirement**, no telemetry, and
no scheduled network check.

The `skill-reflect` plugin includes a `SessionStart` update-check hook. When you
work inside a plugin that contains `.skill-reflect-vendor.json`, it walks up from
the current working directory, reads that pin, and compares `upstreamVersion` to
the locally installed plugin's `skills/skill-reflect/VERSION`.

That check is local-only:

- **no network**;
- **no AI**;
- **no auto-update**;
- a throttled nudge only when your vendored copy is behind.

When nudged, ask:

> update skill-reflect

The maintainer runs:

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py update --to <your-plugin>
```

`update` re-syncs the skill and hook scripts, preserves your
`skill-reflect.config.json`, preserves your own skill nudge wording, re-merges
`hooks.json`, and re-stamps `.skill-reflect-vendor.json`. It refuses with exit
`3` if local drift is detected unless you explicitly force it. Review the diff
and approve it like any other source change.

Use `CHANGELOG.md` as the human record of what changed between core skill
versions.

For health checks, the engine also provides:

```sh
python3 skills/skill-reflect-maintainer/scripts/adopt.py doctor --to <your-plugin>
```

Per `docs/CONTRACT.md` §11.3, `doctor` exits `0` when healthy and current, `10`
when an update is available, `11` on drift, and `12` for config/hooks/nudge
problems.

## Referencing reflection in your other skills

Each skill you want covered should include the reference block from:

```text
skills/skill-reflect/templates/improve-this-skill.md
```

The block is static guidance for the agent. It offers a review only after
friction and only with user consent; the actual collection still happens inside
`skill-reflect`.

To add another skill later, either:

1. add the skill name to `skill-reflect.config.json` under `scope.skills` and
   append the Improve This Skill block to that skill's `SKILL.md`; or
2. ask the maintainer skill: `wire reflection into <skill>`.

## Won't this double-nudge my users?

No. `docs/CONTRACT.md` §11.6 defines the dedupe behavior. If a user has both a
central install and your vendored copy active, review nudges dedupe by skill name
at the marker level.

The maintainer update-check is different: it is author-only, keyed per
`.skill-reflect-vendor.json` pin, and exists only to tell you when your vendored
copy is behind. It is not an end-user feedback nudge.

## Checklist

- [ ] Choose vendored mode unless you have a strong reason not to.
- [ ] Install the `skill-reflect` plugin (it bundles the `skill-reflect-maintainer` skill) in your author/dev environment.
- [ ] Run `adopt` with your plugin path, skill scope, and destination repo.
- [ ] Review `.skill-reflect-vendor.json`, `skill-reflect.config.json`, hooks, and
      the inserted Improve This Skill blocks.
- [ ] Confirm `adopt` vendored only the review skill + hooks (the maintainer skill and update-check hook stay in your dev plugin).
- [ ] On update nudges, run `update`, read `CHANGELOG.md`, review the diff, and
      approve manually.

Deep reference: [`vendoring/vendor.md`](vendoring/vendor.md). Binding spec:
[`docs/CONTRACT.md` §11](docs/CONTRACT.md#adoption--maintenance-author-side).
