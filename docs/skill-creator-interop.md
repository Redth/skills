# skill-reflect × skill-creator: Interoperability Guide

---

## 1. How the two tools complement each other

| Dimension | skill-creator | skill-reflect |
|---|---|---|
| **Eval origin** | Author-written, synthetic, pre-release | Real-world sessions, post-field |
| **Who authors** | Skill developer, before shipping | Running agent, during/after a session |
| **What they test** | "Does this skill do what I intended?" | "Did this skill cover what users actually needed?" |
| **Input to harness** | `evals/evals.json` (wrapped `{skill_name, evals:[…]}`) in the skill repo | `.skill-feedback/evals/<slug>.evals.json` (wrapped, emitted by skill-reflect) |
| **PII posture** | Synthetic by construction | Scrubbed before emission (see CONTRACT §7) |

Together they form a complete eval lifecycle: skill-creator covers the **author's
intent** at design time; skill-reflect closes the loop by surfacing **field gaps**
discovered at runtime and converting them into machine-checkable evals in exactly
the same format — so the author can drop skill-reflect's output directly alongside
their existing eval suite and re-run.

---

## 2. Where skill-reflect emits evals

Given the default config:

```jsonc
"eval": {
  "emitFormats": ["skill-creator", "portable"],
  "evalsOutPath": ".skill-feedback/evals"
}
```

After a session reflection, skill-reflect writes:

```
.skill-feedback/evals/
  <skill-slug>.evals.json         ← skill-creator format (wrapped: {skill_name, evals:[…]})
  <skill-slug>.portable.json      ← portable format (JSON array)
```

`<skill-slug>` is the skill name lowercased with non-alphanumerics collapsed to
`-`, consistent with CONTRACT §1.

---

## 3. Feeding emitted evals to skill-creator's harness

### 3.1 Merge into the skill repo's eval file

The emitted `<slug>.evals.json` uses the same wrapped shape as the skill's
`evals/evals.json`. Merge the `evals` arrays with `jq`:

```bash
# merge new field evals into the skill's existing eval suite
jq -s '{ skill_name: .[0].skill_name, evals: (.[0].evals + .[1].evals) }' \
  path/to/skill-repo/evals/evals.json \
  .skill-feedback/evals/container-toolkit.evals.json \
  > path/to/skill-repo/evals/evals.json.merged
mv path/to/skill-repo/evals/evals.json.merged path/to/skill-repo/evals/evals.json
```

Note: ids in `evals.json` are integers. After merging, renumber any collisions
so ids remain unique across the combined array.

### 3.2 Run the harness

> **Note:** Script names and shapes come from `anthropics/skills` →
> `skills/skill-creator/references/schemas.md`. Verify against your local copy.

The canonical skill-creator eval flow:

```
1. run_eval.py                         — invoke skill against task evals; produce results
   (trigger evals: run_eval.py --eval-set <trigger-set-file>)
         ↓
2. Grader agent                        — evaluates each expectations string; produces grading.json
   (summary.pass_rate is the key metric)
         ↓
3. aggregate_benchmark.py             — compare with_skill vs without_skill pass rate;
   produce benchmark.json (delta, mean, stddev)
         ↓
4. run_loop.py + history.json         — iterative improvement ratchet (§4 below)
```

Concretely:

```bash
# from inside the skill repo
python scripts/run_eval.py --evals evals/evals.json --skill SKILL.md
# grader runs automatically; produces grading.json with summary.pass_rate
python scripts/aggregate_benchmark.py --results grading.json
# iterative loop:
python scripts/run_loop.py
```

For trigger evals emitted by skill-reflect:
```bash
python scripts/run_eval.py --eval-set .skill-feedback/evals/container-toolkit.trigger-evals.json
```

Other relevant scripts: `quick_validate.py`, `package_skill.py`, `generate_report.py`,
`improve_description.py`.

Each emitted `evals.json` entry is a self-contained
`{ id:int, prompt, expected_output, files, expectations:[strings] }` object
compatible with skill-creator's grader regardless of harness version.

---

## 4. The keep/revert ratchet

`run_loop.py` drives iterative improvement. After each iteration it writes an entry
to `history.json`:

```jsonc
{
  "iteration": 3,
  "expectation_pass_rate": 0.82,
  "grading_result": "won",          // "baseline" | "won" | "lost" | "tie"
  "is_current_best": true
}
```

A change is **kept** only when `grading_result == "won"` (improved pass rate without
regressing). `aggregate_benchmark.py` produces `benchmark.json` comparing
`with_skill` vs `without_skill` pass rate (mean, stddev, delta).

The ratchet policy:

```
┌──────────────────────────────────────────────────────────────┐
│  CHANGE ACCEPTED iff:                                        │
│    pass_rate(new) > pass_rate(baseline)  (grading_result=won)│
│    AND                                                       │
│    no previously-passing eval regressed                      │
└──────────────────────────────────────────────────────────────┘
```

Operationally:

1. **Baseline snapshot** — before any skill change, record the current pass rate
   (new field evals will all fail at this point). Stored as the `baseline` entry
   in `history.json`.

2. **Apply the fix** — edit `SKILL.md` (or references) per `proposedFix`.

3. **Re-run** — `run_loop.py` reruns and records a new `history.json` entry.

4. **Ratchet decision:**
   - `grading_result == "won"` → **keep**, `is_current_best: true`, promote baseline.
   - `grading_result == "lost"` or `"tie"` → **revert** the change, revise the fix.

Git is the memory: every baseline promotion is a commit, giving a monotonically
non-decreasing pass-rate history and a clear blame trail for regressions.

---

## 5. End-to-end flow diagram

```
Session ends
    │
    ▼
skill-reflect reflects, classifies findings
    │
    ├─ trigger-problem findings ──────────────────────────────────────────┐
    │                                                                     ▼
    ▼                                               .skill-feedback/evals/<slug>.trigger-evals.json
FrictionFinding.proposedEval emitted to             (trigger eval set [{query, should_trigger}])
  .skill-feedback/evals/<slug>.evals.json            ↓
  (wrapped: {skill_name, evals:[…]})        run_eval.py --eval-set <file>
  .skill-feedback/evals/<slug>.portable.json
    │
    ▼
Author merges evals.json into skill repo
    │
    ▼
Run: run_eval.py → grader → grading.json (summary.pass_rate)
Run: aggregate_benchmark.py → benchmark.json (with/without-skill delta)
    │
    ├─ all new evals fail   → confirms the finding is reproducible
    │
    ▼
Author edits SKILL.md per proposedFix
    │
    ▼
run_loop.py iterates → history.json records (expectation_pass_rate, grading_result, is_current_best)
    │
    ├─ grading_result=won, no regressions → KEEP, promote baseline, ship
    └─ grading_result=lost/tie            → REVERT, revise fix, repeat
```

---

## 6. FAQ

**Q: Do I have to use skill-creator?**

No. The **portable form** (`.skill-feedback/evals/<slug>.portable.json`) works
with any harness or even by hand. Each entry is just `{ id, prompt,
must_contain, must_not_contain }` — you can test it with a simple shell script,
a pytest parametrize, or a manual read-through. skill-creator is the reference
harness, not a requirement.

---

**Q: What if I only want one format?**

Set `config.eval.emitFormats` to `["skill-creator"]` or `["portable"]`. The
skill-reflect core respects the array; the other format simply won't be written.

---

**Q: The skill-creator harness evaluates expectations as natural-language strings.
Can I add more nuanced assertions?**

Yes — `expectations` are plain strings evaluated by a grader agent, which
determines pass/fail from natural language. You can make statements as precise as
you need (e.g. "The output includes a complete JSON object with a 'region' key").
The portable form's `must_contain` / `must_not_contain` lists can mirror the same
intent, or you can write a more descriptive expectation string that the portable
form doesn't capture — leave a note in the portable entry if so.

---

**Q: Can I add fixture files to the eval?**

Yes, via the `files` array in the skill-creator form. All fixture content must
be synthetic/paraphrased — no real paths, hostnames, or credentials. See
`eval-format.md §3.5`.

---

**Q: How do I prevent duplicate evals accumulating over many sessions?**

Each eval's `id` is a stable hash of `{skill, pattern, normalized-summary}`.
When you merge, dedupe on `id`. A future v2 skill-reflect feature will handle
this automatically via the local registry.

---

**Q: When should skill-reflect file a GitHub issue vs just emitting evals?**

Eval emission is a **local-only** step — no network, no consent required. Filing
a GitHub issue is a separate action that requires the user's explicit second
consent (CONTRACT §6). The emitted evals are yours to use locally even if you
never file an issue.
