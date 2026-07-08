# skill-reflect adapter — Gemini CLI (Tier A)

Opt-in, local-only adapter that stages a pending-review marker at session end
and offers a non-blocking nudge at session start.  No AI, no network calls.

> ⚠️ **Gemini CLI hook documentation is not fully public at time of writing.**
> Items marked `# ASSUMPTION:` in the scripts and config snippet must be
> verified against Gemini CLI's own hooks documentation before deployment.

---

## What this does

| Hook | Script | Purpose |
|---|---|---|
| `SessionEnd` | `stage_pending.py` | Reads transcript JSONL, detects skill usage + friction, writes `~/.skill-reflect/pending/<session-id>.json` |
| `SessionStart` | `nudge_start.py` | Prints a one-line opt-in offer if pending markers exist |

Both scripts are **defensive**: every code path is wrapped in `try/except`;
they always exit 0.

---

## Assumptions (verify before use)

| Item | Assumption | Where to verify |
|---|---|---|
| Hook config file | `~/.gemini/settings.json` or equivalent | Gemini CLI docs |
| Hook event key names | `session_end` / `session_start` (snake_case) | Gemini CLI hooks reference |
| Hook config shape | `{"hooks": {"session_end": {"command": "..."}}}` | Gemini CLI hooks reference |
| stdin format | JSON with `session_id`, `transcript_path`, `cwd` | Gemini CLI hook API docs |
| Transcript format | JSONL with Gemini API parts/functionCall format | Gemini CLI transcript docs |

---

## Install

### 1. Note the full path to this adapter directory

```sh
ADAPTER_DIR="$HOME/code/skill-reflect/adapters/gemini-cli"
```

### 2. Add hooks to the Gemini CLI config

Consult Gemini CLI documentation for the correct config file location
(e.g. `~/.gemini/settings.json` or `~/.config/gemini/settings.json`).
Add the hooks section from `settings.snippet.json`, replacing placeholders:

```json
{
  "hooks": {
    "session_end": {
      "command": "python3 /YOUR/PATH/adapters/gemini-cli/stage_pending.py"
    },
    "session_start": {
      "command": "python3 /YOUR/PATH/adapters/gemini-cli/nudge_start.py"
    }
  }
}
```

> If Gemini CLI uses a different event-key format (e.g. `SessionEnd` in
> PascalCase like Claude Code), update the keys accordingly.

### 3. Verify Python 3 is on PATH

```sh
python3 --version   # 3.8+ required; stdlib only
```

### 4. (Optional) configure thresholds

```json
{
  "nudge": {
    "frictionThreshold": 2,
    "throttleHours": 12
  }
}
```

Save as `skill-reflect.config.json` in your project root or
`~/.skill-reflect/skill-reflect.config.json`.

---

## Privacy

The marker contains **only**: session ID, ISO timestamp, distributed skill
names, per-skill friction counts, stop reason.  No transcript content, no
paths, no secrets.  Nothing is sent anywhere without your explicit approval.

---

## Opting out

Remove the hook entries from your Gemini CLI config file, or set
`"nudge": {"enabled": false}` in `skill-reflect.config.json`.
