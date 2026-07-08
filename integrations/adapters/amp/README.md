# skill-reflect adapter — Amp (Tier B)

Opt-in, local-only adapter that stages a pending-review marker on each
`agent.end` event when a distributed skill was used and friction crossed
the threshold.  Optionally emits a non-blocking nudge via an `agent.end`
continue message.

Because Amp's `agent.end` hook fires at agent/turn-end (not true process-exit),
this adapter uses the same **throttle + dedupe** logic as the opencode adapter.

No AI, no network calls.  The marker is a minimal JSON pointer; the actual
reflection is done by the `skill-reflect` core skill when **you** ask for it.

> ⚠️ **Amp hook API details are not fully public at time of writing.**
> Items marked `# ASSUMPTION:` in `adapter.mjs` must be verified against
> Amp's extension/plugin documentation before deployment.

---

## What this does

On every `agent.end` event:

1. Parses the conversation history for distributed-skill usage and friction.
2. If qualifying (skill used + friction ≥ threshold) and not throttled:
   - Writes / updates `~/.skill-reflect/pending/<session-id>.json`.
   - Optionally returns a `continue` message as a non-blocking nudge.

---

## Assumptions (verify before use)

| Item | Assumption | Where to verify |
|---|---|---|
| Hook event name | `agent.end` | Amp extension docs |
| Plugin export shape | `export default { name, version, hooks: { "agent.end": fn } }` | Amp plugin API |
| Hook context fields | `{ sessionId, workingDirectory, messages }` | Amp agent.end payload docs |
| `messages` format | Array of `{ role, content: [...blocks] }` with tool_use/tool_result | Amp message format docs |
| Nudge return shape | `{ continue: "text" }` to emit a follow-up | Amp agent.end return API |
| Plugin config location | `.amp/plugins/` or `amp.config.mjs` | Amp config docs |

---

## Install

### 1. Register the plugin with Amp

**Option A — config file** (if Amp supports a plugins list):

```js
// amp.config.mjs  (# ASSUMPTION: verify file name)
export default {
  plugins: [
    "/YOUR/PATH/skill-reflect/adapters/amp/adapter.mjs"
  ]
};
```

**Option B — plugins directory** (if Amp auto-discovers plugins):

```sh
mkdir -p ~/.amp/plugins
ln -s /YOUR/PATH/skill-reflect/adapters/amp/adapter.mjs \
      ~/.amp/plugins/skill-reflect.mjs
```

> Verify the correct registration mechanism with Amp documentation.

### 2. Verify Node.js ESM support

```sh
node --version   # 18+ recommended
```

### 3. (Optional) configure thresholds

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

## Tier B behaviour

- A marker may be staged mid-run and updated on later `agent.end` events;
  deduplication merges friction counts, taking the higher per-skill value.
- The 5-minute per-session throttle prevents excessive disk writes within a
  single run.
- The global nudge throttle (`throttleHours`, default 12 h) prevents
  repeated nudge messages across sessions.

---

## Privacy

The marker contains **only**: session ID, ISO timestamp, distributed skill
names, per-skill friction counts, reason `"complete"`.  No conversation
content, no file paths, no secrets.  Nothing is sent anywhere without your
explicit approval via the `skill-reflect` core skill.

---

## Opting out

Remove the plugin registration or set `"nudge": {"enabled": false}` in
`skill-reflect.config.json`.
