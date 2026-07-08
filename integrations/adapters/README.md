# skill-reflect — Adapters

This directory contains per-agent automation adapters for `skill-reflect`.
All adapters stage the **same CONTRACT §8 pending-marker** into the same
`$SKILL_REFLECT_HOME/pending/` directory so the portable core skill can
consume them uniformly, regardless of which agent produced them.

**Hard invariants (every adapter, no exceptions):**
- 🚫 No AI calls, no network calls — adapters only stage a local JSON pointer.
- 🚫 No transcript content, PII, paths, or values in the marker.
- ✅ `skill-reflect` and `skill-reflect-auto` are always excluded from
  "distributed skills" tracking (CONTRACT §9).
- ✅ The marker is the same shape everywhere (see §Marker shape below).
- ✅ The core skill does all real work — on **explicit user consent only**.

---

## Capability tier matrix

| Agent | Adapter | Tier | Hook(s) | What it stages |
|---|---|---|---|---|
| **Copilot CLI** | `skill-reflect-auto/` (M5 reference) | A | `onSessionEnd` + `onSessionStart` | Full marker at session end; nudge at start |
| **Claude Code** | `adapters/claude-code/` | A | `SessionEnd` + `SessionStart` | Reads transcript JSONL; full marker at end; nudge at start |
| **Gemini CLI** | `adapters/gemini-cli/` | A | `SessionEnd` + `SessionStart` | Reads transcript JSONL; full marker at end; nudge at start |
| **opencode** | `adapters/opencode/` | B | `session.idle` (turn-end) | Throttled + deduped marker per turn |
| **Amp** | `adapters/amp/` | B | `agent.end` | Throttled + deduped marker; optional nudge via `continue` |
| **Cursor** | `adapters/static/` | C | None | Static `AGENTS.md` nudge + explicit invocation only |
| **Copilot cloud agent** | `adapters/static/` | C | None | Static `AGENTS.md` nudge + explicit invocation only |
| **Codex CLI** | `adapters/static/` | C | None | Static `AGENTS.md` nudge + explicit invocation only |
| **Windsurf** | `adapters/static/` | C | None | Static `AGENTS.md` nudge + explicit invocation only |

---

## Tier definitions

### Tier A — true SessionEnd + transcript access

The agent fires a real `SessionEnd` hook with a path to the full session
transcript JSONL.  The adapter reads the transcript, detects distributed-skill
invocations and friction signals, and writes a marker **once** at session end.
A `SessionStart` hook prints a non-blocking nudge at the next session start.

**Result:** most accurate skill attribution and friction counts; marker is
written exactly once per session.

### Tier B — turn/agent-end only

The agent has no true process-exit hook; it fires a turn-end or agent-end
event.  The adapter applies two mitigations:

- **Throttle**: only stages once per session per N minutes to avoid
  excessive writes.
- **Dedupe**: if a marker for this session already exists, updates friction
  counts in-place instead of overwriting.

**Result:** slightly less precise timing and potentially mid-session markers,
but the same marker shape and same core-skill compatibility.

### Tier C — no hooks

The agent has no hook system.  Automation is impossible.  The user relies on:
1. A static nudge line in `AGENTS.md` / rules files — offers a review when
   distributed skills were used.
2. Explicit invocation of `skill-reflect` at session end.

The core skill works from the **visible conversation window** only.
Attribution confidence is typically `Possible` (lower than Tier A/B).

---

## How markers flow into `$SKILL_REFLECT_HOME/pending/`

```
Session ends
    │
    ▼
Adapter (Tier A/B) detects distributed skills + friction
    │
    │  Only if: at least one in-scope distributed skill was used
    │           AND its friction count ≥ frictionThreshold (default 2)
    │
    ▼
Atomic write: $SKILL_REFLECT_HOME/pending/<session-id>.json
```

### Marker shape (CONTRACT §8)

```json
{
  "sessionId": "<string>",
  "endedAt":   "<ISO 8601 timestamp>",
  "skills":    ["skill-a", "skill-b"],
  "friction":  { "skill-a": 3, "skill-b": 1 },
  "reason":    "complete | error | abort | timeout | user_exit"
}
```

**Nothing else.**  No transcript excerpts.  No file paths.  No user data.
No secrets.  The marker is a minimal pointer — cheap to write, privacy-safe
by construction.

---

## How the core skill consumes markers

At review time (user explicitly runs `skill-reflect`):

1. The skill reads all `*.json` files in `$SKILL_REFLECT_HOME/pending/`.
2. It uses the `skills` and `friction` fields to determine scope and
   prioritise which skills to review.
3. After the user consents to a review, the skill examines the session
   transcript or conversation (depending on host tier) for detailed friction
   analysis.
4. It paraphrases findings, runs them through the scrubber, shows a
   redaction preview, and writes a local artifact.
5. On **second explicit consent**, the artifact can be filed as a GitHub issue.
6. Once consumed, the marker files are left in place (they act as an audit
   trail); the user can delete them manually or via a future `--clean` command.

---

## Directory structure

```
adapters/
├── README.md               ← this file
├── claude-code/
│   ├── stage_pending.py    ← SessionEnd hook (reads JSONL, writes marker)
│   ├── nudge_start.py      ← SessionStart hook (prints nudge)
│   ├── settings.snippet.json  ← ~/.claude/settings.json hooks block
│   └── README.md
├── gemini-cli/
│   ├── stage_pending.py    ← SessionEnd hook
│   ├── nudge_start.py      ← SessionStart hook
│   ├── settings.snippet.json  ← Gemini CLI config snippet  [ASSUMPTION]
│   └── README.md
├── opencode/
│   ├── plugin.mjs          ← session.idle plugin (throttle + dedupe)
│   └── README.md
├── amp/
│   ├── adapter.mjs         ← agent.end hook (throttle + dedupe + nudge)
│   └── README.md
└── static/
    ├── AGENTS.md.snippet   ← ⚠️  OWNED BY M6 — DO NOT MODIFY
    └── README.md           ← Tier C story
```

---

## $SKILL_REFLECT_HOME layout

```
~/.skill-reflect/               ← $SKILL_REFLECT_HOME (default)
├── pending/
│   ├── <session-id-1>.json     ← staged markers (written by adapters)
│   └── <session-id-2>.json
├── throttle.json               ← nudge throttle state
├── registry.json               ← skill-name→repo map (optional)
└── skill-reflect.config.json   ← user-level config (optional)
```

Config is also discovered by walking up from the project's working directory,
so a per-project `skill-reflect.config.json` takes precedence over the
home-level one.

---

## Privacy guarantee (repeated for emphasis)

Every adapter is designed so that **a failure to stage a marker is always
safe** — the session continues normally and the user loses nothing except the
optional review prompt.  Adapters never read secrets, never make network calls,
and never write anything outside `$SKILL_REFLECT_HOME/pending/`.

The heavy work — transcript analysis, paraphrasing, scrubbing, artifact
writing — happens **inside the core skill**, gated behind two explicit user
consents.
