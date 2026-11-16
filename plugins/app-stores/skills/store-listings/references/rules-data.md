# Rules data: `rules/<store>.json`

Each store's rules are data, one file a store (`apple.json`, `google.json`; Amazon, Steam and itch.io to
follow), validated by `rules/rules.schema.json`. `listing.py check` runs every rule of every enabled store on the
resolved words and the screenshot files. Nothing is hard-coded in the scripts that a store could change.

## A rule

```json
{ "id": "google.title.length", "kind": "limit", "applies": { "field": "google.title" },
  "max": 30, "count": "characters", "severity": "error",
  "source": "https://support.google.com/googleplay/android-developer/answer/9898842",
  "checked": "2026-11-14", "status": "verified" }
```

| Field | Meaning |
|---|---|
| `id` | `<store>.<area>.<what>`, **stable forever**: configs relax rules by id. The last part reuses fastlane precheck's names where they mean the same (`other_platforms`, `placeholder_text`, `test_words`, `free_stuff_in_iap`, `copyright_date`, `unreachable_urls`) |
| `kind` | one of the kinds below |
| `applies` | `field` (a dotted path after locale fallback: `apple.subtitle`, `google.title`, `description`), `slot` (a store slot), or `fields`/`slots` lists |
| `severity` | `error` (stops `build`) or `warning` |
| `source` | the store's own page that says so |
| `checked` | the date someone last read that page and found the rule there |
| `status` | `verified` (the store's page says so), `observed` (seen happening, not written down by the store), `unverified` (secondary sources only, or the page is silent) |
| `note` | optional: why, or what's uncertain |

**A rule that isn't `verified` is reported as a warning, whatever its severity, and says it's unverified.**
That keeps a guess from blocking a release while still showing it.

## Kinds

| Kind | Fields | Example |
|---|---|---|
| `limit` | `max`, optional `min`, `count`: `characters` (code points), `graphemes`, `bytes` (UTF-8) | Apple keywords: 100 bytes |
| `count` | `min`/`max` pictures or items | Play phone screenshots: up to 8 |
| `size` | `sizes` (`[w, h]` pairs, either orientation unless `orientation` is set) or `range` (`minSide`, `maxSide`, `maxAspect`) | Play screenshots: 320–3840 px, long side at most 2× the short |
| `format` | `formats` (`png`, `jpeg`), `alpha` (`false` = no alpha channel), `transparency` (`false` = no see-through pixels; an opaque alpha channel is fine), `maxBytes` | Apple screenshots: no alpha; Play's icon: no transparency |
| `words` | `words` (whole words, case-insensitive; an entry starting or ending with a symbol matches as written), `fields` | price words in Apple's name and subtitle |
| `required` | a field or slot that must be present, with an optional `when` (`{"platform": "IOS", "screenKind": "tablet"}`) | iPad 13" screenshots when the app runs on iPad |
| `video` | `codecs`, `fps`, `minSeconds`, `maxSeconds`, `sizes`, `audioRequired`, `maxBytes` | Apple previews: 15–30 s, at most 30 fps |
| `pattern` | `regex` the field must match (or, with `"forbid": true`, must not) | support URL starts with `https://` |

Each file also has a `slots` table: Apple's display types (`APP_IPHONE_67`, `APP_IPHONE_61`,
`APP_IPAD_PRO_3GEN_129`, `APP_DESKTOP`, `APP_APPLE_TV`, …) with their platform, kind, accepted sizes, whether
required and what each falls back to; Google's `phone`, `tablet7`, `tablet10`, `tv`, `wear` with the API's image
type and size ranges, and the graphics (icon, feature graphic, TV banner). See [apple.md](apple.md) and
[google.md](google.md).

## When a check fails: fix the listing

A finding means the words or pictures break a store's rule. Change the config, the words or the picture. Don't
edit the rules files to make a check pass: they're copied into the skill from the plugin's shared folder, so a
local edit is overwritten on the next update, and it hides a real rejection until the store makes it.

## Relaxing a rule (the user's choice)

When the user decides a rule doesn't apply to them (a recommendation they choose not to follow, or a rule they
believe the store no longer enforces), it goes in the config with a reason:

```json
"rules": {
  "extraForbiddenWords": ["beta", "lorem"],
  "relax": [
    { "id": "google.screenshots.tablet10.count",
      "reason": "Four tablet shots are recommended, not required; we ship two for now." }
  ]
}
```

- `relax` turns that rule's findings off (`check` lists what was relaxed, so it stays visible).
- `extraForbiddenWords` adds the user's own words to every field: an old product name, a competitor, test words.
- The agent proposes a relaxation; the user makes it. Never add one to get past a check on your own.

## When the store has changed

If a rule's `source` page now says something else:

1. Read the page. Note what changed and the date.
2. **For the user, now:** relax the rule in their config with a reason that cites the page and date, if they
   agree, so their work isn't blocked.
3. **Upstream:** the rule, its `source` and its `checked` date change together, in the plugin's source
   repository (`plugins/app-stores/shared/rules/<store>.json` there), never in an installed skill's copy. That
   repository's `tools/sync_shared.py` copies it into each skill and `tools/test_sync_shared.py` checks the
   copies match. Open an issue or pull request there with the page and what it says now.
4. A rule that only a secondary source supports is `unverified`. A rule seen in a store's behaviour but not
   written down is `observed`.

## Stale rules

Every rule carries the date it was checked. Stores change their pages without notice: when a rule that matters
to the user's release was checked long ago (months), say so, and read its `source` before relying on it. The
check's report lists unverified rules; the agent should list them in its report too.
