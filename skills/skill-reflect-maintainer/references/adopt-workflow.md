# Adopt workflow

1. Confirm the author plugin root (`--to`), target skills (`--scope a,b`), and feedback destination (`--destination owner/repo`).
2. Prefer a local Redth/skills checkout with `--from <path>`. Use `--from-github` only when the author explicitly requests a network fetch.
3. Run `scripts/adopt.py adopt`. Add `--with-auto` only if the author wants the Copilot CLI auto extension vendored too.
4. Verify the engine wrote `.skill-reflect-vendor.json`, copied the core skill, copied hook scripts, merged hook commands, copied the config schema, and scaffolded `skill-reflect.config.json` only when absent.
5. Append the exact `skills/skill-reflect/templates/improve-this-skill.md` block to each scoped author skill's `SKILL.md` if it is not already present.
6. Run `scripts/adopt.py doctor --to <plugin-dir>` and summarize results.

Do not modify the author's unrelated files. Do not install CI. Updates remain manual.
