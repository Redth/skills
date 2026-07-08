# Nudge Guide — skill-reflect

How `skill-reflect` surfaces itself to agents across every tier, from full
lifecycle-hook automation down to a single paste-in line.

---

## The three nudge mechanisms

### 1. Extension hook (Tier A / Tier B) — strongest signal

The `skill-reflect-auto` Copilot CLI extension (and per-agent adapters in
`adapters/`) attaches lifecycle hooks that **automatically detect** when a
distributed skill was used and friction occurred, stage a lightweight marker
in `$SKILL_REFLECT_HOME/pending/`, and emit a non-blocking nudge at the next
session start.

- **Tier A** agents (Copilot CLI, Claude Code, Gemini CLI): full
  `SessionEnd` + transcript path available → reliable, single nudge per session.
- **Tier B** agents (opencode, Amp): turn/agent-end only → throttled staging
  with dedupe to avoid duplicate markers.

Marker and throttle state are stored in `$SKILL_REFLECT_HOME/` (default
`~/.skill-reflect/`). The extension performs **no AI work and no network
calls** — it only stages cheap pointers. The portable core skill does all
real work, on consent.

See `skill-reflect-auto/extension.mjs` and `adapters/` for implementations.

---

### 2. Convention block (any agent) — "Improve This Skill"

The **Improve This Skill** block (`skill-reflect/templates/improve-this-skill.md`)
is a copy-paste snippet that any skill author embeds directly in their `SKILL.md`.
Because it lives in the skill file that the agent reads at invocation time, it
reaches **every agent on every platform** — no hooks, no extensions required.

At natural stopping points (task completion, before `/clear`, user asks "what
next?") the agent reads the block, recognises friction if it occurred, and offers:

> "This session used **[skill-name]**. Want me to capture privacy-safe feedback
> for the skill author using `skill-reflect`?"

The block instructs the agent to pass the skill's own identity when invoking
`skill-reflect` (**the nudge carries context**), so attribution in the resulting
artifact is exact.

Authors add the block with one command — see *For skill authors* below.

---

### 3. Static AGENTS.md / rules line (Tier C) — broadest reach

For agents with **no lifecycle hooks at all** — Cursor, Copilot cloud agent,
Codex CLI, Windsurf — the only reliable channel is an instruction in
`AGENTS.md` (or `.cursor/rules`, or equivalent editor rules).

The snippet in `adapters/static/AGENTS.md.snippet` gives the agent a standing
instruction to offer `skill-reflect` at session end when distributed skills
were used, with the same consent-first rules.

---

## Tier mapping

| Tier | Agents | Mechanism(s) |
|------|--------|--------------|
| A | Copilot CLI, Claude Code, Gemini CLI | Extension hook (automatic) + convention block |
| B | opencode, Amp | Extension hook (throttled) + convention block |
| C | Cursor, Copilot cloud, Codex CLI, Windsurf | Convention block + static `AGENTS.md` snippet |
| Any | All | Convention block alone (minimum viable nudge) |

Even on Tier A agents, the convention block and static snippet provide a
belt-and-suspenders fallback if the extension is not installed.

---

## Nudge-fatigue mitigations

Nudge fatigue is a first-class concern. All mechanisms respect these rules:

### Friction threshold

A nudge is only staged/offered when the session crossed a minimum number of
friction signals (`nudge.frictionThreshold`, default `2` in
`skill-reflect.config.json`). Smooth sessions produce no nudge.

### Throttle

The extension enforces a minimum gap between nudges (`nudge.throttleHours`,
default `12` h) tracked in `$SKILL_REFLECT_HOME/throttle.json`. Even if
multiple pending markers exist, only one nudge fires per throttle window.

### Per-skill and per-repo opt-outs

Set `nudge.neverForSkills` or `nudge.neverForRepos` in
`skill-reflect.config.json` to permanently silence nudges for specific skills
or repos:

```jsonc
{
  "nudge": {
    "neverForSkills": ["my-internal-skill"],
    "neverForRepos": ["my-org/my-private-repo"]
  }
}
```

### Always non-blocking

Every nudge is an **offer in a log message or inline suggestion** — never an
interrupt, never a forced confirmation dialog. The agent continues normally
if the user ignores it.

### Always consent-first

No review runs, no artifact is created, and nothing leaves the machine without
**explicit user consent** at each step. Declining once doesn't silence the
skill permanently (unless `neverForSkills` is set).

---

## For skill authors

### Why add the Improve This Skill block?

Embedding the block in your `SKILL.md` is the lowest-friction way to get
quality feedback from real-world usage. It reaches every agent without
requiring users to install any extension, and it attributes findings directly
to your skill so you get actionable, targeted feedback.

### Adding the block with `stamp_nudge.py`

The script at `skill-reflect/scripts/stamp_nudge.py` inserts or updates the
block idempotently using stable HTML-comment markers — safe to run repeatedly.

```sh
# Add (or refresh) the block in your skill file
python3 /path/to/skill-reflect/skill-reflect/scripts/stamp_nudge.py path/to/your/SKILL.md

# Verify it was added
python3 .../stamp_nudge.py path/to/your/SKILL.md --check   # exits 0 if present

# Remove it
python3 .../stamp_nudge.py path/to/your/SKILL.md --remove
```

The block is always inserted at the end of the file, separated by a blank
line. Running the command again after the block is already present updates it
in place without duplicating content.

### What to customise

After stamping, replace the `[skill-name]` and `[owner/repo or "unknown"]`
placeholders in the block with your skill's actual name and source repository
so the agent can pass exact attribution to `skill-reflect`.

### Keeping the block current

If the template (`improve-this-skill.md`) is updated in a new release of
`skill-reflect`, re-run `stamp_nudge.py` on your `SKILL.md` to pull in the
latest wording. The idempotent replace ensures only one copy of the block
ever exists in your file.
