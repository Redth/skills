# Starting from what's live

Most apps already have a listing. Its words, its categories and the screens its screenshots feature are what
shoppers see today, and they're the baseline. Read them first. Make them the draft, decide with the user what
to keep, and only then write anything new.

```sh
python3 <skill>/scripts/push.py pull apple  [--id com.example.samplerecipes]   # with the App Store Connect key
python3 <skill>/scripts/push.py pull apple  --public [--country us,gb,de]      # no key: what the App Store shows anyone
python3 <skill>/scripts/push.py pull google [--id com.example.samplerecipes]   # with the service account's key
python3 <skill>/scripts/listing.py import --from live existing/                 # the draft store-listing.json
python3 <skill>/scripts/listing.py diff --existing existing/                    # later: the config against what's live
```

`pull` takes the app from `--id`, else from `--config`'s `app.ids` (default `./store-listing.json`, which may not
exist yet), and the key from the same environment variables `plan` uses (the config's `stores.<store>.auth` can name
others).

## pull is read-only

`push.py pull` never writes to a store, like `plan`. Every request is a GET, with one exception: on Google Play it
opens an edit to read (the API needs one) and deletes it, never committing. It reaches only the stores' own hosts:

| Host | What for |
|---|---|
| `api.appstoreconnect.apple.com` | App Store Connect, with the key |
| `itunes.apple.com` | Apple's public iTunes Lookup API (`--public`) |
| `*.mzstatic.com` | Apple's image and media CDN: the screenshots and previews the API or the lookup names |
| `oauth2.googleapis.com`, `androidpublisher.googleapis.com` | Google Play, with the service account's key |
| `play-lh.googleusercontent.com`, `lhN.googleusercontent.com` | Play's image hosts: the screenshots and graphics the API names |

A picture address anywhere else isn't fetched (the pull says so and exits 1, with the words still written), and a
download follows a redirect only to these hosts. The store's key goes only to its API, never to an image host.

## What it writes

```
existing/
  apple/
    listing.json                                     the listing in listing.json's vocabulary (below)
    README.md                                        a summary: locales, lengths, pictures per slot, what's missing
    screenshots/<apple locale>/<display type>/<NN>.<ext>
    previews/<apple locale>/<preview type>/<NN>.<ext>
  google/
    listing.json
    README.md
    screenshots/<play locale>/<image type>/<NN>.<ext>   phoneScreenshots…, icon, featureGraphic, tvBanner
```

`existing/<store>/` is a snapshot. Pulling again replaces it (only a folder `pull` wrote; any other folder there is
left alone and the pull stops). Don't edit it: edit the config. It needn't be committed. Commit it only if the
team wants the record.

`listing.json` keeps the store's own locale codes, as `out/listing.json` does:

- **Apple:** `apple.appId`, `bundleId`, `primaryLocale`; `apple.app` holds the app information's `state`,
  `categories`, the `ageRating` answers (App Store Connect's attribute names) and `localizations` (`name`,
  `subtitle`, `privacyPolicyUrl`, `privacyChoicesUrl`, `privacyPolicyText`); `apple.platforms.<P>` holds `version`,
  `state`, `copyright`, `localizations` (`description`, `keywords` as the store keeps them, `promotionalText`,
  `whatsNew`, `marketingUrl`, `supportUrl`), `screenshots` and `previews` per locale and slot; `apple.review` holds
  `notes` and `demoAccountRequired`, **never App Review's contact or demo account** (personal: not written).
- **Google:** `google.package`, `defaultLanguage`, `details` (`contactEmail`, `contactWebsite`, `contactPhone`),
  `listings` per language (`title`, `shortDescription`, `fullDescription`, `video`) and `images` per language and
  image type.
- Each picture: `file`, its `width` and `height`, Apple's uploaded `fileName` and `md5` (the upload's checksum) and
  the downloaded file's `downloadedMd5`; Play's `sha256` and `downloadedSha256`. When they differ, the file is the
  store's re-encoded copy, not the upload.
- `notes` (what the pull saw: a version in preparation, a storefront with the same words as another), `failed`
  (downloads that didn't come), and for `--public`, `notPublic` and `public` (each storefront's seller, version,
  genres, age rating text, price, languages).

**Which version.** On Apple, `pull` reads the version on sale on each platform (the app information that's live
too). If a version is in preparation its words may differ, and the notes say so. On Google, the listing is
the store's current one (Play has no versions of a listing).

## Without keys: `--public` (Apple only)

`pull apple --public` reads Apple's public iTunes Lookup API (`https://itunes.apple.com/lookup?bundleId=…&country=…`,
falling back to `&entity=macSoftware` for a Mac app), one storefront country at a time (`--country us,gb,de`,
default `us`). It gets each storefront's app name, description, What's New (release notes), seller and website, the
version, the genres (as App Store Connect's categories, primary and secondary), the age rating as text, and the
iPhone, iPad and Apple TV screenshot URLs, which it downloads.

Say plainly what it lacks. **The subtitle, keywords and promotional text aren't public**, nor are the support and
privacy URLs, the copyright, the age rating answers, App Review's notes or the previews. They're listed in
`notPublic`. Pull with the key to have them, or write them with the user.

- **A storefront isn't a language.** A country's words are in its language only if the app has a listing in it;
  otherwise the App Store shows another. A storefront whose words are the same as an earlier one's is left out (the
  notes say so). `--country ca:fr-CA` names a storefront's language where the table doesn't know it or guesses wrong.
- **The pictures are the web page's copies,** usually smaller than the uploads (an iPhone shot at 392×696), with no
  display type: their folders are by device (`iphone`, `ipad`, `apple-tv`, `mac`). They show the current set; they
  aren't files to send.
- **Google Play has no public API** for a listing: `pull google` needs the service account's key. Without one, the
  user pastes the words from Play Console (or the store page), and the screenshots come from wherever they were made.

## Import it as the draft

`listing.py import --from live existing/` (or `existing/apple`) writes or merges into `store-listing.json` the way
the other imports do. **A value the config already has (not `null`) is never replaced.** It prints what it took, what
it kept, then a summary of what's live: locales, the words' lengths and the pictures per slot.

- Words per locale; the first platform's (iPhone's) become the locale's, and another platform's that differ become
  its own (`locales.<loc>.apple.platforms.<P>`). A field a non-primary locale leaves empty on the store is set to
  `""`, so it isn't filled with the primary's words by fallback.
- Ids, the copyright (without a leading ©: Apple adds it), URLs, Play's contact details, categories, the age rating
  answers the rules know, App Review's notes, and a demo account's environment variable names when App Review needs a
  sign-in. App Review's contact is never pulled: the import names the variables to set.
- Screenshots go into the config's layout (`<folder>/<locale>/<screen>/<shot>.png`), screens named by device class as
  the fastlane import names them. Shot ids come from the uploaded file names (`03_APP_IPHONE_67_plan.png` → `plan`),
  and another locale's pictures on a screen take the primary's ids by position. **A store's copy isn't the upload:**
  if the copies stay in the config, `push.py plan` replaces the store's pictures with them. Put the originals or the
  new set in their place before planning, or leave a screen out of `stores.apple.platforms.<P>.screens` to keep
  that slot as the store has it. Pictures at no store size (the public lookup's) stay in `existing/` as the
  reference and aren't copied.
- **The live screenshots are the current set** for the screenshots work (the `store-screenshots` skill, or any
  tool): `existing/<store>/screenshots/` shows what each shot features today, in order. New screenshots start
  from it: which moments to keep, which to replace, in what order.

What the config can't say comes out as a note: a platform without one of the App Store's locales (the config gives
every App Store locale to every platform, so a plan would add it), Play Console's fields (category, tags, content
rating, target audience, alt text).

## Decide with the user, then diff

Look at the draft with the user before changing anything: read each locale's words back (the summary gives the
lengths), open the pictures, and ask what to keep. Keep what works. Change what the user wants changed.

`listing.py diff [--config store-listing.json] [--existing existing/] [--stores apple,google] [--json]` compares the
config's resolved words (after fallback, per platform) and picture counts with what was pulled, per store, locale and
field:

| Mark | Status | Meaning |
|---|---|---|
| `=` | unchanged | the same (keywords compared without spaces round the commas) |
| `~` | changed | a short before → after (with both lengths for long texts) |
| `-` | only live | the config leaves it unset, so a plan leaves the store's as it is |
| `+` | only ours | the store has none; a plan would add it |

Pictures are compared by count only ("the same number"). A plan compares the pictures themselves. For a public pull,
the fields that aren't public aren't compared. `diff` reads files only. It's for showing the user what a new listing
would change before any plan. `push.py plan` still reads the store itself, and is what an apply goes by.
