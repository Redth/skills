# Privacy & Scrub Reference

> **Authority:** CONTRACT.md §0 (two non-negotiables) · §2 (privacy config) · §7 (scrubber contract)
> **Applies to:** every artifact, preview, issue body, eval, and data staged or transmitted by skill-reflect.

---

## 1. Mandatory scrub list

The following **MUST NEVER appear** in any artifact, redaction preview, GitHub issue body,
pending marker, eval fixture, or inter-component data:

| Class | Examples |
|---|---|
| Real names | Any person's full name, first name, or display name |
| Email addresses | `alice@example.com` |
| Usernames / handles | GitHub handles, OS usernames, IAM user names |
| Session IDs | Opaque session identifiers from any agent runtime |
| Absolute file paths | `/Users/alice/…`, `/home/bob/…`, `C:\Users\carol\…` |
| Machine / host names | Laptop names, internal server hostnames |
| Private URLs | Any URL containing credentials, tokens, or user-specific path segments |
| Tokens & credentials | GitHub PATs, AWS access/secret keys, Slack tokens, Google API keys, JWT, bearer tokens, API keys |
| PEM / private keys | Any `-----BEGIN PRIVATE KEY-----` block or equivalent |
| High-entropy secrets | Strings that exhibit high Shannon entropy and look like generated secrets |
| Request / response bodies | Verbatim HTTP request/response content |
| Screenshots | Images of any user's screen, terminal, or browser |
| Verbatim transcript excerpts | Any raw text copied from the agent's session transcript |
| Product / project / brand names | App, product, service, brand, or internal project/codename that identifies what was being built |
| App type / domain identifiers | Descriptions that give away the app's industry, purpose, or category (e.g. "a fintech payments dashboard", "a medical records portal") |
| Implementation-revealing details | Repro steps, feature names, data models, screen/route names, or business logic specific enough to fingerprint the real app |

---

## 2. Paraphrase rules

1. **Refer to the variable, flag, or tool name — never its value.**
   - ✗ `"The API key sk-abc123… was passed to --api-key"`
   - ✓ `"The --api-key flag was invoked with a value from the environment"`

2. **Describe what happened; never quote it.**
   - ✗ `"Error: FileNotFoundError: /Users/alice/data/config.json"`
   - ✓ `"A file-not-found error occurred when loading the config from a user-specific path"`

3. **Generalise; never name individuals.**
   - ✗ `"Alice ran the deploy command"`
   - ✓ `"The deploy command was invoked"`

4. **Summarise tool output; never paste it verbatim.**
   - ✗ `"The model returned: 'Here is your detailed answer…'"`
   - ✓ `"The model provided an explanation of the requested topic"`

5. **Report patterns, not payloads.**  When describing a tool failure, say *what the tool
   was asked to do* and *what the failure pattern was*; never include the actual arguments
   or return values.

---

## 2a. Domain & implementation abstraction

> **Authority:** CONTRACT.md §0.3. This is a semantic scrub the **model** performs — the
> deterministic backstop can only catch terms someone thought to list, so the model is the
> primary defense here.

The feedback is about **how a skill behaved**, never **what the user was building**. Two
sessions that hit the same skill bug should produce interchangeable feedback regardless of
the app, industry, or company involved.

### Rules

1. **Never name the product, app, brand, or project.** Not the real name, not the internal
   codename, not a lightly-disguised version of it. Refer to "the project" or "the app".
2. **Never reveal the app's type, industry, or purpose** when it isn't required to explain
   the skill's failure. "A web app" is usually enough; "a hospital patient-intake portal" is
   not.
3. **Strip domain-specific nouns.** Feature names, entity/table names, route and screen
   names, and business rules are all fingerprints. Replace them with generic analogues
   ("a record", "a list view", "a form field").
4. **Recast reproduction steps as an invented, analogous scenario.** Keep the *shape* of the
   friction — the sequence that made the skill stumble — but relocate it into a neutral,
   made-up context that shares none of the original specifics. The reader must be able to
   reproduce the *skill* problem without learning anything about the real app.
5. **Preserve only what the author needs to fix the skill:** the tool/flag/step involved,
   the failure pattern, and the corrected behavior. Everything else is domain noise.

### Repro before / after (all synthetic)

**Before (leaks the domain — never emit this):**

> While wiring the **MediTrack** patient-intake portal, I asked the skill to scaffold a
> `PatientVisit` model with an `insuranceClaimId` foreign key. It generated a migration
> using the old `belongs_to` syntax, so the claims-reconciliation screen failed to load.

**After (analogized — safe to emit):**

> Using the skill to scaffold a data model with a foreign key to a related record, it
> emitted a migration using an outdated association syntax; a view that depended on that
> relationship then failed to load. Reproduce with any two related models where one
> references the other.

### What changed and why

| Leaked detail | Action |
|---|---|
| `MediTrack` (product name) | Removed — refer to "the skill" / "the app" |
| "patient-intake portal" (app type/industry) | Generalized to "an app" |
| `PatientVisit`, `insuranceClaimId`, "claims-reconciliation screen" | Replaced with generic analogues ("a data model", "a foreign key", "a view") |
| The specific repro walkthrough | Recast as a neutral, reproducible scenario that still exercises the skill bug |

The **friction mechanism** (stale association syntax in a generated migration) is fully
preserved; the **domain** is gone.

---

## 3. Redaction-preview protocol

> `privacy.redactionPreview` is **always `true`** — see CONTRACT.md §2.  
> This protocol cannot be disabled by any configuration.

### Steps (always in this order)

1. **Model paraphrase scrub** — the model rewrites its draft artifact in its own words,
   applying all rules in §2.  This is the primary line of defense.

2. **Deterministic backstop** — `scripts/scrub.py` runs over the model-scrubbed draft,
   applying regex/entropy-based rules as a defense-in-depth layer.

3. **Preview display** — the fully scrubbed artifact is shown to the user for review and
   optional editing.  *Nothing is written to disk or transmitted at this point.*

4. **User approval** — the artifact is written to `.skill-feedback/` only after the user
   explicitly approves (Gate 1, §4 below).

5. **Send gate** — any transmission to a remote destination (e.g. GitHub issue) requires
   separate explicit approval (Gate 2, §4 below).

---

## 4. Two consent gates

### Gate 1 — Consent to review (scope-bounded)

*"Would you like to review feedback for skill `<name>` from this session?"*

- Scope is pinned to the exact skill(s) and session identified at invocation time.
- The user may decline; nothing happens.
- The user may edit the displayed draft before it is saved or sent.
- Gate 1 approval does **not** imply any data leaves the machine.
- The artifact is written to `.skill-feedback/<date>-<slug>.md` only after Gate 1.

### Gate 2 — Consent to send (per destination)

*"Send this feedback as a GitHub issue to `<owner/repo>`?"*

- Asked separately, per destination, after Gate 1.
- Silence or ambiguity = no send.
- One Gate 2 approval covers exactly one send to exactly one destination.
- Re-use of an approval for a different destination is never permitted.
- Sending is performed via `gh issue create` (CONTRACT.md §6) — no other network call is made.

---

## 5. How the model scrub and deterministic backstop layer together

```
Session content (transcript, tool calls, outputs)
         │
         ▼
 ┌─────────────────────────────────────────────┐
 │  Model paraphrasing scrub   ← PRIMARY       │
 │  • Rewrites in the model's own words        │
 │  • Catches semantic PII: names, context,    │
 │    intent — things patterns can't see       │
 │  • Produces the draft artifact              │
 └────────────────────┬────────────────────────┘
                      │  draft (model-scrubbed)
                      ▼
 ┌─────────────────────────────────────────────┐
 │  scrub.py deterministic backstop  ← DEFENSE │
 │  IN DEPTH (never the only defense)          │
 │  • Regex/entropy rules on the draft text    │
 │  • Catches residual literal PII the model   │
 │    may have missed                          │
 │  • Never emits any redacted value           │
 └────────────────────┬────────────────────────┘
                      │  scrubbed draft
                      ▼
        Redaction preview → user review/edit (§3)
                      │
                  Gate 1 ▼
              Written to .skill-feedback/
                      │
                  Gate 2 ▼
            gh issue create  (if approved)
```

### When to run `scrub.py`

Run on **every** piece of content staged to disk or included in an artifact or issue body —
always, with no exceptions, even if the model scrub was thorough:

```bash
python3 skill-reflect/scripts/scrub.py draft.md --report --fail-on-secret \
  $(printf -- '--term %q ' "${redactTerms[@]}") \
  $(printf -- '--pattern %q ' "${extraScrubPatterns[@]}")
```

Pass any `privacy.redactTerms` (product/app/project names) as `--term` and any
`privacy.extraScrubPatterns` as `--pattern` so the deterministic layer also catches
configured domain terms (category `domain-term`) and custom patterns (category `custom`).
These are a **backstop** for the domain abstraction in §2a — the model's semantic rewrite is
still the primary defense, because product names and implementation details cannot be fully
enumerated in advance.

If `--fail-on-secret` exits non-zero, the artifact **must be withheld** and the user
notified; do not proceed to the preview step.

---

## 6. "What good looks like" — before / after example

> **All data below is synthetic.** No real credentials, names, or systems are referenced.

### Before (raw session content — would never leave the agent)

```
Tool call : file_read
  path    : /Users/jdoe/projects/acme-api/config.json
  result  : { "api_key": "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" }

Error     : failed to connect to 10.0.0.42 using token xoxb-111-222-xxxSECRETyyy
Contact   : Jane Doe <jane@example.com>
```

### After (model paraphrase → scrub.py → ready for preview)

```
Tool: `file_read`
The config file at a user-specific path was read successfully.
It contained an `api_key` field; the value was not used and is not recorded here.

Error: a connection failure occurred when contacting an internal service using
a bot credential. The credential value is not recorded.

Contact: the skill author (contact details withheld).
```

### What changed and why

| Raw value | Action | Why |
|---|---|---|
| `/Users/jdoe/projects/…` | Described as "user-specific path"; `scrub.py` replaces literal with `[REDACTED:path]` | Absolute path with username |
| `ghp_aBcDeFgH…` | Described as "api_key field"; `scrub.py` catches as `github-token` | GitHub PAT |
| `10.0.0.42` | Described as "internal service"; `scrub.py` catches as `ip-address` | Internal IP address |
| `xoxb-111-222-xxxSECRETyyy` | Described as "bot credential"; `scrub.py` catches as `slack-token` | Slack bot token |
| `jane@example.com` | Described as "skill author"; `scrub.py` catches as `email` | Email address |

The model scrub handles *meaning* (paraphrase); `scrub.py` handles *literals* (pattern matching).
Both layers are always applied.
