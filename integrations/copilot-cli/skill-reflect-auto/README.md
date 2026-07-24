# skill-reflect-auto

Copilot CLI automation extension for the [`skill-reflect`](../../../skills/skill-reflect/) feedback family.

---

## What it does

`skill-reflect-auto` runs as a silent background extension in every Copilot CLI session. It does two things:

### 1. Stage at session end

While the session runs, the extension watches for invocations of the `skill` tool and
attributes tool/model failures only to the latest skill candidate within six subsequent
tool calls and ten minutes. When the session ends, if a candidate accumulated friction at
or above `nudge.frictionThreshold`, the extension writes a compact JSON marker to disk.
The core review resolves provenance before describing a candidate as distributed:

```
$SKILL_REFLECT_HOME/pending/<session-id>.json
```

**Marker shape** (CONTRACT §8 — no transcript, no values, no PII):

```json
{
  "sessionId": "...",
  "endedAt": "2024-01-15T10:30:00.000Z",
  "skills": ["my-skill"],
  "friction": { "my-skill": 3 },
  "reason": "complete",
  "candidate": true
}
```

### 2. Nudge at next start

At the start of the next session, if unresolved markers exist and the nudge has not been throttled (see `nudge.throttleHours`), the extension:

- Logs a **non-blocking** info message to the timeline listing the skills with pending reviews.
- Injects a short `additionalContext` note so the agent knows a review is available **if the user asks**.

**The review is never started automatically.** It is only launched after the user explicitly requests it (e.g. "run skill-reflect"). The review itself is done by the `skill-reflect` core skill, not by this extension.

---

## Privacy posture

| What | Detail |
|---|---|
| AI | **None** — this extension runs no model calls |
| Network | **None** — no outbound requests |
| Storage | Disk only, under `$SKILL_REFLECT_HOME` |
| Marker content | Opaque session ID, timestamp, unverified candidate names, friction counts, end reason, candidate flag |
| PII | **Never** — no transcript excerpts, no file paths, no user data, no values |

All real analysis (provenance, paraphrasing, scrubbing, and optional artifact generation)
happens in the `skill-reflect` core skill after review authorization.

---

## Installation

The CLI discovers extensions in `.github/extensions/<name>/` (project-scoped) or the user extensions directory (user-scoped).

### Project-scoped (one repo)

```bash
cp -r skill-reflect-auto/ /path/to/your-repo/.github/extensions/skill-reflect-auto/
```

The CLI discovers `extension.mjs`; the extension imports `attribution.mjs`, so copy the
whole directory. `extension.json` is metadata-only and is **not** read by the CLI runtime.
Reload with `/clear` or restart the CLI.

### User-scoped (all repos)

Copy the directory into your Copilot CLI user extensions folder (typically `~/.config/github-copilot/extensions/`; check your CLI docs for the exact path):

```bash
cp -r skill-reflect-auto/ ~/.config/github-copilot/extensions/skill-reflect-auto/
```

### Verify it loaded

After reloading extensions, check:

```
/extensions list
```

You should see `skill-reflect-auto` with status `loaded`.

---

## Configuration

Create a `skill-reflect.config.json` anywhere in your project tree (or at `$SKILL_REFLECT_HOME/skill-reflect.config.json` for a global default). The extension searches upward from the session working directory.

Full schema: [`skill-reflect.config.schema.json`](../../../skill-reflect.config.schema.json). Relevant knobs:

```jsonc
{
  "scope": {
    "skills": [],                   // allowlist (names or globs). [] = all observed candidates
    "excludeSkills": ["skill-reflect", "skill-reflect-auto"]  // always excluded
  },
  "nudge": {
    "enabled": true,                // set false to disable all nudges
    "frictionThreshold": 2,         // min friction signals before staging a marker
    "throttleHours": 12,            // min hours between nudges (0 = always nudge)
    "neverForSkills": [],           // skill names to never nudge about
    "neverForRepos": []             // "owner/repo" strings to suppress nudges in
  }
}
```

Missing config → uses built-in defaults (all non-excluded candidates, threshold 2,
throttle 12 h). Marker candidates remain unverified until core provenance resolution.

---

## Opting out / disabling

| Goal | How |
|---|---|
| Disable entirely | Remove the extension directory, or set `"nudge": { "enabled": false }` in config |
| Never nudge about a specific skill | Add its name to `nudge.neverForSkills` |
| Never nudge in a specific repo | Add `"owner/repo"` to `nudge.neverForRepos` |
| Increase throttle | Raise `nudge.throttleHours` (e.g. `168` = one week) |
| Suppress all throttled nudges | Set `nudge.throttleHours` to a very large value |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SKILL_REFLECT_HOME` | `~/.skill-reflect/` | Root directory for markers, throttle state, and home config |

---

## How the review works (the full flow)

```
Session N ends
  └─ onSessionEnd: friction ≥ threshold?
       └─ yes → write $SKILL_REFLECT_HOME/pending/<id>.json

Session N+1 starts
  └─ onSessionStart: pending markers + not throttled?
       └─ yes → log nudge + inject additionalContext

User says "run skill-reflect"
  └─ onUserPromptSubmitted: trigger detected?
       └─ yes → session.send({prompt: "invoke skill-reflect"})
                  └─ skill-reflect core skill runs
                       └─ reviews markers and returns scrubbed chat findings
                            └─ writes or sends only if separately requested
```

The `skill-reflect` core skill handles all model-driven analysis, scrubbing, optional
artifact creation, and optional GitHub issue filing. This extension only handles cheap
candidate bookkeeping.

---

## Files written to disk

| Path | Written when |
|---|---|
| `$SKILL_REFLECT_HOME/pending/<sessionId>.json` | Session ends with qualifying friction |
| `$SKILL_REFLECT_HOME/throttle.json` | Nudge is emitted (updates `lastNudgeAt`) |

The `pending/` markers are consumed by the core skill after successful chat analysis or
artifact creation. Declined, aborted, and failed reviews leave them pending. The extension
itself never deletes them.
