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
- **Locales per Apple platform:** `stores.apple.platforms.<P>.locales` lists the App Store locales a platform gets
  (each one of the store's, the store's primary among them; `null` or absent: every one). App Store Connect keeps a
  version's listing per platform, so an Apple TV version can have fewer languages than the iPhone one. Only those are
  checked, built (`out/listing.json`'s `apple.platforms.<P>`, fastlane's `apple/<P>/`) and sent for that platform.
- **Kept slots:** `stores.<store>.keep` lists slots whose pictures stay as the store has them (Apple's display
  types, e.g. `APP_IPHONE_61`; Play's `phone`, `tablet7`, `tablet10`, `tv`, `wear`, `icon`, `featureGraphic`,
  `tvBanner`). Their pictures are still checked and previewed; the build marks each entry `"keep": true` in
  `out/listing.json`, and `push.py plan` leaves the slot alone (listed as unchanged). An unknown slot name is a
  `config.keep` warning.
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

- `id`: `<store>.<area>.<what>`, stable forever (configs relax rules by id). A `design` entry (8.6) has the id
  `<store>.design.<entry in snake case>` (`google.design.frames`, `google.design.ui_first`); `rules.relax` relaxes
  those too, and `listing.py check` warns only for a relaxed id the store's rules data has nowhere. Reuse fastlane precheck's names in the
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
  `.slots`, `.design_ids` (the `design` entries' ids), `.known(id)` (a rule or a design entry);
  `design_rule_id(store, entry)`; `relaxed(ruleset, relax_list)` (its result's `relaxed_rules`, `relaxed_design` and
  `unknown_relaxed`: ids in nothing the rules data defines). `Finding` namedtuple (`rule_id`, `severity`, `where`, `message`,
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
  prints a summary of what's live (locales, lengths, pictures per slot). It round-trips: the copyright exactly as
  live (a leading © kept, unlike the fastlane import); `stores.apple.platforms.<P>.locales` where a platform has
  fewer of the App Store's locales; `stores.<store>.keep` for every slot holding the store's re-encoded copies, or
  pictures per locale the config's fallback can't reproduce (a locale with fewer, or a Play graphic one language
  lacks); a public pull's pictures at an App Store size are copied in with their slots in `keep` (they're
  `reencoded`). A store not pulled is named at the end of the summary, with how to read it and what its listing
  still needs (its rules' unconditional `required` fields and graphics, the least screenshots, the screens for its
  slots). Pull → import → build → plan against the same store plans no action; only fields no API reads (Play's
  feature graphic alt text and privacy URL) may need writing for the check to pass.
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

- `pull <apple|google> [--out existing] [--config store-listing.json] [--id ID] [--public] [--country us,gb]
  [--thumbnails]`: reads
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
  version, genres as categories, and the iPhone, iPad and Apple TV screenshots, downloaded at the uploads' own size:
  the lookup's mzstatic address with its size box (`392x696bb.jpg`) swapped for `9999x9999bb.<png|jpg>` (the
  upload's format), which Apple's image service answers at the upload's size, never enlarged; the page's copy when
  that can't be had (noted), or with `--thumbnails` (Apple only, `--public` only; usage otherwise). Each picture's
  size is checked against the rules' slots for its device folder (`storeSize`). A storefront whose words repeat an
  earlier one's is left out. `pull google --public` is exit 3 (no public API). Downloads go only to
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
      "previews": { "en-US": { "IPHONE_67": [ { "file": "…", "url": null, "posterFrame": "…", "mime": "video/mp4" } ] } },
      "review": { "notes": "…", "demoAccountRequired": false } } },
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
`iTunes Lookup (public)`. Its pictures carry `url` (the lookup's), `fetchedUrl` (what was downloaded, when the
upload's size was asked for), `fileName`, `width`, `height`, `storeSize` (the display type the size fills, or `null`)
and `reencoded: true`; the README says they're the App Store's re-encoded copies and that the import keeps their
slots.

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
  without `--json`, the same as text. Relaxed rules are listed (with the reason), not hidden; a relaxed design entry
  carries `"for": "store-screenshots"`. A locale field or
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

## 8. `store-screenshots`

Designs and renders store screenshots from an app's real captures: one design, every store, size and locale.
Proposal issue #12. Research behind it: screenshot design principles with their evidence (shots 1–3 decide the first
impression; one message a shot; captions sized for the thumbnail; one set per store; drawn frames only).

### 8.1 Layout

```
skills/store-screenshots/
  SKILL.md  VERSION
  references/      principles.md (each with its evidence grade), store-rules.md (what each store allows in a
                   screenshot), layouts.md, frames.md (fitted drawn frames, the device classes; a maker's art as it is),
                   panoramas.md, localisation.md, legibility.md, checklist.md (the pre-ship list), evidence.md,
                   style.md, baseline.md, current-set.md (reading the listing's current set first)
  schema/store-screenshots.schema.json
  templates/       set.html (the engine page), layouts/*.css, base.css
  (frames)         drawn by scripts/frames.py for each capture (no frame files): phone, tablet, watch, tv, laptop,
                   desktop and the classes phone-classic, foldable-outer, foldable-inner. Generic: no notch, island,
                   home button, camera bump or brand shape; no buttons or cutout on Apple targets (Apple's
                   guidelines forbid simulating its devices).
  mocks/           search-row.html, product-page.html, play-listing.html, contact-sheet.html
  rules/           (copied from shared/rules: the stores' `design` tables)
  scripts/
    appstores_lib/ (copied)
    render.py  check.py  sheet.py  styles.py  baseline.py  frames.py (fitted frames, device classes, finding a
    device art's screen)  samples.py (made-up screens for --styles)  test_*.py
  evals/  evals.json  trigger-evals.json  files/
```

### 8.2 The design config: `store-screenshots.json`

Beside `store-listing.json` usually; paths relative to it. Plain JSON, schema in `schema/`.

```json
{
  "$schema": "./store-screenshots.schema.json",
  "version": 1,
  "captures": "captures",
  "out": "screenshots",
  "primaryLocale": "en-US",
  "locales": ["en-US", "de-DE"],
  "theme": {
    "fonts": [ { "family": "Brand Sans", "src": "fonts/BrandSans.woff2", "weight": "400 900", "style": "normal" } ],
    "palette": { "background": "#0E3B2E", "ink": "#FFFFFF", "accent": "#FFC94D" },
    "background": { "kind": "color" },
    "caption": { "placement": "top", "align": "center", "maxLines": 2, "weight": 800, "sizePct": 8.0,
                 "floorPct": 6.0, "font": "Brand Sans" },
    "frame": "phone"
  },
  "targets": {
    "iphone":        { "store": "apple",  "width": 1320, "height": 2868, "capture": "iphone-6.9" },
    "iphone-medium": { "store": "apple",  "width": 1206, "height": 2622, "capture": "iphone-6.3" },
    "ipad":          { "store": "apple",  "width": 2064, "height": 2752, "capture": "ipad-13", "frame": "tablet" },
    "android-phone": { "store": "google", "width": 1080, "height": 1920, "capture": "android-phone" }
  },
  "shots": [
    { "id": "plan",   "capture": "plan",   "layout": "hero",         "caption": "cap.plan", "proof": "cap.proof" },
    { "id": "recipe", "capture": "recipe", "layout": "framed-bleed", "caption": "cap.recipe",
      "callout": { "rect": [0.08, 0.42, 0.84, 0.12], "scale": 1.35 } },
    { "id": "shop",   "capture": "shopping", "layout": "tilt", "tilt": "left", "caption": "cap.shop",
      "targets": ["iphone", "iphone-medium", "ipad"] }
  ],
  "panorama": null,
  "stores": { "google": { "frame": "none" }, "apple": {} },
  "strings": {
    "en-US": { "cap.plan": "Plan a week of meals in minutes", "cap.recipe": "Every recipe, step by step",
               "cap.shop": "Your list, sorted by aisle", "cap.proof": "Loved by home cooks" },
    "de-DE": { "cap.plan": "Eine Woche Essen in Minuten planen" }
  }
}
```

- **Captures** are `store-capture`'s layout: `<captures>/<locale>/<capture device id>/<capture screen id>.png`; a
  locale without one falls back to the primary locale's (reported). A capture must be at least the size its target
  shows it at (never upscaled past 1.0; the check says when it would be).
- **Targets** are the output screens: each one's id is the `screens` name `store-listing.json` uses, `width`×`height`
  its exact pixels, `store` which store's rules apply, `capture` which capture device feeds it, optional overrides
  (`frame`, `layout`, `caption`). Output: `<out>/<locale>/<target id>/<shot id>.png` — exactly the folder layout
  `store-listings` reads.
- **Shots** are the ordered set: `capture` (the capture screen id), `layout`, `caption` and `kicker`/`proof` (string
  keys), `targets` (null = all), layout options (`tilt`: `left`|`right`, `callout`: rect as fractions of the capture
  and a scale, `pair`: a second capture, `at`: `top`|`bottom` for `fullbleed`).
- **Strings** per locale, falling back key by key to the primary locale (reported). Placeholders none.
- **Stores** override theme and per-shot settings for every target of that store (`frame`, `layout`, `caption`:
  `false` for no words, e.g. a store whose rules want none).
- **Panorama** (optional): `{ "shots": [ids in order], "background": "path or null", "seam": 6 }` — those shots
  share one canvas N slots wide; each slot is rendered with the canvas shifted; nothing load-bearing within `seam`
  units of a seam.

### 8.3 Units and layouts

`--u` is 1% of the slot's width. Aspect classes: `tall` (< 0.6 w/h), `mid` (0.6–0.85), `square` (0.85–1.2), `wide`
(> 1.2); each layout's CSS has rules per class (`[data-aspect="tall"]` etc.), so one design renders every size.

| Layout | What it is |
|---|---|
| `fullbleed` | the capture fills the slot, a caption plate over it (`at` top or bottom) — games' usual |
| `band` | a caption band, the capture below it, no frame |
| `framed` | the capture in a drawn frame, whole, caption above |
| `framed-bleed` | framed and cut off by the bottom edge (the apps' usual) |
| `tilt` | framed, rotated in 3D (CSS `perspective` + `rotate3d` presets), soft shadow |
| `pair` | two framed captures at true relative scale |
| `callout` | `framed-bleed` plus a clipped, enlarged copy of `callout.rect` lifted out with a shadow |
| `hero` | brand and claim large, `proof` line, and real UI (2.3.3: the app in use); beside the words on wide and square slots |
| `gameplay` | the capture full-bleed, no words, no frame |
| `fold` | a foldable's inner display split at the hinge and shown partly folded in 3D (`fold`: hinge, angle, outer) |

### 8.4 The render report: `<out>/render-report.json`

```json
{
  "version": 1, "renderedAt": "…", "config": "store-screenshots.json", "inputsSha256": "…",
  "files": [
    { "path": "en-US/iphone/plan.png", "locale": "en-US", "target": "iphone", "store": "apple", "shot": "plan",
      "layout": "hero", "width": 1320, "height": 2868, "captureFallback": false, "stringFallback": false,
      "caption": { "text": "Plan a week of meals in minutes", "lines": 2, "fontPx": 105.6, "floorPx": 79.2,
                   "atFloor": false, "fits": true, "box": [x, y, w, h], "textShare": 0.11,
                   "missingGlyphs": [] },
      "frame": { "name": "phone", "class": "phone", "box": [x, y, w, h], "screenRadius": 158.4,
                 "corners": { "radiusFrom": 158.4, "reduced": false, "clippedPx": 0 } },
      "callout": null, "captureScale": 0.92, "uiShare": 0.42, "seams": [], "notes": [], "sha256": "…" }
  ]
}
```

The page reports these through `window.__appstoresReport` (`chrome.render` returns it). `textShare` is the summed
area of every text box over the slot's area. Rendering is cached: a file isn't re-rendered when its inputs'
hash (config section, strings, capture bytes, fonts, templates, frames) is unchanged.

### 8.5 Commands

- `render.py [--config store-screenshots.json] [--locales …] [--targets …] [--shots …] [--force]`: renders through
  one `chrome.Chrome`, writes the PNGs (opaque, RGB, exact size) and the report. Exit 0, 1 (a render failed or a
  caption couldn't fit at the floor), 3 (usage/environment).
- `check.py [--config …] [--json]`: from the report and the PNG headers: exact size per target, no alpha, counts per
  store, caption fit/floor/lines/words (≤ 2 lines, warn over 6 words), text share (Google ≤ 20%, from the rules'
  `design` table), frame rules per store (Apple: drawn frames fine, a user's Apple bezel never tilted, cropped or
  overlapped; Google: frames discouraged — warning; Wear: none), forbidden words in captions (the rules' `words`
  rules whose fields include `captions`), missing glyphs, seams, contrast (WCAG ratio of the caption's ink against
  the median of the pixels behind its box, ≥ 4.5:1, from `png.decode_rgb`), capture upscaling, fallbacks; plus the
  checklist items a person must judge. Exit codes as `listing.py check`.
- `sheet.py [--config …] [--png]`: the mocks at real display size from the rendered files: Apple's search row (first
  three portrait shots at the row's real width, with the caption's size in points computed and shown), the product
  page's first screen, Play's listing row, and a contact sheet of every target × locale × shot with seams as
  gutters. `--png` renders them through Chrome to `<out>/sheets/*.png` for an agent to look at. The design sheets
  (§8.7): `--current [DIR]`, `--inspiration`, `--styles`, `--directions DIRS [--draft]`, `--compare DIR`.

### 8.5a Settled details

- **Drawn frames are fitted:** each is drawn for its capture (`frames.py`): the screen opening is the capture's
  exact size, the bezel even, the screen's corner radius the device class's (fractions of the short side), shrunk by
  the page where it would cut the capture's content, the corner's tip and pure-black pixels near it (a simulator's
  mask) aside (reported as the frame's `corners`; `check.py` warns if any is still cut, or the radius was cut to under
  half). A radius the frame object sets is kept (`corners.radiusSet`; what it cuts is reported). `frame` may be an object: `{name, class, radius, bezel, buttons, cutout, finish}`; buttons and cutouts
  are never drawn on Apple targets (`check.py` errors if a report shows them). A target's `device` names its class.
- **A user's own device art:** `frame` may be a path (relative to the config) to a PNG or SVG, or `{art, maker,
  screen?, screenRadius?, drawn?}`. A PNG's screen is its largest enclosed see-through region (from its alpha), unless
  the object or a JSON beside it (the drawn frames' shape, `"drawn": false`) gives it; an SVG needs one. `render.py`
  uses it as it is: the capture under the opening at its size (cut to fill if the shapes differ, never stretched), no
  shadow added, the report's `frame.art` = `{scale, fit: {captureAspect, screenAspect, cut}, screenSource}`. `check.py`
  refuses (error) tilt, crop (`framed-bleed`), callout overlap, a fold or 3D on a `maker: "apple"` frame (or one of no
  said maker) for Apple targets, and any maker's device art on Google targets is a warning; it warns on art upscaled,
  cut to fit or hiding content in its corners.
- **The fold layout:** the report's frame has `threeD: true` and `fold: {hinge, angle, pose: open|cover, outer:
  {box, captureScale}|null}`, its `box` the projected device. A fold always draws a generic frame.
- **Precedence:** a target's `layouts` entry for the shot beats the target's overrides, which beat store overrides,
  which beat shot settings, which beat the theme.
- **Exit codes:** `render.py` and `sheet.py` exit 3 when Chrome is missing. `render.py` writes the report even when it
  exits 1 for a caption that won't fit at the floor.
- **Sheets** are `<out>/sheets/search-row-<locale>.png`, `product-page-<locale>-<target>.png`,
  `play-listing-<locale>.png`, `contact-sheet.png`.
- **Targets' `store`** is `apple` or `google` in 0.1 (Steam and itch.io are reference only).
- `store-listings` ignores `render-report.json` and `sheets/` beside the locale folders.
- `check.py` and `sheet.py` take `--report PATH` (default `<out>/render-report.json`; file paths in it stay relative
  to `<out>`) and `--listing PATH` (default `store-listing.json` beside the config, if there), from which they read
  `stores.google.slots` (which Play slot a target fills), the category (Play's featuring counts) and `rules.relax`;
  `sheet.py` also takes the app's name, subtitle and icon from it.
- The report's `caption` also carries `ink` and `accent` (#RRGGBB), and `kicker`/`proof` their `ink`, for contrast.
- `uiShare`: the share of the slot showing the app's screen; a `hero` counts as in use when it's 0.3 or more.
- `check.py` and `sheet.py` take `--out DIR` (a rendered folder relative to the config: an exploration); a report's
  file paths are relative to its own folder, and a report outside the config's `out` is an exploration (its style
  from the report, its sheets beside it, no counts, no baseline). Once `stores.google.slots` gives Play slots, a
  Google target it leaves out is in no slot (never guessed).
- `sheet.py --compare` takes a render folder (drift) or the live set: a folder of pictures with no report, or
  `current`/a `current.json` (its `source`): each new shot beside the live one it replaces, by the screen it shows,
  else by place. Sheets and the report order targets App Store first, phones before foldables, tablets, computers,
  TVs and watches.
- Frame JSON: `{name, kind, orientation, drawn, maker, viewBox, screen: {x, y, width, height}, screenRadius, stretch,
  realWidthMm}`. A user's own art: the same with `"drawn": false` and its `maker`; never stretched.
- Schema additions to §8.2: `theme.icon`; `theme.palette.{background2, plate, plateInk, band, bandInk}`;
  `theme.background.kind` ∈ `color` | `gradient` | `glow` (default) | `image` with `src`, `angle`, `dim`;
  `caption.plate` ∈ `solid` | `scrim` | `none` (fullbleed); `caption.align: "end"`; `shot.frame`, `shot.captionStyle`;
  `shot.pair` (a capture screen id or `{capture, device, frame}`); `panorama.seam` may be null. In captions, `*word*`
  takes the accent colour (across a `\n` too) and `\n` breaks the line. Later: `theme.hero` (`logo`, `fit: wide|tile`,
  `widthPct`), `theme.tilt` and a shot's tilt object (`side`, `y`, `x`, `z`, `perspective`), `theme.fold` and
  `shot.fold`, `caption.maxWidthPct` and `caption.widthPct`, `theme.hero.maxHeightPct`, `target.device`, `target.slot`,
  `target.layouts` (a shot's layout on that target), `target.hero` (over `theme.hero`), the frame object. A caption
  whose words or hero mark leave the slot doesn't fit (`caption.fits: false`, `caption.outside: [roles]`); the hero's
  mark shrinks before its claim to keep the block in its room. The render cache's hash covers the job and
  every config value a file depends on (its target, store overrides, shots, theme, panorama).

### 8.6 Rules data: the `design` table

Each store's rules file gets a top-level `design` object (beside `slots`), each entry with `source`, `checked`,
`status` like a rule: `frames` (`allowed` | `discouraged` | `required` | `forbidden`, per slot group where it
differs, e.g. Google's Wear `forbidden`: Wear OS screenshots must have no frame), `maxTextShare` (Google 0.2 for promotion), `captions` (allowed or not),
`awards` (allowed or not), `deviceArt` (whose device art may be used and how), `inUseMajority` (Apple: more than
half of a set shows the app in use), `backgrounds`, and `uiFirst` (Google: real UI in the first three).
A finding from an entry has the id `<store>.design.<entry in snake case>` (`rules.design_rule_id`: `uiFirst` ->
`google.design.ui_first`); `store-listing.json`'s `rules.relax` relaxes it, and `listing.py check` knows the id.

### 8.7 Taste, directions and the baseline

A set should look like one family across updates. The skill gets there in five steps, after a step 0 for an app
that already has a listing; the files live in the user's project beside the config (paths relative to it), under
`design/` unless the config's `"design"` names another folder.

0. **The current set.** Most apps have a live listing; its screenshots are the baseline for the story. They come from
   `store-listings`' `push.py pull` (`existing/<store>/screenshots/<locale>/<slot>/<NN>.<ext>`) or any folder (e.g.
   `assets/screenshots/<device>/Screenshot-NN.png`). `sheet.py --current <folder>` groups the pictures (a pulled
   listing by store, locale and slot, App Store first, its other pictures left out; any other folder by subfolder),
   orders each group by the number in the names, writes a skeleton `design/current.json` when there's none, and lays
   each shot beside its analysis in `design/sheets/current.png` (`--current` alone reads `current.json`'s `source`).
   The agent fills `design/current.json` (schema `$defs/current` in the style schema): `{"version": 1, "source":
   "<folder>", "shots": [{"file" (relative to source), "group", "order" (from 1), "screen" (the app screen it
   shows), "capture" (the capture screen id for it now), "caption" (the words on it, read from the picture), "layout"
   (the skill's vocabulary; a plain screenshot is gameplay), "traits": {…}, "verdict": "keep"|"change"|"drop"|null,
   "notes"}], "summary": {"traits": {…}, "look": "keep"|"evolve"|"replace"|null, "whatWorks": [..], "whatDoesnt":
   [..], "notes", "confirmedByUser": bool}}`. Verdicts, `look` and `confirmedByUser` are the user's. The storyboard
   starts from it (the screens kept, in order; their captions kept or rewritten); the inspiration board shows it as
   one example (to keep or move away from).
1. **Inspiration.** The user provides 3–6 examples they like and 1–2 they don't (images they saved, of any app or game)
   in `design/inspiration/`. The agent writes `design/inspiration/inspiration.json`:
   `{"version": 1, "examples": [{"file", "source" (free text: where it came from), "likes": [..], "dislikes": [..],
   "traits": {…}}], "summary": {"traits": {…}, "confirmedByUser": true|false}}`. `traits` use the vocabulary in the
   style schema (§ below). Examples inform the style only: never their marks, illustrations or trade dress. Scripts
   never fetch anything; `sheet.py --inspiration` lays the examples out with their notes for the user to confirm
   (the current set's card first, when `current.json` exists). With no examples, `sheet.py --styles` renders every
   starting style on one made-up app (screens drawn at run time by `samples.py`, never committed) into
   `design/sheets/styles.png`, for the user to pick by eye.
2. **Directions.** 2–4 candidate styles, each `design/directions/<name>/screenshot-style.json` (from the shipped
   starting points in `styles/` or written fresh). `render.py --style <file> --out design/explore/<name> --shots
   <first 3> --targets <one>` renders each; `sheet.py --directions design/explore/a,design/explore/b,…` shows them side
   by side at search-row size and full size. When the user asks for directions up front, the agent may in one turn
   draft the brief and storyboard (from the current set) and render 2–3 directions' first three shots; `--draft`
   heads the sheet "Drafts for you to correct", and nothing is chosen, logged, approved or locked until the user
   answers.
3. **Iterate.** One change a round; `sheet.py --compare <previous out>` shows before and after. Each decision the user
   makes goes in `design/decisions.md` (date, what, why, in the user's terms).
4. **Approve the baseline.** `baseline.py approve [--note "…"]`: needs a render report for the current config and style
   (same `inputsSha256`), copies the renders, the report and the style file into `design/baseline/` (the previous
   baseline moves to `design/baseline/history/<date>/`), writes `design/baseline/baseline.json`
   `{version, approvedAt, note, style: "<path>", styleSha256, configSha256, report: "render-report.json",
   files: [...]}`, and sets the style's `"locked": true`.
5. **Updates.** Renders use the locked style. `check.py --baseline [design/baseline]` measures drift per target and
   role (or layout) against the baseline's report — caption size relative to width, caption box top and height, line
   count, frame name and box (x, y, width, height as fractions), tilt, text share, caption ink and accent, background
   kind — using the style's `drift` tolerances; drift is a warning (the user decides). A locked style whose hash
   differs from the baseline's is an **error** ("the locked style changed: approve a new baseline with the user, or
   put it back"). `sheet.py --compare design/baseline` pairs baseline and current shots. `baseline.py status` says
   whether the style or config changed since the baseline and which shots have no baseline counterpart.
   `baseline.py unlock --reason "…"` (only when the user asks) clears `locked` and logs the reason in `decisions.md`.

**The style file `screenshot-style.json`** (schema `schema/screenshot-style.schema.json`):

```json
{
  "version": 1, "name": "Bold caption on brand colour", "locked": false,
  "traits": { "captionPosition": "top", "captionSize": "loud", "captionWeight": "heavy", "captionCase": "sentence",
              "emphasis": "accent-word", "device": "realistic", "devicePlacement": "bleed-bottom",
              "background": "brand-colour", "density": "standard", "colour": "monochrome-brand", "mood": "bold" },
  "theme": { "…": "the same object as the config's theme (§8.2)" },
  "roles": { "hero": { "layout": "hero" }, "feature": { "layout": "framed-bleed" },
             "detail": { "layout": "callout" }, "accent": { "layout": "tilt", "maxPerSet": 1 },
             "gameplay": { "layout": "fullbleed" } },
  "stores": { "google": { "frame": "none" } },
  "copy": { "maxWords": 5, "maxLines": 2, "case": "sentence", "emphasis": "one accent word at most" },
  "drift": { "…": "tolerances: see schema/screenshot-style.schema.json and references/baseline.md" }
}
```

- A role may carry `stores`: `{"google": {"layout", "frame"}}`, the role's layout and frame on that store's targets
  where the shot sets none of its own (between the shot's settings and the config's store overrides). The app
  starting styles give their `hero` a Play layout of real UI this way, so shot 1 doesn't trip `google.design.ui_first`.
- The config names it with `"style": "screenshot-style.json"`. With a style, a shot may give a `role` instead of a
  `layout` (the style's `roles` map it); a shot's own `layout` still works, and with a locked style one that isn't in
  `roles` is a warning. The config's `theme` and `stores` are merged under the style's (the style wins); with a locked
  style, a config `theme` key that differs from the style's is a check error.
- `traits` values come from a fixed vocabulary in the schema (enums), shared with `inspiration.json`.
- The skill ships starting points in `skills/store-screenshots/styles/*.json` (named directions, each with its traits,
  numbers and who it suits).
- `copy` rules are checked on captions (`maxWords`, `maxLines`, `case`) as warnings.

## 10. `store-capture`

Captures an app's screens (and preview videos) at exactly the sizes the stores want, on any stack, by whichever
technique fits the app. Proposal issue #13. Its output is what `store-screenshots` reads as captures and what
`store-listings` reads as screenshots when they go up as they are.

### 10.1 Layout

```
skills/store-capture/
  SKILL.md  VERSION
  references/   staging.md (agreeing with the user which screens and how each is staged: sign-in, data, skips,
                permissions, flags, clock, network, what each looks like in use, state and verify, confirming on
                one screen, reuse, updating after the app changed),
                choosing.md (which technique for which app: a decision table), screenshot-mode.md (adding a
                launch-argument / deep-link screenshot mode to an app, per stack), devflow.md, ailoha.md, appium.md,
                ui-automation.md (XCUITest, UI Automator, Maestro, macOS Accessibility), simctl.md, adb.md, web.md,
                desktop.md, engines.md (Unity, Godot, Unreal), importing.md, video.md, clean-state.md (status bar,
                demo data, clock, locale, appearance), sizes.md (which device renders which store size natively),
                pitfalls.md, config.md (every field of the plan)
  schema/capture-plan.schema.json
  scripts/
    appstores_lib/   (copied)
    capture.py       plan → drivers → folder + report
    drivers/         one module per driver (§10.3)
    import_captures.py  check_captures.py  video.py  test_*.py
  evals/  evals.json  trigger-evals.json  files/
```

### 10.2 The capture plan: `capture-plan.json`

```json
{
  "$schema": "./capture-plan.schema.json",
  "version": 1,
  "out": "captures",
  "app": { "ios": { "bundleId": "com.example.samplerecipes", "app": "build/SampleRecipes.app" },
           "android": { "package": "com.example.samplerecipes", "activity": ".MainActivity", "apk": "build/app.apk" },
           "web": { "url": "http://localhost:8080" } },
  "locales": ["en-US", "de-DE"],
  "appearance": "light",
  "clock": "09:41",
  "statusBar": "clean",
  "seed": "demo",
  "appSource": { "repo": ".", "paths": ["src/SampleRecipes/Pages"] },
  "staging": {
    "account": { "kind": "demo", "env": ["SAMPLE_DEMO_USER", "SAMPLE_DEMO_PASSWORD"] },
    "seed": { "kind": "command", "run": "./store/seed-demo.sh" },
    "launch": { "args": { "DemoUser": "${SAMPLE_DEMO_USER}" }, "env": { "DemoUser": "${SAMPLE_DEMO_USER}" } },
    "skip": [ { "what": "onboarding", "how": "the screenshot mode marks it seen" } ],
    "permissions": { "ios": ["photos"], "android": ["android.permission.POST_NOTIFICATIONS"] },
    "clock": { "now": "2026-11-14T09:41", "how": "ScreenshotNow" },
    "network": { "kind": "offline" },
    "inUse": { "rule": "screens look filled out, in use", "by": "the user, in chat, 2026-11-14", "save": false },
    "notes": ["no real addresses on the map"],
    "confirmed": { "screen": "plan", "device": "iphone-6.9", "on": "2026-11-14" }
  },
  "devices": [
    { "id": "iphone-6.9", "platform": "ios", "driver": "simctl", "width": 1320, "height": 2868,
      "target": { "deviceType": "iPhone 17 Pro Max", "runtime": "latest" } },
    { "id": "android-phone", "platform": "android", "driver": "adb", "width": 1080, "height": 1920,
      "target": { "avd": "Medium_Phone", "wmSize": "1080x1920", "density": 420 } },
    { "id": "maui-iphone", "platform": "ios", "driver": "devflow", "width": 1320, "height": 2868,
      "target": { "deviceType": "iPhone 17 Pro Max" } }
  ],
  "screens": [
    { "id": "plan", "state": "this week's plan, five invented recipes", "inUse": "Tuesday's dinner ticked off",
      "steps": [ { "launch": { "args": { "ScreenshotScreen": "plan" } } }, { "wait": { "text": "This week" } } ],
      "verify": { "text": "Lemon Pasta" } },
    { "id": "recipe", "steps": [ { "deepLink": "samplerecipes://recipe/demo" }, { "wait": { "id": "recipe-title" } } ] },
    { "id": "search", "devices": ["iphone-6.9"],
      "steps": [ { "launch": {} }, { "tap": { "id": "search" } }, { "type": { "text": "pasta" } },
                 { "wait": { "ms": 800 } } ] },
    { "id": "add-recipe", "inUse": "half written, not saved",
      "steps": [ { "launch": {} }, { "tap": { "id": "add" } },
                 { "fill": { "fields": [ { "field": "recipe-name", "text": "Lemon Pasta" }, { "field": "servings", "text": "4" } ],
                             "in": { "id": "recipe-form" }, "scrollTo": "top" }, "name": "fill" } ],
      "verify": [ { "id": "recipe-name", "contains": "Lemon Pasta" }, { "keyboard": "hidden" } ] },
    { "id": "flow-made", "steps": [ { "flow": "flows/onboarding.yaml" } ] }
  ]
}
```

- **Devices** promise an exact `width`×`height` (from the store's rules); a capture that comes out any other size is
  `failed`, never resized. `driver` picks the technique; `target` is the driver's own settings.
- **Screens** are reached by **steps**, run in order, then a screenshot. Step kinds: `launch` (`args`, `env`,
  `clean`: reinstall/clear data first), `deepLink` (a URL), `url` (web), `tap`, `type` (`text`, optional target),
  `wait` (`ms`, or an element to appear, with `timeout`), `scroll` (`to` an element, looked for one way then the
  other until the content stops moving, or `"top"`/`"bottom"`; or a `direction`; `in` an element: a pane scrolled
  within, not the screen's middle: the scroll view or anything inside it, whose nearest scrolling ancestor (a dump's
  or page source's `scrollable="true"`, a scroll view's type in a tree without that, the page's overflow container)
  is what's scrolled, else the element itself, said in the report's `panes` and kept for the screen's later scrolls
  once the element named is out of sight; on iOS through Appium a quick `mobile: swipe`, never a direction-only `mobile:
  scroll`, whose opening press can land on a field and reopen the keyboard), `back`,
  `swipe`, `flow` (a Maestro flow or a UI test name, run by the driver that understands it), `script` (a command
  the user provides, run as is, with `APPSTORES_DEVICE`, `APPSTORES_LOCALE`, `APPSTORES_SCREEN`,
  `APPSTORES_PLATFORM`, `APPSTORES_APP_ID` and the host's `APPSTORES_UDID` or `ANDROID_SERIAL`/`APPSTORES_SERIAL`),
  `appFile` (a file copied into the app's own data: the simulator's data container, Android's data folder through
  `run-as`), `settle` (wait for no animation: two identical frames, optionally ignoring rectangles), `posture`
  (`folded`, `open`, `half-open`: a foldable's posture mid-screen), `hideKeyboard` (close the on-screen keyboard if
  it's up, trying in order until it's down: the driver's own (Android's back only while it's up, Appium's `mobile:
  hideKeyboard`; `own: false` leaves it out), the app's own Done (`done`, an element or `{x, y}`; Appium on iOS
  looks for a button named Done, Close or Hide keyboard: a number pad has no key that closes it), a `scroll`, and
  last a `tap` on something neutral; still up, the step fails naming each try), `unfocus` (clear a text field's
  focus so no caret blinks: `tap` first if given, then Android's Escape only while the dump shows a focused field,
  failing if the screen changed; the web's `blur()`), `fill` (a form's fields typed in one step: a list of
  `{field, text}` (`field` an element or an id), or `{fields, in, keyboard, unfocus, scrollTo}`: each field
  scrolled into view both ways within `in` and typed, the keyboard closed before the next on Android; then the
  keyboard closed, the focus cleared and, with `scrollTo`, the form scrolled back, with a warning for each field the
  screen's `verify` names that's out of sight then (a `verify` sees only what's on screen); nothing submitted). Any step may carry a `name`. Elements are found by `id` (accessibility identifier / automation id /
  resource id / test id), `text`, `label` or `xpath`; `text` and `label` match exactly, then ignoring case and
  surrounding space, then contained, on every driver that can (Maestro: its own regex); the drivers that read a
  tree themselves (adb, uiautomator, the agents' trees) evaluate XPath 1.0's everyday part (`contains()`, `not()`,
  `and`/`or`, positions). A `wait` or `verify` element may add `contains`: the element found must show that text,
  itself or anything under it (ignoring case and runs of space), read from the dump, the agent's tree, Appium's page
  source, the page or the Accessibility tree; a driver that can't (`maestro`) skips such a `wait` and reports such a
  `verify` `unchecked`. Each driver says which it supports and reports `skipped` for steps it can't do.
- `locales`, `appearance` (`light` | `dark`), `clock`, `statusBar` (`clean` | `as-is`), `seed` (passed to the
  app as `ScreenshotSeed` in launch args / extras) and `posture` (a foldable's: `folded`, `open`, `half-open`; each
  posture captured is its own device, with its own id and size) are set per device by the driver before the screens
  and reset after.
- Any field may be overridden per device or per screen (`devices[].locales`, `screens[].devices`, …). A screen's
  `overrides` are keyed by a platform, a device's `layout` (a name devices that lay out alike share) or a device id,
  applied in that order: settings, `state`, `verify`, `steps` (a replacement), `stepsPatch` (changes to the steps
  before it: `prepend`, `append`, `remove`, `replace`+`with`, `before`/`after`+`insert`, by a step's `name` or
  position; a ref that isn't there is a plan error) and `omit` (the screen isn't captured there).
- **Staging** (`staging`, agreed with the user before the plan runs): `account` (`kind`: `none`, `guest`, `bypass`,
  `demo`; a demo account only by the names of its environment variables, `env`, never values and never a real
  person's account), `seed` (`kind`: `command` run before each screen, `file` copied into the app's data as an
  `appFile` step, `launch`, `backend`, `none`; `when`: `each-screen` or `once`), `launch` (`args` and `env` added
  to every `launch` step; `${NAME}` takes one of `account.env`, from the environment, masked in logs and reports),
  `skip`, `permissions` (by platform: granted before launch, revoked after), `flags`, `clock` (the app's own
  "now"), `network`, `inUse` (how the screens look in use, as the user put it: `rule`, `by`, `values`, `save`,
  default `false`; a run warns about each screen without its own `inUse`), `notes` (house rules, in `staging.md`),
  `confirmed` (`{screen, device, on}`: until set, `capture.py` captures one screen at a time),
  `doc` (the readable copy, default `staging.md`, written by `capture.py --write-staging`; a run warns when it no
  longer matches). A screen's `"staging": false` leaves it out.
- **Per screen**: `state` (what it must show, in plain words), `inUse` (what it looks like in use: forms partly
  filled with believable values, lists populated, or why it's empty on purpose; `staging.md` shows it beside the
  values its `fill` and `type` steps enter) and `verify` (an element, or a list, that must be on
  screen before the shot, and `{"keyboard": "hidden"|"shown"|"any"}`; otherwise the shot is `missed`, "wrong
  state"). A screen that types nothing is checked for a hidden keyboard without asking, where the driver can tell
  (adb's `dumpsys input_method`, Appium's `mobile: isKeyboardShown`). `settle` after typing with no `unfocus` since
  warns when a field still has the focus (adb's dump, the page) or, where the driver can't tell, when the settled
  screen changes again within a second (a caret). Overrides may change `state`, `inUse` and `verify`.
- **The app's source** (`appSource`: `repo`, relative to the plan, default its folder; `paths`, relative to
  `repo`) and each screen's `sources` (its files, folders or globs): the report records the git revision each shot
  was taken at, and `capture.py --changes` lists what changed since then in those paths and the screens to re-check.
- `staging.confirmed` is set only on the user's own answer; an agent that can reach the user only through another
  agent stops after the one screen and asks, with the picture attached.

### 10.3 Drivers

| Driver | Platforms | How it reaches screens | Needs |
|---|---|---|---|
| `simctl` | iOS, iPadOS, tvOS, watchOS, visionOS simulators | `launch` args/env, `deepLink` (`simctl openurl`); taps only through another driver | Xcode |
| `adb` | Android phones, tablets, TV, Wear, Fire (emulators or devices) | `launch` extras, `deepLink` (`am start -d`), `tap`/`type`/`swipe`/`back` via `input` and `uiautomator dump` lookups | Android SDK platform-tools (and emulator) |
| `devflow` | .NET MAUI apps with the DevFlow agent (dotnet/maui-labs) | the agent's visual tree, actions and screenshots over its local HTTP API / CLI | the agent package in a debug build; its CLI |
| `ailoha` | MAUI, native Android, Swift, Flutter, React Native/Expo, WinUI, WPF apps with the Ailoha agent | the agent's UI tree, actions and screenshots via the `ailoha` CLI (or its local HTTP API) | the agent package; `@ailoha/cli` |
| `appium` | iOS (XCUITest driver), Android (UiAutomator2), Mac, Windows; MAUI, RN, Flutter, native | W3C WebDriver JSON over HTTP to a local Appium server (stdlib; no client library) | Appium 2/3 server and drivers |
| `xcuitest` | iOS/iPadOS/tvOS/macOS native and anything XCUITest drives | `flow`: runs `xcodebuild test -only-testing:` the user's screenshot tests, then exports attachments with `xcresulttool` | Xcode, a UI test target |
| `uiautomator` | Android | the device's own `uiautomator dump` + `input` (the `adb` driver's element finding, usable on its own) | platform-tools |
| `maestro` | iOS, Android, web | `flow`: `maestro test` a flow that calls `takeScreenshot`; or steps translated to a generated flow | Maestro CLI |
| `macos` | Mac apps | `launch`, Accessibility via `osascript` (System Events: click by name, keystrokes), `screencapture -l <window id>` with the shadow off | macOS, Accessibility permission |
| `chrome` | web apps, PWAs | headless Chrome (shared client): `url`, `tap`/`type`/`wait` by selector via `Runtime.evaluate` | Chrome |
| `import` | anything that already made screenshots | reads another tool's folder with a mapping (`import_captures.py`) | — |

Each driver is a module in `scripts/drivers/` with `prepare(device, plan)`, `run_screen(device, screen, locale)
-> Shot`, `reset(device)` (always called, in `finally`) and `capabilities()` (the step kinds and element finders it
supports). Drivers run external commands only through `drivers/base.py`'s `run()` (logs the command, a timeout,
a fake for tests) and talk HTTP only to `localhost`/`127.0.0.1` through `web.py`. `base.run_screen` checks the
screen's `verify` after its steps (`Shot.state_check`: `passed`, `failed`, `unchecked`, `none`) and, with
`--inspect`, saves its UI tree (`inspect_tree`).

**In-app agents are pinned**: `devflow` and `ailoha` list the agents, read each one's status (device id, package,
process), and use only the one that is the plan's app on the dedicated device (the simulator's UDID, directly or
through the process's path; on Android the process `pidof` reports on the serial), passing `--agent-port` (and on
Android `--device <serial>` and `ANDROID_SERIAL`) on every command; found again after each launch; none or several
is an error, never a guess. The app is changed only through the CLI (DevFlow's lease), one command at a time,
retried when another client's command turned it away; a reply of `success: false` fails the step. Status bars:
`verified` only when confirmed (iOS: `status_bar list`; Android: the bar's pixels moved with demo mode's clock),
else `unverified`.

**Foldables**: `adb` folds an emulator through its console (`emu fold`, `emu unfold`, `emu posture 2`, the hinge
sensor) and a real foldable through `cmd device_state state` (reset after), then wakes and unlocks it, finds the
physical display in use (`dumpsys display`), sets `wm size`/`wm density` again on it (each display keeps its own;
each is put back in its posture) and re-applies demo mode; `screencap -d` takes the display in use. `simctl` folds
the iPhone Duo simulator through DevFlow's fold control (`maui devflow device fold set …`, experimental, no agent
needed) and captures the display it made active (else the built-in screen of the device's size). Hosted drivers
fold through their host. **The full-screen keyboard**: before every tap on Android (`adb`'s, and Appium's and the
agents' on a device `adb` hosts) a keyboard that `dumpsys input_method` says is up and `mIsFullscreen=true` (text
entry in landscape: it covers the app) is closed with back, only while it's up; `hideKeyboard` closes it the same
way. A CoreSimulator hiccup ("server died") in `simctl` boot, install, launch or capture is
tried once more.

**Appium's WebDriverAgent port**: an XCUITest session on a simulator asks for the device's own
`appium:wdaLocalPort` (8130-8199) and `appium:mjpegServerPort` (9130-9199), the same offset in both, derived from
the plan's device id (CRC-32), never WebDriverAgent's default 8100; chosen once a run, before the first session.
A port something already listens on (`base.LISTENING`, 127.0.0.1) is passed over for the next in the range, logged
and kept in the device's warnings, unless it's a WebDriverAgent whose `GET /status` names the device's own
simulator; one that names another, or none, is passed over. A port `target.capabilities` sets is kept unchecked;
with `appium:webDriverAgentUrl` no WDA port is set. The report's `devices` entry carries them as `source.wdaPort`
and `source.mjpegPort`; `--dry-run` prints them.

**Network**: drivers talk only to the local machine (simulators, emulators, devices over adb, a local Appium
server, the in-app agents on loopback ports). Nothing reaches the internet.

### 10.4 Output

`<out>/<locale>/<device id>/<screen id>.png` — 8-bit RGB (no alpha, no `tRNS`), sRGB, not interlaced, exactly the
device's size — and `<out>/capture-report.json`:

```json
{ "version": 1, "startedAt": "…", "plan": "capture-plan.json",
  "shots": [ { "locale": "en-US", "device": "iphone-6.9", "screen": "plan", "status": "taken",
               "path": "en-US/iphone-6.9/plan.png", "width": 1320, "height": 2868, "sha256": "…",
               "driver": "simctl", "source": { "deviceType": "iPhone 17 Pro Max", "runtime": "iOS 27.2" },
               "statusBar": "verified" | "overridden" | "unverified" | "none", "fixes": [], "warnings": [],
               "panes": ["in id 'servings': scrolled its nearest scrolling ancestor, android.widget.ScrollView …"],
               "state": "…", "stateCheck": "passed" | "failed" | "unchecked", "appRevision": "<git commit>" },
             { "…": "status missed: not reached (kept: previous|none, reason); failed: wrong size etc.; skipped: a step or device the driver can't do" } ],
  "app": { "revision": "<git commit>", "describe": "…", "committed": "…", "dirty": false, "repo": ".",
           "builds": { "ios": { "version": "2.1", "build": "214" } } } }
```

`app` is the app this run captured (git's, of `appSource.repo`; `builds` from an iOS-family `.app`'s `Info.plist`),
left out when the app isn't in a git checkout; each taken shot's `appRevision` is the commit it was taken at, so a
partial run's kept entries keep theirs. `devices` lists each device's `id`, `driver`, `source` (an Appium
simulator's with `wdaPort` and `mjpegPort`) and `warnings`. A run warns when the app moved since the shots the report keeps.

Adapters write into a temp folder and move files into place at the end. A run keeps the report's earlier entries
for plan items it didn't run (filters) and drops those the plan no longer has (removed or omitted), naming them in
`notes`. `panes` (left out when empty) says what a
scroll's `in` scrolled where it wasn't the element named. `fixes` lists what was changed
(`alpha-flattened`, `converted-to-srgb`, `16-bit-to-8-bit`), never a resize; an alpha channel that's all opaque is
flattened without a per-shot mention and counted once in the report's `notes`. `check_captures.py` reads PNG headers
against the plan (and, with `--rules`, the stores' accepted sizes; a required App Store display type no device fills
is a note) and lists what's wrong.

### 10.5 Rules every driver keeps

One state for every device of a kind, in one pass, same seed and clock; every screen as someone using the app sees
it (forms partly filled, lists populated, no placeholder-only fields, nothing saved unless that's the point; no
keyboard, caret or half-scrolled form unless asked); lay out at the target size (pick the device,
`wm size`, viewport) and never scale; a clean status bar where there is one, recorded as verified or not; wait for
the screen to settle (no toasts, spinners, keyboards unless asked); reset everything changed (status bar, demo mode,
`wm size`, locale, appearance, permissions) in `finally`; never touch the person's own simulators or devices unless
the plan names them (create and own dedicated ones by default: `appstores-<device id>`); report honestly.

### 10.6 Commands

- `capture.py [--plan capture-plan.json] [--devices …] [--screens …] [--locales …] [--keep-going] [--cleanup]
  [--dry-run] [--inspect]`: `--dry-run` prints each device's preparation and each step as the driver would run it,
  running nothing; `--inspect` saves each screen's UI tree to `<out>/.inspect/`. Exit 3 when a staged plan isn't
  confirmed and the run has more than one screen, or a staging account's variable isn't set.
- `capture.py --changes [revision]`: what changed in the app since the last capture (the oldest `appRevision` the
  report keeps, or the revision given), in `appSource.paths` and the screens' `sources`, uncommitted changes
  included: the commits, the files, and the screens to re-check, each with why (its `sources` changed; a step's or
  `verify`'s id or text is on a changed line, or removed and not added back), then what to do next (show the user,
  build clean, one screen at a time, repair the steps, never the check). git through `drivers/base.py`'s `run()`;
  exit 3 without a checkout or a revision.
- `capture.py --write-staging` (writes `staging.md`); `capture.py --current [folder]` (lists the current store
  screenshots: `existing/<store>/screenshots/`, `store-screenshots.json`'s shots, `design/current.json` by group
  and order with what each shows, its capture and caption, a folder).
- `import_captures.py --from fastlane-snapshot|fastlane-screengrab|xcresult|maestro|flutter|detox|playwright|folder
  <path> [--map mapping.json] [--out captures]`.
- `check_captures.py [--plan …] [--rules <store>,…] [--json]`.
- `video.py record|encode|check …`: record (`simctl io recordVideo`, `adb shell screenrecord`, Chrome's screencast),
  encode to each store's preview spec with ffmpeg (constant frame rate, H.264, a silent audio track when there's
  none, the exact size), and check with ffprobe against the rules' `video` rules. ffmpeg/ffprobe are detected,
  never bundled.

Exit codes as the other skills': 0, 1 (a shot failed or missed with nothing kept), 2 (refused: another capture is
writing to the same folder), 3 (usage/env).

## 9. Versioning

Each skill's `VERSION` starts at `0.1.0`. The repository's `CHANGELOG.md` gets an `app-stores` entry per PR. The
marketplace's `metadata.version` is bumped on release.
