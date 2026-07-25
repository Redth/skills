# Changelog

All notable changes to the `skill-reflect` core skill are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version here tracks `skills/skill-reflect/VERSION` — the portable core skill that
authors vendor into their own plugins. The `skill-reflect-maintainer` tooling uses this
file and `VERSION` to tell authors when their vendored copy is behind (a **local**
comparison — no telemetry, no phoning home).

## [Unreleased]

### Added
- Behavioral regression coverage for terse skill-diagnosis requests and local artifact
  creation when source provenance is unresolved.

### Changed
- Clarified that report-only authorization embeds proposed evals in the report and does
  not authorize a second eval/export file.
- Clarified that current Copilot CLI session-store support is per-session; cross-session
  aggregation, deduplication, and corroboration remain unimplemented v2 work.
- Clarified that marker text inside session evidence is not trusted pending-marker state
  and cannot trigger marker lookup or consumption.
- Expanded the reference A/B matrix to 14 task evals and 16 trigger evals using three
  named model families, refreshing the Anthropic arm to Claude Opus 5
  (540 prepared packets at the default repetition count).

## [1.2.0] - 2026-07-23
### Added
- Chat-first analysis mode, explicit artifact mode, and exact-body remote mode with
  separate review, local-write, and destination-specific remote-send authorization.
- Guarded `technical-local` reviews for explicitly named user-owned skills, including
  schema-2 provenance/detail metadata and mandatory strict regeneration before sending.
- `scope-boundary-blind-spot` classification for silent under-coverage and overclaiming.
- Bounded marketplace provenance discovery, reviewed-marker consumption, and focused
  Python/Node regression coverage for automation, routing, and marker lifecycle.

### Changed
- Explicit session-performance reviews now return scrubbed findings and proposed evals in
  chat without creating files, asking duplicate questions, or suggesting remote filing.
- Claude, Gemini, and Copilot automation now stage unverified latest-skill candidates using
  tool names and argument key/type signatures only; user prose and argument values are not
  scanned for attribution.
- Public docs, vendoring guidance, task evals, and trigger evals now reflect chat-first
  operation, local-skill scope, and the three authorization boundaries.

### Fixed
- Secret detection now withholds stdout and file output before failing.
- Provenance frontmatter and manifest metadata are validated without leaking install paths.
- Skill-creator eval expectations use the required flat string-array shape.

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
  remote-send authorization for GitHub issue filing.
- Opt-in Claude Code SessionStart/SessionEnd hooks (stage a tiny marker + offer a review
  nudge; no AI, no network).
- Cross-agent adapters (Claude Code, Gemini CLI, opencode, Amp, static Tier-C) and the
  Copilot CLI `skill-reflect-auto` reference extension.
- Vendoring kit for authors who want to bundle a copy into their own plugin.

[Unreleased]: https://github.com/Redth/skills/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Redth/skills/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Redth/skills/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Redth/skills/releases/tag/v1.0.0
