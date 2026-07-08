# Maintainer update-check hook

This Claude Code `SessionStart` hook helps plugin authors notice when their vendored copy of `skill-reflect` is behind the version shipped with the `skill-reflect-maintainer` plugin.

It is **local-only**: no network, telemetry, AI, or auto-update. The hook only reads `.skill-reflect-vendor.json` from the current plugin tree and the local `VENDORED_SKILL_VERSION` file, compares semver strings, and prints one optional nudge.

Nudges are throttled per vendored pin for 24 hours in `$SKILL_REFLECT_HOME/maintainer-throttle.json` (default home: `~/.skill-reflect`). This is separate from the review nudge's `$SKILL_REFLECT_HOME/throttle.json`; the two hooks have different purposes and throttle independently.

Opt out by setting `nudge.enabled` to `false` in `.skill-reflect-vendor.json` or in a `skill-reflect.config.json` found by walking up from the current directory.

The Copilot CLI equivalent is a future addition; v1 ships only this Claude Code `SessionStart` hook.
