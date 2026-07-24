# ab_eval — a repeatable empirical A/B harness for skill changes

`tools/ab_eval` is a repository-local, stdlib-only framework for measuring
whether a change to a skill (a new `SKILL.md`, a reworded authorization
model, a new reference file) actually improves things — instead of asserting
it in prose. The reference instance is
[`experiments/skill-reflect-v1.1.0-vs-v1.2.0/`](experiments/skill-reflect-v1.1.0-vs-v1.2.0/README.md),
comparing the released `skill-reflect` v1.1.0 against the in-progress v1.2.0
using the skill's own 13 task evals + 15 trigger evals.

## Why this exists (and what it deliberately does NOT do)

**This repo has no universal model API runner**, and this framework does not
try to become one. It draws a hard line between two concerns:

- **Model execution** — actually running a prompt against a skill variant
  with some model — happens *outside* this framework: in Arena, in a
  Copilot CLI subagent, or by a human pasting into whatever agent they use.
  Nothing here calls a model API. For a full matrix, use Arena or automated
  subagent fan-out; manual execution is suitable only for a small smoke run.
- **Evidence collection and grading** — turning "what actually happened"
  into a structured record, and checking that record against deterministic
  rules — happens *inside* this framework, deterministically, from files on
  disk.

The connective tissue between the two is a stable, versioned **packet**
(input) / **run-bundle** (output) file format (`schemas.py`), designed so
"someone/something else ran the model" can be Arena, a subagent, or a human
with a text editor, without this framework caring which.

**This framework also does not pretend semantic quality is deterministic.**
Whether a response actually satisfies a natural-language `expectations`
string, and which of two blinded responses is better, are genuine judgment
calls — this harness exports **blind grader packets** for both and *ingests*
external/human judgments back in; it never scores prose itself. What it does
score deterministically: filesystem side effects, attempted commands, exact
known-secret leakage, authorization-prompt counts against a per-case cap, and
trigger correctness — because those have unambiguous right answers that
don't need a judgment call, and prose about them ("no file was created")
is exactly what should never be trusted on its own.

## Quick start (the reference experiment)

```sh
cd tools/ab_eval
EXP=experiments/skill-reflect-v1.1.0-vs-v1.2.0

# 1. PREPARE — build blinded packets. Nothing here calls a model.
python3 prepare.py --experiment "$EXP/experiment.json" \
  --run-dir /tmp/ab-run-1 --repo-root "$(git rev-parse --show-toplevel)"

# 2. EXECUTE EXTERNALLY — for each packets/*.packet.json, run it through
#    Arena / automated subagent fan-out, inside the sandbox from runner_env.py
#    (see "Runner contract" below), and use record_run.py to assemble a
#    validated run-bundle into /tmp/ab-run-1/incoming/.

# 3. COLLECT — validate and ingest whatever run-bundles came back.
python3 collect.py --run-dir /tmp/ab-run-1 --from /tmp/ab-run-1/incoming

# 4. GRADE — deterministic checks now; semantic rubric packets for later.
python3 grade.py run --run-dir /tmp/ab-run-1 \
  --scrub-module ../../skills/skill-reflect/scripts/scrub.py
python3 grade.py export-rubric --run-dir /tmp/ab-run-1
#   ... a human or LLM grader fills in rubric_packets/pending/*.json and
#   moves them to rubric_packets/judged/ ...
python3 grade.py ingest-rubric --run-dir /tmp/ab-run-1

# 5. BLIND REVIEW — pairwise preference, still blind.
python3 blind_review.py build --run-dir /tmp/ab-run-1
#   ... a grader judges preference_packets/pending/*.json (A vs B, no labels)
#   and moves them to preference_packets/judged/ ...
python3 blind_review.py ingest --run-dir /tmp/ab-run-1

# 6. SUMMARIZE — the ONE step that de-blinds, aggregates, and thresholds.
python3 summarize.py --run-dir /tmp/ab-run-1 --experiment "$EXP/experiment.json"
# writes /tmp/ab-run-1/summary.json + summary.md; exits non-zero if any
# acceptance gate failed (pass --no-fail-on-gate to only report).
```

The reference configuration emits **504 packets** (28 cases × 3 models ×
3 repetitions × 2 variants). Do not plan to execute that matrix by hand.
Use the manual runner walkthrough below to prove the integration on one pair,
then use Arena or another batch executor for the full run.

Every stage is idempotent and safe to re-run; `collect`/`grade`/`ingest-rubric`
skip or update-in-place rather than duplicate.

## Concepts

| Term | Meaning |
|---|---|
| **variant** | `baseline` or `candidate` — the two real things being compared. Named in `experiment.json`, materialized by `variant_source.py` from a `git_ref`, `worktree`, or arbitrary `directory`. |
| **case** | A paired stimulus (prompt + fixture files, optionally `expectations` or `should_trigger`) loaded once from a skill's own `evals.json`/`trigger-evals.json` (`case_loader.py`) and run against **both** variants unmodified — see the reference experiment's README for why. |
| **token** | `"A"` or `"B"` — the *blind* label an executor/grader sees. Never `"baseline"`/`"candidate"`. |
| **token map** | Per `(case, model, repetition)`, a deterministic-but-unpredictable `{"A": "candidate", "B": "baseline"}`-shaped mapping (`blinding.py`), seeded so re-running `prepare.py` reproduces it exactly. |
| **packet** | What `prepare.py` hands to an executor: a case's prompt/files + a variant's content (by hash, blind token only) + that case's deterministic `checks`. Safe to share — contains no ground truth. |
| **run-bundle** | What an executor hands back after actually running a packet: response text, metrics, required hash-map filesystem snapshots, required attempted-command evidence, and an optional pre-filled rubric. `collect.py` validates its shape and binds its identity/content hash back to the prepared packet before grading trusts it. |
| **blinding key** | `.private/blinding_key.json` — the *only* place the real token↔variant mapping lives. Never shared with an executor or grader; read only by `summarize.py`. |

## Directory layout

```
tools/ab_eval/
  schemas.py          structural validation (malformed-bundle detection)
  hashing.py          canonical JSON + content hashing
  blinding.py         seeded, deterministic A/B token assignment
  fs_snapshot.py       filesystem before/after diffing + glob matching
  commands.py          network/remote command signature detection
  leakage.py            exact-term + external-scrubber secret/PII scanning
  variant_source.py    materialize a variant from git_ref/worktree/directory
  case_loader.py        evals.json/trigger-evals.json -> cases; checks.json
  prepare.py    (1)     build packets + blobs + manifest + blinding key
  collect.py    (3)     validate + ingest returned run-bundles
  grade.py      (4)     deterministic grading; rubric export/ingest
  aggregate.py           pure de-blind/pass-rate/PRF1/gate-evaluation logic
  blind_review.py (5)   pairwise blind preference build/ingest
  summarize.py  (6)     de-blind, aggregate, evaluate gates, report
  runner_env.py         sandbox env builder; stub PATH; blob materialization
  record_run.py (2)     turn raw sandbox evidence into a valid run-bundle
  stub_bin/gh, stub_bin/curl   safe network stubs (see below)
  test_*.py              unit tests for every module above (see §Testing)
  experiments/
    skill-reflect-v1.1.0-vs-v1.2.0/
      experiment.json    the experiment spec
      checks.json        hand-authored per-case deterministic safety rules
      README.md          what's specific to THIS experiment
      holdout/           NOT holdout data — a template + the import boundary
```

A `<run-dir>` (the `--run-dir` of a specific execution) looks like:

```
<run-dir>/
  manifest.json              expected run_ids (safe to share)
  packets/<run_id>.packet.json          (safe to share)
  blobs/<hash>.json                     (safe to share)
  .private/blinding_key.json            NEVER share this
  collected/<run_id>.json               validated run-bundles
  graded/<run_id>.json                  deterministic + (later) semantic grades
  rubric_packets/{pending,judged}/      per-run semantic expectation grading
  preference_packets/{pending,judged}/  pairwise blind preference judging
  preferences.json                      ingested preference judgments
  summary.json / summary.md             final report (from summarize.py)
```

## The runner contract

Nothing in this repo can execute an arbitrary model, but everything in this
repo insists that whoever does follows the same three rules, because a model
under evaluation should never be able to actually touch the network or the
real filesystem outside its sandbox — the whole reason to run an *evaluation*
in the first place is that you don't yet trust the thing being evaluated:

1. **Sandbox.** Give the model a fresh, disposable working directory
   (`runner_env.fresh_sandbox`), never a real project checkout.
2. **Stub `gh`/`curl`.** Prepend `stub_bin/` to `PATH`
   (`runner_env.build_sandbox_env`) so any attempt to invoke `gh` or `curl`
   is intercepted, logged to `$AB_EVAL_CMD_LOG`, and refused with exit 1.
   This prevents those named command paths from reaching the network; it is
   not an OS-level network boundary.
3. **Snapshot before/after.** Hash every file in the sandbox before and
   after (`record_run.py snapshot` / `finish`) so `filesystem.created`/
   `modified`/`deleted` in the run-bundle is computed from evidence, not
   from what the transcript claims.

```sh
# Minimal manual walkthrough of the contract for one packet:
python3 record_run.py snapshot --sandbox-dir ./sandbox --out before.json
# ... build the model's environment with runner_env.build_sandbox_env(),
#     materialize the packet's variant blob into ./sandbox with
#     runner_env.materialize_files(), and run the model there ...
python3 record_run.py finish --run-dir /tmp/ab-run-1 --run-id <run_id> \
  --sandbox-dir ./sandbox --before before.json \
  --response-file response.txt --cmd-log ./sandbox_cmdlog.jsonl \
  --executor "human:you"
```

`record_run.py finish` looks up the packet, computes the filesystem diff,
ingests the command log, and writes a schema-valid run-bundle to
`<run-dir>/incoming/<run_id>.json` — ready for `collect.py`.

The runner is part of the measurement trust boundary. The harness rejects
missing/list-only snapshots, malformed hashes, self-reported diffs that do not
match recomputation, missing command evidence, and bundles whose identity or
content hash does not match the prepared packet. It cannot prove that an
untrusted executor honestly captured the initial snapshot or complete command
log. Run `record_run.py` from a trusted wrapper around model execution rather
than accepting hand-edited evidence for a decision-grade experiment.

## Grading model: deterministic vs. semantic

| Layer | What it checks | Deterministic? | Command |
|---|---|---|---|
| Side effects | Recomputed created/modified/deleted hash-snapshot diff vs. `allowed_created_paths`/`forbidden_created_paths`; mutation count vs. `max_local_writes` | Yes, given runner-captured snapshots | `grade.py run` |
| Commands | Captured `gh`/`curl`/network-shaped commands vs. `forbid_remote_commands`/`allowed_commands` | Yes, given the runner command log | `grade.py run` |
| Leakage | Exact known secret/PII literals (`leakage_terms`) + optional external scrubber secret categories | Yes | `grade.py run --scrub-module <skill>/scripts/scrub.py` |
| Duplicate prompts | `metrics.review_authorization_prompts` (executor-supplied count) vs. `max_review_authorization_prompts` | Yes — the *threshold check* is deterministic; the *count itself* is a judgment call the executor makes reading the transcript | `grade.py run` |
| Trigger correctness | Executor-supplied `trigger_decision` vs. `should_trigger` | Yes for comparison; deciding whether the skill triggered must be captured consistently by the executor | `grade.py run` |
| Expectations pass/fail | Does the response satisfy each `expectations` string? | **No** — exported as a blind rubric packet, graded externally | `grade.py export-rubric` / `ingest-rubric` |
| Pairwise preference | Which of two blind responses is better? | **No** — exported as a blind preference packet, graded externally | `blind_review.py build` / `ingest` |

`--scrub-module` reuses a skill's own deterministic scrubber (e.g.
`skills/skill-reflect/scripts/scrub.py`'s `scrub_text()`) as an additional
secret cross-check, so a token shaped like a secret but not byte-identical
to the one hand-listed in `checks.json` is still caught — see `leakage.py`.

## Acceptance gates

`experiment.json`'s `acceptance_gates` are evaluated once, at `summarize.py`
time, against de-blinded, graded records. Three kinds are implemented in
`aggregate.py` (`evaluate_acceptance_gates` dispatches by `kind`):

- `max_deterministic_violations` — total violation count (optionally
  filtered by `categories`, scoped to specific `variants`) must be `<= max`.
- `metric_reduction` — over pairs where both sides reported the metric,
  candidate's mean of some `metrics.*` path must be at least
  `min_relative_reduction` lower than the matched baseline mean. Set
  `case_kinds` to the applicable case types and `min_pairs` to the predeclared
  coverage floor so unrelated cases or a tiny subset cannot pass.
- `trigger_no_regression` — candidate's trigger `precision`/`recall`/`f1`
  must be within `tolerance` of baseline's (not required to *beat* it).

See [the reference experiment's gates](experiments/skill-reflect-v1.1.0-vs-v1.2.0/README.md#acceptance-gates)
for a worked example, including a documented, deliberate design decision
about whether gates should be scoped to both variants or candidate-only.
`summarize.py` refuses to evaluate any gate unless every `manifest.json`
run ID has a graded record and every case/model/repetition has exactly one
baseline and one candidate result.

## Arena handoff

This harness produces exactly what an Arena eval request needs and nothing
an Arena eval request shouldn't have to invent from scratch: a stable case
set (`case_sets.dev_regression`, already the skill's own evals), a controlled
A/B pairing with real blinding, and a machine-checkable acceptance
threshold instead of "looks better to me." Per the **skill-trainer** agent's
workflow (Training Session Workflow §3 "Assess" and the Arena Integration
section — open an Arena issue when "quick multi-model validation is
insufficient" or "eval results should be tracked long-term"):

1. Run `prepare.py` for the experiment, then have Arena (or your own automated
   multi-model subagent fan-out) execute the packets under the runner
   contract above — Arena's own execution substrate satisfies "somewhere
   else that isn't this repo," which is all this framework requires of it.
2. Run `collect.py` → `grade.py run` → `summarize.py` on the results Arena
   returns.
3. Attach `summary.md` (and, for a formal request, `summary.json`) to the
   Arena issue using the **skill-trainer-knowledge** skill's eval-issue
   template and trigger-test structure — that skill (not this repo) owns
   the issue template and the Arena workflow contract; this harness only
   guarantees the evidence going into it is real.
4. If `summary.md`'s acceptance gates all pass and multi-model validation
   scores ≥ 4/5 across 3 families with no misapplied guidance (skill-trainer's
   own stop signal), the training session is done; otherwise iterate — one
   change per eval cycle, per skill-trainer's Core Principles — and re-run
   from step 1 with the same seed to keep the comparison paired.

## Building a new experiment for a different skill

1. `mkdir tools/ab_eval/experiments/<your-skill>-<label-a>-vs-<label-b>/`
2. Write `experiment.json` (see `schemas.validate_experiment_spec` for the
   required shape; the reference experiment's file is the best template).
   Pick an `include` list for both variant sources that captures real
   behavioral files (`SKILL.md`, `references/*`, `scripts/*.py`,
   `templates/*`) and excludes anything that would spoil blinding (a
   `VERSION` file, the skill's own `evals/` — see
   `test_prepare.py::TestMaterializeVariants` for what this catches).
3. Write `checks.json` by hand from your skill's actual fixtures and
   authorization contract — see "Why `checks.json` is hand-authored" in the
   reference experiment's README for the reasoning; don't derive it from
   `expectations` text.
4. Add a `holdout/README.md` (copy this repo's) if you want to document a
   real external holdout path; otherwise set `holdout.included: false` and
   don't invent in-repo holdout data.
5. Run the Quick Start commands above with your new `experiment.json`.

## Testing the harness itself

Every module has a `test_*.py` sibling, discovered automatically by
`tools/validate.sh`'s existing unittest-discovery loop (no changes needed
there — it already walks every directory containing `test_*.py`). Run them
directly with:

```sh
cd tools/ab_eval && python3 -m unittest discover -s . -p 'test_*.py'
```

`test_skill_reflect_experiment.py` specifically locks the reference
experiment's `experiment.json`/`checks.json` to the *live*
`skills/skill-reflect/evals/*.json` files, so a future change that adds an
eval without a matching `checks.json` entry fails loudly instead of silently
shipping an incomplete or blinding-broken run.

## Limitations (read before trusting a `summary.md`)

- **No OS-level network sandboxing.** `stub_bin/gh` and `stub_bin/curl`
  intercept those two *named* binaries on `PATH`; they cannot stop a model
  from reaching the network through some other binary or a raw socket call
  from within its own runtime. Treat the sandbox as a strong safety net for
  agentic tool-call-shaped execution (the realistic threat model for a
  skill), not a security boundary against arbitrary code.
- **`review_authorization_prompts` is executor-supplied, not derived.**
  Counting "how many times did the transcript ask essentially the same
  yes/no question" is itself a judgment call; only the *threshold* check
  against a case's `max_review_authorization_prompts` is deterministic.
- **Blinding hides the label, not genuine behavioral differences.** An
  attentive executor watching two visibly different skill instruction sets
  execute can still often infer which is "the new one" — that's inherent to
  comparing two really-different variants locally, not a bug to fix here.
  What blinding *does* guarantee: grader-facing metadata exposes only token A/B,
  never a real variant field or label. Free-text prompts, fixtures, responses,
  or rubric expectations may legitimately use words such as "candidate" in
  their domain meaning; `schemas.validate_packet` rejects explicit variant
  labels without banning that vocabulary.
- **Evidence integrity ends at the trusted runner.** Hash-map snapshots,
  recomputed diffs, packet binding, and completeness checks detect malformed,
  omitted, swapped, or internally inconsistent evidence. They are not a
  cryptographic attestation that a hostile executor captured every action.
- **Semantic numbers are only as good as who judged them.** `summarize.py`
  will happily report a 100% semantic pass rate from a single rushed
  self-judgment. Multi-model / multi-grader corroboration is a discipline
  this tool enables but does not enforce.
