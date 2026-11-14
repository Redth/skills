# The words: limits, banned terms by field, What's New

Read with `rules/apple.json` and `rules/google.json`, which hold each rule with its source and date. Pages read
2026-11-14.

## Limits, and how each counts

Count what the store counts. A byte count on a character field gives false errors (a `•` is 3 bytes in UTF-8);
a character count on a byte field lets a listing through that the store refuses.

| Store | Field | Config path | Limit | Counts |
|---|---|---|---|---|
| Apple | Name | `apple.name` | 2–30 | characters |
| Apple | Subtitle | `apple.subtitle` | 30 | characters |
| Apple | Promotional text | `apple.promotionalText` | 170 | characters |
| Apple | Description | `apple.description` / `description` | 4,000, plain text (no HTML) | characters |
| Apple | Keywords | `apple.keywords` | 100, comma-separated, each more than 2 characters | **bytes** (UTF-8) |
| Apple | What's New | `apple.whatsNew` | 4,000; not on a first version, required on every later one | characters |
| Apple | App Review notes | `stores.apple.review.notes` | 4,000 | **bytes** |
| Google | Title | `google.title` | 30 | characters |
| Google | Short description | `google.shortDescription` | 80 | characters |
| Google | Full description | `google.fullDescription` / `description` | 4,000 | characters |
| Google | Release notes | `google.releaseNotes` | 500 | characters |
| Google | Feature graphic alt text | `altText.featureGraphic` | 140 | characters |

Play counts full-width and half-width characters as one each. How Apple counts emoji isn't stated (`unverified`):
the check counts conservatively. Sources: https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information,
https://developer.apple.com/help/app-store-connect/reference/app-information/app-information,
https://support.google.com/googleplay/android-developer/answer/9859152 (checked 2026-11-14).

## Price words: banned in some fields, not others

A blanket ban on "free" blocks honest copy: a free app with a subscription must say what's free and what the
trial is (Apple 3.1.2). The stores ban prices and price claims **in particular fields**:

| Store | Banned in | Allowed in | Source |
|---|---|---|---|
| Apple | **name, subtitle, screenshots, previews**: "should not include prices, terms, or descriptions that are not specific to the metadata type" (2.3.7) | the description (say what's free, what the trial is, what needs buying); promotional text, carefully | https://developer.apple.com/app-store/review/guidelines/ |
| Google | **title, icon, developer name** (policy): price or promotion ("10% off", "free for limited time only"), ranking ("#1", "App of the year"), Play programs ("Editor's choice", "New") | the full description may say what's free | https://support.google.com/googleplay/android-developer/answer/9898842 |
| Google | **short description, screenshots, feature graphic** (strongly recommended against): "Free", "Sale", "Discount", prices, "Best", "#1", "Top", "New", calls to action ("Download now") | | https://support.google.com/googleplay/android-developer/answer/9866151 |

(All checked 2026-11-14.) So: move "Free" out of the subtitle or title and into the description, where it can
say exactly what's free. A Play short description with "Free!" is reported (a recommendation, but it affects
promotion); rewrite it to say what the app does.

## Claims, other platforms, reserved words

- **Unverifiable claims** ("best", "#1", "top-rated") are out of Apple's subtitle (2.3.7) and Play's title, short
  description and pictures. In Play's full description, no deceptive claims ("best game ever"), no unattributed
  testimonials, no keyword lists.
- **Other platforms:** Apple's metadata may not name or show other mobile platforms or app marketplaces
  (2.3.10): "Android" and "Google Play" are out; other stores and PC platforms fall under "irrelevant
  information". Naming iPhone or the App Store on Play has no written ban, but the check warns. itch.io's page may
  name platforms.
- **"For Kids" and "For Children"** are reserved for Apple's Kids category, anywhere in the metadata (2.3.8).
- **Keywords (Apple):** no other apps' or companies' names; don't repeat the app's name, the subtitle's words, the
  category's name, or "app"; no plurals of words already there; no spaces after commas.
- **Unfinished words:** "beta", "demo", "coming soon", "TODO", "lorem", "placeholder", "test" anywhere public
  (precheck's `placeholder_text`, `test_words`). Add your own in `rules.extraForbiddenWords`.
- **Play's title:** no emoji, emoticons or repeated special characters; no ALL CAPS unless it's the brand.
- **TV:** an Apple TV app that requires a game controller must say so in its metadata (2.4.3). An Android TV
  listing's description must mention "Android TV".

## What's New and release notes

- Apple 2.3.12: describe significant changes specifically; generic text ("bug fixes and improvements") only
  when that's all it is.
- Write it for the build being released, at release time: notes written early describe the wrong build.
- Apple's What's New is blank on a first version and required after. Play's release notes go with the release
  (500 characters a language), not the listing.

## Where words go

- **Time-sensitive** words (an event, a season, a sale described honestly) go in Apple's promotional text: it
  changes any time without review and isn't searched.
- **One shared description**, with store-specific overrides only where they differ (a TV app's controller
  paragraph, Play's "Android TV"): copies drift apart.
- **Markup:** plain text for Apple and Play; Steam's About This Game is BBCode with **no links**; itch.io's
  description is rich text (HTML).
- **A headline feature** changes every store at once: description, keywords, promotional text, release notes,
  and which screenshots show it.
- **Each store's primary language** may not be `en-US`. Write to the one the store shows.

## Others' names and marks

Trademarks, product names, celebrities, sports leagues and the like, in the words or readable in the pictures:
flag them to the user; don't decide whether they're allowed. Apple can ask for proof of rights (2.3.9, 5.2).
