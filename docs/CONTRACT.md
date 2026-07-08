# skill-reflect — Interface Contract (v1)

This file is the **single source of truth** that every component in this repo must
honor so that independently-authored pieces interlock. If you are building any part
of `skill-reflect`, read this first and do not deviate from the names, paths, and
data shapes defined here without updating this file.

---

## 0. What this project is

`skill-reflect` is a **universal, cross-agent skill** that, at/near the end of a
coding session, helps an agent **self-reflect on which distributed skills it used
and where it hit friction**, then turns that into **structured, PII-safe feedback
for the skill's author** — a local Markdown artifact by default, or a GitHub issue
on explicit second consent.

Two hard constraints, everywhere, no exceptions:
1. **Nothing leaves the user's machine without explicit consent.**
2. **No PII, secrets, credentials, tokens, private URLs, file paths, machine names,
   or verbatim transcript excerpts** ever appear in any artifact. Paraphrase; refer
   to variable/tool names, never their values.

Design shape: **one portable core skill** (works on every agent via explicit or
nudged invocation) **+ a progressive automation layer** (opt-in per-agent hooks).
The hook layer never runs AI and never makes network calls — it only stages a cheap
pointer and nudges; the core skill does the real (model-driven) work, on consent.

---

## 1. Canonical names

| Thing | Canonical name |
|---|---|
| Family / brand | `skill-reflect` |
| Core skill directory | `skill-reflect/` (contains `SKILL.md`, `references/`, `templates/`, `scripts/`) |
| Automation extension (Copilot CLI reference) | `skill-reflect-auto/` — required entry `extension.mjs` (auto-discovered by the CLI); `extension.json` is metadata-only, not read by the runtime |
| Config file (consumer-provided) | `skill-reflect.config.json` |
| Config JSON Schema (this repo) | `skill-reflect.config.schema.json` (repo root) |
| Local feedback artifact dir | `.skill-feedback/` |
| Artifact file name | `.skill-feedback/<YYYY-MM-DD>-<skill-slug>.md` |
| User-level home (markers, registry, throttle state) | `$SKILL_REFLECT_HOME`, default `~/.skill-reflect/` |
| Pending-review marker (automation) | `$SKILL_REFLECT_HOME/pending/<session-id>.json` |
| Throttle state | `$SKILL_REFLECT_HOME/throttle.json` |
| Local registry map (name→repo) | `$SKILL_REFLECT_HOME/registry.json` (or path from config) |

`<skill-slug>` = the skill name lowercased, non-alphanumerics collapsed to `-`.

---

## 2. `skill-reflect.config.json` (schema authority = `skill-reflect.config.schema.json`)

```jsonc
{
  "version": 1,
  "mode": "standalone",                 // "standalone" | "vendored"
  "scope": {
    "skills": [],                        // allowlist (names or globs). [] = all DISTRIBUTED skills
    "excludeSkills": ["skill-reflect", "skill-reflect-auto"]
  },
  "destination": {
    "mode": "ask",                       // "local" | "issue" | "ask"
    "repo": null,                        // "owner/repo" — used in vendored/hardcoded routing
    "registryMapPath": null              // overrides $SKILL_REFLECT_HOME/registry.json
  },
  "nudge": {
    "enabled": true,
    "frictionThreshold": 2,              // min friction signals in a session to stage a marker
    "throttleHours": 12,                 // min hours between nudges
    "neverForSkills": [],
    "neverForRepos": []
  },
  "privacy": {
    "extraScrubPatterns": [],            // extra regexes to redact
    "redactionPreview": true,            // ALWAYS true; cannot be disabled
    "allowTranscriptExcerpts": false     // ALWAYS false
  },
  "eval": {
    "emitFormats": ["skill-creator", "portable"],
    "evalsOutPath": ".skill-feedback/evals"
  },
  "artifactDir": ".skill-feedback"
}
```

Rules:
- `privacy.redactionPreview` is treated as `true` and `privacy.allowTranscriptExcerpts`
  as `false` regardless of what the file says. The schema documents them but code/skill
  must hard-enforce.
- Missing config ⇒ use the defaults above. The skill must work with **no config file**.

---

## 3. Core data shape: `FrictionFinding`

Detection → classification → reporting all pass objects of this shape. Every field is
already-paraphrased and PII-free by the time it exists.

```jsonc
{
  "id": "string",                 // stable hash of {skill, pattern, normalized-summary}; enables dedupe (v2)
  "skill": "string",              // attributed skill name
  "sourceRepo": "owner/repo|null",// resolved via provenance-routing.md; null = unknown
  "severity": "High|Medium|Low|Unknown",
  "confidence": "Confirmed|Likely|Possible",
  "outcome": "Solved|Worked-around|Unresolved",
  "pattern": "advertised-feature-failed|repeated-command-loop|workaround-chain|stale-guidance|unclear-routing|trigger-miss|false-trigger",
  "category": "missing-case|wrong-or-stale-guidance|missing-detail|missing-or-failing-asset|unclear-routing|trigger-problem",
  "summary": "string",            // paraphrased: what the agent was trying to do and where it stumbled
  "evidence": "string",           // paraphrased signal (e.g. 'the advertised --foo flag errored; agent retried 3x then hand-rolled'). NEVER raw values.
  "proposedFix": "string",        // concrete change to the skill (what to add/correct/clarify)
  "proposedEval": { /* see §4 */ }
}
```

`pattern` ⇄ `category` mapping guidance lives in `references/skill-improvement-taxonomy.md`.

---

## 4. Proposed eval — category-to-form mapping (skill-creator interop)

Every finding MUST carry a `proposedEval`. The **form** depends on `category`/`pattern`:

| `category` | `pattern` | Emitted form |
|---|---|---|
| `trigger-problem` | `trigger-miss` | Trigger eval set item `{query, should_trigger: true}` |
| `trigger-problem` | `false-trigger` | Trigger eval set item `{query, should_trigger: false}` |
| All other categories | any | Task eval entry in `evals/evals.json` |

---

**Task eval entry** — inside the skill's `evals/evals.json`
(schema authority: `anthropics/skills` → `skills/skill-creator/references/schemas.md`):
```jsonc
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,                             // INTEGER — unique per eval
      "prompt": "string",                  // realistic task that exercises the fix
      "expected_output": "string",         // brief description of a correct result
      "files": [],                         // optional paths relative to skill root
      "expectations": [                    // FLAT ARRAY OF STRINGS — verifiable natural-language statements
        "The output uses the '--region' flag",
        "The output does not use the deprecated '--deploy-region' flag"
      ]
    }
  ]
}
```

**Trigger eval set** — JSON array file, run with `python scripts/run_eval.py --eval-set <file>`:
```jsonc
[
  { "query": "Publish the image to the registry", "should_trigger": true },
  { "query": "List files in the current directory", "should_trigger": false }
]
```

**Portable form** (our convenience — NOT skill-creator native):
```jsonc
{
  "id": "ct-7e2a1f",          // string finding-id for traceability
  "prompt": "string",
  "must_contain":     ["X"],  // maps 1:1 → "The output contains X"
  "must_not_contain": ["Y"]   // maps 1:1 → "The output does not contain Y"
}
```

Full authoring rules + examples: `skill-reflect/references/eval-format.md`.

---

## 5. Local artifact template (`.skill-feedback/<date>-<slug>.md`)

```markdown
---
generated_by: skill-reflect
schema: 1
date: <YYYY-MM-DD>
skill: <skill-name>
source_repo: <owner/repo|unknown>
sessions_reviewed: <n>
consent: review-only            # becomes "sent:<destination>" after a send
---

# Field feedback for `<skill-name>`

## Summary
<1–3 sentence paraphrased overview. No PII.>

## Findings
### <#> <short title>  ·  <severity> / <confidence> / <outcome>
- **Category:** <category>
- **What happened:** <paraphrased summary>
- **Signal:** <paraphrased evidence>
- **Proposed fix:** <concrete change>
- **Proposed eval:**
  ```json
  { ...portable form... }
  ```

## Privacy
This report was scrubbed of names, paths, secrets, and verbatim excerpts. Values are
paraphrased. Reviewed by the user before creation.

## Routing
Suggested destination: <local | owner/repo issue>. Not sent unless the user approves.
```

---

## 6. GitHub issue template (`skill-reflect/templates/github-issue.md`)

- **Title:** `[<skill>] Field feedback: <short summary>`
- **Body:** the findings (same content as the artifact, PII-safe), each proposed eval
  in a fenced ```json block, and a footer:
  `> Generated by skill-reflect from a real session, with the user's explicit consent. No PII/secrets included.`
- Filed only via `gh issue create` after the **second** consent gate. The repo never
  auto-files. See `references/provenance-routing.md`.

---

## 7. Scrubber contract (`skill-reflect/scripts/scrub.py`)

Deterministic, dependency-light (Python 3 stdlib only). Two uses:

- **CLI:** `python3 scrub.py <infile> [--out <outfile>] [--report] [--fail-on-secret]`
  - Reads text/markdown/json; redacts; writes to `--out` (or stdout).
  - `--report` prints a summary of what categories were redacted (counts, not values).
  - `--fail-on-secret` exits non-zero if a high-entropy/known-token secret remains.
- **Importable:** `scrub_text(s: str) -> tuple[str, list[dict]]` returns
  `(scrubbed_text, findings)` where each finding is `{ "category": str, "count": int }`.

Must detect at minimum: emails, common tokens/keys (AWS, GitHub `ghp_/gho_/ghs_`,
Slack, Google API, PEM blocks, JWTs, bearer tokens), high-entropy strings, absolute
file paths (`/Users/...`, `/home/...`, `C:\...`), machine/user names in paths, and
IP addresses. This is the **deterministic backstop** layered under the model's scrub.

---

## 8. Automation extension contract (`skill-reflect-auto/extension.mjs`)

Copilot CLI reference implementation. Rules:
- Connect via `joinSession` from `@github/copilot-sdk/extension`.
- **No AI. No network.** Only tracking + disk staging + non-blocking nudges.
- Persist everything to `$SKILL_REFLECT_HOME` (extension is reloaded on `/clear`, so
  in-memory state is lost).
- Hooks:
  - `onPreToolUse`: when a `skill` tool runs, open/refresh that skill's "active window".
  - `onPostToolUseFailure` / `onErrorOccurred`: increment the friction counter attributed
    to the currently-active skill window(s).
  - `onSessionEnd`: if a **distributed** skill was used **and** friction ≥
    `nudge.frictionThreshold`, write `$SKILL_REFLECT_HOME/pending/<sessionId>.json`
    (a small marker: session id, skills, counts, timestamp — NO transcript, NO values).
  - `onSessionStart`: if unresolved markers exist and not throttled (`nudge.throttleHours`),
    emit a **non-blocking** `session.log` nudge (+ optional `additionalContext`) offering
    the opt-in review. Only run the review when the user explicitly asks; then
    `session.send({ prompt })` the core skill invocation.
- Respect `nudge.enabled`, `neverForSkills`, `neverForRepos`, and the throttle.
- Marker file shape:
  ```jsonc
  { "sessionId": "…", "endedAt": "ISO8601", "skills": ["a","b"],
    "friction": { "a": 3 }, "reason": "complete|error|abort|timeout|user_exit" }
  ```

**Discovery & registration (verified):** Copilot CLI **auto-discovers** the extension
by scanning for a subdirectory containing **`extension.mjs`** (project
`.github/extensions/<name>/` or the user extensions dir). Hooks/tools are registered
**programmatically** via the session options passed to `joinSession()` — **the CLI does
not read any manifest.** The `extension.json` we ship is **metadata-only** (name,
version, description, declared hooks) for humans/tooling and is **not** consumed by the
CLI runtime; never rely on it for behavior or provenance.

---

## 9. "Distributed skill" definition (attribution scope)

Only reflect on **distributed** skills — those installed from a plugin/marketplace/repo,
i.e. that have resolvable provenance OR live outside the user's own project. Never file
feedback about the user's own in-repo skills unless explicitly scoped in. `skill-reflect`
and `skill-reflect-auto` are always excluded (§2 `excludeSkills`).

---

## 10. Cross-agent tiers (for adapters/)

- **Tier A** (true SessionEnd + transcript): Copilot CLI (reference), Claude Code
  (`SessionEnd` + `transcript_path` + `InstructionsLoaded`), Gemini CLI (`SessionEnd`
  + `transcript_path`). Full stage-at-end → nudge-at-start.
- **Tier B** (turn/agent-end only): opencode (`session.idle`), Amp (`agent.end`).
  Throttled staging on turn end + dedupe.
- **Tier C** (no hooks): Cursor, Copilot cloud agent, Codex CLI, Windsurf. Portable
  skill via explicit invocation + a static `AGENTS.md`/rules nudge line only.

Every adapter stages the SAME marker shape (§8) into `$SKILL_REFLECT_HOME/pending/`
and defers all real work to the portable core skill.
