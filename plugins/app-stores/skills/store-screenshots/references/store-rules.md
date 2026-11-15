# What each store allows in a screenshot

Read with `rules/apple.json` and `rules/google.json` (the rules `check.py` runs, each with its source, date and
status, and the `design` table: frames, backgrounds, captions, awards, device art, text share, Apple's in-use
majority and Play's UI-first count, each with a `bySlot` where a slot differs). Every page below was read on
**2026-11-14**; stores change these without notice, so re-read a source when it matters. Sizes and counts are
`store-listings`' rules too; this file is about what goes *in* the picture.

## Apple App Store

**Format and sizes** (https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications):

- JPEG or PNG, "can't include alpha channels or transparencies"; 1 to 10 per size, per locale.
- iPhone 6.9": 1320×2868 (also 1290×2796, 1260×2736). iPhone 6.3"/6.1" (Dynamic Island, medium display):
  1206×2622 or 1179×2556. iPad 13": 2064×2752 (or 2048×2732). Mac: 16:10, up to 2880×1800. Apple TV: 1920×1080
  or 3840×2160. Vision Pro: 3840×2160. Portrait or landscape.
- **Required:** the specification page lists iPhone with Dynamic Island (medium display) and iPad 13" (if the app
  runs on iPad). It differs from the older "6.9-inch only" advice; nothing says a 6.9" set alone meets it, so make
  the medium set.
- **iPhone Duo** (outer 1398×2034, inner 2007×2853): Apple's news post says screenshots for it from April 2027 for
  every app submitted; the specification page ties it to the iOS 27.1 SDK. **Unverified which holds.** Apps with
  Duo shots get an "optimized for iPhone Duo" badge.

**What shows:** the first one to three screenshots in search (by orientation) when there's no preview; up to 10
screenshots and 3 previews on the product page (https://developer.apple.com/app-store/product-page/). iOS 27 adds an
optional 3:2 search asset (1920×1280 to 3840×2560, art safe area 2168×1030 at 836,765) and a 21:9 product page
header (3840×1646, safe area 1646×661 at 1097,493): both swappable without a new version, and not rendered by this
skill's version 0.1
(https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications).

**Content** (App Review Guidelines, https://developer.apple.com/app-store/review/guidelines/):

- **2.3.3** Show "the app in use, and not merely the title art, login page, or splash screen"; "text and image
  overlays" are allowed. App Review's guideline reference reads it as more than half of a set (per device, per
  locale) showing the app in use, the rest free for marketing art; a panorama is fine
  (https://developer.apple.com/help/app-review/guideline-reference/2-3-3-screenshots). Overlays mustn't obscure
  the app's primary function.
- **2.3.7** No prices, terms or descriptions "not specific to the metadata type" in screenshots (the check's
  `apple.metadata.prices`, on captions).
- **2.3.8** Every screenshot suits 4+, whatever the app's rating; "For Kids" and "For Children" are reserved for the
  Kids category.
- **2.3.9** You hold the rights to everything shown; account information is fictional.
- **2.3.10** No "names, icons, or imagery of other mobile platforms or alternative app marketplaces": no Android
  phones, Play badges or other platforms' status bars or button glyphs.

**Asset best practices** (new in 2026, covering screenshots, https://developer.apple.com/app-store/asset-best-practices/):

- No "specific pricing, discounts, website URLs, copyright symbols".
- No unverifiable claims; no Apple-designated recognitions ("Editor's Choice, App of the Day… or Apple Design
  Award"); no other platforms' logos.
- Text: "use a short phrase that enhances your visual rather than describes it… localize."
- Screenshots: "avoid using the entire asset to highlight general accolades or call-to-action statements."
- Violent games may show action, but no gore and no "weapons that are pointed directly at a person or the
  audience".
- Sequence screenshots "so they tell a cohesive story"; keep one visual style.

**Device imagery** (Marketing guidelines, written for "marketing materials",
https://developer.apple.com/app-store/marketing/guidelines/): Apple's own bezels "as is", latest generation, never
tilted, cropped, obstructed, shadowed, rendered in 3D, or with graphics coming out of the screen; "any simulation
of an Apple product" isn't permitted; generic device illustrations mustn't carry details unique to Apple products
(Home button, sensor housing, Ring/Silent switch, volume controls). App Review's guidelines don't repeat these and
tilted, cropped iPhones are common in live screenshots, so: binding when using Apple's bezels, good practice
otherwise. **Whether App Review enforces them on screenshots is unverified.** Detail: [frames.md](frames.md).

## Google Play

**Format and sizes** (https://support.google.com/googleplay/android-developer/answer/9866151):

- JPEG or 24-bit PNG, no alpha; 2 to 8 per device type; each side 320 to 3840 px; the long side at most twice the
  short.
- Phones: at least 2 across device types. To be eligible for recommendation formats that use screenshots: apps
  at least 4 screenshots of at least 1080 px; games 3 landscape 16:9 (at least 1920×1080) or 3 portrait 9:16 (at
  least 1080×1920).
- Tablets and Chromebooks: at least 4, 1080 to 7680 px, 16:9 or 9:16 (4 recommended, not required).
- TV: at least one, shown only on TV, and at least one **unaltered** (no caption or art;
  https://developer.android.com/docs/quality-guidelines/tv-app-quality).
- Wear OS: 1:1, at least 384×384, the interface only: "do not use device frames", no extra text, graphics,
  backgrounds, transparency or masking. **A requirement, not a recommendation.**
- XR: 4 to 8 at 8:5 (3840×2400 recommended). Automotive: generic system UI, 2 portrait and 2 landscape. Both
  through Play Console only.

**Content: "highly recommended", and required for the recommendation formats** (same page):

- The actual in-app experience; prioritise UI in the first three (`check.py` warns about a `hero` there).
- Taglines only if necessary, at most 20% of the image (`check.py`'s text share); no small dense text.
- No rankings, awards, accolades, testimonials, prices or promotions ("Free", "Sale", "#1", "Best", "Top", "New",
  "Million downloads", "Editor's choice"), no calls to action ("Download now", "Play now"), no store badges.
- Nothing time-sensitive; a clean notification bar with no carrier name; nothing blurry or skewed.
- **No device imagery** ("can become obsolete quickly or alienate some users"); no people interacting with the
  device unless the app is used off-device.
- No third-party characters or logos without permission.
- Localise "graphic and branding text"; "In-game UI does not need to be localized per market."
- Tablet shots: "exclude additional text that is not part of your core app experience, as this can get cut off".
- "Stylized screenshots that break UI across multiple uploaded images are allowed" (panoramas).
- **Alt text:** each screenshot and the feature graphic can have alt text of at most 140 characters, not starting
  with "photo of" or "image of". It's typed in Play Console per locale; draft it from each shot's message.

**Metadata policy** (https://support.google.com/googleplay/android-developer/answer/9898842): no misleading
metadata, no graphic violence in promotional images, no celebrities' names or brands' logos without permission.
Its ranking, price and "Editor's choice" bans are scoped to the title, icon and developer name, with examples that
mention promotional images: ambiguous, so the check treats the screenshot words as errors
(`google.captions.promotional`).

**Feature graphic** (1024×500, no alpha, required): the video's cover and a poster in large collections. Focal
point central, key elements out of the cut-off zones and the play button, no pure white, black or dark grey. Not a
version 0.1 layout.

## Steam (for reference; no rules data yet)

https://partner.steamgames.com/doc/store/assets/standard and https://partner.steamgames.com/doc/store/assets/rules:

- At least 5 screenshots, at least 1920×1080, 16:9. They "should exclusively show the gameplay of your game": no
  concept art, cinematic stills, awards or "marketing copy"; menus only if they're a unique part of the game; in-game
  UI is fine.
- At least 4 marked suitable for all ages, or the game may not show in some places (the front page's hover).
- Hovering a capsule cycles the first four screenshots: make them four parts of the core loop (practitioners'
  advice).
- Capsules carry the art, the name and an official subtitle only: no review scores, awards, logos or discount copy.
  Promotional text only in a 14-day artwork override, localised into every supported language.

Version 0.1's targets are for the App Store and Google Play. Steam's screenshots are gameplay with no words, so
they are the captures themselves at 1920×1080 or larger: check them against this list by eye.

## itch.io (for reference)

https://itch.io/docs/creators/design: no published content rules for screenshots. They sit in the page's right
column (about 347 px wide on the page, per a creator's guide) and can be hidden. The cover is 315×250 at least, 630×500
recommended, and works like Steam's small capsule: legible at its smallest. Show gameplay.

## What's still unverified

- iPhone Duo's requirement date and scope, and its API display type.
- Whether App Review enforces the marketing guidelines' device rules on screenshots.
- The on-device thumbnail sizes in search, and how many product-page shots show before scrolling (iOS 26 and 27,
  iPhone and iPad, and Play): the mocks use estimates.
- Whether right-to-left storefronts reverse the carousel.
- How the App Store shows a mix of portrait and landscape shots, or a preview with screenshots, in search.
