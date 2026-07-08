# skill-reflect plugin hooks (Claude Code)

These hooks are wired **automatically** when the `skill-reflect` plugin is
installed from this marketplace. They are the auto path for the same behavior
documented (for manual installs) in
[`../integrations/adapters/claude-code/`](../integrations/adapters/claude-code/).

| Hook | Script | Purpose |
|---|---|---|
| `SessionEnd` | [`stage_pending.py`](./stage_pending.py) | Reads the session transcript, detects distributed-skill usage + friction, and — only if a distributed skill crossed the friction threshold — writes `~/.skill-reflect/pending/<session-id>.json` (a tiny CONTRACT §8 marker). |
| `SessionStart` | [`nudge_start.py`](./nudge_start.py) | If unresolved markers exist and the nudge isn't throttled, surfaces a one-line, non-blocking offer to review last session's friction. |
| `SessionStart` | [`check_updates.py`](./check_updates.py) | **Author-only.** If the current working tree contains a `.skill-reflect-vendor.json` pin, compares its `upstreamVersion` to this plugin's `skills/skill-reflect/VERSION` and prints one throttled nudge when the vendored copy is behind. Silent for everyone else. See [`../AUTHORS.md`](../AUTHORS.md). |

## Guarantees

- **No AI. No network.** The hooks are pure stdlib Python that stage a small local
  marker and print a nudge. All the actual reflection happens later, only when you
  explicitly run `skill-reflect`.
- **Defensive.** Every code path is wrapped in `try/except`; the scripts always exit
  0 and never throw into the host agent.
- **Privacy.** The marker contains only: session id, ISO timestamp, distributed
  skill names, per-skill friction counts, and a stop-reason string. No transcript
  content, paths, or user data. See [`../docs/CONTRACT.md`](../docs/CONTRACT.md) §§7–9.
- **Self-excluding.** `skill-reflect` and `skill-reflect-auto` are always excluded
  from tracking.
- **Author update-check is separate.** `check_updates.py` throttles via
  `~/.skill-reflect/maintainer-throttle.json` (distinct from the review nudge's
  `throttle.json`) and is **not** copied into vendoring authors' plugins by the
  `adopt` engine — only `stage_pending.py` + `nudge_start.py` are vendored.

## Configuration

Drop a `skill-reflect.config.json` in your project root or at
`~/.skill-reflect/skill-reflect.config.json`:

```json
{
  "nudge": {
    "enabled": true,
    "frictionThreshold": 2,
    "throttleHours": 12,
    "neverForSkills": [],
    "neverForRepos": []
  }
}
```

Set `"enabled": false` to turn the hooks off without uninstalling. The full schema
is in [`../skill-reflect.config.schema.json`](../skill-reflect.config.schema.json).

`${CLAUDE_PLUGIN_ROOT}` in [`hooks.json`](./hooks.json) resolves to the installed
plugin directory, so the hooks work regardless of where the plugin is cached.
