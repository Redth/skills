# skill-reflect-maintainer

Dev-time author tooling for vendoring `skill-reflect` into plugin repositories.

This plugin is for plugin/skill authors only. It is not redistributed to end users. It provides:

- `tools/adopt.py adopt` to vendor `skill-reflect`, hooks, schema, optional Copilot auto extension, config, and pin.
- `tools/adopt.py doctor` to check current version, drift, config, hooks, and per-skill nudge wiring.
- `tools/adopt.py update` to manually refresh the vendored copy after author approval.
- `skills/skill-reflect-maintainer` as a thin conversational wrapper over the deterministic engine.

No CI automation is installed. Updates are manual and author-approved.
