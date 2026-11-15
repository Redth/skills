# The config: `store-listing.json`

One plain-JSON file in the user's project (any path; the scripts take `--config`, default
`./store-listing.json`). Paths inside it are relative to the config's own folder. The schema is the skill's
`schema/store-listing.schema.json`; `listing.py check` validates against it before any rule runs. Comments go in
`"$comment"` keys: JSON has none.

The examples use an invented app, "Sample Recipes" by Example Studio (`com.example.samplerecipes`).

## Top level

| Field | Type | Meaning |
|---|---|---|
| `$schema` | string | `"./store-listing.schema.json"` if a copy sits beside it (editors then complete and check fields) |
| `version` | `1` | the config format's version |
| `app` | object | the app itself, shared by every store (below) |
| `primaryLocale` | BCP 47 | the locale every other one falls back to last, e.g. `en-US` (each store can name its own primary first: `stores.apple.primaryLocale`, `stores.google.defaultLanguage`) |
| `locales` | object | the words, per locale (below) |
| `screenshots` | object | which pictures, in what order (below) |
| `screens` | object | the user's own device names and their kind (below) |
| `stores` | object | each store's own section, opt-in by `enabled` (below) |
| `forms` | object | drafted answers for forms with no API; free-form; printed by the checklist ([forms.md](forms.md)) |
| `rules` | object | `extraForbiddenWords` and `relax` ([rules-data.md](rules-data.md)) |

## `app`

```json
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
}
```

- `name`: the app's name. A store's own `name`/`title` overrides it per locale.
- `ids.apple.bundleId` finds the app in App Store Connect; `appId` (the numeric Apple ID) is optional and
  checked against it. `ids.google.package` is the Play package name. The app record must already exist in each
  store: neither API creates one.
- `copyright`: `"YEAR Owner"`; Apple adds the ©.
- `contact`: Play's public contact details (`email` is required by Play and shown publicly; `website`
  recommended; `phone` optional). Not App Review's contact: that's in `stores.apple.review`.
- `urls.support` must lead to real contact details (Apple: a legal address, email or phone where local law
  requires). `urls.privacy` is required by both stores. `privacyChoices` is Apple's optional privacy-choices
  page.

## `locales`

```json
"primaryLocale": "en-US",
"locales": {
  "en-US": {
    "description": "Plan a week of meals in minutes. …",
    "apple":  { "name": null, "subtitle": "Plan meals in minutes",
                "keywords": ["recipes", "meal plan", "grocery"],
                "promotionalText": "…", "whatsNew": "…", "description": null,
                "platforms": { "TV_OS": { "description": "… A game controller isn't needed: the Siri Remote does it all." } } },
    "google": { "title": "Sample Recipes: Meal Planner",
                "shortDescription": "Plan a week of meals in minutes.",
                "fullDescription": null, "video": null, "releaseNotes": null },
    "altText": { "featureGraphic": "A phone showing a week of planned meals" }
  },
  "de-DE": { "description": "…", "apple": { "subtitle": "…" }, "google": { "title": "…" } }
}
```

- Keys are BCP 47 (`en-US`, `pt-BR`, `zh-Hans`). Mapping to each store's own codes is the scripts' job; a locale
  a store doesn't support is an error naming it.
- **Fallback, field by field:** a locale's missing field takes the store's primary locale's
  (`stores.apple.primaryLocale` or `stores.google.defaultLanguage`), then the config's `primaryLocale`'s. A store's
  own `description` falls back to the locale's shared `description` first, so write one shared description and
  override only where a store needs its own words.
- **`null` means "not set" (fall back); `""` means "set to empty".** Use `""` only on purpose. When a field is
  still unset after falling back (What's New, Play's video), `push.py` leaves the store's value as it is; `""` clears
  it on the store.
- `apple`: `name` (defaults to `app.name`), `subtitle`, `keywords` (a list; written comma-separated with no
  spaces), `promotionalText`, `whatsNew` (not on a first version; required on every later one), `description`.
- `apple.platforms.<IOS|MAC_OS|TV_OS|VISION_OS>`: App Store Connect keeps a version's words per platform, so one
  platform can have its own `description`, `keywords`, `promotionalText`, `whatsNew`, `marketingUrl` or
  `supportUrl` (an Apple TV description that says what controller it needs, a Mac one that doesn't mention touch).
  A platform's field is looked for in this order: that platform's override in the locale, the locale's `apple.<field>`,
  (for the description) the locale's shared `description`, then the same three in the App Store's primary locale,
  then in the config's primary locale; the URLs end at `app.urls`. `name` and `subtitle` are the whole app's (App
  Store Connect's app information isn't per platform), so they have no override. The check runs the rules on each
  platform's words where they differ (a finding then names the platform: `en-US apple.description (TV_OS)`).
- `google`: `title`, `shortDescription`, `fullDescription`, `video` (one YouTube URL), `releaseNotes` (these go
  with a release, not the listing; see [google.md](google.md)).
- `altText.featureGraphic`: Play's alt text for the feature graphic (up to 140 characters; it's Console-only
  today, so it's printed in the checklist).

Limits and what each field may say: [words.md](words.md).

## `screenshots` and `screens`

```json
"screenshots": {
  "folder": "screenshots",
  "shots": [
    { "id": "plan",     "screens": null, "stores": null },
    { "id": "recipe",   "screens": ["iphone", "android-phone"], "stores": null },
    { "id": "shopping", "screens": null, "stores": ["apple"] }
  ]
},
"screens": {
  "iphone":         { "kind": "phone" },
  "ipad":           { "kind": "tablet" },
  "android-phone":  { "kind": "phone" },
  "android-tablet": { "kind": "tablet" }
}
```

- Files live at `<folder>/<locale>/<screen>/<shot id>.png` (or `.jpg`): the layout `store-capture` and
  `store-screenshots` write. Any tool's output works if it's renamed into this layout.
- A locale without a file falls back to the store's primary locale's file for that screen and shot, then the
  config's primary's. The check reports each fallback, so a shot meant to be localised isn't silently in English.
- `shots` is the order the store shows them. `screens` and `stores` filter a shot (`null` = all).
- `screens` are the user's own names; `kind` is `phone`, `tablet`, `desktop`, `tv`, `watch` or `xr`.
- **Which Apple slot a picture fills is decided by its pixel size**, against Apple's display types in the
  rules data ([apple.md](apple.md)). For Google, `stores.google.slots` says which screen fills which slot.
  Never resize a picture to make it fit: capture or render it at the size.

## `stores.apple`

```json
"apple": {
  "enabled": true,
  "primaryLocale": null,
  "locales": null,
  "categories": { "primary": "FOOD_AND_DRINK", "primarySubcategories": [],
                  "secondary": "LIFESTYLE", "secondarySubcategories": [] },
  "platforms": {
    "IOS": { "screens": ["iphone", "ipad"],
             "previews": { "iphone": [ { "file": "previews/iphone.mp4", "posterFrame": "00:00:05:00" } ] } },
    "MAC_OS": null, "TV_OS": null, "VISION_OS": null
  },
  "ageRating": { "violenceCartoonOrFantasy": "NONE", "contests": "NONE" },
  "review": { "notes": "…",
              "contact": { "firstNameEnv": "APPLE_REVIEW_FIRST_NAME", "lastNameEnv": "APPLE_REVIEW_LAST_NAME",
                           "phoneEnv": "APPLE_REVIEW_PHONE", "emailEnv": "APPLE_REVIEW_EMAIL" },
              "demoAccount": null },
  "tvPrivacyText": null
}
```

- `primaryLocale`: the App Store's primary language (App Store Connect sets it per app; it may not be `en-US`), or
  `null` for the config's `primaryLocale`. The App Store's words fall back to it before the config's.
- `locales`: the config's locales the App Store gets, e.g. `["en-CA"]`; `null` (or absent): every one. Only these
  are checked, built and sent, so a locale the store has no listing in isn't added. The primary must be one of them.
- `categories`: App Store Connect's category ids (`FOOD_AND_DRINK`, `GAMES`, …); games take subcategories.
- `platforms`: `IOS`, `MAC_OS`, `TV_OS`, `VISION_OS` (App Store Connect's names). `null` = not shipped there.
  Each lists the `screens` whose pictures it uses and optional `previews` per screen (up to 3; `posterFrame` as
  `HH:MM:SS:FF`).
- `ageRating`: App Store Connect's own attribute names and values (`NONE`, `INFREQUENT_OR_MILD`,
  `FREQUENT_OR_INTENSE`, booleans for capabilities). Sent only with `push.py plan apple --age-rating`, so it's
  sent once settled. Definitions: [forms.md](forms.md).
- `review.notes`: App Review's notes (4,000 bytes). `review.contact` names environment variables, never values.
  `demoAccount`: `null`, or environment variable names for a sign-in that must not expire.
- `tvPrivacyText`: path to the privacy policy as plain text, required for tvOS (Apple TV has no browser).

## `stores.google`

```json
"google": {
  "enabled": true,
  "defaultLanguage": "en-US",
  "locales": ["en-US", "de-DE"],
  "slots": { "phone": "android-phone", "tablet7": null, "tablet10": "android-tablet", "tv": null, "wear": null },
  "graphics": { "icon": "graphics/icon-512.png", "featureGraphic": "graphics/feature-1024x500.png",
                "tvBanner": null },
  "dataSafetyCsv": null
}
```

- `defaultLanguage`: Play's default listing language, and Play's primary: its words fall back to it before the
  config's `primaryLocale`. Check it matches the Console's (the plan says when not).
- `locales`: the config's locales Play gets (`null` or absent: every one); `defaultLanguage` must be one of them.
- `slots`: which of the user's screens fills each Play slot (`phone`, `tablet7`, `tablet10`, `tv`, `wear`).
- `graphics`: the 512×512 icon, the 1024×500 feature graphic (required), the 1280×720 TV banner (with TV).
- `dataSafetyCsv`: a path to the Data safety CSV exported from Play Console, or `null` ([forms.md](forms.md)).

## `stores.amazon`, `stores.steam`, `stores.itch`

`{ "enabled": false }` for now. Amazon's sending is to follow. Steam and itch.io have no listing API; their
checklist is in [sending.md](sending.md#stores-with-no-api).

## Secrets

Never in the config. The scripts read fixed environment variables:

| Store | Variables | Value |
|---|---|---|
| Apple | `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY` | the key's id, the issuer id, and the `.p8` key as a path, its PEM text, or base64 of either |
| Google | `GOOGLE_PLAY_SERVICE_ACCOUNT` | the service account's JSON key as a path, its text, or base64 |

A store section can name other variables with an `"auth"` object of `…Env` fields (the exact names are in
the schema), for projects that keep several apps' keys side by side. App Review's contact and a demo account are
named the same way.

## Starting from what's live

For an app already on the stores, the first config is usually the live listing: `push.py pull` then
`listing.py import --from live existing/` ([existing.md](existing.md)). The import fills only what's `null`, so it
can be run again after the user's edits without losing them. Where a non-primary locale's field is empty on the
store but would fall back to the primary's words, the import writes `""`, so the plan leaves it empty.
`listing.py diff --existing existing/` compares the config's resolved words with what was pulled.

## A minimal config

For an Android-only app with no screenshots yet (the check will say what's missing):

```json
{
  "version": 1,
  "app": { "name": "Sample Recipes", "ids": { "google": { "package": "com.example.samplerecipes" } },
           "copyright": "2026 Example Studio",
           "contact": { "email": "support@example.com", "phone": null, "website": "https://example.com" },
           "urls": { "marketing": null, "support": "https://example.com/support",
                     "privacy": "https://example.com/privacy", "privacyChoices": null } },
  "primaryLocale": "en-US",
  "locales": { "en-US": { "description": "Plan a week of meals in minutes.",
                          "google": { "title": "Sample Recipes",
                                      "shortDescription": "Plan a week of meals in minutes." } } },
  "screenshots": { "folder": "screenshots", "shots": [] },
  "screens": { "android-phone": { "kind": "phone" } },
  "stores": { "google": { "enabled": true, "defaultLanguage": "en-US",
                          "slots": { "phone": "android-phone", "tablet7": null, "tablet10": null,
                                     "tv": null, "wear": null },
                          "graphics": { "icon": "graphics/icon-512.png",
                                        "featureGraphic": "graphics/feature-1024x500.png", "tvBanner": null },
                          "dataSafetyCsv": null } }
}
```

## What `listing.py` reports

- `check --json` prints `{"findings": [...], "fallbacks": [...], "relaxed": [...]}` plus `checklist`, `notChecked`,
  `notes`, `summary`, `stores` and `config`; each finding has `rule_id`, `severity`, `where`, `message`, `source`,
  `status` and `store`.
- Findings about the config itself (a screen named but not defined, a file that isn't there, a locale a store
  doesn't have) use `config.*` ids. They can't be relaxed: fix the config.
- `preview` works from `out/` (run `build` first), so it shows what was built, not the config as it is now.
- `diff [--existing existing] [--stores …] [--json]` compares the config with what `push.py pull` wrote: each entry has
  `store`, `locale` (the store's code), `platform`, `field`, `kind` (`words` or `pictures`), `status` (`unchanged`,
  `changed`, `only-live`, `only-ours`), `live` and `ours`.
- `out/listing.json` carries the Apple TV privacy text in `apple.app.localizations[<primary>].privacyPolicyText`, each store's
  `auth` (variable names only) and App Review's `contact` and `demoAccount` (variable names only). Each Apple
  platform's `localizations` are that platform's own words; each store lists only its own locales, its primary
  as `apple.primaryLocale` and `google.defaultLanguage`. `google.developer` (the copyright's holder, else the app's
  name) is for the preview's developer line; nothing sends it.
- A store's `locales` naming a locale the config hasn't (`config.locales`), or a store's primary that isn't one of its
  locales (`config.primary_locale`, `config.default_language`), is an error; words for a platform the config
  doesn't ship (`config.platforms`) are a warning.
