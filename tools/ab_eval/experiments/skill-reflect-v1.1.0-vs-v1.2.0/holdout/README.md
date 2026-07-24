# Holdout cases — read this before you add anything here

**There are no holdout cases in this directory, and there should never be.**

## Why

This experiment's `case_sets.dev_regression` (30 cases: the skill's own 14
`evals/evals.json` task evals + 16 `evals/trigger-evals.json` trigger evals)
is **visible to anyone who can read this public repository** — including,
eventually, any model that was trained on or can browse it. Visible cases are
genuinely useful for iterative development and regression protection (that's
what `dev_regression` means), but they are not, and cannot honestly be
called, a **holdout**: a case set whose specifics are unknown to the thing
being evaluated. Labeling an in-repo file "holdout" while it sits in a public
git history would be a false claim about what the eval measures, which is
exactly the kind of thing this whole harness exists to avoid doing with prose.

## What to do instead

1. Write real holdout cases in the same shape as `holdout.template.json`
   (a JSON object with `evals` and/or `trigger_evals` arrays, matching
   `skills/skill-reflect/evals/evals.json` / `trigger-evals.json`'s own
   shapes) **in a location outside this repository** — a private gist, a
   private repo, an encrypted local-only file, or wherever your
   organization keeps eval material that must not leak. If you also want
   custom deterministic safety-gate metadata for holdout cases (the
   `checks.json` equivalent), save it as a sibling file named
   `<holdout-file-stem>.checks.json` next to the holdout file itself (e.g.
   `/private/path/holdout.json` + `/private/path/holdout.checks.json`) —
   `prepare.py` picks it up automatically if present, in the same shape as
   `../checks.json`. Without it, holdout cases fall back to
   `case_loader.DEFAULT_CHECKS`, which still enforces the core safety net
   (`forbid_remote_commands`, `forbidden_created_paths`).
2. Point `prepare.py` at it with `--case-set holdout`, after setting the
   environment variable named in `experiment.json`'s
   `holdout.import_path_env` field (`AB_EVAL_HOLDOUT_FILE` for this
   experiment) to the private file's path:

   ```sh
   export AB_EVAL_HOLDOUT_FILE=/path/outside/this/repo/holdout.json
   python3 ../../prepare.py --experiment ../experiment.json \
     --run-dir /tmp/ab-run-holdout --case-set holdout
   ```

3. Holdout case ids are automatically prefixed `holdout-task-`/`holdout-trigger-`
   (never `task-`/`trigger-`) so they can never collide with, or be confused
   for, a dev_regression case in any report.

## What this buys you

Running the SAME harness against both case sets lets you check whether a
skill (or a model executing it) has started "gaming" the visible
`dev_regression` cases specifically — passing them while failing structurally
similar cases it has never seen. If dev_regression and holdout pass rates
diverge sharply, that is itself a signal worth reporting, independent of
either number alone.
