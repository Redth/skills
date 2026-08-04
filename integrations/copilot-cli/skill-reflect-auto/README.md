# skill-reflect-auto

Copilot CLI automation extension for the [`skill-reflect`](../../../skills/skill-reflect/) feedback family.

---

## What it does

`skill-reflect-auto` runs as a silent background extension in every Copilot CLI session. It does two things:

### 1. Capture durably, then stage at session end

While the session runs, the extension listens to direct `skill.invoked`, tool-completion, and
subagent-failure events, plus model/tool/system error hooks. It attributes value-free signals
only to the latest skill candidate within six subsequent tool calls and ten minutes. After an
in-scope skill is observed, each relevant state change is atomically snapshotted so extension
reload does not erase attribution; unrelated sessions create no journal:

```
$SKILL_REFLECT_HOME/journal/<session-id>.json
```

The journal contains skill names, counts by signal category, timestamps, and bounded opaque
correlation hashes. It never contains tool names, argument/result values, messages, paths, or
error text. A failed call followed by the same tool + argument-key/type shape records a retry;
unsuccessful completions, rejected/denied/timeout statuses, model failures, and subagent failures
are also eligible. Overlapping hook/event representations dedupe by opaque call key.

When the session ends, if a candidate accumulated friction at or above
`nudge.frictionThreshold`, the extension writes a compact JSON marker. The default threshold
remains `2`; broader signals do not turn smooth sessions into markers. The core review resolves
provenance before describing a candidate as distributed:

```
$SKILL_REFLECT_HOME/pending/<session-id>.json
```

If the extension process exits before `onSessionEnd`, the next startup recovers a qualifying
marker from the durable journal only after confirming that the original session process is no
longer live. Recovery uses the capture threshold persisted by the original session, not the next
project's configuration. Recovered markers use `reason: "unknown"`.

**Marker shape** (CONTRACT §8 — no transcript, no values, no PII):

```json
{
  "sessionId": "...",
  "endedAt": "2024-01-15T10:30:00.000Z",
  "skills": ["my-skill"],
  "friction": { "my-skill": 3 },
  "reason": "complete",
  "candidate": true,
  "journalVersion": 1
}
```

### 2. Nudge at next start

At the start of the next different session, if unresolved markers exist and the nudge has not
been throttled (see `nudge.throttleHours`), the extension:

- Logs a **non-blocking** info message to the timeline listing the skills with pending reviews.
- Injects a short, name-free `additionalContext` note so the agent knows a review is available
  **if the user asks**.

A marker for the active resumed session is excluded. It remains pending for the next different
session, avoiding a race where reviewing it while its capture engine is active would recreate it.

**The review is never started automatically.** It is only launched after the user explicitly requests it (e.g. "run skill-reflect"). The review itself is done by the `skill-reflect` core skill, not by this extension.

---

## Privacy posture

| What | Detail |
|---|---|
| AI | **None** — this extension runs no model calls |
| Network | **None** — no outbound requests |
| Storage | Disk only, under `$SKILL_REFLECT_HOME` |
| Journal content | Opaque session ID/correlation hashes, timestamps, candidate names, signal counts, bounded capture state |
| Marker content | Opaque session ID, timestamp, unverified candidate names, friction counts, end reason, candidate/journal flags |
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

The CLI discovers `extension.mjs`; the extension imports `capture.mjs` and
`attribution.mjs`, so copy the whole directory. `extension.json` is metadata-only and is
**not** read by the CLI runtime.
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
  },
  "diagnostics": {
    "enabled": false                // opt-in ephemeral capture lifecycle logs
  }
}
```

Missing config → uses built-in defaults (all non-excluded candidates, threshold 2,
throttle 12 h). Marker candidates remain unverified until core provenance resolution.

### Opt-in diagnostics and E2E check

Set `"diagnostics": {"enabled": true}` (or `SKILL_REFLECT_DIAGNOSTICS=1`) and reload the
extension. Diagnostics are ephemeral and value-free. They distinguish:

```
skill_observed → failure_observed (attributed=true|false)
  → journal_persisted → marker_written → nudge_shown
```

Suppressed markers/nudges report a reason such as `below_threshold`, `throttled`, or
`no_pending_markers`. Diagnostics may name the observed skill, but never log session ids,
arguments, results, paths, error messages, or correlation hashes.

The automated E2E uses the same `CaptureEngine` as the live extension and keeps the threshold
at two:

```bash
node --test attribution.test.mjs capture.test.mjs
```

It simulates skill observation, an unsuccessful timeout, a retry, journal restoration,
marker staging, and next-session nudge display in an isolated temporary home.

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
| `SKILL_REFLECT_DIAGNOSTICS` | unset | `1`/`true` enables ephemeral value-free diagnostics; `0`/`false` overrides config off |

---

## How the review works (the full flow)

```
Session N ends
  ├─ during session: atomically update value-free journal
  └─ onSessionEnd: friction ≥ threshold?
       └─ yes → write $SKILL_REFLECT_HOME/pending/<id>.json

Session N+1 starts
  ├─ recover qualifying journals whose session process exited before onSessionEnd
  └─ pending markers + not throttled?
       └─ yes → log nudge + inject additionalContext

User says "run skill-reflect"
  └─ onUserPromptSubmitted: trigger detected?
       └─ yes → session.send({prompt: "invoke skill-reflect"})
                  └─ skill-reflect core skill runs
                       └─ reads marker-selected journal and returns scrubbed chat findings
                            └─ writes or sends only if separately requested
```

The `skill-reflect` core skill handles all model-driven analysis, scrubbing, optional
artifact creation, and optional GitHub issue filing. This extension only handles cheap
candidate bookkeeping.

---

## Files written to disk

| Path | Written when |
|---|---|
| `$SKILL_REFLECT_HOME/journal/<sessionId>.json` | Relevant state changes after a skill is observed; restored on same-session reload |
| `$SKILL_REFLECT_HOME/pending/<sessionId>.json` | Session ends with qualifying friction |
| `$SKILL_REFLECT_HOME/active/<sessionId>.json` | Session is live; stale entries are ignored when their process exits |
| `$SKILL_REFLECT_HOME/selections/<token>.json` | A nudge's marker-digest-bound selection and allowed skill subsets |
| `$SKILL_REFLECT_HOME/locks/<sessionId>.<pid>.<token>.json` | Short-lived cross-process claim for activation, release, recovery, and consumption |
| `$SKILL_REFLECT_HOME/throttle.json` | Nudge is emitted (updates `lastNudgeAt`) |

For a nudge-entered review, the core reads the exact filtered set through
`scripts/read_journal.py --selection <token>`; explicit broad reviews may use `--all-pending`.
The reader excludes every live session, verifies the selected marker digest, enforces the selected
skill subset, and returns value-free receipts bound to exact marker+journal state rather than
session ids. It does not assume the local Copilot session store exposes `tool_requests`.
Receipt-selected markers and journals are consumed together after successful chat analysis or
artifact creation. Cleanup acquires the same per-session lock used by capture and rechecks liveness
and receipt-bound state before deletion. Declined, aborted, and failed reviews leave evidence
pending. A legacy marker with no journal is returned as `journal: false`, reviewed from visible
context, and remains consumable by receipt. Cleanup removes the journal first so interruption
cannot leave an unreviewable orphan.
