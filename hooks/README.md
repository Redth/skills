# skill-reflect plugin hooks (Claude Code)

These hooks are wired **automatically** when the `skill-reflect` plugin is
installed from this marketplace. They are the auto path for the same behavior
documented (for manual installs) in
[`../integrations/adapters/claude-code/`](../integrations/adapters/claude-code/).

| Hook | Script | Purpose |
|---|---|---|
| `SessionEnd` | [`stage_pending.py`](./stage_pending.py) | Reads the session transcript, detects distributed-skill usage + friction, and — only if a distributed skill crossed the friction threshold — writes `~/.skill-reflect/pending/<session-id>.json` (a tiny CONTRACT §8 marker). |
| `SessionStart` | [`nudge_start.py`](./nudge_start.py) | If unresolved markers exist and the nudge isn't throttled, surfaces a one-line, non-blocking offer to review last session's friction. |

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
