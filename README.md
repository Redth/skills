# Redth/skills

**Redth's cross-agent skills marketplace.** A [Claude Code plugin
marketplace](https://code.claude.com/docs/en/plugin-marketplaces) of portable,
privacy-conscious [Agent Skills](https://code.claude.com/docs/en/skills) that
also work on Copilot CLI, Gemini CLI, opencode, Amp, and any agent that can
invoke a skill by name.

## Plugins

Each plugin gets its own section below with an elevator pitch, a **consumer**
quick start (using it), and an **author** quick start (shipping it with your own
skills).

| Plugin | Elevator pitch | Jump to |
|---|---|---|
| **`skill-reflect`** | A privacy-conscious feedback loop that reflects on how the **distributed skills** you used actually performed, then routes scrubbed, actionable findings (plus verifiable evals) back to their authors. | [↓ skill-reflect](#skill-reflect) |

---

# skill-reflect

**Skills shipped via plugins and marketplaces have no feedback loop once
deployed.** When an agent follows stale guidance, retries a broken command, or
works around a missing case, that signal normally disappears. `skill-reflect`
captures it — with your consent — scrubs PII, and turns it into a
structured, actionable report for the skill's author, complete with a proposed
fix and a machine-checkable eval.

- 🔒 **Consent-gated & local-first.** Default output is a Markdown file on your
  machine. Nothing is sent anywhere without a second, explicit approval.
- 🕵️ **PII-conscious.** Names, emails, tokens, keys, paths, machine names, private
  URLs, and verbatim excerpts are paraphrased and scrubbed, with a deterministic
  scrubber running as a backstop under the model.
- 🌐 **Portable.** One prompt-driven skill that runs on Claude Code, Copilot CLI,
  Gemini CLI, opencode, Amp, and Tier C hosts like Cursor/Codex/Windsurf.

## For consumers — using skill-reflect

Install once, then let it review the skills you use.

**Claude Code:**

```text
/plugin marketplace add Redth/skills
/plugin install skill-reflect@redth-skills
```

Installing also wires two **opt-in, local-only** lifecycle hooks
(`SessionStart` / `SessionEnd`) that cheaply stage a "pending review" marker when
a distributed skill hit friction, and offer a non-blocking nudge next session.
**No AI and no network calls run in the hook** — the actual review only happens
when you explicitly ask for it. Disable anytime with
`"nudge": {"enabled": false}` in `skill-reflect.config.json`, or by uninstalling.

**Any agent** — just say:

> reflect on the skills I used this session.

**Other agents** use the same portable skill; the hook layer is a progressive
enhancement:

| Agent | How | Path |
|---|---|---|
| **Copilot CLI** | Automation extension (`onSessionEnd` staging + `onSessionStart` nudge) | [`integrations/copilot-cli/`](./integrations/copilot-cli/) |
| **Claude Code** | Auto via the plugin, or manual settings snippet | [`integrations/adapters/claude-code/`](./integrations/adapters/claude-code/) |
| **Gemini CLI / opencode / Amp** | Per-agent hook adapters (Tier A/B) | [`integrations/adapters/`](./integrations/adapters/) |
| **Cursor / Codex / Windsurf** | Explicit invocation + static `AGENTS.md` nudge (Tier C) | [`integrations/adapters/static/`](./integrations/adapters/static/) |

## For authors — shipping skill-reflect with your own skills

Want privacy-conscious field feedback for the skills *you* publish? The recommended
path is **vendoring**: bundle a copy of `skill-reflect` inside your own plugin,
pre-scoped to your skills and routed to your repo, so every user who installs
your plugin gets the feedback loop — no dependency on them installing anything
extra.

### Set it up (once)

The workflow, in short:

1. **Install** the `skill-reflect` plugin in your dev environment. It bundles the
   dev-time **`skill-reflect-maintainer`** skill (never shipped to your users).
2. **Adopt** — ask your agent *"adopt skill-reflect into this plugin"*. The
   maintainer copies the review skill + hooks into your plugin, merges your
   `hooks.json`, scopes it to your skills, pins the upstream version in
   `.skill-reflect-vendor.json`, and appends an "Improve This Skill" block to each
   in-scope `SKILL.md`.
3. **Stay current** — a local-only, no-network, no-AI `SessionStart` check nudges
   you when your vendored copy falls behind. Ask *"update skill-reflect"* to
   re-sync (your config and wording are preserved; drift is flagged).
4. **Pairs with [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator).**
   skill-creator writes *synthetic, author-side* evals before you ship;
   skill-reflect emits *real-world* evals in the same `evals.json` shape, so field
   findings drop straight into skill-creator's loop and re-run.

### Once it's live — the loop from your users

After you ship, the feedback loop runs on your users' machines with no action
required from you. Here is what a single cycle looks like end to end:

1. **A user hits friction.** During a normal session, one of your skills sends the
   agent down a stale path, a retried command, or a workaround. The vendored
   `SessionEnd` hook stages a tiny local marker — **no AI, no network.**
2. **They get a gentle nudge.** Next session, the `SessionStart` hook offers a
   non-blocking prompt to review. The user can ignore it; nothing else happens.
3. **They opt in to a review.** `skill-reflect` reflects on that session locally,
   drafts a scrubbed Markdown report with a proposed fix and a verifiable eval,
   and shows the user a redaction preview before writing anything.
4. **They opt in to send.** Only on a second, explicit consent does it run
   `gh issue create` against the repo you set as `--destination` at adopt time. If
   they decline, the report stays a local file and you never see it — that's by
   design.
5. **You receive a high-signal issue.** What lands in your repo is a PII-scrubbed
   issue: the friction pattern, a concrete `proposedFix`, and a ready-to-run eval
   in both the skill-creator and portable formats.
6. **You close the loop.** Triage it like any bug report: drop the eval into your
   suite, confirm it fails, apply the fix, confirm it now passes, and ship the
   update. Your users pull the fix through your normal plugin update path.

Coverage is opportunistic and consent-gated: you only hear from users who both hit
friction *and* choose to send. Volume is intentionally low, so treat each issue as
a concentrated, real-world signal rather than routine noise.

📘 **Full setup, install, and update/maintenance guide:
[AUTHORS.md](./AUTHORS.md)** (adoption models, the `adopt`/`update`/`doctor`
engine, wiring reflection into more skills, and dedupe behavior). Binding spec:
[`docs/CONTRACT.md` §11](./docs/CONTRACT.md). Interop details:
[`docs/skill-creator-interop.md`](./docs/skill-creator-interop.md).

## Non-negotiables

- 🔒 **Consent-gated.** Nothing leaves your machine without explicit approval — two
  gates: consent to *review*, then consent to *send* (per destination).
- 🕵️ **PII-conscious.** Names, emails, tokens, keys, paths, machine names, private
  URLs, and verbatim transcript excerpts are kept out of artifacts — values are
  paraphrased, and a deterministic scrubber runs as a backstop under the model.
- 🌐 **Local-first.** Default output is a Markdown file. GitHub filing is an explicit
  `gh` action you approve. The hooks never touch the network.

---

## Repository layout

```
.claude-plugin/marketplace.json   # marketplace manifest (this repo)
skills/skill-reflect/             # the portable core skill (SKILL.md + references/ scripts/ evals/ templates/)
skills/skill-reflect-maintainer/  # dev-time author tooling: vendor/update/doctor skill-reflect
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

## License

[MIT](./LICENSE) © Jonathan Dick
