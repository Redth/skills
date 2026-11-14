# Importing an existing listing

When a project already keeps its store words somewhere, start the config from them rather than retyping:

```sh
python3 <skill>/scripts/listing.py import --from fastlane  fastlane          --out store-listing.json
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

## After importing

1. **Locales:** fastlane's and Play's folder names map to BCP 47 (`en-US`, `de-DE`, `zh-Hans`). Set
   `primaryLocale` to the locale each store actually uses as primary (check in each console or with a `plan`):
   it may not be `en-US`, and may differ between the stores.
2. **Ids:** set `app.ids.apple.bundleId` and `app.ids.google.package`; the importers rarely know them.
3. **App Review's contact and demo account are personal:** fastlane's `review_information/` (first name, last
   name, phone, email, demo user and password) are **not** copied into the config. Name environment variables in
   `stores.apple.review` instead and tell the user to set them (and to stop committing those files).
4. **Screenshots:** copied as `<folder>/<locale>/<screen>/<shot>.png`. Check the screen and shot names the
   importer chose; rename them to meaningful ids (`plan`, `recipe`) if they aren't, and set `shots` in the order
   the store should show them. The pixel sizes decide Apple's slots, so a picture at the wrong size shows up in
   the check, not here.
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
