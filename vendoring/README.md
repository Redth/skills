# vendoring/

This directory contains everything a **plugin or marketplace author** needs to vendor
`skill-reflect` into their own plugin — pre-scoped to their skills, with feedback
routed to their repository.

## Contents

| File / Dir | Purpose |
|---|---|
| [`vendor.md`](vendor.md) | **Start here.** Full step-by-step vendoring guide: when to vendor, what to copy, how to configure, provenance in vendored mode, custom nudge wording, keeping in sync, privacy reminder. |
| [`skill-reflect.config.vendored.example.json`](skill-reflect.config.vendored.example.json) | A fully-filled, schema-valid vendored config example (host: `dotnet/maui-labs`). Copy and adapt for your plugin. |
| [`sync_vendor.sh`](sync_vendor.sh) | POSIX shell helper to copy `skill-reflect/` (and optionally `skill-reflect-auto/`) from a source checkout into your plugin directory. Never overwrites your `skill-reflect.config.json`. |
| [`examples/dotnet-maui/`](examples/dotnet-maui/) | Worked example: vendoring into the `dotnet/maui-labs` plugin. Shows the post-vendoring directory layout, the per-host config, and how to embed the "Improve This Skill" nudge in each skill. |

## Quick start

```sh
# 1. Clone skill-reflect
git clone https://github.com/redth/skill-reflect /tmp/skill-reflect-src

# 2. Copy core (and optional automation extension) into your plugin
/tmp/skill-reflect-src/vendoring/sync_vendor.sh \
  --from /tmp/skill-reflect-src \
  --to   /path/to/your-plugin \
  --with-auto

# 3. Copy and adapt the vendored config
cp /tmp/skill-reflect-src/vendoring/skill-reflect.config.vendored.example.json \
   /path/to/your-plugin/skill-reflect.config.json
# Edit: set destination.repo, scope.skills, nudge thresholds, any extraScrubPatterns

# 4. Add "Improve This Skill" nudge blocks to your skills' SKILL.md files
#    (see vendor.md §Custom nudge wording)
```

## Vendored safety model

Vendoring **does not** weaken skill-reflect's privacy or consent guarantees. The vendor
config changes only the default *destination* (`destination.repo`) and *scope*
(`scope.skills`) — nothing else. The two mandatory consent gates (Gate 1: review
consent; Gate 2: send consent) remain in force, the deterministic scrubber always runs
as a backstop, `privacy.redactionPreview` is hard-enforced as `true`, and
`privacy.allowTranscriptExcerpts` is hard-enforced as `false`. Nothing leaves the
user's machine without their explicit approval. A local `.skill-feedback/` Markdown
artifact is always created first; GitHub issue filing is an additive, user-approved
step only.
