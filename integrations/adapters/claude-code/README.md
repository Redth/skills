# skill-reflect adapter — Claude Code (Tier A)

Opt-in, local-only adapter that stages a pending-review candidate marker whenever
nearby friction signals cross the configured threshold after a skill was observed.
No AI, no network calls; the marker is just a cheap
JSON pointer.  The actual reflection is done by the `skill-reflect` core skill
when **you** explicitly ask for it.

---

## What this does

| Hook | Script | Purpose |
|---|---|---|
| `SessionEnd` | `stage_pending.py` | Reads the session transcript JSONL, detects skill usage + friction, writes `~/.skill-reflect/pending/<session-id>.json` if warranted |
| `SessionStart` | `nudge_start.py` | If unresolved markers exist and nudge isn't throttled, prints a one-line opt-in offer |

Both scripts are **defensive**: every code path is wrapped in `try/except`;
they always exit 0 and never throw into Claude Code.

---

## Install

> **Preferred: install the plugin.** If you add this repo as a Claude Code
> plugin marketplace and install the `skill-reflect` plugin, these hooks are
> wired **automatically** (via `hooks/hooks.json`) — skip the manual steps
> below. See the repo root `README.md` for the one-line install.
>
> The manual steps below are only for people who don't want the plugin and
> prefer to reference the scripts directly from a clone.

### 1. Note the full path to your clone of this repo

```sh
# Example — adjust to wherever you cloned Redth/skills:
REPO="$HOME/code/redth-skills"
```

### 2. Merge the hooks into `~/.claude/settings.json`

Open (or create) `~/.claude/settings.json` and add the `hooks` section shown in
`settings.snippet.json`, replacing `<REPO>` with the path from step 1:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 <REPO>/hooks/stage_pending.py"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 <REPO>/hooks/nudge_start.py"
          }
        ]
      }
    ]
  }
}
```

If you already have a `hooks` block, merge the `SessionEnd`/`SessionStart` keys
into it rather than replacing the whole block.

### 3. Verify Python 3 is on PATH

```sh
python3 --version   # 3.8+ required; stdlib only — no pip install needed
```

### 4. (Optional) configure thresholds

Create or edit `skill-reflect.config.json` in your project root or at
`~/.skill-reflect/skill-reflect.config.json`:

```json
{
  "nudge": {
    "frictionThreshold": 2,
    "throttleHours": 12,
    "neverForSkills": [],
    "neverForRepos": []
  }
}
```

See `docs/CONTRACT.md §2` for the full schema.

---

## Privacy guarantees

- Repeated-call signatures contain tool names and argument keys/types only; user prose
  is not scanned. Friction is attributed only to the latest skill candidate within a
  bounded tool window.
- The marker stored in `~/.skill-reflect/pending/` contains **only**:
  opaque session ID, ISO timestamp, unverified skill-candidate names, per-skill
  friction counts, a stop-reason string, and `candidate: true`.
- **No transcript content, no file paths, no user data, no secrets** are
  written into the marker.
- Nothing is sent anywhere.  The marker is read only when you explicitly run
  `skill-reflect`.

---

## How to run a review

When Claude Code shows the nudge at session start, just say:

> "run skill-reflect"

Or invoke it any time:

> "Please run the skill-reflect skill to review last session's friction."

Accepting the nudge authorizes the announced review. Findings return in chat by default;
the skill asks separately only if you request a file or remote send.

---

## Opting out

Remove the `SessionEnd`/`SessionStart` entries from `~/.claude/settings.json`
at any time, or set `"nudge": {"enabled": false}` in `skill-reflect.config.json`.
