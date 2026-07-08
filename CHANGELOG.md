# Changelog

All notable changes to the `skill-reflect` core skill are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version here tracks `skills/skill-reflect/VERSION` — the portable core skill that
authors vendor into their own plugins. The `skill-reflect-maintainer` tooling uses this
file and `VERSION` to tell authors when their vendored copy is behind (a **local**
comparison — no telemetry, no phoning home).

## [Unreleased]

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

[Unreleased]: https://github.com/Redth/skills/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Redth/skills/releases/tag/v1.0.0
