# skill-reflect — Interface Contract (v2)

This file is the **single source of truth** that every component in this repo must
honor so that independently-authored pieces interlock. If you are building any part
of `skill-reflect`, read this first and do not deviate from the names, paths, and
data shapes defined here without updating this file.

---

## 0. What this project is

`skill-reflect` is a **universal, cross-agent skill** that reviews how a skill
performed in a coding session and turns observed friction into a structured finding,
an author-side fix, and a regression eval. Explicit review requests return findings
in chat by default. A local Markdown artifact or GitHub issue is produced only when
the user asks for that output.

Hard constraints, everywhere, no exceptions:
1. **No feedback artifact is written and no remote issue is filed without the
   corresponding user authorization.** Model/session processing remains governed by
   the active host; `skill-reflect` itself makes no implicit network call.
2. **No PII, secrets, credentials, tokens, private URLs, file paths, machine names,
   absolute paths, or verbatim transcript excerpts** ever appear in chat findings,
   artifacts, evals, previews, or issue bodies. Paraphrase; refer to variable/tool
   names, never their runtime values.
3. **Strict outputs have no domain leakage.** Do not reveal product/app/brand names,
   internal project names, the type or purpose of the app, or its specific
   functionality. Recast reproduction details as an invented, analogous scenario.
   A `technical-local` review may retain bounded implementation detail only for a
   user-confirmed local skill, only after per-run opt-in, and only in local output.
   Such output is never remotely sendable.

Design shape: **one portable core skill** (works on every agent via explicit or
nudged invocation) **+ a progressive automation layer** (opt-in per-agent hooks).
The hook layer never runs AI and never makes network calls — it only stages a cheap
local candidate marker and nudges. Enabling the hook authorizes that minimal local
metadata processing; the core skill does the real model-driven review only after
review authorization.

---

## 1. Canonical names

| Thing | Canonical name |
|---|---|
| Family / brand | `skill-reflect` |
| Core skill directory | `skill-reflect/` (contains `SKILL.md`, `references/`, `templates/`, `scripts/`) |
| Automation extension (Copilot CLI reference) | `skill-reflect-auto/` — required `extension.mjs` entry plus imported sibling `attribution.mjs`; `extension.json` is metadata-only, not read by the runtime |
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
    "skills": [],                        // allowlist. [] = all observed candidates; provenance checked later
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
    "extraScrubPatterns": [],            // extra regexes to redact (category "custom")
    "redactTerms": [],                   // literal product/app/project names to redact ("domain-term")
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

## 2a. Review modes and authorization

### Metadata preflight

Before reading session evidence, perform a metadata-only preflight and show a short
notice with:

- what `skill-reflect` does and its version/install scope;
- the target skill, ownership/install scope, provenance source, and confidence;
- the session source and selected output mode; and
- what will not happen (for example, no file or remote issue in analysis mode).

Do not ask the user to resolve unknown provenance unless remote sending is requested.
Never show an absolute installation path.

### Output modes

| Mode | Entry condition | Output |
|---|---|---|
| `analysis` | Default for an explicit request to analyze session skill performance | Scrubbed findings in chat only; no artifact, routing prompt, or remote call |
| `artifact` | Explicit `save` / `capture` / `create a report` intent, or accepted follow-up | Local Markdown artifact after summary-first preview |
| `remote` | Explicit intent to send/file feedback | Strict artifact plus exact outbound preview and destination-specific send authorization |

### Authorization

Use these authorization terms consistently:

1. **Review authorization** permits reading the announced session evidence.
   - An explicit request about how a named skill performed in a stated session is
     authorization after the short scope notice; do not ask the same yes/no question again.
   - A passive nudge or ambiguous request must ask once.
   - An accepted nudge passes authorization into the core skill.
   - Any expansion to another skill, session, or history requires authorization.
2. **Local-write authorization** permits one artifact write to the announced path.
   An explicit save/capture request counts; otherwise ask after showing the summary preview.
3. **Remote-send authorization** is always fresh, explicit, and scoped to the exact
   destination and exact scrubbed body. A content or destination change invalidates it.

A static request to inspect or improve a `SKILL.md` is not a session-performance review
and must route to skill-authoring/training tooling instead.

### Detail levels

`strict` is the default and applies full domain abstraction. `technical-local` is
available only when all conditions hold:

1. The target is user-confirmed as local/user-owned.
2. The user opts in for this run.
3. The output remains chat-only or a local artifact.
4. PII/secret/absolute-path/private-URL/transcript-excerpt rules remain enforced.
5. Any later remote request regenerates a separate strict artifact and obtains new
   remote-send authorization.

Technical-local output may contain repository-relative paths, line ranges, symbols,
API/flag names, CI job names, scope boundaries, and short skill-source excerpts.
It must be marked `remote_eligible: false`.

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
  "pattern": "advertised-feature-failed|repeated-command-loop|workaround-chain|stale-guidance|scope-boundary-blind-spot|unclear-routing|trigger-miss|false-trigger",
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
schema: 2
date: <YYYY-MM-DD>
skill: <skill-name>
source_repo: <owner/repo|unknown>
install_scope: <project|user|vendored|unknown>
provenance_source: <frontmatter|manifest|marketplace|vendored|registry|unknown>
provenance_confidence: <Confirmed|Likely|Possible|None>
sessions_reviewed: <n>
review_mode: artifact
detail_level: <strict|technical-local>
remote_eligible: <true|false>
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
This report was scrubbed of names, paths, secrets, product/domain specifics, and
verbatim excerpts. Values are paraphrased and any reproduction details are recast as
an invented, analogous scenario. Reviewed by the user before creation.

## Routing
Suggested destination: <local | owner/repo issue>. Not sent unless the user approves.
```

---

## 6. GitHub issue template (`skill-reflect/templates/github-issue.md`)

- **Title:** `[<skill>] Field feedback: <short summary>`
- **Body:** the findings (same content as the artifact, PII-safe), each proposed eval
  in a fenced ```json block, and a footer:
  `> Generated by skill-reflect from a real session with explicit remote-send authorization. No PII/secrets included.`
- Filed only via `gh issue create` after the exact strict body is shown and the user
  grants destination-specific remote-send authorization. A technical-local artifact
  must never be used as the issue body. See `references/provenance-routing.md`.

---

## 7. Scrubber contract (`skill-reflect/scripts/scrub.py`)

Deterministic, dependency-light (Python 3 stdlib only). Two uses:

- **CLI:** `python3 scrub.py <infile|-> [--out <outfile>] [--report] [--fail-on-secret] [--term TERM ...] [--terms-file FILE] [--pattern REGEX ...]`
  - Reads text/markdown/json from a file, or stdin when `<infile>` is `-`; redacts;
    writes to `--out` (or stdout).
  - `--report` prints a summary of what categories were redacted (counts, not values).
  - `--fail-on-secret` exits non-zero before emitting or writing any output if a
    high-entropy/known-token secret was detected.
  - `--term` / `--terms-file` redact literal confidential terms (product/app/project
    names, codewords) as `domain-term`; `--pattern` redacts extra regexes as `custom`.
    Populate these from config `privacy.redactTerms` and `privacy.extraScrubPatterns`.
- **Importable:** `scrub_text(s, extra_terms=None, extra_patterns=None) -> tuple[str, list[dict]]`
  returns `(scrubbed_text, findings)` where each finding is `{ "category": str, "count": int }`.

Must detect at minimum: emails, common tokens/keys (AWS, GitHub `ghp_/gho_/ghs_`,
Slack, Google API, PEM blocks, JWTs, bearer tokens), high-entropy strings, absolute
file paths (`/Users/...`, `/home/...`, `C:\...`), machine/user names in paths, and
IP addresses, plus any configured `domain-term`/`custom` values. This is the
**deterministic backstop** layered under the model's scrub. The `domain-term`
denylist is a backstop for domain/product leakage — the model's semantic
abstraction (CONTRACT §0.3) remains the primary defense, since product names and
implementation details are open-ended and cannot be fully enumerated.

---

## 8. Automation extension contract (`skill-reflect-auto/extension.mjs`)

Copilot CLI reference implementation. Rules:
- Connect via `joinSession` from `@github/copilot-sdk/extension`.
- **No AI. No network.** Only tracking + disk staging + non-blocking nudges.
- Persist everything to `$SKILL_REFLECT_HOME` (extension is reloaded on `/clear`, so
  in-memory state is lost).
- Hooks:
  - `onPreToolUse`: count every tool call; when a `skill` tool runs, make it the latest
    attribution candidate.
  - `onPostToolUseFailure` / `onErrorOccurred`: increment the friction counter attributed
    only to that latest candidate within six subsequent tool calls and ten minutes.
  - `onSessionEnd`: if an in-scope skill candidate was used **and** friction ≥
    `nudge.frictionThreshold`, write `$SKILL_REFLECT_HOME/pending/<sessionId>.json`
    (a small candidate marker: session id, skills, counts, timestamp — NO transcript,
    NO values).
  - `onSessionStart`: if unresolved markers exist and not throttled (`nudge.throttleHours`),
    emit a **non-blocking** `session.log` nudge (+ optional `additionalContext`) offering
    the opt-in review. Only run the review when the user explicitly asks; then
    `session.send({ prompt })` the core skill invocation.
- Respect `nudge.enabled`, `neverForSkills`, `neverForRepos`, and the throttle.
- Empty `scope.skills` means "track all observed non-excluded candidates," not "proven
  distributed." Core provenance resolution decides whether a candidate is distributed.
- Transcript-backed adapters may form repeated-call signatures from tool name and argument
  keys/types only. They must not include argument values or scan user prose for corrections
  before review authorization.
- Marker file shape:
  ```jsonc
  { "sessionId": "…", "endedAt": "ISO8601", "skills": ["a","b"],
    "friction": { "a": 3 }, "reason": "complete|error|abort|timeout|user_exit",
    "candidate": true }
  ```
- Legacy markers without `candidate` are also unverified candidates.
- Unsafe/non-filename session identifiers are replaced with a deterministic opaque hash before
  they enter marker content or filenames.
- After scrubbed analysis is successfully delivered or an artifact is successfully written,
  the core skill consumes matching reviewed markers with `scripts/consume_pending.py`.
  Declined, aborted, or failed reviews leave markers pending. Session ids remain opaque local
  control-plane state and never enter user-facing output.

**Discovery & registration (verified):** Copilot CLI **auto-discovers** the extension
by scanning for a subdirectory containing **`extension.mjs`** (project
`.github/extensions/<name>/` or the user extensions dir). Hooks/tools are registered
**programmatically** via the session options passed to `joinSession()` — **the CLI does
not read any manifest.** The `extension.json` we ship is **metadata-only** (name,
version, description, declared hooks) for humans/tooling and is **not** consumed by the
CLI runtime; never rely on it for behavior or provenance.

---

## 9. "Distributed skill" definition (attribution scope)

Automatic nudges target **distributed** skill candidates — skills installed from a
plugin/marketplace/repo or living outside the user's project. The core skill may also
review a user-owned/local skill when the user explicitly names it. Local reviews default
to strict analysis; `technical-local` requires the per-run opt-in in §2a.

Remote sending requires strict output and provenance confidence of at least `Likely`,
regardless of ownership. `skill-reflect` and `skill-reflect-auto` are always excluded
(§2 `excludeSkills`).

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

---

## 11. Adoption & maintenance (author-side)

This section governs the **author-adoption** workstream: how a skill/plugin author
**vendors** `skill-reflect` into their own plugin and **keeps that copy up to date**.
Every component in this workstream binds to the names, paths, shapes, and exit codes
here. User-chosen constraints for v1: **vendoring-first**, a **maintainer skill +
SessionStart nudge** (both bundled in the single `skill-reflect` plugin),
**manual (author-approved) updates**, and **no CI**.

### 11.1 Versioning anchor (the thing "check for updates" compares against)
- `skills/skill-reflect/VERSION` — a single semver line (e.g. `1.0.0`). The canonical
  version of the core skill; bump when the core skill changes.
- `CHANGELOG.md` (repo root) — Keep-a-Changelog format, newest first, one section per
  released core-skill version.
- The `skill-reflect` plugin bundles both the core skill and the maintainer skill, so
  `skills/skill-reflect/VERSION` is the single source of truth. The installed plugin's own
  `skills/skill-reflect/VERSION` is the **local** reference the update-check compares a
  vendored pin against, so the check needs **no network**.

### 11.2 Vendor pin file — `.skill-reflect-vendor.json`
Written into the author's plugin at the parent of the vendored skill dir. Shape:
```jsonc
{
  "schema": 1,
  "upstreamVersion": "1.0.0",          // skills/skill-reflect/VERSION at vendor time
  "sourceRepo": "Redth/skills",
  "sourceRef": "main",                 // branch/tag/sha adopted from
  "vendoredAt": "ISO8601",
  "targets": {                         // relative paths inside the author's plugin
    "skill": "skills/skill-reflect",
    "hooks": "hooks",
    "autoExtension": null              // e.g. "extensions/skill-reflect-auto" or null
  },
  "contentHash": "sha256:…",           // hash of the vendored skill tree at adopt time -> drift detection
  "scope": ["their-skill-a", "their-skill-b"], // author skills to collect feedback for
  "destinationRepo": "owner/their-repo"        // hardcoded routing for vendored mode
}
```

### 11.3 Engine CLI — `skills/skill-reflect-maintainer/scripts/adopt.py`
Python 3 **stdlib only**, deterministic, **no AI**. Network **only** when `--from-github`
is explicitly passed (and it prints a notice first). Refuses to write outside `--to`.
Supports `--dry-run` on `adopt`/`update`. Subcommands:

- `adopt --to <plugin-dir> [--from <redth-skills-checkout> | --from-github Redth/skills[@ref]]
   [--skill-target <rel>] [--hooks-target <rel>] [--with-auto] [--scope a,b]
   [--destination owner/repo]`
  - Copies `skills/skill-reflect/` → `<to>/<skill-target default: skills/skill-reflect>`.
  - Copies the marketplace-level `hooks/stage_pending.py` + `hooks/nudge_start.py` →
    `<to>/<hooks-target default: hooks>/`.
  - **Merges** the SessionStart/SessionEnd command entries into an existing
    `<to>/hooks/hooks.json` (creates it if absent) **without clobbering** the author's
    other hooks; commands use `${CLAUDE_PLUGIN_ROOT}`.
  - Optionally copies `integrations/copilot-cli/skill-reflect-auto/` when `--with-auto`.
  - Writes `.skill-reflect-vendor.json` (§11.2) with a computed `contentHash`, `scope`,
    `destinationRepo`.
  - Scaffolds `<to>/skill-reflect.config.json` (`mode:"vendored"`, `scope`,
    `destination.repo`, `destination.mode:"ask"`) **only if absent**; NEVER overwrites an
    existing config.
  - Idempotent; safe to re-run.
- `update --to <plugin-dir> [--from … | --from-github …] [--to-version <semver|ref>] [--force]`
  - Re-syncs the skill + hook scripts, **preserving** `<to>/skill-reflect.config.json` and
    any author edits to their own skills' nudge wording. Re-merges hooks.json. Re-stamps
    the pin (new `upstreamVersion`/`sourceRef`/`vendoredAt`/`contentHash`).
  - **Refuses (exit 3)** if local drift is detected (see `doctor`) unless `--force`, so
    author edits are never silently clobbered; prints what drifted.
- `doctor --to <plugin-dir> [--reference-version <semver>]`
  - Reports, changing nothing: (a) **update available?** `pin.upstreamVersion` vs the
    reference (default: the plugin's own `skills/skill-reflect/VERSION`, else
    `--reference-version`); (b) **local drift?** recomputed hash vs `pin.contentHash`;
    (c) config valid vs `skill-reflect.config.schema.json`; (d) both hook commands present
    in `<to>/hooks/hooks.json`; (e) the reference/nudge block present in each scoped
    skill's `SKILL.md`.
  - Exit codes: `0` healthy & current; `10` update available; `11` drift; `12`
    config/hooks/nudge problem. A human-readable summary prints regardless of exit code.

### 11.4 Maintainer skill — `skills/skill-reflect-maintainer` (dev-time; NOT redistributed)
A **portable core skill for the plugin author** (audience differs from `skill-reflect`,
whose audience is the end user). It is bundled alongside the core skill in the single
`skill-reflect` plugin, but the `adopt` engine vendors **only** the core skill + review
hooks into an author's plugin (§11.3 `HOOK_SCRIPTS` allowlist), so this skill **never
ships to the author's end users**. It is a thin conversational wrapper
over §11.3 — it orchestrates the deterministic engine and edits files; it does not
re-implement the engine. Responsibilities:
- **"adopt skill-reflect into this plugin"** → runs `adopt`, helps pick targets/scope/
  destination, then appends the "Improve This Skill" reference block (from
  `skill-reflect/templates/improve-this-skill.md`) to each in-scope `SKILL.md`.
- **"check for updates" / "is my copy current"** → runs `doctor`; only does a live GitHub
  check if the author explicitly asks.
- **"update skill-reflect"** → runs `update` (author-approved), summarizes the CHANGELOG
  delta, and surfaces any drift for the author to resolve.
- **"wire reflection into `<skill>`"** → injects the reference block + adds the skill to the
  vendored config `scope`.
- Always excluded from reflection. Its `SKILL.md` MUST state it is dev-time / not for
  redistribution to end users.

### 11.5 Maintainer update-check hook (Tier A; LOCAL-ONLY, no network)
`hooks/check_updates.py` in the `skill-reflect` plugin — a SessionStart hook registered in
the plugin's `hooks/hooks.json` alongside the review hooks. Mirrors `hooks/nudge_start.py`'s
home/throttle discipline. The `adopt` engine does NOT vendor this hook to authors (only
`stage_pending.py` + `nudge_start.py`), so an author's end users never receive it.
- On SessionStart: if the cwd (walking up) contains a `.skill-reflect-vendor.json`,
  compare its `upstreamVersion` to `${CLAUDE_PLUGIN_ROOT}/skills/skill-reflect/VERSION`
  (**local read; NO network**). If behind, print **one** non-blocking nudge naming the
  vendored version vs available and saying: ask the `skill-reflect-maintainer` skill to
  "update skill-reflect" — and that nothing changes without approval.
- Throttle via `$SKILL_REFLECT_HOME/maintainer-throttle.json` (a **distinct** key from the
  review nudge's `throttle.json`), default **24h**, written BEFORE printing.
- Stdlib only; never raises into the host; always `exit 0`. **No AI, no network, no
  auto-update.** MUST NOT interfere with the review staging/nudge hooks (different files,
  throttle, and purpose).

### 11.6 Double-fire / dedupe
All hooks share `$SKILL_REFLECT_HOME`. If a user has BOTH a central `skill-reflect` and a
vendored copy active, the **review** nudge dedupes by skill name at the marker level
(existing §8 behavior). The maintainer **update-check** is per-vendored-pin and
independent of the review nudge. The author guide documents this so authors don't fear
double-nudging their users.
