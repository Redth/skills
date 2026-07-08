# Troubleshooting

- Missing pin: run `adopt` before `doctor` or `update`.
- Exit `3` from `update`: local drift exists in the vendored `skills/skill-reflect` tree. Review the drift and use `--force` only after author approval.
- Exit `10` from `doctor`: pinned version is older than the maintainer plugin's local `VENDORED_SKILL_VERSION` or the supplied `--reference-version`.
- Exit `11` from `doctor`: content hash does not match the vendored skill tree.
- Exit `12` from `doctor`: fix config JSON, merged hook commands, or missing Improve This Skill blocks.
- Network failures: avoid `--from-github`; use `--from <local Redth/skills checkout>`.

The engine is stdlib-only and deterministic. It performs no AI work.
