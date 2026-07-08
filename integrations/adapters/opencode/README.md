# skill-reflect adapter — opencode (Tier B)

Opt-in, local-only plugin that stages a pending-review marker on each
`session.idle` event (turn-end) when a distributed skill was used and friction
crossed the threshold.

Because opencode has no true process-exit hook, this adapter uses:
- **Throttle**: only stages once per session per 5 minutes.
- **Dedupe**: if a marker for this session already exists, updates counts
  in-place rather than creating duplicates.

No AI, no network calls.  The marker is a minimal JSON pointer.

> ⚠️ **opencode plugin API details are not fully public at time of writing.**
> Items marked `# ASSUMPTION:` in `plugin.mjs` must be verified against
> opencode's plugin documentation before deployment.

---

## Assumptions (verify before use)

| Item | Assumption | Where to verify |
|---|---|---|
| Plugin export shape | `export default { name, version, setup(api) }` | opencode plugin docs |
| Event name | `session.idle` fires between agent turns | opencode event reference |
| Event payload | `{ sessionId, workingDirectory, messages }` | opencode event API |
| `messages` format | Array of `{ role, content: [...blocks] }` with tool_use/tool_result blocks | opencode session API |
| Config registration | `opencode.config.mjs` `plugins` array or `.opencode/plugins/` dir | opencode config docs |

---

## Install

### 1. Register the plugin with opencode

**Option A — config file** (if opencode supports a `plugins` array in
`opencode.config.mjs`):

```js
// opencode.config.mjs
export default {
  plugins: [
    "/YOUR/PATH/skill-reflect/adapters/opencode/plugin.mjs"
  ]
};
```

**Option B — plugins directory** (if opencode discovers plugins from
`~/.opencode/plugins/` or `.opencode/plugins/`):

```sh
mkdir -p ~/.opencode/plugins
ln -s /YOUR/PATH/skill-reflect/adapters/opencode/plugin.mjs \
      ~/.opencode/plugins/skill-reflect.mjs
```

> Verify the correct registration mechanism with opencode documentation.

### 2. Verify Node.js ESM support

```sh
node --version   # 18+ recommended for ESM + fs/os/path built-ins
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

Since `session.idle` fires on turn-end (not true session exit):

- A marker may be staged mid-session and then **updated** on later turns as
  more friction accumulates.  The `endedAt` timestamp reflects the last update.
- The throttle (default 5-minute cooldown per session) prevents excessive
  disk writes.
- Deduplication merges the new friction counts with any existing marker for
  the same session id, taking the higher count per skill.

---

## Privacy

The marker contains **only**: session ID, ISO timestamp, distributed skill
names, per-skill friction counts, reason `"complete"`.  No conversation
content, no file paths, no secrets.  Nothing is sent anywhere without your
explicit approval via the `skill-reflect` core skill.

---

## Opting out

Remove the plugin registration from `opencode.config.mjs` (or remove the
symlink/file from the plugins directory), or set
`"nudge": {"enabled": false}` in `skill-reflect.config.json`.
