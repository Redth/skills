# Example eval files

| File | Format | Notes |
|---|---|---|
| `evals.example.json` | skill-creator native — `{skill_name, evals:[{id:int, expectations:[strings]}]}` | Drop into `evals/evals.json` in a skill repo; consumed by the skill-creator grader → `aggregate_benchmark.py` → `benchmark.json` flow. |
| `trigger-evals.example.json` | Trigger eval set — `[{query, should_trigger}]` | Run with `python scripts/run_eval.py --eval-set <file>`; tests whether the skill's description triggers at the right rate. |
| `evals.portable.example.json` | Portable — `[{id:string, must_contain:[], must_not_contain:[]}]` | Convenience format for any lightweight harness or manual review. **NOT skill-creator native** — see `docs/skill-creator-interop.md` for the 1:1 mapping to expectations strings. |

> `evals.example.json` and `trigger-evals.example.json` use the real schema from
> `anthropics/skills` → `skills/skill-creator/references/schemas.md`.
> `evals.portable.example.json` is a skill-reflect convenience format only.
