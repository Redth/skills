# Vendoring skill-reflect into Your Plugin

This guide is for **plugin / marketplace authors** who want to ship `skill-reflect`
inside their own plugin so that all session feedback from their skills is automatically
pre-scoped and routed to their own repository — with no end-user configuration required.

---

## When to vendor vs. standalone

| | **Standalone** | **Vendored** |
|---|---|---|
| Who installs it | The end user installs one shared copy | You ship it inside your plugin |
| Scope | All distributed skills the user has installed | Only your plugin's skills (pre-scoped) |
| Feedback routing | User configures destination, or the resolver looks it up | Hardcoded to your repo (Confirmed confidence) |
| Nudge wording | Generic skill-reflect copy | You can name your plugin in the nudge text |
| Maintenance | Upstream handles updates | You re-vendor when skill-reflect releases |

**Choose vendored when:**
- You want feedback from your skills routed to *you* without asking users to configure anything.
- You want the allowlist pre-scoped so `skill-reflect` only ever reflects on your plugin's skills.
- You want custom nudge wording that names your plugin.

**Choose standalone when:**
- You want users to bring one copy that reviews all their installed skills.
- You do not want to maintain a vendored copy.

---

## What to copy

From the `skill-reflect` source repository, copy:

| Source path | Target path (in your plugin) | Required? |
|---|---|---|
| `skill-reflect/` | `<your-plugin>/skill-reflect/` | **Required** — the portable core skill |
| `skill-reflect-auto/` | `<your-plugin>/skill-reflect-auto/` | Optional — Copilot CLI automation extension |

The core skill (`skill-reflect/`) is **agent-agnostic** — it works on every agent
via explicit invocation or the static nudge block in your skills' `SKILL.md` files.
The automation extension (`skill-reflect-auto/`) adds hands-free Copilot CLI lifecycle
tracking (no AI, no network) and is a progressive enhancement: users get value from
the core skill even without it.

After copying, drop a `skill-reflect.config.json` at the root of your plugin directory
(see §Pre-configure below).

### Realistic post-vendoring layout

```
my-plugin/
│
├── skill-reflect.config.json          ← vendor-provided config (pre-scoped + routed)
│
├── skills/                            ← your plugin's own skills
│   ├── my-skill-a/
│   │   └── SKILL.md                  ← include "Improve This Skill" nudge block here
│   └── my-skill-b/
│       └── SKILL.md
│
├── skill-reflect/                     ← vendored core skill (full copy)
│   ├── SKILL.md
│   ├── assets/
│   ├── references/
│   ├── scripts/
│   └── templates/
│
└── skill-reflect-auto/                ← optional: Copilot CLI automation extension
    ├── extension.mjs
    └── extension.json
```

---

## How to pre-configure (`skill-reflect.config.json`)

Drop a `skill-reflect.config.json` at the root of your plugin directory. The minimum
vendored config:

```json
{
  "version": 1,
  "mode": "vendored",
  "scope": {
    "skills": ["my-skill-a", "my-skill-b"],
    "excludeSkills": ["skill-reflect", "skill-reflect-auto"]
  },
  "destination": {
    "mode": "issue",
    "repo": "your-org/your-repo"
  },
  "nudge": {
    "enabled": true,
    "frictionThreshold": 2,
    "throttleHours": 12,
    "neverForSkills": [],
    "neverForRepos": []
  },
  "privacy": {
    "extraScrubPatterns": [],
    "redactionPreview": true,
    "allowTranscriptExcerpts": false
  }
}
```

See `skill-reflect.config.vendored.example.json` in this directory for a fully-filled
realistic example, and `skill-reflect.config.schema.json` in the repo root for the
authoritative JSON Schema.

### Key fields

**`mode: "vendored"`**  
Signals to the skill and the provenance resolver that this is a vendored deployment.
The resolver bypasses SKILL.md frontmatter and registry lookups and returns
**Confirmed** confidence immediately (Step 3 of `skill-reflect/references/provenance-routing.md`).

**`destination.repo: "your-org/your-repo"`**  
Hardcodes the feedback destination. When `mode` is `"vendored"` and `destination.repo`
is set, provenance confidence is **Confirmed** — the resolver does not need to read
any SKILL.md frontmatter or registry. The two consent gates and the mandatory scrub
still apply; this only affects where the feedback is offered to be sent.

**`scope.skills`** (allowlist)  
List exactly the skill names your plugin ships. An empty list would match *all*
distributed skills; in vendored mode always provide an explicit allowlist so the skill
never reflects on unrelated skills the user might also have installed.

**`scope.excludeSkills`**  
Must always include `"skill-reflect"` and `"skill-reflect-auto"`. These two are
excluded by design (CONTRACT §9) — the skill never reflects on itself.

**`nudge.frictionThreshold`**  
Minimum friction signals in a session before a marker is staged. Default is `2`.
Increase if your skills are complex and short friction bursts are normal; decrease if
you want earlier capture.

**`nudge.throttleHours`**  
Minimum hours between nudges. Default is `12`. In a vendored deployment you may want
`24` to reduce noise for active users.

**`privacy.extraScrubPatterns`**  
Additional regex patterns to redact on top of the built-in deterministic scrubber list.
Add patterns specific to your domain (e.g., internal token formats). The two privacy
constants (`redactionPreview: true`, `allowTranscriptExcerpts: false`) are hard-enforced
regardless of what this file says.

---

## Provenance in vendored mode

When `mode: "vendored"` and `destination.repo` is set, the provenance resolver short-
circuits to **Step 3** of `skill-reflect/references/provenance-routing.md`:

> **Step 3 — Vendored Config (`destination.repo`) — Confidence: `Confirmed`**
>
> When `skill-reflect.config.json` has `"mode": "vendored"` and
> `"destination": { "repo": "owner/repo" }`, the destination is hardcoded to that repo.

This means:
- No SKILL.md frontmatter with `source_repo` is required.
- No registry lookup (`~/.skill-reflect/registry.json`) is performed.
- Confidence is immediately **Confirmed** — the highest level.

**However, vendored mode does NOT skip the safety model.** The two consent gates and
the mandatory deterministic scrub remain in force:

1. **Gate 1 (review consent):** The skill describes what it will read and produce;
   the user must approve before any session data is examined.
2. **Gate 2 (send consent):** After the user reviews and confirms the redaction preview,
   the skill offers to file a GitHub issue. The user must approve; the skill never
   auto-files.
3. **Mandatory scrub:** `scripts/scrub.py` runs as a deterministic backstop before any
   artifact is written or sent, regardless of config.

---

## Custom nudge wording

The skill surfaces two nudge text surfaces you can customize in your vendored copy:

### 1. Per-skill static nudge block (`skill-reflect/templates/improve-this-skill.md`)

Each of your skills' `SKILL.md` files should include a nudge block. Copy the template
from `skill-reflect/templates/improve-this-skill.md` and fill in your skill name and
repo. Example for a skill called `native-library-bindings`:

```markdown
<!-- BEGIN skill-reflect nudge -->

## Improve This Skill

**For the agent:** If this skill was used during the session and you or the user
encountered friction, you may offer a brief skill-quality review at a natural stopping
point:

> "This session used **native-library-bindings** (from the dotnet/maui-labs plugin).
> Want me to capture privacy-safe feedback for the MAUI Labs team using `skill-reflect`?"

If the user says **yes**, invoke the `skill-reflect` skill:

    Run skill-reflect. Skill used this session: native-library-bindings
    (source repo: dotnet/maui-labs).

<!-- END skill-reflect nudge -->
```

The `[skill-name]` and `[owner/repo]` placeholders from the template become your
skill's actual name and your plugin's repo. This text is static — the agent reads it
only to decide whether to *offer* a review; the actual review work is done by
`skill-reflect` on user consent.

### 2. Automation extension nudge message (`skill-reflect-auto/extension.mjs`)

If you ship `skill-reflect-auto/`, the `onSessionStart` hook emits a non-blocking
`session.log` nudge when a pending-review marker exists. The nudge text is in
`extension.mjs`. In your vendored copy you may edit that string to mention your plugin
by name (e.g., replacing `skill-reflect` with `skill-reflect for MAUI Labs`), so users
know the nudge is scoped to your skills.

> ⚠️ Keep the functional logic unchanged — only the display string is safe to edit.
> Re-check this string each time you re-vendor (see §Keeping in sync).

---

## Keeping the vendored copy in sync

Use `sync_vendor.sh` (in this directory) when a new version of `skill-reflect` is
released:

```sh
cd /path/to/skill-reflect-source   # a local checkout of the skill-reflect repo

./vendoring/sync_vendor.sh \
  --from /path/to/skill-reflect-source \
  --to   /path/to/your-plugin \
  --with-auto                       # omit if you don't ship skill-reflect-auto/
```

The script:
- Copies `skill-reflect/` (and optionally `skill-reflect-auto/`) from the source repo.
- Uses `rsync --delete` if available (preserves only upstream files); falls back to
  `cp -R` with a prior `rm -rf`.
- **Never overwrites** an existing `<to>/skill-reflect.config.json`. A note is printed
  if one is found; you keep your vendored config across updates.
- After syncing, review the schema (`skill-reflect.config.schema.json`) to confirm your
  config uses no deprecated or renamed fields.

> **Preserve your config.** `skill-reflect.config.json` is the only file you own in
> the vendored layout. Keep it in version control and do not delete it during updates.

---

## Privacy / consent reminder

> ⚠️ **Vendoring does NOT weaken the privacy model.**

The vendor config only changes two things:
1. The **default destination** (your repo, hardcoded).
2. The **scope** (only your plugin's skills).

Everything else is unchanged:
- Two consent gates are always required (review consent, then send consent).
- The deterministic scrubber (`scripts/scrub.py`) always runs as a backstop.
- `privacy.redactionPreview` is hard-enforced as `true` — the user always sees the full
  proposed artifact before anything is written.
- `privacy.allowTranscriptExcerpts` is hard-enforced as `false` — verbatim transcript
  excerpts are never included; all content is paraphrased.
- Nothing leaves the user's machine without explicit approval at Gate 2.
- The local `.skill-feedback/` artifact is always created first; the GitHub issue is an
  additive, user-approved step.

You as a vendor **cannot** weaken these guarantees via config — the skill hard-enforces
them regardless of what the config file says.
