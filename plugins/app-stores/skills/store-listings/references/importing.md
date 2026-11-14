# Importing an existing listing

When a project already keeps its store words somewhere, start the config from them rather than retyping:

```sh
python3 <skill>/scripts/listing.py import --from fastlane  fastlane          --out store-listing.json [--platform TV_OS]
python3 <skill>/scripts/listing.py import --from supply    fastlane/metadata/android --out store-listing.json
python3 <skill>/scripts/listing.py import --from triple-t  app/src/main/play --out store-listing.json
python3 <skill>/scripts/listing.py import --from expo      store.config.json --out store-listing.json
```

The import writes a first config: the words per locale, URLs, categories where present, and screenshots copied
into the config's folder layout. Then read it, fill the gaps, and run `listing.py check`.

## What each source looks like

| Source | Store | Layout |
|---|---|---|
| fastlane `deliver` | Apple | `metadata/<locale>/{name,subtitle,description,keywords,promotional_text,release_notes,privacy_url,support_url,marketing_url,apple_tv_privacy_policy}.txt`; top-level `copyright.txt`, `primary_category.txt`, `secondary_category.txt` and sub-category files; `review_information/*.txt`; a `default/` folder as fallback; `screenshots/<locale>/` (slot from the pixel size); `app_previews/<locale>/` |
| fastlane `supply` | Google | `metadata/android/<locale>/{title,short_description,full_description,video}.txt`, `changelogs/<versionCode>.txt`, `images/{icon,featureGraphic,tvBanner}.png`, `images/{phone,sevenInch,tenInch,tv,wear}Screenshots/` |
| Triple-T (Gradle Play Publisher) | Google | `src/<sourceSet>/play/{contact-email,contact-phone,contact-website,default-language}.txt`, `listings/<locale>/{title,short-description,full-description,video-url}.txt`, `listings/<locale>/graphics/{icon,feature-graphic,phone-screenshots,tablet-screenshots,large-tablet-screenshots,tv-banner,tv-screenshots,wear-screenshots}/`, `release-notes/<locale>/<track>.txt` |
| Expo `store.config.json` | Apple only | `apple.info.<locale>` (`title`, `subtitle`, `description`, `keywords[]`, `releaseNotes`, `promoText`, `marketingUrl`, `supportUrl`, `privacyPolicyUrl`, `privacyChoicesUrl`, `privacyPolicyText`), `apple.categories`, `apple.copyright`, `apple.advisory` (age rating), `apple.review`; no screenshots |

A project with both `fastlane/metadata/<locale>` and `fastlane/metadata/android/` has both stores: import each
(`--from fastlane` for Apple, `--from supply` for Google) and merge into one config, or import one and copy the
other's words in. Both import into the same shape, so the shared `description` can be one text with store
overrides only where the two differ.

**Several Apple platforms.** fastlane `deliver` runs once a platform, so a project shipping on iPhone, Apple TV
and the Mac often has a folder each. Import each into the same config, iPhone's first. A folder's platform is
`--platform` if given, else the one its screenshots fit (a 1920×1080 picture is Apple TV's), else `IOS`. The
first platform's words become the locale's; a later platform's words that differ go in its overrides
(`locales.<loc>.apple.platforms.<P>`: an Apple TV description saying a controller is needed stays Apple TV's),
and the same words are left to fall back. `name` and `subtitle` are the whole app's: a later platform's that
differ are kept as they were, and said.

**Each store's locales.** The import sets `stores.apple.locales` and `stores.google.locales` to the languages each
source actually had, and each store's primary (`stores.apple.primaryLocale`, `stores.google.defaultLanguage`):
an App Store listing in `en-CA` only and a Play listing in `en-US` only stay that way, with no `en-US` App Store
localisation or `en-CA` Play listing added. A later import of the same store adds its languages to the list.

## After importing

1. **Locales:** fastlane's and Play's folder names map to BCP 47 (`en-US`, `de-DE`, `zh-Hans`). Check each
   store's primary (`stores.apple.primaryLocale`, `stores.google.defaultLanguage`) is the one it actually uses (in
   each console, or with a `plan`): it may not be `en-US`, and may differ between the stores. `primaryLocale` is
   the one every store falls back to last.
2. **Ids:** set `app.ids.apple.bundleId` and `app.ids.google.package`; the importers rarely know them.
3. **App Review's contact and demo account are personal:** fastlane's `review_information/` (first name, last
   name, phone, email, demo user and password) are **not** copied into the config. Name environment variables in
   `stores.apple.review` instead and tell the user to set them (and to stop committing those files).
4. **Screenshots:** copied as `<folder>/<locale>/<screen>/<shot>.png`.
   - **Shot ids come from the file names**, without the order number, the device or size and the locale
     (`01-plan-week-iphone.jpg` → `plan-week`, `03_APP_IPHONE_67_recipe.png` → `recipe`), so one id is the same
     moment on every screen. A folder whose names don't all name a different moment (`1_iPhone-01.png`) is named
     `shot-01`, `shot-02`… in file order: rename those to meaningful ids.
   - `shots` follows each folder's order. A shot only some screens have lists them (`screens`); a screen a later
     import adds doesn't take shots it has no picture for.
   - **Apple screens are named by device class** (`iphone`, `ipad`, `mac`, `apple-tv`, `vision-pro`), or by display
     type (`iphone-67`, `iphone-61`) where one class has pictures for two.
   - **Play's slots with the same pictures, byte for byte, share a screen** (the 7-inch and 10-inch tablets often
     do): `android-tablet` fills both in `stores.google.slots`. One tablet screen is `android-tablet`; two with
     their own pictures are `android-tablet7` and `android-tablet10`.
   - The pixel sizes decide Apple's slots, so a picture at the wrong size shows up in the check, not here.
5. **Shared description:** if both stores' descriptions are the same, keep one in `locales.<locale>.description`
   and drop the store copies.
6. **Release notes and changelogs:** check what came across. Apple's What's New belongs to the next version, so
   rewrite it for the build being released. Play's changelogs belong to releases, which this skill doesn't send.
7. Run `listing.py check`. Imported listings often fail a rule the store never enforced at the time, or one it
   enforces now: fix the words, don't relax the rule (unless the user chooses to).
8. Run `push.py plan` for each store: an imported listing that matches the store should plan few or no actions.
   Differences show where the files and the store had drifted.

## Afterwards

The config is the source of truth. `listing.py build` writes fastlane's layouts into `out/`, so fastlane, CI
steps that read them, and F-Droid (which reads `supply`'s layout) keep working from the built output. Don't edit
the old metadata folders by hand any more: they'd drift from the config.

## What's different from fastlane and the App Store Connect CLIs

- One config for both stores (and the checklists for the rest), not one folder a store and a run per Apple
  platform.
- Rules are checked offline before anything is sent, with a source and a date for each. fastlane's `precheck`
  checks only Apple, only what's already on App Store Connect, and only words.
- Sending is plan, then apply exactly that plan; nothing changes without the user reading the plan first.
- Stdlib Python and `openssl`: no Ruby, no Node, no account, no telemetry.
