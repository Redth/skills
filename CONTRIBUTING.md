# Contributing to Redth/skills

Thanks for your interest! This repo is a **Claude Code plugin marketplace** of
portable, privacy-respecting agent skills. Contributions are welcome — please
read this first, because the bar for merging is deliberately high and a few
rules here are **non-negotiable** (privacy, especially).

## Ways to contribute

1. **Skill feedback** — you used a skill from this marketplace and hit friction.
   The best feedback is generated *by* `skill-reflect` itself (it scrubs PII and
   proposes a fix + an eval). Open a
   [Skill feedback issue](https://github.com/Redth/skills/issues/new?template=skill_feedback.yml) and paste
   the scrubbed report.
2. **Bug reports** — a script, hook, or manifest misbehaves. Open a
   [Bug report](https://github.com/Redth/skills/issues/new?template=bug_report.yml).
3. **Improve an existing skill** — fix stale guidance, add a missing case, or add
   an eval. Small, focused PRs preferred.
4. **Propose a new skill** — open a
   [New skill proposal](https://github.com/Redth/skills/issues/new?template=new_skill.yml) **before** sending
   a PR, so we can align on scope.

## The bar

- **One skill (or one focused fix) per PR.** Don't bundle unrelated changes.
- **Issue before a new-skill PR.** New skills need a proposal issue first.
- **Skills are production assets.** Even though they're Markdown, treat them like
  code: precise, testable, and covered by evals.
- **Cross-platform.** Scripts must be stdlib Python 3.8+ (no pip deps) or POSIX
  shell where possible, and must run on macOS and Linux.

## Privacy — non-negotiable

This is the whole point of `skill-reflect`, and it applies to *every*
contribution:

- **No PII, ever.** No real names, emails, usernames, machine names, absolute
  paths, private URLs, tokens, keys, or secret values — not in skills, scripts,
  examples, evals, or fixtures.
- **No verbatim transcript excerpts** in examples or docs. Paraphrase.
- **No config may weaken privacy.** `privacy.allowTranscriptExcerpts` must never
  be `true`; `privacy.redactionPreview` must never be `false`. CI enforces this.
- Test fixtures that intentionally contain *fake* secrets (to prove the scrubber
  catches them) must be **obviously synthetic** and live under an `evals/files/`
  or `examples/` directory.

## Anatomy of a good SKILL.md

A skill's `SKILL.md` should make its **purpose, non-goals, when-to-use, inputs,
workflow, validation, and failure modes** obvious. Frontmatter must include a
`name` and a `description` written as natural-language trigger phrases (how a
user would ask for it). Keep the skill **self-contained**: reference only files
*inside the skill directory* with relative paths — installed plugins are copied
to a cache, so `../` references outside the skill will break.

## Plugin & marketplace conventions

- The marketplace manifest is [`.claude-plugin/marketplace.json`](./.claude-plugin/marketplace.json).
- Plugin hooks live in [`hooks/`](./hooks/) and use `${CLAUDE_PLUGIN_ROOT}` for
  paths so they resolve from the installed cache location.
- Hooks must be **defensive**: stdlib only, no network, wrap everything in
  `try/except`, and always exit 0 — never throw into the host agent.

## Validate locally before you push

CI runs these on every PR; run them yourself first:

```sh
# 1. Repo-wide gate: py_compile, unit tests, node --check, JSON + shell syntax
bash tools/validate.sh

# 2. Marketplace / plugin / skill consistency + privacy invariants
python3 tools/validate_marketplace.py

# 3. Privacy spot-check: the scrubber must FLAG a dirty file (exit 1) ...
python3 skills/skill-reflect/scripts/scrub.py --fail-on-secret \
  skills/skill-reflect/evals/files/pdf-forms-session.md ; echo "exit $? (want 1)"

# ... and PASS a scrubbed one (exit 0)
python3 skills/skill-reflect/scripts/scrub.py --fail-on-secret \
  examples/dogfood/2026-01-01-pdf-forms.md ; echo "exit $? (want 0)"
```

`bash tools/validate.sh` already discovers and runs every `test_*.py`
automatically, including `tools/ab_eval/`'s own suite — no separate command
needed. If your change is a *behavioral* claim about a skill ("this is
safer", "this asks fewer questions"), consider backing it with
[`tools/ab_eval`](./tools/ab_eval/README.md): a repeatable, paired A/B
harness that measures unauthorized side effects, remote-command attempts,
leakage, and interaction friction from real evidence instead of prose.

## PR process

1. Fork, branch, make your change.
2. Run the validators above; make sure they're green.
3. Open a PR filling in the template. Link the proposal/bug issue if there is one.
4. CI must pass (`marketplace`, `test`, `privacy-guard`). The `skill-lint` job is
   informational and won't block.
5. A maintainer reviews. Expect requests to tighten scope, add an eval, or
   strengthen the scrub.

## License & attribution

By contributing you agree your contribution is licensed under the repo's
[MIT License](./LICENSE). Don't paste content you don't have the right to
license, and don't include internal or proprietary URLs, names, or data.
