# Redth/skills

**Jonathan Dick's cross-agent skills marketplace.** A [Claude Code plugin
marketplace](https://code.claude.com/docs/en/plugin-marketplaces) of portable,
privacy-respecting [Agent Skills](https://code.claude.com/docs/en/skills) that
also work on Copilot CLI, Gemini CLI, opencode, Amp, and any agent that can
invoke a skill by name.

## Plugins

| Plugin | What it does |
|---|---|
| **[`skill-reflect`](./skills/skill-reflect/)** | Post-session reflection on how well the **distributed skills** you used actually performed. Detects friction, proposes a concrete fix **and** a verifiable eval, scrubs PII, writes a local Markdown report, and (only on an explicit second consent) files a GitHub issue to the skill's source repo. |

## Install (Claude Code)

```text
/plugin marketplace add Redth/skills
/plugin install skill-reflect@redth-skills
```

Installing the plugin also wires two **opt-in, local-only** lifecycle hooks
(`SessionStart` / `SessionEnd`) that cheaply stage a "pending review" marker when
a distributed skill hit friction, and offer a non-blocking nudge next session.
**No AI and no network calls run in the hook** — the actual review only happens
when you explicitly ask for it. Disable anytime with
`"nudge": {"enabled": false}` in `skill-reflect.config.json`, or by uninstalling
the plugin.

## Use on other agents

`skill-reflect` is a portable, prompt-driven skill — the hook layer is a
progressive enhancement. The core skill runs anywhere via explicit or nudged
invocation:

| Agent | How | Path |
|---|---|---|
| **Copilot CLI** | Automation extension (`onSessionEnd` staging + `onSessionStart` nudge) | [`integrations/copilot-cli/`](./integrations/copilot-cli/) |
| **Claude Code** | Auto via the plugin, or manual settings snippet | [`integrations/adapters/claude-code/`](./integrations/adapters/claude-code/) |
| **Gemini CLI / opencode / Amp** | Per-agent hook adapters (Tier A/B) | [`integrations/adapters/`](./integrations/adapters/) |
| **Cursor / Codex / Windsurf** | Explicit invocation + static `AGENTS.md` nudge (Tier C) | [`integrations/adapters/static/`](./integrations/adapters/static/) |

Or just say to any agent: *"reflect on the skills I used this session."*

## Non-negotiables

- 🔒 **Consent-gated.** Nothing leaves your machine without explicit approval — two
  gates: consent to *review*, then consent to *send* (per destination).
- 🕵️ **No PII, ever.** Names, emails, tokens, keys, paths, machine names, private
  URLs, and verbatim transcript excerpts are never included — values are
  paraphrased, and a deterministic scrubber runs as a backstop under the model.
- 🌐 **Local-first.** Default output is a Markdown file. GitHub filing is an explicit
  `gh` action you approve. The hooks never touch the network.

## Repository layout

```
.claude-plugin/marketplace.json   # marketplace manifest (this repo)
skills/skill-reflect/             # the portable core skill (SKILL.md + references/ scripts/ evals/ templates/)
hooks/                            # Claude Code plugin hooks (auto-wired on install)
integrations/
  copilot-cli/skill-reflect-auto/ # Copilot CLI automation extension (reference)
  adapters/                       # claude-code, gemini-cli, opencode, amp, static (Tier C)
vendoring/                        # copy skill-reflect into your own plugin, pre-scoped
examples/                         # sample artifacts + sample evals
docs/                             # CONTRACT.md (the interface spec every component honors) + design docs
tools/                            # local validation gates
```

## Contributing

Contributions welcome — see **[CONTRIBUTING.md](./CONTRIBUTING.md)**. Every change
is validated in CI (marketplace/manifest consistency, skill structure, unit tests,
and a privacy-guard job). Run the same gates locally:

```sh
tools/validate.sh                 # repo-wide: py_compile, unit tests, JSON/shell/node checks
python3 tools/validate_marketplace.py   # marketplace <-> plugin <-> skill consistency + privacy invariants
```

## Relationship to skill-creator

`skill-reflect` is the **field-feedback complement** to Anthropic's
[skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator):
skill-creator improves skills with *synthetic, author-side* evals; `skill-reflect`
produces the *real-world inputs* — friction observed in actual sessions — and emits
them as `evals.json`-shaped proposed evals that drop straight into skill-creator's loop.

## License

[MIT](./LICENSE) © Jonathan Dick
