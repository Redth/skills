# M9 Dogfood Report — skill-reflect

> **Note:** This is a dogfood exercise using a **synthetic session fixture**
> (`skill-reflect/evals/files/pdf-forms-session.md`). All names, emails, paths,
> tokens, and IP addresses in the fixture are fake and were planted deliberately to
> test PII detection. The fictional skill `pdf-forms` from fictional repo
> `acme/pdf-skills` does not exist. No real session data was read.

---

## (a) Friction detected and classification

The synthetic session showed a fictional `pdf-forms` distributed skill hitting
friction across two distinct tasks (fill and validate), producing three findings.

### Finding 1 — Stale `--flatten` flag

| Field | Value |
|---|---|
| `pattern` | `stale-guidance` |
| `category` | `wrong-or-stale-guidance` (primary per taxonomy) |
| `severity` | High |
| `confidence` | Likely |
| `outcome` | Worked-around |

**Rubric reasoning:** The `fill` subcommand exited non-zero on three consecutive
identical retries after the tool named the flag as unknown and suggested the renamed
form. Direct tool failure with the error naming the skill's documented feature and no
other plausible cause → `Likely` (not `Confirmed` because the calling skill did not
self-identify). The task was completed via an external tool, not the skill → severity
`High` (skill failed to deliver its core promise for this sub-task).

**Taxonomy mapping:** `stale-guidance` → primary category `wrong-or-stale-guidance`. ✓

---

### Finding 2 — Undocumented `validate` output schema

| Field | Value |
|---|---|
| `pattern` | `repeated-command-loop` |
| `category` | `wrong-or-stale-guidance` (primary per taxonomy) |
| `severity` | Medium |
| `confidence` | Likely |
| `outcome` | Worked-around |

**Rubric reasoning:** Four consecutive identical `validate` invocations with no
material variation in arguments; no successful parse between repetitions. The
documented schema did not match the actual schema. Repeated-command-loop heuristic
(3+ identical calls) met at iteration 3; held through iteration 4. Confidence `Likely`
because the mismatch is directly traceable to the skill's documented output format
vs. the actual tool output (no other plausible cause). Severity `Medium` — the task was
ultimately completed via raw JSON parsing.

**Taxonomy mapping:** `repeated-command-loop` → primary category
`wrong-or-stale-guidance`. ✓ (The loop arises from wrong documented schema, not
missing parameter knowledge, so primary mapping applies over `missing-detail`.)

---

### Finding 3 — Trigger miss for fill-task phrasing

| Field | Value |
|---|---|
| `pattern` | `trigger-miss` |
| `category` | `trigger-problem` |
| `severity` | Medium |
| `confidence` | Possible |
| `outcome` | Worked-around |

**Rubric reasoning:** The user's natural phrasing (fill an expense PDF) matched the
skill's purpose but not its trigger vocabulary. The agent did not invoke the skill
immediately. Confidence capped at `Possible` because: (1) the session source is
synthetic; (2) the causal link between trigger vocabulary and invocation failure cannot
be confirmed from a synthetic fixture alone. Severity `Medium` — the skill's value
was underutilised.

**Taxonomy mapping:** `trigger-miss` → primary category `trigger-problem`. ✓

---

## (b) Proposed evals emitted

### Task evals (Findings 1 and 2 → `evals/evals.json` entries for `pdf-forms`)

These evals would be added to `pdf-forms`'s own `evals/evals.json` by the skill author
after accepting the finding:

| Finding id | Pattern | Eval prompt (excerpt) | Key expectations |
|---|---|---|---|
| `pf-flatten-stale` | `stale-guidance` | "Use pdf-forms to fill a multi-field PDF form and produce a flattened output file." | must contain `--flatten-fields`; must not contain `--flatten ` |
| `pf-validate-schema` | `repeated-command-loop` | "Use pdf-forms to validate a completed PDF form and interpret the validation result." | must contain `fields_validated`, `warnings`; must not contain `valid`, `errors` |

In skill-creator format:
```json
{
  "skill_name": "pdf-forms",
  "evals": [
    {
      "id": 1,
      "prompt": "Use pdf-forms to fill a multi-field PDF form and produce a flattened output file.",
      "expected_output": "The fill subcommand succeeds using --flatten-fields and produces the output file.",
      "files": [],
      "expectations": [
        "The output uses the '--flatten-fields' flag",
        "The output does not use the deprecated '--flatten' flag"
      ]
    },
    {
      "id": 2,
      "prompt": "Use pdf-forms to validate a completed PDF form and interpret the validation result.",
      "expected_output": "The validate subcommand succeeds and the agent correctly reads the status, fields_validated, and warnings fields.",
      "files": [],
      "expectations": [
        "The output references the 'fields_validated' field from the response",
        "The output references the 'warnings' field from the response",
        "The output does not treat 'valid' as a response field",
        "The output does not treat 'errors' as a response field"
      ]
    }
  ]
}
```

### Trigger eval (Finding 3 → trigger set item for `pdf-forms`)

```json
[
  {
    "query": "Fill out the quarterly expense PDF form and flatten the fields for submission.",
    "should_trigger": true
  }
]
```

---

## (c) PII-safety proof

The fixture `skill-reflect/evals/files/pdf-forms-session.md` contained four planted
fake PII/secret values. The final artifact `examples/dogfood/2026-01-01-pdf-forms.md`
was written with all values paraphrased from scratch (no copy-paste from the fixture).

### Scrub run 1 — raw fixture (expect secrets flagged → exit 1)

```
python3 skill-reflect/scripts/scrub.py \
  skill-reflect/evals/files/pdf-forms-session.md \
  --report --fail-on-secret
```

**Report (categories only — no values):**
```
=== scrub report ===
  email: 3 redaction(s)
  github-token: 1 redaction(s)
  ip-address: 1 redaction(s)
  path: 9 redaction(s)
scrub: FAIL — secret-category content detected
```

**Exit code: 1** ✓ (expected — `github-token` is in `SECRET_CATEGORIES`)

The scrubber correctly detected:
- 3 email occurrences (fake user email appeared in the header, data payload ×2)
- 1 GitHub token (`ghp_`-prefixed, fake)
- 1 IP address (fake internal host address)
- 9 path occurrences (fake `/Users/...` paths across multiple bash command blocks)

### Scrub run 2 — final dogfood artifact (expect clean → exit 0)

```
python3 skill-reflect/scripts/scrub.py \
  examples/dogfood/2026-01-01-pdf-forms.md \
  --report --fail-on-secret
```

**Report:**
```
=== scrub report ===
  (no redactions)
```

**Exit code: 0** ✓ (expected — artifact is fully paraphrased; no PII/secrets remain)

**Contrast confirmed:** The raw fixture triggers 4 categories (including a
secret-category fail). The paraphrased artifact is clean. This demonstrates the
model-layer paraphrasing workflow + scrubber-as-backstop operating as designed.

---

## (d) skill-reflect self-improvement backlog

Concrete gaps and ambiguities encountered while dogfooding, each actionable by an
author:

1. **Artifact template doesn't distinguish trigger-problem proposed eval format.** The
   CONTRACT §5 template says `{ ...portable form... }` for all findings, but for
   `trigger-problem` findings the correct emitted form is `{query, should_trigger}`.
   Update the template (and reporting.md) to show both cases explicitly.

2. **`FrictionFinding.id` hash function is unspecified.** The schema says "stable hash
   of `{skill, pattern, normalized-summary}`" but gives no hash algorithm or
   normalization rules. Two independent runs on the same session can produce different
   string IDs. Define a concrete recipe (e.g. SHA-256 first 8 hex chars of
   `<skill>|<pattern>|<lowercase-stripped-summary>`) so deduplication in v2 is
   actually reliable.

3. **No guidance for synthetic/eval-mode sessions.** SKILL.md Step 2 describes how to
   locate real sessions; it does not address running skill-reflect against a synthetic
   fixture file (as in evals). Add an "eval mode" note: when the user provides a file
   path directly, treat it as the session source without querying a session store.

4. **Routing section wording is inconsistent.** CONTRACT §5 says
   `"destination: unknown → local-only"` while reporting.md says
   `"Suggested destination: local only. No remote filing suggested."` — two different
   phrasings for the same state. Align both to a single canonical wording.

5. **`sessions_reviewed: 0` edge case underdocumented.** reporting.md says use `0`
   for Tier C (no transcript), but SKILL.md doesn't mention this, creating ambiguity.
   Add a one-line note in SKILL.md Step 2 referencing the `0` case.

6. **Remote-send metadata transition is not shown in a worked example.** The frontmatter
   starts as `review-only` and becomes `sent:<destination>` after remote-send authorization,
   but no worked example in reporting.md shows the before/after. Add one to reduce author
   confusion.

7. **Scrubber doesn't flag `~/.skill-reflect/...` as a path.** The fixture's marker
   path `~/.skill-reflect/pending/...` was not redacted because `_UNIX_PATH_RE` only
   matches `/Users/...` or `/home/...`, not `~/...`. Consider adding a `~/` path
   pattern or documenting this gap in privacy-scrub.md so authors know it's a
   model-layer responsibility.
