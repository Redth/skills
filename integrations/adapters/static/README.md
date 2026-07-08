# skill-reflect adapter — Static / Tier C

Agents with no hook system — **Cursor, Copilot cloud agent, Codex CLI,
Windsurf** — cannot stage markers automatically.  Instead they rely on two
lightweight mechanisms:

1. **A static nudge line** in `AGENTS.md` / rules files (already installed by
   M6 — see `AGENTS.md.snippet`).
2. **Explicit invocation** of the `skill-reflect` skill at session end, on
   request.

No automation.  No markers.  The core skill works purely from the visible
conversation when run on these hosts.

---

## How Tier C works

### The static AGENTS.md nudge line

Add the contents of `AGENTS.md.snippet` to the agent's instruction file:

| Agent | Instruction file location |
|---|---|
| Cursor | `.cursorrules` or `.cursor/rules/*.mdc` |
| Windsurf | `.windsurfrules` |
| Codex CLI | `AGENTS.md` in project root |
| Copilot cloud agent | `AGENTS.md` in project root (or `.github/copilot-instructions.md`) |

The snippet tells the agent to **offer** (never auto-run) a `skill-reflect`
review when distributed skills were used and friction was noticeable.

**To add it:**

```sh
cat adapters/static/AGENTS.md.snippet >> AGENTS.md
# or append to .cursorrules / .windsurfrules as appropriate
```

> **Do not modify `AGENTS.md.snippet`** — it is owned by M6.

### Explicit invocation

At any time, ask your agent:

> "Run skill-reflect to review the distributed skills used this session."

or:

> "Run skill-reflect."

The core skill (`skill-reflect/SKILL.md`) will walk you through two consent
gates before writing anything.

---

## What the core skill can work with on Tier C hosts

Because there is no transcript or session store available:

- The skill reflects only on the **visible conversation window**.
- Findings may be fewer and attribution confidence is typically `Possible`
  (no store corroboration).
- The skill will note these limitations in the artifact.

See `skill-reflect/references/session-sources.md §Fallback` for full details.

---

## Upgrading to Tier A/B

If the agent you use gains a hook system:

| Agent gains … | Upgrade to … |
|---|---|
| `SessionEnd` + transcript path | `adapters/claude-code/` or `adapters/gemini-cli/` pattern |
| Turn-end idle event | `adapters/opencode/` or `adapters/amp/` pattern |

---

## No markers, no problem

The `skill-reflect` core skill runs fine without a pending marker — it simply
skips the marker-reading step and works from conversation context.  Tier C
hosts get full skill reflection; they just need an explicit invocation and have
slightly less context than Tier A/B.
