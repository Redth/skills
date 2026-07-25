---
document_version: v2
status: DESIGNED — NOT IMPLEMENTED IN v1
created: 2026-07-07
authors: [design session]
---

# skill-reflect v2 — Cross-Session Aggregation Design

> **v2 — DESIGNED, NOT IMPLEMENTED IN v1.**
> This document describes a planned future capability. No code described here is
> shipped. The v1 interface contract (`docs/CONTRACT.md`) remains the sole source
> of truth for all currently implemented behaviour. Every component described below
> must remain consistent with the v1 CONTRACT when implemented; deviations require
> a CONTRACT revision first.

---

## Contents

1. [Motivation & scope](#1-motivation--scope)
2. [Data model](#2-data-model)
   - 2.1 [Pending queue & JSONL staging](#21-pending-queue--jsonl-staging)
   - 2.2 [Local SQLite store — DDL](#22-local-sqlite-store--ddl)
   - 2.3 [Fingerprint design](#23-fingerprint-design)
   - 2.4 [Corroboration model](#24-corroboration-model)
3. [Lifecycle / state machine](#3-lifecycle--state-machine)
4. [Batch review command (UX design)](#4-batch-review-command-ux-design)
5. [Anonymized aggregate posture](#5-anonymized-aggregate-posture)
6. [Privacy & consent](#6-privacy--consent)
7. [Compatibility & migration from v1](#7-compatibility--migration-from-v1)
8. [Open questions / risks](#8-open-questions--risks)

---

## 1. Motivation & scope

### The v1 gap

v1 is intentionally **single-session**: the automation extension (`skill-reflect-auto`,
CONTRACT §8) cheaply stages a marker file in `$SKILL_REFLECT_HOME/pending/<sessionId>.json`
every time a distributed skill accrues friction above the nudge threshold. The portable
core skill then, on explicit consent, classifies findings and produces a Markdown artifact
or GitHub issue for that one session.

The gap: **markers pile up across sessions but are never cross-referenced.** A skill bug
that irritates a user in session 12, session 19, and session 31 generates three independent
artifacts — or worse, three nudges the user declines, producing three orphaned marker
files nobody reads. The author never learns the finding appeared multiple times. A single
session's friction could be a fluke; the same friction pattern corroborated across
N ≥ 3 sessions is a confident, actionable signal.

v2 closes this gap by adding a **local aggregation layer** between the cheap staging step
and the expensive distillation step: findings are fingerprinted, deduplicated, and
corroborated across sessions before any model work or network action occurs.

### In scope for v2

| Capability | Description |
|---|---|
| **Local queue** | An append-only SQLite store + JSONL staging log in `$SKILL_REFLECT_HOME/` that accumulates raw markers (§8) and classified `FrictionFinding` records (§3) across sessions |
| **Fingerprint & dedupe** | A deterministic, PII-free fingerprint per finding that enables exact-match deduplication on ingest |
| **Near-duplicate merge** | FTS5-based similarity search to detect and merge paraphrase variants of the same underlying issue |
| **Corroboration scoring** | A numeric score (0–1) that rises as the same finding appears in more sessions, enabling prioritization |
| **Batch distillation** | An explicit, review-authorized "review queue" workflow that runs the model once over the corroborated queue and produces consolidated chat findings |
| **Tombstones & pruning** | TTL-based cleanup and explicit "forget" controls so the queue stays bounded and sent findings are never re-reported |
| **Optional aggregate posture** | An OPT-IN mode for vendored deployments to share k-anonymous trend counts (never raw findings) with a marketplace or skill author |

### Out of scope for v2

- **Any automatic network send.** The queue is local-first. Every remote action requires
  an exact-body preview and fresh destination-specific send authorization.
- **Raw telemetry upload.** No per-session data, no transcripts, no verbatim content
  is ever transmitted. The aggregate posture (§5) emits only taxonomy-typed counts.
- **Changes to v1 adapters or the extension.** The §8 marker shape is the forward-compatible
  input format. Adapters require zero modification.
- **Real-time streaming aggregation.** The queue is processed on request ("review my pending
  feedback"), not in a background daemon.
- **Cross-user aggregation.** Each user's queue is local to their machine. v2 does not pool
  data from multiple users; the aggregate posture is a threshold-gated count summary, not
  a multi-user join.

---

## 2. Data model

### 2.1 Pending queue & JSONL staging

#### Paths (extending CONTRACT §2)

| Path | Purpose |
|---|---|
| `$SKILL_REFLECT_HOME/pending/<sessionId>.json` | **v1 marker** (§8 shape). Written by adapters/extension. Unchanged. |
| `$SKILL_REFLECT_HOME/pending/findings.jsonl` | **v2 staging log** (append-only). One JSON line per `FrictionFinding` staged by the core skill after a session review. Created by v2; ignored by v1 components. |
| `$SKILL_REFLECT_HOME/queue.db` | **v2 SQLite store**. Created and managed by the v2 aggregation layer. |

The JSONL log is an append-only pre-ingest buffer. Its function is to accept staged
findings from the core skill without requiring the SQLite write path to be in the session's
hot path. A separate ingest pass (triggered at "review queue" time or lazily on session
start) drains the JSONL into `queue.db`. This also makes recovery simple: if `queue.db`
is deleted, ingest can reconstruct it from the JSONL log and the `pending/*.json` files.

#### JSONL record shape

Each line in `findings.jsonl` is a JSON object extending the §3 `FrictionFinding` with
two additional staging fields:

```jsonc
{
  // --- §3 FrictionFinding fields (verbatim, already PII-free) ---
  "id": "a3f9c1b2",                // v1 fingerprint: hash of {skill, pattern, normalized-summary}
  "skill": "container-toolkit",
  "sourceRepo": "acme/container-toolkit",
  "severity": "High",
  "confidence": "Likely",
  "outcome": "Worked-around",
  "pattern": "stale-guidance",
  "category": "wrong-or-stale-guidance",
  "summary": "The skill's --region flag no longer accepted in v2 of the underlying CLI; agent retried with the legacy flag and succeeded after two failures.",
  "evidence": "Tool call to skill-owned deploy command exited with 'unknown flag --region'; two retries; agent switched to undocumented positional argument.",
  "proposedFix": "Update the deploy-command example in SKILL.md to reflect the v2 CLI's positional-argument form and remove the --region flag example.",
  "proposedEval": {
    "id": "ct-a3f9c1b2",
    "prompt": "Deploy the staging container image to the eu-west zone using container-toolkit.",
    "must_contain": ["positional zone argument", "no --region flag"],
    "must_not_contain": ["--region"]
  },

  // --- v2 staging extensions ---
  "stagedAt": "2026-07-07T21:03:11Z",     // ISO8601; set by core skill at stage time
  "sessionId": "ses_abc123"               // which session produced this finding
                                           // NEVER propagated into fingerprint or cluster output
}
```

**PII posture at stage time:** The core skill (which already runs the §7 scrubber before
producing v1 artifacts) MUST also run `scrub_text()` on `summary`, `evidence`, and
`proposedFix` before appending to the JSONL log. The JSONL is a local disk artifact; the
scrub is a belt-and-suspenders requirement, not a substitute for not collecting PII in the
first place.

### 2.2 Local SQLite store — DDL

The SQLite store (`queue.db`) is the authoritative state for the v2 aggregation layer.
File location: `$SKILL_REFLECT_HOME/queue.db`. The schema is versioned; migrations are
additive (no destructive `ALTER` or `DROP` without a major schema version bump).

All ISO8601 timestamps are UTC. All JSON columns store compact (no-whitespace) serialized
JSON. All text comparisons are case-sensitive unless stated otherwise.

```sql
-- ─────────────────────────────────────────────────────────────
-- Schema metadata
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '2');
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('created_at', 'ISO8601-placeholder');

-- ─────────────────────────────────────────────────────────────
-- markers — raw §8 automation markers ingested from pending/*.json
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS markers (
  session_id    TEXT PRIMARY KEY,          -- from §8 "sessionId"
  ended_at      TEXT NOT NULL,             -- ISO8601 from §8 "endedAt"
  skills_json   TEXT NOT NULL,             -- JSON array: ["skill-a","skill-b"]
  friction_json TEXT NOT NULL,             -- JSON object: {"skill-a": 3}
  reason        TEXT NOT NULL,             -- complete|error|abort|timeout|user_exit
  ingested_at   TEXT NOT NULL,             -- ISO8601; set at ingest time, not from marker
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','ingested','pruned'))
);

CREATE INDEX IF NOT EXISTS idx_markers_status     ON markers (status);
CREATE INDEX IF NOT EXISTS idx_markers_ended_at   ON markers (ended_at DESC);
CREATE INDEX IF NOT EXISTS idx_markers_ingested   ON markers (ingested_at DESC);

-- ─────────────────────────────────────────────────────────────
-- findings — classified FrictionFindings (§3) staged by core skill
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS findings (
  fingerprint           TEXT NOT NULL,   -- v2 dedupe key (see §2.3); may differ from v1 id
  session_id            TEXT NOT NULL,   -- ingest idempotency key; never exposed in output
  skill                 TEXT NOT NULL,   -- taxonomy: skill name
  source_repo           TEXT,            -- nullable; resolved via provenance routing
  severity              TEXT NOT NULL    CHECK (severity IN ('High','Medium','Low','Unknown')),
  confidence            TEXT NOT NULL    CHECK (confidence IN ('Confirmed','Likely','Possible')),
  outcome               TEXT NOT NULL    CHECK (outcome IN ('Solved','Worked-around','Unresolved')),
  pattern               TEXT NOT NULL    CHECK (pattern IN (
                                           'advertised-feature-failed','repeated-command-loop',
                                           'workaround-chain','stale-guidance',
                                           'scope-boundary-blind-spot','unclear-routing',
                                           'trigger-miss','false-trigger')),
  category              TEXT NOT NULL    CHECK (category IN (
                                           'missing-case','wrong-or-stale-guidance',
                                           'missing-detail','missing-or-failing-asset',
                                           'unclear-routing','trigger-problem')),
  normalized_summary    TEXT NOT NULL,   -- output of normalize_text(summary); used by FTS
  proposed_fix          TEXT NOT NULL,   -- paraphrased; scrubbed
  proposed_eval_json    TEXT NOT NULL,   -- JSON; §4 portable form
  staged_at             TEXT NOT NULL,   -- ISO8601 from JSONL record's "stagedAt"
  status                TEXT NOT NULL DEFAULT 'staged'
                        CHECK (status IN ('staged','merged','distilled','pruned')),
  cluster_id            TEXT,            -- set after merge step (FK → clusters.cluster_id)

  PRIMARY KEY (fingerprint, session_id)
);

CREATE INDEX IF NOT EXISTS idx_findings_skill       ON findings (skill);
CREATE INDEX IF NOT EXISTS idx_findings_status      ON findings (status);
CREATE INDEX IF NOT EXISTS idx_findings_cluster_id  ON findings (cluster_id);
CREATE INDEX IF NOT EXISTS idx_findings_staged_at   ON findings (staged_at DESC);

-- FTS5 on normalized_summary + proposed_fix for near-duplicate detection.
-- Uses content= so the FTS index stays in sync with the findings table.
-- Must be rebuilt after bulk ingests: INSERT INTO findings_fts(findings_fts) VALUES('rebuild');
CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5 (
  fingerprint         UNINDEXED,
  session_id          UNINDEXED,
  skill,
  normalized_summary,
  proposed_fix,
  content   = 'findings',
  content_rowid = 'rowid',
  tokenize  = 'porter unicode61 remove_diacritics 1'
);

-- ─────────────────────────────────────────────────────────────
-- clusters — deduplicated, corroborated finding groups
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS clusters (
  cluster_id                  TEXT PRIMARY KEY,  -- fingerprint of representative/first finding
  skill                       TEXT NOT NULL,
  source_repo                 TEXT,              -- most-common source_repo, or null if varied
  severity                    TEXT NOT NULL,     -- highest severity across member findings
  confidence                  TEXT NOT NULL,     -- highest confidence across member findings
  outcome                     TEXT NOT NULL,     -- most common outcome (mode)
  pattern                     TEXT NOT NULL,
  category                    TEXT NOT NULL,
  canonical_summary           TEXT NOT NULL,     -- scrubbed best-paraphrase for this cluster
  canonical_proposed_fix      TEXT NOT NULL,     -- scrubbed best-fix paraphrase
  canonical_proposed_eval_json TEXT NOT NULL,    -- JSON; best proposedEval for this cluster
  distinct_session_count      INTEGER NOT NULL DEFAULT 1,
  raw_marker_count            INTEGER NOT NULL DEFAULT 0, -- raw markers (no finding) corroborating
  first_seen                  TEXT NOT NULL,     -- ISO8601; earliest staged_at among members
  last_seen                   TEXT NOT NULL,     -- ISO8601; latest staged_at among members
  corroboration_score         REAL NOT NULL DEFAULT 0.0
                              CHECK (corroboration_score BETWEEN 0.0 AND 1.0),
  status                      TEXT NOT NULL DEFAULT 'active'
                              CHECK (status IN ('active','distilled','sent','tombstoned')),
  distilled_at                TEXT,              -- ISO8601; set when distilled
  sent_at                     TEXT,              -- ISO8601; set when report is filed/written
  sent_to                     TEXT               -- 'local' | 'owner/repo' | null
);

CREATE INDEX IF NOT EXISTS idx_clusters_skill          ON clusters (skill);
CREATE INDEX IF NOT EXISTS idx_clusters_status         ON clusters (status);
CREATE INDEX IF NOT EXISTS idx_clusters_score_desc     ON clusters (corroboration_score DESC);
CREATE INDEX IF NOT EXISTS idx_clusters_last_seen_desc ON clusters (last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_clusters_category       ON clusters (category);

-- ─────────────────────────────────────────────────────────────
-- cluster_members — many-to-one: finding → cluster
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cluster_members (
  cluster_id       TEXT NOT NULL,   -- FK → clusters.cluster_id
  fingerprint      TEXT NOT NULL,   -- FK → findings.fingerprint (partial)
  session_id       TEXT NOT NULL,   -- FK → findings.session_id (ingest key, not exposed)
  similarity_score REAL NOT NULL DEFAULT 1.0,  -- 1.0 = exact fingerprint match

  PRIMARY KEY (cluster_id, fingerprint, session_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_members_cluster ON cluster_members (cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_members_finding ON cluster_members (fingerprint);

-- ─────────────────────────────────────────────────────────────
-- tombstones — permanent exclusion records
-- Clusters in tombstones must never appear in distillation output
-- even if their status in clusters table is still 'active'.
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tombstones (
  cluster_id   TEXT PRIMARY KEY,
  reason       TEXT NOT NULL   CHECK (reason IN ('sent','user_dismissed','user_deleted','expired')),
  created_at   TEXT NOT NULL   -- ISO8601
);
```

#### Example rows (illustrative, jsonc comments for clarity)

```jsonc
// markers row — raw §8 marker for a session where the core skill was never run
// session_id: "ses_abc123", 4 friction signals on "container-toolkit", reason: "complete"
{
  "session_id": "ses_abc123",
  "ended_at": "2026-07-01T14:22:05Z",
  "skills_json": "[\"container-toolkit\",\"mise-v2-standard-agent\"]",
  "friction_json": "{\"container-toolkit\":4}",
  "reason": "complete",
  "ingested_at": "2026-07-07T21:00:00Z",
  "status": "ingested"
}

// findings row — classified finding, fingerprinted, merged into cluster "a3f9c1b2..."
{
  "fingerprint": "a3f9c1b2d4e6f8a0b2c4d6e8f0a2b4c6",  // 32-char hex; see §2.3
  "session_id": "ses_def456",
  "skill": "container-toolkit",
  "source_repo": "acme/container-toolkit",
  "severity": "High",
  "confidence": "Likely",
  "outcome": "Worked-around",
  "pattern": "stale-guidance",
  "category": "wrong-or-stale-guidance",
  "normalized_summary": "deploy command region flag unknown retri agent switch positional argument succeed",
  "proposed_fix": "Replace --region flag example with positional zone argument in the deploy section of SKILL.md.",
  "proposed_eval_json": "{\"id\":\"ct-a3f9c1b2\",\"prompt\":\"...\",\"must_contain\":[\"positional zone argument\"],\"must_not_contain\":[\"--region\"]}",
  "staged_at": "2026-07-02T09:14:33Z",
  "status": "merged",
  "cluster_id": "a3f9c1b2d4e6f8a0b2c4d6e8f0a2b4c6"
}

// clusters row — this cluster has been seen in 3 sessions (strongly corroborated)
{
  "cluster_id": "a3f9c1b2d4e6f8a0b2c4d6e8f0a2b4c6",
  "skill": "container-toolkit",
  "source_repo": "acme/container-toolkit",
  "severity": "High",
  "confidence": "Likely",
  "outcome": "Worked-around",
  "pattern": "stale-guidance",
  "category": "wrong-or-stale-guidance",
  "canonical_summary": "The skill's --region flag is no longer accepted by the underlying CLI v2; the agent hit the error, retried, and switched to a positional argument to complete the deployment.",
  "canonical_proposed_fix": "Update the deploy-command example in SKILL.md: replace --region <zone> with the positional argument form. Remove the deprecated flag from all examples.",
  "canonical_proposed_eval_json": "{\"id\":\"ct-a3f9c1b2\",...}",
  "distinct_session_count": 3,
  "raw_marker_count": 1,
  "first_seen": "2026-06-28T11:05:00Z",
  "last_seen": "2026-07-04T16:30:00Z",
  "corroboration_score": 0.85,
  "status": "active",
  "distilled_at": null,
  "sent_at": null,
  "sent_to": null
}
```

### 2.3 Fingerprint design

The fingerprint is the **single key that drives deduplication**. It is computed from a
canonical, PII-free subset of a `FrictionFinding`'s typed fields.

#### Formula

```
fingerprint = hex( SHA256(
  "skill-reflect-v2" + NUL +
  normalize_slug(skill)   + NUL +
  category                + NUL +
  pattern                 + NUL +
  normalize_text(summary) + NUL +
  normalize_text(proposedFix)
) )
```

Where `NUL` = `\x00` (null byte field separator, cannot appear in text fields).

The resulting fingerprint is 64 hex characters. For display it may be truncated to the
first 8 characters (cluster short-id), but the full 64-char value is always stored.

#### `normalize_slug(s: str) → str`

```
1. lowercase(s)
2. strip leading/trailing whitespace
3. collapse internal whitespace to single space
4. collapse non-alphanumeric runs to hyphen
   → "My Skill (v2)!" → "my-skill-v2"
```

This ensures "container-toolkit" and "Container Toolkit" produce the same normalized
slug.

#### `normalize_text(s: str) → str`

```
1.  lowercase(s)
2.  strip all characters that are not [a-z0-9 ]
3.  split into tokens on whitespace
4.  strip common English stopwords:
    {a, an, and, are, as, at, be, been, but, by, do, for, from,
     had, has, have, he, her, him, his, how, i, if, in, is, it,
     its, may, not, of, on, or, our, out, so, than, that, the,
     their, them, then, there, they, this, to, up, us, was, we,
     were, what, when, which, who, will, with, would, you, your}
5.  apply Porter stem reduction (e.g. "retried" → "retri",
    "deploying" → "deploy", "flagged" → "flag")
6.  deduplicate tokens (remove repeated tokens, order-independent)
7.  sort tokens alphabetically
8.  take the first 60 tokens
9.  join with single space
```

Sorting and deduplication make the fingerprint **order-invariant**: "the deploy command
failed with an unknown flag" and "an unknown flag caused the deploy command to fail"
produce the same normalized text and therefore the same fingerprint, as intended.

#### Fields included in the fingerprint

| Field | Included | Rationale |
|---|---|---|
| `skill` | ✅ | Attribution scope; findings from different skills are always separate |
| `category` | ✅ | Taxonomy type; two findings about the same symptom but different categories are distinct issues |
| `pattern` | ✅ | Taxonomy type; `stale-guidance` vs `trigger-miss` on the same skill are different problems |
| `summary` (normalized) | ✅ | The semantic content of the finding |
| `proposedFix` (normalized) | ✅ | Different fix proposals for similar symptoms indicate distinct aspects of the problem |

#### Fields explicitly EXCLUDED from the fingerprint

| Field | Excluded | Rationale |
|---|---|---|
| `sessionId` | ❌ | Volatile; changes every session; would make every finding unique |
| `sourceRepo` | ❌ | The skill is the unit of attribution; the same skill bug appears in any repo using it |
| `severity` | ❌ | Two reporters may assess the same bug differently; not part of the finding's identity |
| `confidence` | ❌ | Different reporters may have different evidence quality; corroboration raises confidence later |
| `outcome` | ❌ | Two sessions may resolve the same bug differently; not part of identity |
| `evidence` | ❌ | Session-specific paraphrasing; the same bug produces different evidence each time |
| paths, values, names | ❌ | Never present in any field (scrubbed before staging); listed for explicitness |

#### Relationship to the v1 `FrictionFinding.id`

CONTRACT §3 defines the v1 `FrictionFinding.id` as "stable hash of {skill, pattern,
normalized-summary}". The v2 fingerprint is a superset: it also conditions on `category`
and `normalize_text(proposedFix)`. In practice, v1 ids and v2 fingerprints will be close
but not identical (different hash inputs). During migration (§7), v1 artifacts that carry
pre-computed `id` values are re-fingerprinted using the v2 formula at ingest time. The v1
`id` is retained as a `v1_id` column (nullable, for traceability) but is not used as the
deduplication key in `queue.db`.

### 2.4 Corroboration model

Corroboration answers: **how confident are we that this cluster reflects a real, recurring
skill issue rather than a one-off session anomaly?**

The model is borrowed from engraim/autoresearch's corroboration posture: "the same signal
appearing independently in multiple sessions is more solid than a single occurrence,
regardless of how confident any single reporter was."

#### Effective observation count

```
N_eff = distinct_session_count + 0.5 × raw_marker_count
```

`raw_marker_count` is the number of §8 raw markers (without a corresponding classified
finding) that implicate this skill during the same period. Raw markers count as
half-observations because they prove friction occurred but don't confirm classification.

#### Corroboration score

```
corroboration_score = min(1.0,  log2(1 + N_eff) / log2(7))
                    × confidence_weight(highest_confidence)
```

Where:

| `highest_confidence` | `confidence_weight` |
|---|---|
| `Confirmed` | 1.00 |
| `Likely` | 0.80 |
| `Possible` | 0.60 |

`log2(7) ≈ 2.807` causes the score to saturate at 1.0 when `N_eff ≥ 6`. Illustrative
milestones:

| `N_eff` | Confirmed | Likely | Possible |
|---|---|---|---|
| 1 | 0.36 | 0.28 | 0.21 |
| 2 | 0.57 | 0.45 | 0.34 |
| 3 | 0.71 | 0.57 | 0.43 |
| 4 | 0.82 | 0.66 | 0.49 |
| 6 | 1.00 | 0.80 | 0.60 |

A finding corroborated at score ≥ 0.70 is considered "strongly corroborated" and is
highlighted in the batch review UX. A finding at score ≥ 0.50 is "corroborated". Below
0.50 is "single-session or speculative".

#### Near-duplicate detection and merge thresholds

When a new finding `F` is ingested and no exact fingerprint match exists in `clusters`:

1. **FTS5 query**: Search `findings_fts` for `normalized_summary` AND `proposed_fix`
   using the FTS5 BM25 ranking, restricted to the same `skill` and `category`.
2. **Similarity score** (0–1): Derived from the BM25 rank, normalized to [0,1] by
   comparison against a known-identical pair (score = 1.0) and a known-unrelated pair
   (score = 0.0). The exact normalization function is implementation-defined but must
   be monotonic.
3. Apply thresholds:

| Similarity | Action |
|---|---|
| ≥ `τ_merge` (default **0.80**) | Merge `F` into the nearest cluster. Increment `distinct_session_count`. Recompute `corroboration_score`. Update `canonical_summary` / `canonical_proposed_fix` to whichever is longer and more specific (prefer higher-confidence source). |
| ∈ [`τ_link`, `τ_merge`) (default **0.60–0.80**) | Soft-link: create a new cluster for `F`, but record a `cluster_link` relationship (separate table, out of scope for v2 MVP) for display as "related findings". Do not merge. |
| < `τ_link` (default **0.60**) | New independent cluster. |

Thresholds `τ_merge` and `τ_link` are implementation-tunable constants. They are NOT
user-configurable in v2 (too technical); they may move to config in a future revision.

#### Tie-breaking when multiple clusters exceed τ_merge

Choose the cluster with the **highest `distinct_session_count`** (most corroborated).
If tied, choose the cluster with the **earliest `first_seen`** (longer track record).
If still tied, choose the cluster with the **highest `confidence`** member (Confirmed >
Likely > Possible).

---

## 3. Lifecycle / state machine

```
 [v1 adapter/extension]           [v2 aggregation layer]          [v1 pipeline, extended]
        │                                  │                                │
        ▼                                  ▼                                ▼
   ┌─────────┐   ingest    ┌────────────────────────────┐  distill  ┌──────────────┐
   │ STAGED  │ ──────────► │ INGESTED → FINGERPRINTED   │ ────────► │ DISTILLED    │
   └─────────┘             │           → CLUSTERED      │           └──────┬───────┘
        │                  │           → CORROBORATED   │                  │ (authorized)
        │ (§8 marker or    └────────────────────────────┘                  ▼
        │  §3 finding in                                           ┌──────────────┐
        │  findings.jsonl)            ┌──────────────┐            │ SENT / LOCAL │
        │                            │  TOMBSTONED  │ ◄───────── └──────────────┘
        │                            └──────┬───────┘                  │
        │                                   │                          │ (pruning TTL
        │                                   ▼                          │  or user delete)
        └────────────────────── PRUNED (retention expired) ◄──────────┘
```

### State definitions

| State | Entity | Definition |
|---|---|---|
| `STAGED` | Marker (§8) or finding (JSONL) | Written to disk by automation or core skill. Not yet in SQLite. |
| `INGESTED` | Marker | Read from `pending/<sessionId>.json`; inserted into `markers` with `status='ingested'`. |
| `FINGERPRINTED` | Finding | Read from `findings.jsonl`; fingerprint computed; inserted into `findings` with `status='staged'`. |
| `CLUSTERED` | Finding | Merged into an existing cluster or a new cluster created. Finding row updated: `status='merged'`, `cluster_id` set. |
| `CORROBORATED` | Cluster | `distinct_session_count ≥ 2` and `corroboration_score ≥ 0.50`. No explicit status change; this is a computed property surfaced in the UX. |
| `DISTILLED` | Cluster | Model has run on this cluster with review authorization to produce consolidated finding text. `clusters.status='distilled'`, `clusters.distilled_at` set. |
| `SENT` | Cluster | Strict report filed as a GitHub issue after remote-send authorization. `clusters.status='sent'`, `clusters.sent_at`, `clusters.sent_to` set. Tombstone record created. |
| `TOMBSTONED` | Cluster | Permanently excluded from future distillation. Reason: sent, user dismissed, user explicitly deleted, or expired. |
| `PRUNED` | Any | Row deleted (or archived) after TTL or explicit user action. |

### Transition triggers

| Transition | Trigger | Idempotency guarantee |
|---|---|---|
| staged → ingested | "review queue" command, or lazy check at session start | `INSERT OR IGNORE` on `markers.session_id` PK; re-ingesting a marker is a no-op |
| staged → fingerprinted | Same trigger; processes `findings.jsonl` lines | `INSERT OR IGNORE` on `(fingerprint, session_id)` PK; re-processing a finding line is a no-op |
| fingerprinted → clustered | Immediately after fingerprinting | Fingerprint lookup + FTS merge is deterministic; running it twice on the same finding produces the same cluster assignment |
| clustered → corroborated | Implicit; recomputed on every new merge | Score recomputation is monotonically safe (new members only increase score) |
| active → distilled | Explicit review request or accepted nudge for the announced queue scope | Core skill checks `clusters.status`; already-distilled clusters are skipped |
| distilled → sent | Fresh authorization for the exact strict body and destination | Sent clusters are tombstoned; tombstone presence blocks re-send at distillation check time |
| any → tombstoned | sent, user "dismiss this finding forever", or expired | `INSERT OR IGNORE` on `tombstones.cluster_id` PK |
| any → pruned | TTL check at ingest time (configurable; default 365 days for active, 90 days for tombstoned) | Pruning deletes from findings/cluster_members/clusters; tombstone persists for 90 additional days as a re-send guard |

### Retention / TTL defaults

```jsonc
// Proposed addition to skill-reflect.config.json (v2 section)
{
  "v2": {
    "queue": {
      "activeTTLDays": 365,         // active clusters older than this are auto-tombstoned
      "tombstoneTTLDays": 90,       // tombstones (and their clusters) are pruned after this
      "maxQueueSizeMB": 50,         // if queue.db exceeds this, oldest prunable rows are dropped
      "minCorroborationToDistill": 1 // include single-session findings? 1=yes, 2=require corroboration
    }
  }
}
```

---

## 4. Batch review command (UX design)

> This section describes the **user-facing workflow only** — no code. The implementation
> will be a new invocation path for the core skill, respecting all v1 consent and scrub
> requirements.

### 4.1 Entry points

The batch review can be triggered in two ways:

1. **Explicit invocation**: User says "review my pending skill feedback" or equivalent.
   The nudge guide (§3 of `nudge-guide.md`) extends to include this phrasing as a
   trigger variant.

2. **Opportunistic nudge**: At session start, if `distinct_session_count ≥ 2` for any
   cluster, the automation extension may include an additional line in its existing nudge
   (CONTRACT §8 `additionalContext`): *"N findings have been seen across M sessions. Run
   a batch review to distill them."* This is still non-blocking and subject to the
   existing throttle.

### 4.2 Phase 1 — Queue summary (no model)

Before any model work, the skill reads `queue.db` and presents a **low-
cost structured summary** of what's in the queue. This is purely a read operation; nothing
is generated, sent, or modified.

```
📋 skill-reflect queue — 7 findings across 3 skills (4 sessions)

  container-toolkit    3 findings    ★★★ (2 corroborated ≥0.70, 1 single-session)
  mise-v2-standard     2 findings    ★★  (1 corroborated, 1 single-session)
  ado                  2 findings    ★   (both single-session)

  Oldest finding: 28 days ago   Newest: 2 days ago

  → To distill and review, say "yes" or name the skills you want to include.
  → To skip and review later, say "skip" or "not now".
  → To permanently dismiss a finding, say "dismiss <skill>".
```

**Key UX principle:** This phase is cheap. No AI runs. The user can say "not now" with
zero cost. The queue remains unchanged.

### 4.3 Review authorization and scope

An explicit request such as "review my pending skill feedback" authorizes the announced queue
scope; do not ask the same yes/no question again. An accepted opportunistic nudge also carries
review authorization. If the queue summary was shown without either signal, ask:

> "I can distill these findings into a consolidated review. This will use the language
> model to group, summarize, and propose evals for the corroborated issues. No data
> leaves your machine at this step. Would you like to proceed?"

The user may:
- Approve all (`"yes"` / `"distill all"`)
- Approve subset (`"container-toolkit only"` / `"just the corroborated ones"`)
- Defer (`"not now"`, `"later"`) — no state change, throttle resets
- Dismiss specific clusters (`"dismiss the ado findings"`) — creates tombstone records

**"Distill-don't-dump" principle:** The queue is staged cheaply with zero model work.
Distillation is intentionally deferred to this explicit consent step. The queue may
accumulate for weeks or months without incurring any model cost or user interruption.

### 4.4 Phase 2 — Distillation (model-driven, review-authorized)

The core skill receives the approved cluster set and performs the following steps (same
pipeline as v1, extended to multiple clusters):

1. **Group** the approved clusters by skill, then by `category` within each skill.

2. **For each cluster**, the model produces:
   - A consolidated `summary` (best paraphrase across member findings, using the
     `canonical_summary` as the seed and the corroboration count as context)
   - A consolidated `proposedFix` (as specific as the evidence allows)
   - A single `proposedEval` (§4 mapping, highest-specificity member's eval as seed)
   - A `corroboration_note`: *"Observed in N sessions over X days."*

3. **Scrub** (§7 `scrub_text()`) is applied to all model-generated text as a mandatory
   backstop before any output is written.

4. The default result is **multi-skill consolidated findings in chat**. If the user requested
   an artifact, render the same findings in the §5 schema after a summary-first preview:

```markdown
---
generated_by: skill-reflect
schema: 2
date: <YYYY-MM-DD>
sessions_reviewed: <N>
skills_reviewed: ["container-toolkit", "mise-v2-standard"]
consent: review-only
---

# Cross-session field feedback

## Summary
N sessions over M days surfaced K distinct findings across 2 skills.
2 findings were corroborated (seen in 3+ sessions each); 3 are single-session.

## container-toolkit

### 1. Stale deploy-command flag  ·  High / Likely / Worked-around  ·  ★★★ 3 sessions
- **Category:** wrong-or-stale-guidance
- **Corroboration:** Seen in 3 sessions, first 28 days ago.
- **What happened:** …
- **Signal:** …
- **Proposed fix:** …
- **Proposed eval:**
  ```json
  { … }
  ```

…
```

### 4.5 Optional artifact or remote output

After returning the distilled findings in chat, stop. Do not offer a file or GitHub issue
unless the user asks.

- On explicit save intent, show a summary-first local preview and obtain local-write
  authorization for the announced path.
- On explicit send intent, route per skill, regenerate strict domain-abstracted content,
  scrub it, show the exact outbound body, and obtain fresh authorization for that body and
  destination.

**Per-skill granularity:** Each skill in the report may be routed independently (same v1
provenance routing, §6 of CONTRACT). One skill's findings may be filed while another's
remain chat-only or are saved locally. The user retains full control per destination.

On send, affected clusters are updated: `status='sent'`, `sent_at`, `sent_to` set,
tombstone created.

---

## 5. Anonymized aggregate posture

> This section describes a capability intended primarily for **skill authors who have
> vendored `skill-reflect` into their own plugin** and wish to receive aggregate friction
> trends from users who opt in. It is **OPT-IN at every level** and requires explicit
> user consent at both config time and at each send time.

### 5.1 What this is and is not

**Is:** A way for a vendored `skill-reflect` deployment to produce a k-anonymous,
taxonomy-typed trend summary (counts and distributions per category/pattern) that the user
may choose to send to the skill author's aggregate endpoint.

**Is not:** Telemetry. Silent data collection. Per-user tracking. There is no background
process, no automatic send, and no network activity without two explicit user consent steps.

### 5.2 Enabling aggregate reporting

In `skill-reflect.config.json`:

```jsonc
{
  "mode": "vendored",
  "v2": {
    "aggregateReporting": {
      "enabled": true,                      // OPT-IN; default false
      "destination": "https://example.com/skill-feedback/ingest",  // vendor's aggregate endpoint
      "sendInterval": "weekly",             // "manual" | "weekly" | "monthly"
      "kAnonymityThreshold": 3,             // suppress trends with fewer than k distinct sessions
      "requireExplicitConsentPerSend": true // ALWAYS true; cannot be disabled
    }
  }
}
```

`requireExplicitConsentPerSend` is hard-enforced: even with `sendInterval: "weekly"`, each
send requires the user to approve a pre-send summary.

### 5.3 What is included in an aggregate report

The aggregate report is assembled from `queue.db` with the following projection. Each row
is a **trend record**: a count of observations for a (skill, category, pattern, severity
distribution, outcome distribution) tuple.

```jsonc
// One trend record — the ONLY shape ever transmitted
{
  "skill": "container-toolkit",              // skill name only — no repo, no user, no session
  "category": "wrong-or-stale-guidance",     // taxonomy-typed
  "pattern": "stale-guidance",               // taxonomy-typed
  "severity_distribution": {                  // counts only, no per-session breakdown
    "High": 2,
    "Medium": 1,
    "Low": 0,
    "Unknown": 0
  },
  "outcome_distribution": {
    "Solved": 0,
    "Worked-around": 3,
    "Unresolved": 0
  },
  "session_count": 3,                        // number of distinct sessions (≥ k)
  "first_seen_week": "2026-W26",             // ISO week number; NOT a precise timestamp
  "last_seen_week": "2026-W27"               // ISO week number
}
```

### 5.4 What is NEVER included in an aggregate report

The following are excluded absolutely, regardless of configuration:

| Category | Examples |
|---|---|
| Session identifiers | `sessionId`, session count ≤ k |
| User identifiers | User aliases, machine names, usernames |
| Paths or URIs | Absolute paths, private URLs, hostnames |
| Raw text fields | `summary`, `evidence`, `proposedFix` — any prose content |
| Secret material | Tokens, keys, credentials (scrubber backstop applies) |
| Timestamps at precision < 1 week | Exact `staged_at`, `first_seen` |
| Source repo | The repo the user was working in (distinct from skill's own `sourceRepo`) |
| Per-session data | Any field that could reconstruct a session's timeline |

### 5.5 k-anonymity enforcement

Before assembling the aggregate report:

```
for each (skill, category, pattern) tuple:
  if cluster.distinct_session_count < k_anonymity_threshold:
    SUPPRESS (do not include in report)
```

Default `kAnonymityThreshold = 3`. Suppressed trends are logged locally
(`$SKILL_REFLECT_HOME/aggregate-suppressed.log`) so the user knows data was withheld.
The vendor never receives suppressed trends.

**Minimum k is 3; values below 3 are rejected at config parse time.** This prevents a
single user from being identifiable via the aggregate endpoint.

### 5.6 Consent copy (pre-send summary)

Before each aggregate send, the user sees:

```
📊 Aggregate trend report — skill-reflect

  This report contains anonymized friction counts (no user data, no raw content,
  no paths, k ≥ 3 sessions per trend) for skills you've used.

  Included trends:
    - container-toolkit: 1 trend (3 sessions)
    - mise-v2-standard:  1 trend (4 sessions)
  Suppressed (< k sessions): ado (2 sessions — not included).

  Destination: https://example.com/skill-feedback/ingest
  Method: HTTPS POST; no auth token, no cookies, no tracking headers.

  This send is one-time. Future sends require your approval again.

  Type "send" to transmit or "cancel" to skip.
```

The user must type an explicit approval token. No keyboard shortcut, no "press enter to
confirm", no default-yes.

### 5.7 Aggregate posture is not a backdoor

Every v1 privacy guarantee (§6) applies to the aggregate posture without exception:
- The scrubber (§7) runs on all text fields before they enter the queue, so no PII can
  arrive in the aggregate report even if a future bug fails to exclude a text field.
- The aggregate posture never transmits the `summary`, `evidence`, or `proposedFix` prose
  fields — only taxonomy-typed enum values and integer counts.
- The `destination` URL is user-visible in both config and the pre-send summary.
- The send is a one-time `gh`-or-`curl`-backed POST; there is no persistent connection,
  no SDK, no tracking SDK, no cookie jar.

---

## 6. Privacy & authorization

This section restates and extends the v1 non-negotiables (CONTRACT §0) for the v2
aggregation layer. Every statement here is a design invariant, not a guideline.

### 6.1 Separate authorizations, extended to batch

v1 distinguishes review, local-write, and remote-send authorization. v2 preserves
those boundaries for the batch case:

| Authorization | v1 trigger | v2 trigger |
|---|---|---|
| Review | Explicit session-performance request or accepted nudge | Explicit queue-review request or accepted batch nudge |
| Local write | Explicit save/capture intent for an announced path | Explicit save intent for the consolidated artifact path |
| Remote send | Exact scrubbed body + exact destination | Exact strict per-skill body + exact destination |

Declining review leaves the queue exactly as it was. Declining a local write creates no
artifact. Declining a remote send does not implicitly save anything and leaves the cluster
in `status='distilled'` — not `'sent'`, not tombstoned — so the user may re-review later.

### 6.2 Mandatory scrub — applied at two points

The §7 scrubber is applied at:

1. **Ingest time** (JSONL staging): `scrub_text()` is run on `summary`, `evidence`, and
   `proposedFix` before each line is appended to `findings.jsonl`. This is the
   deterministic backstop for content entering the queue.

2. **Distillation time** (model output): `scrub_text()` is run on all model-generated
   prose (consolidated summaries, fixes, eval prompts) before writing to the artifact or
   any network payload.

The scrubber is never disabled. Its `--fail-on-secret` mode runs before any chat, file, or
remote output; a non-zero exit withholds all output until the content is redrafted.

### 6.3 No transcript excerpts, ever

`privacy.allowTranscriptExcerpts` is hard-enforced as `false` in the v1 CONFIG and remains
`false` in v2 with no override path. The JSONL staging schema has no `transcript` field.
The SQLite schema has no `transcript` column. Model prompts used for distillation reference
the paraphrased `summary` and `evidence` fields only.

### 6.4 No values, only variable/tool names

`FrictionFinding.evidence` (§3) is already constrained to paraphrased signal. v2 adds no
new prose fields that could carry values. The aggregate posture (§5) transmits no prose at
all.

### 6.5 "Never for this skill / repo" controls (unchanged)

`nudge.neverForSkills` and `nudge.neverForRepos` in `skill-reflect.config.json` continue
to prevent staging for the specified skills/repos. v2 additionally provides:

- **`"forget this finding"`**: User can dismiss a cluster during the batch review; a
  tombstone is created and the cluster never appears again.
- **`"forget all findings for <skill>"`**: Tombstones all active clusters for the named
  skill.
- **`"clear the queue"`**: Tombstones all active clusters (nuclear option; local data only).

All forget/dismiss operations are **local disk operations only**; they do not notify any
external party.

### 6.6 Local-first, no-network-by-default

`queue.db` and `findings.jsonl` are local disk files in `$SKILL_REFLECT_HOME`. No v2
component opens a network connection unless:
- Remote-send authorization is granted for an exact GitHub issue body and destination
  (uses `gh issue create`, same as v1).
- The aggregate posture is enabled AND the user approves a specific send (§5).

There is no background sync, no heartbeat, no crash reporter, no telemetry SDK.

### 6.7 User auditability

The user can at any time:

- **Inspect the queue**: Ask the skill "show me what's in my pending queue" — the skill
  reads `queue.db` and presents the human-readable summary (§4.2 format) without any
  model work.
- **View a specific finding**: Ask "show me the stale-guidance finding for container-toolkit"
  — the skill returns the `canonical_summary`, `canonical_proposed_fix`, and corroboration
  count.
- **Edit a finding**: The user may paraphrase or correct the `canonical_summary` /
  `canonical_proposed_fix` manually; the skill updates the cluster row and re-scrubs.
- **Export the queue**: Ask "export my queue" — the skill writes a human-readable Markdown
  summary of all active clusters to `.skill-feedback/queue-export-<date>.md`. No network
  action.
- **Delete the queue**: Deleting `$SKILL_REFLECT_HOME/queue.db` and
  `$SKILL_REFLECT_HOME/pending/findings.jsonl` is always safe and complete. The skill
  creates them fresh on next use. v1 markers (`pending/*.json`) are unaffected.

---

## 7. Compatibility & migration from v1

### 7.1 Forward compatibility of the §8 marker shape

The v1 marker shape (CONTRACT §8) is the **forward-compatible input** to the v2 queue.
No change to any adapter, extension, or tier-A/B hook is required. v2 adds a new ingest
path that reads `pending/*.json` files alongside the new `pending/findings.jsonl`; the
existing files continue to be written by v1 components without modification.

### 7.2 Ingest mapping from §8 marker → `markers` table

```
§8 marker field        → markers column
─────────────────────────────────────────────────────
"sessionId"            → session_id
"endedAt"              → ended_at
["a","b"]  (skills)    → skills_json  (JSON array, as-is)
{"a":3}    (friction)  → friction_json (JSON object, as-is)
"reason"               → reason
(ingestion timestamp)  → ingested_at  (set by v2 ingest, not from marker)
'pending'              → status       (initial value)
```

Raw markers do not carry classified findings, so no `findings` row is created from them.
They contribute to `raw_marker_count` in `clusters` when a cluster for the same skill and
approximate time period exists. Specifically, after ingesting a raw marker, the ingest
process runs:

```sql
-- pseudocode
UPDATE clusters
   SET raw_marker_count = raw_marker_count + friction_count,
       corroboration_score = recompute_score(distinct_session_count, raw_marker_count + friction_count, confidence)
 WHERE skill IN (SELECT value FROM json_each(marker.skills_json))
   AND status = 'active'
   AND last_seen >= marker.ended_at - INTERVAL '30 days'
   -- only corroborate clusters that were active near the marker's session
```

### 7.3 Ingest mapping from §3 `FrictionFinding` + JSONL → `findings` table

```
JSONL field            → findings column
─────────────────────────────────────────────────────
(computed v2 fingerprint — see §2.3)   → fingerprint
"sessionId" (JSONL extension)          → session_id
"skill"                                → skill
"sourceRepo"                           → source_repo
"severity"                             → severity
"confidence"                           → confidence
"outcome"                              → outcome
"pattern"                              → pattern
"category"                             → category
normalize_text("summary")              → normalized_summary
"proposedFix"                          → proposed_fix
JSON("proposedEval")                   → proposed_eval_json
"stagedAt"                             → staged_at
'staged'                               → status  (initial)
NULL                                   → cluster_id (set after clustering step)
```

The v1 `FrictionFinding.id` field (SHA256 of {skill, pattern, normalized-summary}) is
stored as a non-indexed `v1_id` column (nullable, added via `ALTER TABLE findings ADD
COLUMN v1_id TEXT` in a migration) for traceability but is never used as the deduplication
key.

### 7.4 Schema versioning and migration

The `schema_meta` table stores the current schema version. Migrations are additive:

| Version | Changes |
|---|---|
| `2` | Initial v2 schema (this document) |
| `2.1` (future) | Add `cluster_links` table for soft-linked near-duplicates |
| `3` (future) | Breaking change — requires full `DROP TABLE` and rebuild from JSONL |

v1 leaves no schema to migrate; `queue.db` and `findings.jsonl` are created fresh by the
first v2 ingest pass.

### 7.5 v1 artifact back-fill (optional, non-blocking)

If the user has existing `.skill-feedback/<date>-<slug>.md` artifacts from v1 sessions
(where the core skill was run and findings were written), those artifacts carry the v1
`FrictionFinding` fields in their YAML front-matter. A future "back-fill" command (out of
scope for v2 MVP) could parse these artifacts and stage their findings into the v2 queue,
giving the corroboration model data from past reviewed sessions.

This is explicitly optional and requires the user to invoke it. No automated scan of
`.skill-feedback/` occurs without consent.

---

## 8. Open questions / risks

### 8.1 False corroboration — task friction vs. skill friction

**Risk:** The same task (e.g., "deploy to eu-west") may produce friction across multiple
sessions not because the skill is broken, but because the task itself is inherently complex
or the user's environment is unusual. Naïve corroboration inflates the score for task-level
noise.

**Mitigations:**

1. **v1 confidence downgrade rules carry forward.** Each `FrictionFinding` entering the
   queue carries a `confidence` value computed by the v1 rubric (`friction-rubric.md`).
   A `Possible` confidence caps the corroboration score at 0.60 even at N=6. A cluster
   composed entirely of `Possible` findings never reaches the "strongly corroborated" tier.

2. **A/B signal (optional, from autoresearch).** If the session store is available
   (Copilot CLI history, or future adapter support), the distillation step may optionally
   compare sessions where the same skill was invoked successfully for the same task type
   against sessions where friction occurred. A skill that succeeds in 10 sessions and
   fails in 2 is less likely to have a systematic bug than one that fails in 10 and
   succeeds in 2. This comparison is non-blocking; if unavailable, the corroboration score
   is used as-is.

3. **Explicit "task out of scope" flag.** During the batch review (§4), the user may
   mark a cluster as "task friction, not skill friction" — this tombstones it and adds
   `reason='user_dismissed'`.

### 8.2 Similarity threshold tuning

**Risk:** `τ_merge = 0.80` and `τ_link = 0.60` are initial estimates. Too high: near-
duplicate findings create separate clusters (no corroboration). Too low: unrelated findings
merge (false corroboration).

**Mitigation:** The thresholds are named constants in the implementation (not magic
numbers) and can be adjusted without a schema migration. A future release should include a
small labeled dataset of (finding pairs, expected merge decision) to calibrate them
empirically. The FTS5 BM25 normalization function (which maps raw rank to 0–1) also
requires calibration; its constants should be logged on first ingest so they can be tuned.

### 8.3 SQLite vs. JSONL-only

**Risk:** SQLite adds a dependency and a binary file format. JSONL-only (flat append log)
is simpler, fully human-readable, and recoverable by any text editor.

**Tradeoffs:**

| | SQLite | JSONL-only |
|---|---|---|
| Structured queries | ✅ | ❌ (full scan) |
| FTS5 for near-dupes | ✅ | ❌ |
| Atomic updates | ✅ | ⚠️ (append-only; deletes require rewrite) |
| Human-readable | ❌ | ✅ |
| Rebuild from JSONL | ✅ | — (already is JSONL) |
| Python stdlib | ✅ (`sqlite3`) | ✅ |

**Decision rationale:** SQLite via Python stdlib (`import sqlite3`) adds zero external
dependencies and is recoverable from JSONL. The JSONL staging log remains as a plain-text
backup. If SQLite proves problematic on a platform, a fallback "JSONL-only mode"
(linear scan, no FTS) is viable for queues with < 100 findings.

### 8.4 Cross-agent marker uniformity

**Risk:** Different adapter tiers (CONTRACT §10) may produce markers with varying
information density. Tier A adapters have full session metadata; Tier C adapters produce
no markers at all. The corroboration model is calibrated for Tier A markers; Tier B/C
markers may produce weaker or noisier signals.

**Mitigation:** The marker schema (§8) is already normalized across tiers (all adapters
emit the same JSON shape). Tier C (no hooks) produces no markers, which is a known gap
in v1 and remains so in v2. The `raw_marker_count` field in clusters differentiates
"markers without findings" from "markers with classified findings" in the corroboration
score, giving a lighter weight to raw-marker corroboration (factor 0.5 in the N_eff
formula).

### 8.5 Storage growth

**Risk:** An active developer with many skills and many sessions could accumulate a large
queue over time.

**Mitigations:**
- Default `activeTTLDays = 365` and `tombstoneTTLDays = 90` keep the queue bounded.
- `maxQueueSizeMB = 50` triggers early pruning of oldest tombstoned rows.
- The `findings.jsonl` log is the most likely unbounded file; a periodic compaction step
  (rewrite, removing already-ingested lines) should be part of the "review queue" flow.
- The `normalized_summary` column stores only the normalized form (shorter) not the full
  prose; the full prose is in the canonical cluster columns only.
- If SQLite vacuum is run periodically (`VACUUM;`) after pruning, the file stays compact.

### 8.6 User auditability and editing of the queue

**Risk:** A user who wants to correct or remove a specific finding has no GUI and must
interact through the skill's prompt interface.

**Design:** The §6.7 auditability section describes the text-based controls. For v2 MVP,
these are skill-mediated (user asks the skill to show/edit/dismiss). A future "queue
management" canvas extension could provide a structured UI, but that is out of scope for
v2.

The key invariant: **the user can always inspect the full queue and delete any part of it**
(including `rm $SKILL_REFLECT_HOME/queue.db`) without any data loss guarantee beyond what
they've already seen. The queue is a local convenience store, not a source of truth; the
`.skill-feedback/` artifacts are the user's durable record.

### 8.7 Aggregate endpoint trust model

**Risk:** The `aggregateReporting.destination` URL could be misconfigured by a vendored
plugin to point to an attacker's endpoint, enabling silent exfiltration of trend counts.

**Mitigations:**
- The destination URL is shown to the user in the pre-send consent summary (§5.6).
- The aggregate report contains only enum counts (no prose), so the worst case is leaking
  which taxonomy patterns the user encountered with which skill — not raw content.
- The mode is `vendored`-only and requires explicit `enabled: true` in config. Standalone
  installs have aggregate reporting disabled by default with no opt-in path.
- A future hardening option: `allowedAggregateDestinations` allowlist in the schema,
  verified at config parse time.

### 8.8 Proposed eval deduplication across sessions

**Risk:** Multiple distillation runs followed by separately authorized eval exports may emit
duplicate `proposedEval` entries with different integer `id` values to
`.skill-feedback/evals/<slug>.evals.json`.

**Mitigation (reusing `skill-creator-interop.md` guidance):** Each eval's `id` in the
v2 artifact is derived from the cluster's `cluster_id` short-id (first 8 chars of
fingerprint). This provides a stable, deduplicate-friendly eval identifier across sessions.
The `skill-creator-interop.md` merging recipe (Section 3.1) already handles collisions
via `jq -s` deduplication; v2 makes this more reliable by anchoring eval ids to cluster
ids rather than session-scoped sequence numbers.

---

*End of document. For v1 behaviour, see `docs/CONTRACT.md` (source of truth).
For the skill taxonomy vocabulary (severity / confidence / outcome / pattern / category),
see `skill-reflect/references/friction-rubric.md` and `skill-reflect/references/skill-improvement-taxonomy.md`.*
