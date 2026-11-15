# app-stores — interface contract

The single source of truth for the names, paths and data shapes every part of the `app-stores` plugin shares.
Build to it; change it here first if it must change.

`app-stores` takes an app's store presence from one config to the stores it's on: the App Store, Google Play
(and, to follow, the Amazon Appstore, Steam and itch.io). Any app, any stack. Proposal issues: #11
(`store-listings`), #12 (`store-screenshots`), #13 (`store-capture`); to follow: #14 (`store-signing`), #15
(`game-achievements`).

Hard constraints everywhere:

1. **Scripts are stdlib Python 3.8+** (no pip packages), macOS and Linux. No `match`, no `X | Y` types, no
   `str.removeprefix`, no `dict | dict`, no walrus in comprehensions' scope tricks; `from __future__ import
   annotations` is fine. External commands allowed: `openssl` (token signing), Google Chrome / Chromium
   (rendering), `ffmpeg`/`ffprobe` (video, optional, detected). Each is found at run time and its absence
   explained.
2. **No network by default.** Only `push.py` reaches a network, only the stores' own hosts
   (`api.appstoreconnect.apple.com`, Apple's upload hosts it's told to use, `oauth2.googleapis.com`,
   `androidpublisher.googleapis.com`; for `pull`, also Apple's public `itunes.apple.com`, Apple's image and media
   CDN `*.mzstatic.com` and Play's image hosts `play-lh.googleusercontent.com` and `lhN.googleusercontent.com`), and
   only `push.py apply` writes. `push.py pull` only reads, like `plan`.
3. **Privacy.** No real names, emails, ids, hosts, paths or keys in anything committed: examples use the
   invented app below. Secrets come from environment variables, never the config.
4. **Self-contained skills.** A skill references only files inside its own folder. Code and data two skills
   share live once in `plugins/app-stores/shared/` and are copied into each skill by
   `plugins/app-stores/tools/sync_shared.py`; `test_sync_shared.py` fails when a copy drifts.
5. **Every `.json` is plain JSON** (no comments: use `"$comment"`).

The invented example app: **"Sample Recipes"** by "Example Studio", bundle id / package `com.example.samplerecipes`,
`https://example.com/…` URLs, `support@example.com`.

---

## 1. Layout

```
plugins/app-stores/
  CONTRACT.md                     this file
  README.md                       the plugin's overview (consumer and author quick starts)
  shared/
    appstores_lib/                the shared Python package (§4)
      __init__.py  png.py  chrome.py  schema.py  text.py  web.py  jwt.py  locales.py  rules.py  jsonio.py
      test_*.py                   its unit tests (stdlib unittest)
    rules/
      rules.schema.json           the rules files' schema (§3)
      apple.json  google.json     one file a store (amazon, steam, itch to follow)
  tools/
    sync_shared.py                copies shared/appstores_lib → skills/*/scripts/appstores_lib,
                                  shared/rules → skills/*/rules (only into skills that list them in SYNC)
    test_sync_shared.py           fails if any copy differs from shared/
  skills/
    store-listings/
      SKILL.md  VERSION
      references/                 one topic a file (§6)
      schema/store-listing.schema.json   the config's schema (§2)
      rules/                      (copied from shared/rules)
      scripts/
        appstores_lib/            (copied from shared)
        listing.py                import | check | build | preview | diff (§5)
        push.py                   plan | apply | pull (§5; pull's code is push_pull.py)
        test_*.py                 unit tests, against fixtures in evals/files/
      templates/preview/          the page previews' HTML/CSS
      evals/evals.json  evals/trigger-evals.json  evals/files/
```

The marketplace entry (`.claude-plugin/marketplace.json`): plugin `app-stores`, `source: "./"`, `strict: false`,
`skills: ["./plugins/app-stores/skills/store-listings", …]` (paths from the repository root, as
`validate_marketplace.py` resolves them).

Scripts import the package by putting their own folder on `sys.path`
(`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`), then `from appstores_lib import png, …`.

---

## 2. The config: `store-listing.json`

One file in the user's project (any path; scripts take `--config`, default `./store-listing.json`). Paths inside
it are relative to the config's own folder. Schema: `skills/store-listings/schema/store-listing.schema.json`
(draft 2020-12 subset, §4 `schema.py`).

```json
{
  "$schema": "./store-listing.schema.json",
  "version": 1,
  "app": {
    "name": "Sample Recipes",
    "ids": {
      "apple": { "bundleId": "com.example.samplerecipes", "appId": "1234567890" },
      "google": { "package": "com.example.samplerecipes" }
    },
    "copyright": "2026 Example Studio",
    "contact": { "email": "support@example.com", "phone": null, "website": "https://example.com" },
    "urls": { "marketing": "https://example.com", "support": "https://example.com/support",
              "privacy": "https://example.com/privacy", "privacyChoices": null }
  },
  "primaryLocale": "en-US",
  "locales": {
    "en-US": {
      "description": "Plan a week of meals in minutes. …",
      "apple": { "name": null, "subtitle": "Plan meals in minutes", "keywords": ["recipes", "meal plan", "grocery"],
                 "promotionalText": "…", "whatsNew": "…", "description": null,
                 "platforms": { "TV_OS": { "description": "… the Siri Remote does it all." } } },
      "google": { "title": "Sample Recipes: Meal Planner", "shortDescription": "Plan a week of meals in minutes.",
                  "fullDescription": null, "video": null, "releaseNotes": null },
      "altText": { "featureGraphic": "A phone showing a week of planned meals" }
    },
    "de-DE": { "description": "…", "apple": { "subtitle": "…" }, "google": { "title": "…" } }
  },
  "screenshots": {
    "folder": "screenshots",
    "shots": [
      { "id": "plan",    "screens": null, "stores": null },
      { "id": "recipe",  "screens": ["iphone", "android-phone"], "stores": null },
      { "id": "shopping","screens": null, "stores": ["apple"] }
    ]
  },
  "screens": {
    "iphone":        { "kind": "phone" },
    "ipad":          { "kind": "tablet" },
    "android-phone": { "kind": "phone" },
    "android-tablet":{ "kind": "tablet" }
  },
  "stores": {
    "apple": {
      "enabled": true,
      "primaryLocale": null,
      "locales": null,
      "categories": { "primary": "FOOD_AND_DRINK", "primarySubcategories": [], "secondary": "LIFESTYLE",
                      "secondarySubcategories": [] },
      "platforms": {
        "IOS":    { "screens": ["iphone", "ipad"],
                    "previews": { "iphone": [ { "file": "previews/iphone.mp4", "posterFrame": "00:00:05:00" } ] } },
        "MAC_OS": null, "TV_OS": null, "VISION_OS": null
      },
      "ageRating": { "violenceCartoonOrFantasy": "NONE", "contests": "NONE", "…": "App Store Connect's own attribute names and values" },
      "review": { "notes": "…", "contact": { "firstNameEnv": "APPLE_REVIEW_FIRST_NAME", "lastNameEnv": "APPLE_REVIEW_LAST_NAME",
                  "phoneEnv": "APPLE_REVIEW_PHONE", "emailEnv": "APPLE_REVIEW_EMAIL" },
                  "demoAccount": null },
      "tvPrivacyText": null
    },
    "google": {
      "enabled": true,
      "defaultLanguage": "en-US",
      "locales": ["en-US", "de-DE"],
      "slots": { "phone": "android-phone", "tablet7": null, "tablet10": "android-tablet", "tv": null, "wear": null },
      "graphics": { "icon": "graphics/icon-512.png", "featureGraphic": "graphics/feature-1024x500.png", "tvBanner": null },
      "dataSafetyCsv": null
    },
    "amazon": { "enabled": false }, "steam": { "enabled": false }, "itch": { "enabled": false }
  },
  "forms": { "$comment": "drafted answers for forms with no API, printed by the checklist; free-form" },
  "rules": { "extraForbiddenWords": [], "relax": [ { "id": "google.screenshots.tablet10.count", "reason": "…" } ] }
}
```

Meanings:

- **Locales** are BCP 47 (`en-US`, `pt-BR`, `zh-Hans`). Each locale's fields fall back, field by field, to the
  store's primary locale's, then `primaryLocale`'s; a store's own `description` falls back to the locale's shared
  `description` before moving on. `null` means "not set" (fall back); `""` means "set to empty". Mapping to each
  store's own codes is `locales.py`'s.
- **Locales per store:** `stores.<store>.locales` lists the config's locales a store gets (`null` or absent: every
  one); only those are checked, built and sent. A store's primary is `stores.apple.primaryLocale` or
  `stores.google.defaultLanguage` (`null`: `primaryLocale`) and must be one of its locales (a `config.*` error
  otherwise).
- **Per-platform Apple words:** App Store Connect keeps a version's words per platform. A locale's
  `apple.platforms.<IOS|MAC_OS|TV_OS|VISION_OS>` may set `description`, `keywords`, `promotionalText`, `whatsNew`,
  `marketingUrl`, `supportUrl` for that platform. A platform's field: its override in the locale → the locale's
  `apple.<field>` → (description) the locale's shared `description` → the same chain in the App Store's primary
  locale → in `primaryLocale`; the URLs end at `app.urls`. `name` and `subtitle` are app-wide (appInfo), never
  per platform. Rules run on each platform's words where they differ (`where`: `en-US apple.description (TV_OS)`).
- **Screenshots** are files at `<screenshots.folder>/<locale>/<screen>/<shot id>.png` (or `.jpg`), the layout
  `store-capture` and `store-screenshots` write. A locale without a file falls back to the primary locale's file
  for that screen and shot. `shots` is the order. `screens`/`stores` filters: `null` = all.
- **Screens** are the user's own device names; `kind` is `phone`, `tablet`, `desktop`, `tv`, `watch` or `xr`.
  **Which store slot a picture fills is decided by its pixel size** against the rules data (Apple's display types),
  and for Google by `stores.google.slots`.
- **Stores** are opt-in by `enabled`. Apple platforms are `IOS`, `MAC_OS`, `TV_OS`, `VISION_OS` (App Store
  Connect's names); `null` = not shipped.
- **Secrets** are never here. Fixed environment variables (overridable with `"auth": {…Env}` per store):
  Apple `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY` (a `.p8` path, its text, or its text in base64); Google
  `GOOGLE_PLAY_SERVICE_ACCOUNT` (a JSON key path, its text, or base64).

---

## 3. Rules data: `rules/<store>.json`

```json
{
  "$schema": "./rules.schema.json",
  "store": "google",
  "checked": "2026-11-14",
  "rules": [
    { "id": "google.title.length", "kind": "limit", "applies": { "field": "google.title" },
      "max": 30, "count": "characters", "severity": "error",
      "source": "https://support.google.com/googleplay/android-developer/answer/9898842",
      "checked": "2026-11-14", "status": "verified" }
  ],
  "slots": { "…": "store-specific tables, e.g. Apple's display types (below)" }
}
```

- `id`: `<store>.<area>.<what>`, stable forever (configs relax rules by id). Reuse fastlane precheck's names in the
  last part where they mean the same (`other_platforms`, `placeholder_text`, `test_words`, `free_stuff_in_iap`,
  `copyright_date`, `unreachable_urls`).
- `kind` and its fields:
  - `limit`: `max`, optional `min`, `count` ∈ `characters` (code points) | `graphemes` | `bytes` (UTF-8).
  - `count`: `min`/`max` pictures (or items, e.g. keywords).
  - `size`: `sizes` (list of `[w, h]`, either orientation unless `orientation` set) or `range`
    (`{minSide, maxSide, maxAspect}`).
  - `format`: `formats` (`png`, `jpeg`), `alpha` (false = an alpha channel is forbidden), `transparency` (false =
    see-through pixels are; an opaque alpha channel is fine), `maxBytes`.
  - `words`: `words` (list, matched as whole words, case-insensitive; entries starting or ending with a symbol
    match as written), `fields` they apply to.
  - `required`: a field or slot that must be present (`when` condition: e.g. `{"platform": "IOS", "screenKind": "tablet"}`).
  - `video`: `codecs`, `fps`, `minSeconds`, `maxSeconds`, `sizes`, `audioRequired`, `maxBytes`.
  - `pattern`: `regex` the field must (or with `"forbid": true` must not) match.
- `applies`: `field` (dotted config path after locale resolution: `apple.subtitle`, `google.title`,
  `description`…), or `slot` (a store slot id), or `fields`/`slots` lists.
- `severity`: `error` | `warning`. **A rule whose `status` isn't `verified` is reported as a warning whatever its
  severity**, saying it's unverified.
- `source` (URL), `checked` (date), `status` ∈ `verified` | `observed` | `unverified`, optional `note`.

Extensions (as the rules files use them; `rules.py` or the scripts evaluate every one):

- Kinds `enum` (`values`, or `valuesFrom`: a table in the same file, e.g. `categories.primary`,
  `categories.subcategories`, `ageRating.attributes`) and `checklist` (an `item` no script can decide; printed in
  `checklist.md` and the check's report, never an error).
- `applies.each` (check every item of a list, e.g. each keyword); `applies.media: "preview"` (Apple's previews).
- `count`: `unique`, `across` (a total across the listed slots, e.g. Play's "at least 2 across device types"),
  `of` (count only pictures within a size range, e.g. the featuring rules).
- `size`/`video`: `fromSlots: true` (use each slot's own sizes). `range.minAspect`. `video.containers`.
  `words.wordsFrom` (a field's words, e.g. keywords repeating the name or subtitle). `flags`, `noun`.
- `when` on any rule: `platform` (one or a list), `screenKind`, `slotUsed`, `slotMissing`, `update`, `game`.
  Apple's slots carry `required` with `requiredWhen`. A `required` rule naming several slots is met by any one.
  `orientation` ∈ `portrait` | `landscape` | `asListed`.
- Field paths: `apple.…`, `google.…`, `altText.…`, `description` are a locale's words after fallback; `app.…` and
  `stores.…` are read from the config's root; `captions` are screenshot captions (supplied by `store-screenshots`).
- Google's graphics (`icon`, `featureGraphic`, `tvBanner`) are slots with `group: "graphics"`.
- Apple slot order matters: a size that fits two slots goes in the first listed.

Config additions: `stores.google.category` (never sent; tells checks whether it's a game), `demoAccount:
{usernameEnv, passwordEnv}`, `auth` (Apple `{keyIdEnv, issuerIdEnv, privateKeyEnv}`, Google
`{serviceAccountEnv}`), `tvPrivacyText` is a path to a text file, file paths are relative.

Apple's `slots` table: each display type (`APP_IPHONE_67`, `APP_IPHONE_61`, `APP_IPAD_PRO_3GEN_129`,
`APP_DESKTOP`, `APP_APPLE_TV`, `APP_APPLE_VISION_PRO`, …) with `platform`, `kind`, `sizes`, `required` (and when),
`fallsBackTo`, and its preview type and sizes. Google's: `phone`, `tablet7`, `tablet10`, `tv`, `wear`, with the API's
image type (`phoneScreenshots`, `sevenInchScreenshots`, `tenInchScreenshots`, `tvScreenshots`, `wearScreenshots`),
counts and size ranges, plus the graphics (`icon` 512×512, `featureGraphic` 1024×500, `tvBanner` 1280×720).

---

## 4. `appstores_lib` (shared package)

Every function documented with a docstring; every module has `test_<module>.py`.

- **`jsonio.py`**: `load(path) -> object` (plain JSON, errors name the file and line), `dump(obj, path)`
  (sorted keys off, 2-space indent, trailing newline, atomic write via temp file + `os.replace`).
- **`text.py`**: `count(s, how) -> int` for `characters` | `graphemes` | `bytes`; `graphemes` handles combining
  marks, variation selectors, ZWJ sequences, skin-tone modifiers and regional-indicator pairs (no external data);
  `has_emoji(s) -> bool` (Unicode categories So/Sk plus emoji ranges, variation selector 16);
  `find_words(s, words) -> list[str]` (whole-word, case-insensitive, symbols literal).
- **`png.py`**: `info(path) -> ImageInfo` (namedtuple: `format` `png`|`jpeg`, `width`, `height`, `bit_depth`,
  `color_type`, `has_alpha` (colour types 4/6 or a `tRNS` chunk), `interlaced`, `srgb` (an `sRGB` chunk or
  untagged), `icc_name`); reads PNG chunks and JPEG SOF markers with `struct`. `decode_rgb(path) -> (w, h, bytes)`
  for 8-bit non-interlaced RGB/RGBA PNGs (zlib + the five filters), for contrast and seam checks.
  `md5(path)`, `sha256(path)`.
- **`chrome.py`**: `find_chrome() -> str` (`$CHROME`, then the macOS app paths, then `google-chrome`,
  `google-chrome-stable`, `chromium`, `chromium-browser` on `PATH`; a clear error otherwise).
  `class Chrome` (context manager): starts one headless Chrome with `--remote-debugging-pipe` (fds 3 and 4 via
  `subprocess.Popen(pass_fds=…)`, messages are JSON terminated by `\0`), `--headless=new`, `--disable-gpu`,
  `--hide-scrollbars`, `--force-color-profile=srgb`, a temp `--user-data-dir`. Methods:
  `render(url_or_path, width, height, out_path, fmt="png", quality=None, scale=1.0, timeout=60) -> dict`: opens a
  target, sets `Emulation.setDeviceMetricsOverride` to `width/scale × height/scale` CSS px at `deviceScaleFactor`
  `scale`, navigates, waits for load and `document.fonts.ready`, captures with `Page.captureScreenshot`
  (`format`, `quality`, `captureBeyondViewport: false`), writes `out_path`, and returns `window.__appstoresReport`
  if the page set one (else `{}`). With `full_page=<max CSS px>`, the page is laid out at the width, its
  `document.documentElement.scrollHeight` measured, and the picture made that tall (capped). `evaluate(expr)`.
  Closes targets it opened; kills Chrome on exit.
- **`schema.py`**: `validate(instance, schema) -> list[str]` (JSON-pointer-located messages) for the subset:
  `type` (incl. lists), `properties`, `required`, `additionalProperties` (bool or schema), `patternProperties`,
  `items`, `minItems`, `maxItems`, `uniqueItems`, `enum`, `const`, `minimum`, `maximum`, `minLength`, `maxLength`,
  `pattern`, `format` (`uri`, `email`, `date` loosely), `$ref` to `#/$defs/…`, `anyOf`, `oneOf`, `allOf`, `not`,
  `$comment` ignored.
- **`locales.py`**: BCP 47 ↔ App Store Connect locale codes and ↔ Play language codes (tables in the module for
  every locale each store supports); `apple(code)`, `google(code)`, raising a clear error for a locale a store
  doesn't have.
- **`rules.py`**: `load(store, rules_dir) -> RuleSet`; `RuleSet.for_field(field)`, `.for_slot(slot)`, `.get(id)`,
  `.slots`; `relaxed(ruleset, relax_list)`. `Finding` namedtuple (`rule_id`, `severity`, `where`, `message`,
  `source`, `status`). Helpers that evaluate `limit`, `words`, `pattern`, `count` rules on values.
- **`web.py`**: `request(method, url, headers=None, body=None, timeout=60, retry=False) -> Response`
  (`status`, `headers`, `body` bytes, `.json()`), `urllib.request` only; with `retry`, 5xx, 408, 429, timeouts and
  dropped connections wait 15/30/45 s (or `Retry-After`, capped at 120 s; tests can set
  `web.SLEEP = lambda s: None`) and try again, 4 tries in all; the last answer is returned as it came. Errors raise
  `HttpError(status, method, url, body_text)` only from `request_json(...)`, which also parses JSON.
  `TRANSPORT`: a module-level hook tests replace with a fake (`callable(method, url, headers, body, timeout) ->
  Response`), so no test touches a network.
  `REDIRECT_ALLOWED`: a caller's guard (`callable(url) -> bool`, default `None`: any) on the real transport's
  redirects: a GET follows one only to a URL it accepts (a refused one comes back as its 3xx); writes never follow.
- **`jwt.py`**: `load_key(value) -> str` (PEM text from a path, the text, or base64 of either; strips
  whitespace damage); `es256(pem, header, claims) -> str` (signs with `openssl dgst -sha256 -sign`, converts the
  DER signature to raw `r‖s`, 32 bytes each); `rs256(pem, header, claims) -> str`; `find_openssl()`.

---

## 5. Commands and their files

`listing.py` (store-listings):

- `import --from fastlane|supply|triple-t|expo|live <path> [--out store-listing.json] [--platform IOS|MAC_OS|TV_OS|VISION_OS]`:
  a first config from those layouts (words per locale, URLs, categories where present, screenshots copied into
  the folder layout). A fastlane folder is one Apple platform's (`--platform`, else its screenshots', else IOS); a
  later platform's differing words become its `apple.platforms.<P>` overrides. Each store's `locales` and primary
  are what its source had. Shot ids come from the file names (order number, device, size and locale taken off;
  `shot-NN` for a folder whose names don't each name a moment); Apple screens are named by device class
  (`iphone`, `ipad`, `mac`, `apple-tv`, `vision-pro`) unless a class has two display types; Play slots whose
  pictures are byte-identical share one screen.
  `--from live <existing/>` reads what `push.py pull` wrote (below): words, ids, URLs, categories, the age rating
  answers the rules know, App Review's notes, screenshots (their slot by display type, or by pixel size for the
  public lookup's device folders; pictures at no store size stay in `existing/`; shot ids from the uploaded file
  names, another locale's by position), and a field a non-primary locale leaves empty on the store as `""`; then it
  prints a summary of what's live (locales, lengths, pictures per slot).
- `diff [--config …] [--existing existing] [--stores apple,google] [--json]`: the config's resolved words (per
  locale and Apple platform), categories, copyright and picture counts per slot against `existing/<store>/listing.json`;
  each entry `unchanged`, `changed` (before → after), `only-live` (the config leaves it: the store keeps it) or
  `only-ours`. Fields a public pull lacks (`notPublic`) aren't compared. Offline; exit 0, or 3 with nothing pulled.
- `check [--config …] [--stores apple,google] [--json]`: schema, then every rule of every enabled store on the
  resolved words and the screenshot files; prints findings grouped by store and severity; exit 1 on any error.
- `build [--config …] [--out out]`: runs `check` first (stops on errors), then writes `out/` (below).
- `preview [--out out] [--png]`: writes `out/preview/index.html` (each store's page as it'll look: Apple's search
  row and product page, Play's listing, per locale) and, with `--png`, renders it through `chrome.py` to
  `out/preview/*.png` for an agent to look at: each page whole (up to 6,000 CSS px tall), descriptions shown in
  whole lines (never a word cut with an ellipsis glued on).

`out/` layout:

```
out/
  listing.json                   the normalised manifest push.py reads (below)
  apple/<platform>/metadata/<apple locale>/{name,subtitle,description,keywords,promotional_text,release_notes,
                                            marketing_url,support_url,privacy_url}.txt     (fastlane deliver)
  apple/<platform>/screenshots/<apple locale>/<NN>_<display type>_<shot>.png
  google/metadata/android/<play locale>/{title,short_description,full_description,video}.txt  (fastlane supply)
  google/metadata/android/<play locale>/images/{phoneScreenshots,sevenInchScreenshots,tenInchScreenshots,
                                                 tvScreenshots,wearScreenshots}/<NN>_<shot>.png
  google/metadata/android/<play locale>/images/{icon,featureGraphic,tvBanner}.png
  checklist.md                   every form with no API, with the drafted answers
  preview/
```

`out/listing.json`:

```json
{
  "version": 1, "builtAt": "…", "config": "store-listing.json",
  "apple": {
    "appId": "…", "bundleId": "…", "primaryLocale": "en-US",
    "app": { "categories": {…}, "ageRating": {…}, "copyright": "…",
             "localizations": { "en-US": { "name": "…", "subtitle": "…", "privacyPolicyUrl": "…", "privacyChoicesUrl": null } } },
    "platforms": {
      "IOS": {
        "localizations": { "en-US": { "description": "…", "keywords": "a,b,c", "promotionalText": "…", "whatsNew": "…",
                                      "marketingUrl": "…", "supportUrl": "…" } },
        "screenshots": { "en-US": { "APP_IPHONE_67": [ { "file": "apple/IOS/screenshots/en-US/01_…png", "md5": "…", "size": 123 } ] } },
        "previews":    { "en-US": { "IPHONE_67": [ { "file": "…", "md5": "…", "posterFrame": "…", "mime": "video/mp4" } ] } }
      }
    },
    "review": { "notes": "…", "contact": { "firstNameEnv": "…" }, "demoAccount": null }
  },
  "google": {
    "package": "…", "defaultLanguage": "en-US",
    "details": { "contactEmail": "…", "contactWebsite": "…", "contactPhone": null },
    "listings": { "en-US": { "title": "…", "shortDescription": "…", "fullDescription": "…", "video": "" } },
    "images":   { "en-US": { "phoneScreenshots": [ { "file": "…", "sha256": "…" } ], "featureGraphic": [ … ], "icon": [ … ] } },
    "dataSafetyCsv": null
  }
}
```

Locale keys in `listing.json` are each store's own codes (Apple's `en-US`, `de-DE`…; Play's `en-US`, `de-DE`…),
and each store has only its own locales (`stores.<store>.locales`), its primary as `apple.primaryLocale` /
`google.defaultLanguage`. `apple.platforms.<P>.localizations` are that platform's own words (overrides resolved);
fastlane's `apple/<P>/metadata/` likewise. `google.developer` (the copyright's holder, else the app's name) is for
the preview only; `push.py` never sends it.

`push.py` (store-listings):

- `plan <apple|google> [--out out] [--plan plan-<store>.json] [--age-rating] [--new-version 1.2.0]`: reads
  `out/listing.json` and the store (GET only), writes the plan, prints it. Never writes to the store, with one
  necessary exception made explicit: Google's API needs an edit open to read a listing, so `plan` opens an edit and
  deletes it before returning (it never commits).
- `apply <plan file> [--cancel-review]`: reads the store again, recomputes the fingerprint, **refuses if it differs
  from the plan's** ("the store changed since you planned: plan again"), then performs exactly the plan's actions in
  order and reports each. Google commits with `changesInReviewBehavior=ERROR_IF_IN_REVIEW` unless `--cancel-review`.

The plan file:

```json
{
  "version": 1, "store": "google", "createdAt": "…", "listing": "out/listing.json", "listingSha256": "…",
  "fingerprint": "sha256 of the canonical JSON of every remote value the actions compare against",
  "options": { "ageRating": false, "newVersion": null },
  "actions": [
    { "id": 1, "kind": "google.listing.update", "locale": "en-US",
      "summary": "change title: 'Old' → 'Sample Recipes: Meal Planner'",
      "set": { "title": "…" } },
    { "id": 2, "kind": "google.images.replace", "locale": "en-US", "imageType": "phoneScreenshots",
      "summary": "replace 3 phone screenshots with 4", "files": [ "…" ] }
  ],
  "unchanged": [ "en-US tenInchScreenshots: 4 pictures, as they are" ],
  "notes": [ "Play Console only: category, tags, content rating, target audience, ads, …" ]
}
```

`apply` also refuses when `out/listing.json` no longer matches `listingSha256`.

- `pull <apple|google> [--out existing] [--config store-listing.json] [--id ID] [--public] [--country us,gb]`: reads
  what's live (GET only; on Google an edit opened to read and deleted, as `plan` does) and writes `existing/<store>/`
  (below). The app is `--id` (Apple's bundle id or numeric app id, Play's package), else the config's `app.ids`; the
  key is the environment's, as for `plan` (the config's `stores.<store>.auth` may name the variables). Apple: the
  app information that's live (categories, the age rating declaration, each locale's name, subtitle, privacy URLs
  and Apple TV text), and per platform the version on sale (else the newest): copyright, each locale's words,
  screenshots per display type and previews per preview type, downloaded at full size from each asset's
  `templateUrl`; App Review's `notes` and `demoAccountRequired`, never its contact or demo account. Google: the
  details, each language's listing and every image type's images. `--public` (Apple, no key): Apple's iTunes Lookup
  API (`https://itunes.apple.com/lookup?bundleId=…&country=…`, then `&entity=macSoftware`), per storefront country
  (`--country`, default `us`; `CC:locale` names its language): name, description, release notes, seller, website,
  version, genres as categories, and the iPhone, iPad and Apple TV screenshot URLs, downloaded; a storefront whose
  words repeat an earlier one's is left out. `pull google --public` is exit 3 (no public API). Downloads go only to
  the hosts in constraint 2, following redirects only there; one that can't be had is listed in `failed` and the
  pull exits 1 with the words written. A folder at `existing/<store>/` that `pull` didn't write is never replaced
  (exit 3).

`existing/` layout:

```
existing/<store>/
  listing.json                   the store's shape in listing.json's vocabulary (store's own locale codes)
  README.md                      a summary: locales, lengths, pictures per slot, notes, what isn't public
  screenshots/<locale>/<slot>/<NN>.<ext>     Apple: display type (public: iphone|ipad|apple-tv|mac); Google: image type
  previews/<locale>/<preview type>/<NN>.<ext>   Apple only
```

`existing/<store>/listing.json`:

```json
{
  "version": 1, "store": "apple", "source": "App Store Connect", "pulledBy": "push.py pull", "pulledAt": "…",
  "apple": {
    "appId": "…", "bundleId": "…", "primaryLocale": "en-US",
    "app": { "state": "READY_FOR_DISTRIBUTION", "categories": {…}, "ageRating": {…},
             "localizations": { "en-US": { "name": "…", "subtitle": "…", "privacyPolicyUrl": "…",
                                           "privacyChoicesUrl": null, "privacyPolicyText": null } } },
    "platforms": { "IOS": { "version": "1.3", "state": "READY_FOR_DISTRIBUTION", "copyright": "…",
      "localizations": { "en-US": { "description": "…", "keywords": "…", "promotionalText": "…", "whatsNew": "…",
                                    "marketingUrl": "…", "supportUrl": "…" } },
      "screenshots": { "en-US": { "APP_IPHONE_67": [ { "file": "screenshots/en-US/APP_IPHONE_67/01.png",
          "fileName": "…", "width": 1290, "height": 2796, "md5": "the upload's", "downloadedMd5": "the file's" } ] } },
      "previews": { "en-US": { "IPHONE_67": [ { "file": "…", "url": null, "posterFrame": "…", "mime": "video/mp4" } ] } } } },
    "review": { "notes": "…", "demoAccountRequired": false }
  },
  "notes": [ "…" ], "failed": [ ]
}
```

Google's `google` section: `package`, `defaultLanguage`, `details` (`contactEmail`, `contactWebsite`,
`contactPhone`), `listings` per language (`title`, `shortDescription`, `fullDescription`, `video`), `images` per
language and image type (`file`, `sha256` Play's, `downloadedSha256`, `width`, `height`). A public pull adds
`notPublic` (the fields it can't have: subtitle, keywords, promotional text, support and privacy URLs, copyright,
the age rating answers, review notes, previews) and `public` (per country: locale, store URL, seller, website,
version, release date, genres, age rating text, advisories, languages, price, icon URL); its source is
`iTunes Lookup (public)`.

As built (wave 2): `listing.json` also has the Apple TV privacy text in `apple.app.localizations[<primary>].privacyPolicyText`, `apple.auth` and
`google.auth` (variable names), and `apple.review.contact`/`demoAccount` as variable names (`demoAccount: null` = no
sign-in needed). An unset Play `video` is `null` (left as the store has it); `""` clears it. The plan file also
carries `compared` (each compared key's hash and, for pictures, a count) so a refusal can say what changed. Play's
default language differing from the config is a note, never an action. An edit whose commit is refused
(`CHANGES_ALREADY_IN_REVIEW`) is deleted.

Behaviour the docs and evals rely on:

- **Exit codes** for both scripts: `0` done; `1` a check error or a store's error (its message printed as it
  came, after any cleanup warning, never replaced by it); `2` a refusal (`apply` when the store or the listing
  changed since the plan); `3` usage or environment (a missing key, Chrome, openssl).
- `plan` writes `plan-<store>.json` in the current folder unless `--plan` says otherwise.
- `--new-version X` adds an `apple.version.create` action per platform with no version in preparation. Without it,
  a platform with none gets a note ("no version in preparation: … pass --new-version"), and its version-level
  words and screenshots are left out of the plan (app-level info still goes).
- A non-null `dataSafetyCsv` becomes a `google.dataSafety.update` action.
- `--age-rating` adds `apple.ageRating.update` when the answers differ.
- Review contact values come from the environment named in the config; a phone number is printed with only its
  last 4 digits. A missing variable is a note, not an error (the field is left as the store has it).
- `listing.py check --json` prints `{"findings": [Finding as an object…], "fallbacks": [...], "relaxed": [...]}`;
  without `--json`, the same as text. Relaxed rules are listed (with the reason), not hidden. A locale field or
  screenshot that fell back to the primary locale is reported as a fallback, not a finding. A screenshot or graphic
  a required slot needs and doesn't have is a finding.
- `listing.py import` can be run more than once into the same `--out` config (e.g. `--from fastlane` then
  `--from supply`): it merges, never overwrites a non-null value, and says what it took. It never copies review
  contact details or demo account credentials (fastlane's `review_information`) into the config: it names the
  environment variables to set instead.
- Steam and itch.io (and Amazon) are out of version 0.1's `build`; their checklists live in
  `references/sending.md` until their rules data lands.

---

## 6. References (store-listings)

`references/` holds, one topic a file: `config.md` (every field), `rules-data.md` (the format, how to update a
rule and its source and date), `apple.md`, `google.md` (what each sends, slots, quirks, keys and roles),
`words.md` (limits, price words by field, other platforms, What's New), `forms.md` (App Privacy, Play Data safety,
age and content ratings: the stores' definitions quoted and dated), `sending.md` (plan and apply, retries, the one
open edit, review in progress; pull is read-only), `existing.md` (starting from what's live: pull, `existing/`,
the public lookup, import, diff), `importing.md`, `pitfalls.md`, `agent-rules.md`.

---

## 7. Versioning

Each skill's `VERSION` starts at `0.1.0`. The repository's `CHANGELOG.md` gets an `app-stores` entry per PR. The
marketplace's `metadata.version` is bumped on release.
