# Changelog

All notable changes to the `skill-reflect` core skill are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version here tracks `skills/skill-reflect/VERSION` — the portable core skill that
authors vendor into their own plugins. The `skill-reflect-maintainer` tooling uses this
file and `VERSION` to tell authors when their vendored copy is behind (a **local**
comparison — no telemetry, no phoning home).

## [Unreleased]

## [1.1.0] - 2026-07-08
### Added
- **Domain / product abstraction as a hard privacy constraint** (CONTRACT §0.3). Feedback
  must never reveal product/app/brand/project names, the app's type or purpose, or
  implementation specifics; reproduction steps must be recast as invented, analogous
  scenarios that preserve the friction mechanism without the original domain.
- `scrub.py` deterministic backstop for domain leakage: new `extra_terms` / `extra_patterns`
  params and `--term` / `--terms-file` / `--pattern` CLI flags, redacting configured literal
  terms as `domain-term` and custom regexes as `custom`.
- New config field `privacy.redactTerms` (literal product/app/project names) to feed the
  scrubber's `--term` denylist.
### Changed
- Guidance updated across `SKILL.md`, `references/privacy-scrub.md` (new §2a with a repro
  before/after), `references/reporting.md`, `references/eval-format.md`, and the GitHub
  issue template so eval prompts and repro details use analogized, domain-free scenarios.
- Fixed Privacy-section text now states that product/domain specifics were scrubbed and
  reproduction details were recast as an invented, analogous scenario.

## [1.0.0] - 2026-07-07
### Added
- Initial release of the `skill-reflect` portable core skill: session-end friction
  detection, friction rubric + skill-improvement taxonomy, dual-format proposed evals
  (skill-creator `evals.json` + portable must-contain / must-not-contain), a
  deterministic PII/secret scrubber, provenance routing (frontmatter → manifest →
  vendored config → registry → ask), a local Markdown artifact, and explicit
  second-consent GitHub issue filing.
- Opt-in Claude Code SessionStart/SessionEnd hooks (stage a tiny marker + offer a review
  nudge; no AI, no network).
- Cross-agent adapters (Claude Code, Gemini CLI, opencode, Amp, static Tier-C) and the
  Copilot CLI `skill-reflect-auto` reference extension.
- Vendoring kit for authors who want to bundle a copy into their own plugin.

[Unreleased]: https://github.com/Redth/skills/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Redth/skills/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Redth/skills/releases/tag/v1.0.0
