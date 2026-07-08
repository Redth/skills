<!--
Thanks for contributing! Please keep PRs focused: one skill, or one focused fix.
Delete sections that don't apply.
-->

## What & why

<!-- What does this change do, and why? Link any proposal/bug issue: "Closes #123". -->

## Type of change

- [ ] New skill (has a linked proposal issue)
- [ ] Improve an existing skill (guidance / missing case / eval)
- [ ] Fix a script, hook, or manifest
- [ ] Docs / examples
- [ ] CI / tooling

## Checklist

- [ ] Scope is focused (one skill or one fix).
- [ ] `bash tools/validate.sh` passes locally.
- [ ] `python3 tools/validate_marketplace.py` passes locally.
- [ ] Any new/changed skill is **self-contained** (no `../` references outside the skill dir).
- [ ] Added or updated an **eval** for behavior I changed (where applicable).

## Privacy attestation (required)

- [ ] No PII, secrets, tokens, real names/emails, absolute paths, private URLs, or verbatim transcript excerpts anywhere in this change.
- [ ] Any intentional *fake* secrets exist only in an `evals/files/` or `examples/` fixture and are obviously synthetic.
- [ ] No config sets `privacy.allowTranscriptExcerpts: true` or `privacy.redactionPreview: false`.

## Notes for reviewers

<!-- Anything you want a reviewer to look at closely. -->
