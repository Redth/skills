# Sending: plan and apply, and the stores with no API

Only `push.py` reaches a network, only the stores' own hosts (`api.appstoreconnect.apple.com` and the upload
hosts Apple names, `oauth2.googleapis.com`, `androidpublisher.googleapis.com`; for `pull`, also
`itunes.apple.com`, Apple's `*.mzstatic.com` and Play's image hosts), and only `push.py apply` writes.

## Pull: read what's live (read-only)

`push.py pull apple|google` reads the live listing into `existing/<store>/` (words, categories, the age rating
answers, App Review's notes, every screenshot and preview). Like `plan`, it never writes to a store. On Google it
opens an edit to read and deletes it, so don't pull while another tool is sending. `pull apple --public` reads
Apple's public lookup with no key. Detail, the hosts and the files: [existing.md](existing.md). Before planning a
new listing, `listing.py diff --existing existing/` shows the user what it changes, from those files.

## Before sending

1. `listing.py check` passes.
2. `listing.py build` has written `out/` from the current config and pictures.
3. The preview (`listing.py preview --png`) has been looked at.
4. The keys are in the environment ([apple.md](apple.md#keys-and-roles), [google.md](google.md#service-account-and-permissions)).
5. Nothing else is sending to the same app (Play allows one open edit an app).

## Plan

```sh
python3 <skill>/scripts/push.py plan apple  [--out out] [--plan plan-apple.json] [--age-rating] [--new-version 1.2.0]
python3 <skill>/scripts/push.py plan google [--out out] [--plan plan-google.json]
```

`plan` reads `out/listing.json` and the store (GET only; on Google it opens an edit to read and deletes it), then
writes and prints the plan:

- `actions`: each change in order, with a one-line `summary` ("change title: 'Old' → 'New'", "replace 3 phone
  screenshots with 4").
- `unchanged`: what already matches ("en-US tenInchScreenshots: 4 pictures, as they are").
- `notes`: what the plan can't do and the user must (Console-only fields, a primary locale that differs, no
  version in preparation).
- `fingerprint`: a hash of every store value the actions compare against.
- `listingSha256`: the hash of `out/listing.json` the plan was made from.

`--age-rating` adds the age rating answers (they're the whole app's: send them once settled). `--new-version`
plans to create a version where a platform has none in preparation (it creates something in the user's account,
so ask first).

**Show the plan and stop.** Summarise the actions per locale; quote the summaries; say what's unchanged and what
the notes ask of the user. A plan with no actions means the store already matches.

## Apply

```sh
python3 <skill>/scripts/push.py apply plan-google.json [--cancel-review]
```

Only when the user asks, for the store they named. `apply`:

1. Refuses if `out/listing.json` no longer matches the plan's `listingSha256` (the build changed: plan again).
2. Reads the store again and recomputes the fingerprint; **refuses if it differs** ("the store changed since you
   planned: plan again"). Someone edited the listing in the console, another tool sent, or a review finished.
3. Performs exactly the plan's actions, in order, and reports each.
4. On Google, commits with `changesInReviewBehavior=ERROR_IF_IN_REVIEW`, unless `--cancel-review`.

After a refusal: plan again, show the new plan (it may differ from the old one in ways the user should see), and
wait for the user again. Never edit a plan file by hand, and never retry `apply` hoping it passes.

## A review in progress (Google)

Play's default commit cancels whatever is in review, a release included, and resubmits everything. `apply`
asks Play to fail instead: the error is `CHANGES_ALREADY_IN_REVIEW` (400 `FAILED_PRECONDITION`) and nothing is
committed. Tell the user, quoting the error, and give the choices: wait for the review to finish, then plan and
apply again; or apply with `--cancel-review`, which cancels what's in review and resubmits it with these changes.
That choice is the user's.

On Apple, most changes wait for a version in preparation, and a version in review isn't editable: the plan says
so.

## Retries and errors

- The scripts retry 5xx, 408, 429, timeouts and dropped connections, up to 4 tries (15, 30, 45 s, or the
  `Retry-After` the store gives, capped at 120 s). Large uploads (previews) time out now and then.
- Anything else fails at once. **Pass the store's error on as it came** (status, code, message), then explain it;
  don't paraphrase it away or retry blindly.
- If cleanup fails after an error (deleting an uncommitted Play edit), the original error is the one that
  matters; the scripts report it first.
- A step can succeed without delivering: after an apply, a second `plan` should show no actions.

## One store at a time

Apply one store, report, then the next only if the user asked for both. Two senders against one Play app at once
invalidate each other's edits, including a CI job uploading a build: serialise them (in CI, one concurrency
group for everything that opens a Play edit, cancelling none).

## What's never sent

- The forms with no API (App Privacy, Play's content rating, target audience, ads, category, tags…): they're in
  `out/checklist.md`. See [forms.md](forms.md).
- Builds, releases and release notes on Play tracks: another tool's job (fastlane, Gradle Play Publisher, the
  stores' upload tools).
- Achievements, prices, in-app purchases.

## Stores with no API

Steam and itch.io have no API that writes a store page (Steam's Web API only reads the store and sets build
branches; itch.io's server-side API only reads, and butler uploads builds). **Write the checklist and stop:**
each field's words, every graphic at its size with its file, screenshots in order, under the store's own field
names. Don't drive their web consoles, and don't claim anything was filled in.

### Steam

Sources: https://partner.steamgames.com/doc/store/assets/standard, https://partner.steamgames.com/doc/store/assets/rules,
https://partner.steamgames.com/doc/store/assets/libraryassets, https://partner.steamgames.com/doc/store/page/description,
https://partner.steamgames.com/doc/store/tags, https://partner.steamgames.com/doc/store/trailer,
https://partner.steamgames.com/doc/store/review_process, https://partner.steamgames.com/doc/gettingstarted/contentsurvey
(all checked 2026-11-14).

| Asset | Size | Rule |
|---|---|---|
| Header capsule | 920×430 | key art, logo and name only: no review scores, awards, discounts, calls to action or other text |
| Small capsule | 462×174 | the logo should nearly fill it |
| Main capsule | 1232×706 | as the header |
| Vertical capsule | 748×896 | as the header |
| Page background | 1438×810, optional | ambient; Steam makes one from the last screenshot if none |
| Library capsule | 600×900 | logo, no other text |
| Library header | 920×430 | as the capsule |
| Library hero | 3840×1240 PNG | no text at all; keep the centred 860×380 safe area clear |
| Library logo | 1280 px wide and/or 720 px tall, transparent PNG | the logotype only |
| Shortcut icon | 256×256 or 512×512 | Mac: an ICNS too |
| App icon | 184×184 JPG | |
| Screenshots | 1920×1080 or larger, 16:9; at least 5 | gameplay only (no concept art, awards, marketing copy); mark at least 4 suitable for all ages |
| Trailers | up to 1920×1080, 30 or 60 fps, H.264 + AAC preferred | the first two show before the screenshots |

All art must suit PG-13. Words: a short description of "a few hundred characters" (editors report 300,
`unverified`), nothing time-bound; About This Game in BBCode, **no links** anywhere in the description or images;
at least 5 tags before launch (the top 20 count); the content survey, including the generative AI disclosure, is
required. Process: USD 100 an app; 21 days after paying before a first release; Coming Soon for at least two
weeks; page and build reviews of 3–5 business days (reported up to 12 in November 2026, `unverified`); **the name
can't change after the first review** (ask before submitting); publishing makes every asset public at once.

Checklist:

- [ ] Basic Info: name (final after review), genres, features, links, controller support, languages.
- [ ] Description: short description, About This Game (BBCode, no links), accolades, alt text.
- [ ] Graphics: the four store capsules, page background, library capsule, header, hero, logo (then its
      position), icons.
- [ ] Screenshots: at least 5 gameplay, at least 4 marked all ages, in order.
- [ ] Trailers: upload, category, order, languages.
- [ ] Tags (at least 5, the top 5 telling what it is).
- [ ] Content survey, including generative AI.
- [ ] Preview, publish, Mark as Ready for Review at least 7 business days ahead.

### itch.io

Sources: https://itch.io/docs/creators/getting-started, https://itch.io/docs/creators/quality-guidelines,
https://itch.io/docs/creators/design, https://itch.io/docs/creators/html5 (all checked 2026-11-14).

| Field | Rule |
|---|---|
| Cover image | 315:250, at least 315×250, 630×500 recommended; an animated GIF is allowed (no flashing) |
| Screenshots | any size; 3–5 recommended |
| Short description | shown in listings; no limit given |
| Description | rich text (HTML); no limit |
| Genre | one from itch.io's list |
| Tags | up to 10; prefer suggested ones; none duplicating the metadata, your name or the title |
| Metadata tab (after the first save) | inputs, multiplayer, accessibility, average session, languages (or Textless), **AI disclosure** (required), adult content |
| Platforms | only those you upload a build for and have tested |
| Theme | colours, fonts, banner (no size given; about 960 px wide is common, `unverified`), background; custom CSS only on request |
| HTML5 builds | a ZIP with `index.html`; at most 1,000 files, 500 MB extracted, 200 MB a file, 240-character paths |

Checklist:

- [ ] Create the page: title, URL, short description, classification, kind of project, pricing.
- [ ] Cover, screenshots, video link, description (paste the HTML), genre, tags.
- [ ] Metadata tab: inputs, multiplayer, accessibility, session length, languages, AI disclosure.
- [ ] Theme: colours, fonts, banner, background.
- [ ] Builds with butler; for a web build, tick "This file will be played in the browser".
- [ ] Visibility: Restricted while testing, Public when ready (a page reaches Most Recent only once, when first
      published).

### Amazon Appstore

To follow in this skill. Amazon's Appstore serves only Amazon's devices now (Fire tablets, Fire TV); its
submission API covers the listing. Until it's supported, write its checklist by hand from Amazon's pages.
