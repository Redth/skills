# Update and doctor workflow

## Doctor

Run:

```bash
python3 plugins/skill-reflect-maintainer/tools/adopt.py doctor --to <plugin-dir>
```

Interpret exit codes:

- `0` healthy and current.
- `10` update available versus local `VENDORED_SKILL_VERSION` or `--reference-version`.
- `11` local drift in the vendored core skill tree.
- `12` config, hooks, or nudge wiring problem.

## Update

1. Make sure the author approves the update.
2. Summarize relevant `CHANGELOG.md` entries between the pinned version and target version.
3. Run `tools/adopt.py update --to <plugin-dir> --from <redth-skills-checkout>`.
4. If the engine exits `3`, report drift and stop. Re-run with `--force` only after explicit author approval.
5. Run doctor again and report the result.

Never auto-update from a hook. Live GitHub checks require explicit author request.
