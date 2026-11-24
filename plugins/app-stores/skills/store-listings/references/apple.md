# The App Store (iPhone, iPad, Mac, Apple TV, Vision Pro)

What `push.py` sends to App Store Connect, the slots, what changes when, and the quirks. Store pages read on
2026-11-14; the rules data (`rules/apple.json`) has each limit with its source and date.

## What's sent, and at which level

App Store Connect keeps some fields for the whole app and some per platform version. It matters because they
change at different times.

| Level | Fields | Changes when |
|---|---|---|
| App info (per locale) | name, subtitle, privacy policy URL, privacy choices URL, Apple TV privacy text | only while an app info is editable (a version in preparation) |
| App info | categories, age rating | as above; the age rating only with `--age-rating` |
| Version (per platform, per locale) | description, keywords, What's New, marketing URL, support URL | only on a version in preparation |
| Version (per platform, per locale) | **promotional text** | **any time**, without review |

The config keeps the version fields once per locale, with a platform's own words in
`locales.<loc>.apple.platforms.<P>` where it differs ([config.md](config.md#locales)); `out/listing.json` and the
fastlane folders carry each platform's resolved words, so a plan never proposes overwriting one platform's
description with another's.
| Version | copyright, App Review details (notes, contact, demo account) | on a version in preparation |
| Version (per locale, per display type) | screenshot sets, preview sets | on a version in preparation |

Editable states (the version or app info): `PREPARE_FOR_SUBMISSION`, `DEVELOPER_REJECTED`, `REJECTED`,
`METADATA_REJECTED`, `INVALID_BINARY`. When a platform has no editable version, the plan says so and skips it;
`push.py plan apple --new-version 1.2.0` plans to create one (ask the user first: it's a new version in their
account). iOS, macOS and tvOS versions are submitted and released separately.

Put anything time-sensitive in **promotional text** (170 characters, not searched, changes without review).

Source: https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information
and https://developer.apple.com/help/app-store-connect/reference/app-information/app-information (checked
2026-11-14).

## Screenshot slots (display types)

The slot is decided by the picture's pixel size. 1–10 screenshots a slot, PNG or JPEG, **no alpha channel or
transparency**. If the UI is the same across sizes, giving the largest required size is enough: App Store
Connect scales it down for the smaller ones.

| Apple's name | Portrait sizes (landscape: swapped) | API display type | Required |
|---|---|---|---|
| iPhone, Dynamic Island, medium (6.1"/6.3") | 1179×2556, 1206×2622 | `APP_IPHONE_61` | **yes** (see below) |
| iPhone, Dynamic Island, large (6.9") | 1260×2736, 1290×2796, 1320×2868 | `APP_IPHONE_67` | if no medium set (conflicting; see below) |
| iPhone, Face ID, large (6.5") | 1284×2778, 1242×2688 | `APP_IPHONE_65` | falls back |
| iPhone, Face ID, medium | 1170×2532, 1125×2436, 1080×2340 | `APP_IPHONE_58` | falls back |
| iPhone 5.5" / 4.7" / 4" / 3.5" | 1242×2208 / 750×1334 / 640×1136 / 640×960 | `APP_IPHONE_55` / `_47` / `_40` / `_35` | falls back |
| iPad 13" | 2064×2752, 2048×2732 | `APP_IPAD_PRO_3GEN_129` | **if the app runs on iPad** |
| iPad 11" (incl. mini) | 1488×2266, 1668×2420, 1668×2388, 1640×2360 | `APP_IPAD_PRO_3GEN_11` | falls back to 13" |
| Mac | 1280×800, 1440×900, 2560×1600, 2880×1800 (16:10 only) | `APP_DESKTOP` | for Mac apps |
| Apple TV | 1920×1080, 3840×2160 | `APP_APPLE_TV` | for tvOS |
| Apple Vision Pro | 3840×2160 | `APP_APPLE_VISION_PRO` | for visionOS |
| Apple Watch | per model (e.g. 416×496, 410×502, 422×514) | `APP_WATCH_*` | for watch apps; one size across all locales |

**Which iPhone set is required:** Apple's page says "iPhone: At least one screenshot for iPhone with Dynamic
Island (medium display)", while still describing the large sets as scaling down. Nothing says a 6.9" set alone
meets the requirement. Make the medium set; the mapping of `APP_IPHONE_61` to "medium" is `unverified` (the API's
enum has no descriptions).

**iPhone Duo:** Apple announced Duo screenshots (1398×2034 outer, 2007×2853 inner) as required from April 2027.
Its news and its screenshot page disagree on which apps; plan for every app. **One set takes both postures:**
the API's `APP_IPHONE_DUO` (screenshots: 1398×2034 and 2853×2007, either way round, up to 10 mixed) and `IPHONE_DUO`
(previews, 886×1920 or 1920×886, up to 3). Apple's OpenAPI spec (4.6.1) doesn't list them yet, but App Store Connect
accepts them (its answer to an invalid type lists them, 2026-11-24). The rules keep two slots, `IPHONE_DUO_OUTER`
(folded) and `IPHONE_DUO_INNER` (open), both `APP_IPHONE_DUO`: `listing.py build` makes them one set in the shots'
order, and `check` counts them together, so choose which shots each posture shows (`screenshots.shots[].screens`)
to stay within 10.

Source: https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications
(checked 2026-11-14).

## What screenshots may show

- "Screenshots should show the app in use, and not merely the title art, login page, or splash screen"
  (guideline 2.3.3). App Review's reference for 2.3.3 says it approves submissions where **more than half** of the
  screenshots show the app in use; the rest may be marketing art. Text and image overlays are fine if they don't
  hide the app.
- A panorama across screenshots is allowed.
- Everything in icons, screenshots and previews must suit 4+, whatever the app's rating (2.3.8).
- No other mobile platforms' names, icons or imagery (2.3.10), status bars included. No prices in screenshots or
  previews (2.3.7). Fictional account data, never a real person's (2.3.9).

Sources: https://developer.apple.com/app-store/review/guidelines/ and
https://developer.apple.com/help/app-review/guideline-reference/2-3-3-screenshots (checked 2026-11-14).

## App previews (video)

Up to 3 a slot and locale; 15–30 s; H.264 or ProRes 422 HQ, at most 30 fps, up to 500 MB; stereo audio. iPhone
(Dynamic Island and Face ID sizes) 886×1920; iPad 1200×1600; Mac and Apple TV 1920×1080; Vision Pro
3840×2160. macOS, tvOS and visionOS previews are landscape only. A preview without an audio track is reported to
fail (`unverified`): add a silent track. Processing can take up to 24 hours; Apple reports a refused video only in
App Store Connect. Source:
https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications
(checked 2026-11-14).

## How `push.py` talks to App Store Connect

- **Token:** an ES256 JWT (`aud` `appstoreconnect-v1`, about 20 minutes), signed with `openssl`.
- **Find the app** by `bundleId`. None: stop and say to create it in App Store Connect first (the API can't).
  The app's **primary locale** is read and compared with the config's: a mismatch is a note in the plan, because
  writing to a locale nobody sees is easy to miss.
- **Only differing attributes** are sent (text compared after trimming and normalising line endings).
- **Screenshots and previews:** a set whose files match the store's by MD5 (Apple's `sourceFileChecksum`) and
  order is left alone. A reorder alone is one relationship PATCH. Otherwise each new file is reserved, its parts
  sent where Apple says (each part's own URL, method and headers), committed with its MD5, and processing awaited;
  **new pictures are uploaded before old ones are deleted**, so a failure halfway doesn't leave an empty slot.
  Sets in the store that the config doesn't list are never touched.
- **What's New** is left out on a first version (App Store Connect turns it down).
- **Review details:** the contact comes from environment variables; the phone needs `+` and the country code
  ("numbers only" is refused). The plan shows only its last digits.
- **Retries:** 5xx, 408, 429 and dropped connections, waiting 15/30/45 s or `Retry-After`. Upload parts time out
  now and then, large previews most. Anything else fails at once, with Apple's error as it came.
- **Rate limit:** about 3,500 requests an hour a key (the `X-Rate-Limit` header; 429 `RATE_LIMIT_EXCEEDED` past
  it). Source: https://developer.apple.com/documentation/appstoreconnectapi/identifying-rate-limits (checked
  2026-11-14).

Uploading assets: https://developer.apple.com/documentation/appstoreconnectapi/uploading-assets-to-app-store-connect
(checked 2026-11-14).

## Keys and roles

Create a team key in App Store Connect ▸ Users and Access ▸ Integrations ▸ App Store Connect API. The role must be
**App Manager** or **Admin**. Export `ASC_KEY_ID`, `ASC_ISSUER_ID` and `ASC_PRIVATE_KEY` (the `.p8` path, its
text, or base64: secret managers often store base64). The key file downloads once; keep it in the keychain or a
secret store, never the repository.

## No API (the checklist)

App Privacy (the privacy "nutrition label"), price and availability, the EU trader status (Digital Services
Act; without it the app leaves EU storefronts), content rights, the regulated medical device declaration (Health
& Fitness or Medical apps in the EU, UK and US), Made for Kids (can't be undone once approved), and submitting for
review. The age rating does have an API (`--age-rating`). See [forms.md](forms.md).

## Locales

50 metadata languages. A new localisation starts as a copy of the primary's properties **except the description
and keywords**. With no matching localisation, the store shows the next most relevant one, else the primary.
Changing the primary language needs that language approved, with screenshots at the same sizes. Source:
https://developer.apple.com/help/app-store-connect/manage-app-information/localize-app-information (checked
2026-11-14).

## Icons

Icons come only from the build, never the listing. A new icon means a new build and review.
