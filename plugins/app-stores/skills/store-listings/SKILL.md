---
name: store-listings
description: >
  Use this skill to set up our App Store / Google Play listing, start from the listing that's live now (read it
  from the stores, even without API keys), update the store description, subtitle,
  keywords, promotional text or what's new, check our store listing against the App Store and Play rules
  before we submit, preview how our store pages will look, see what would change on the App Store or Play
  compared with what's live,
  send the new listing to the App Store or Google Play, import our fastlane / supply / Gradle Play Publisher /
  Expo store.config.json metadata, help answer App Privacy, Play Data safety, the age rating or content
  rating, or say what Steam or itch.io need for our store page. Any app, any stack (iPhone, iPad, Apple TV,
  Mac, Android phones, tablets, TV, Wear). Do not use for designing or captioning screenshots, capturing
  screenshots from a simulator, emulator or device, uploading builds or TestFlight, code signing, in-app
  purchases or pricing, or ASO keyword research.
license: MIT
---

# store-listings

Takes an app's store presence from one config file (`store-listing.json`) to the stores it's on: checked
offline against each store's rules, built into each store's layout, previewed as each store's page, then sent
through the stores' own APIs with a plan the user reads before anything changes. Stores and forms with no API
get a checklist with the answers drafted.

## Purpose

- **One config** for the words (per locale), the screenshots (per screen), the URLs, categories and age rating
  answers of every store the app is on. Schema: `schema/store-listing.schema.json`.
- **Store rules as dated, sourced data** (`rules/<store>.json`): every limit, size, count and banned word has
  the store page it came from, the date it was checked and a status. An unverified rule only warns.
- **Start from what's live:** `push.py pull` reads the listing the stores have now (words, categories, every
  screenshot) into `existing/`, read-only; `listing.py import --from live` makes it the draft and `listing.py diff`
  shows what a new listing would change.
- **Look first, then send:** `push.py plan` reads the store and writes what would change; `push.py apply` does
  exactly that plan and refuses if the store changed since.

## Non-goals

- Designing, captioning or framing screenshots (the `store-screenshots` skill; this one takes PNGs from any tool).
- Capturing screenshots or recording previews (`store-capture`).
- Builds, signing, uploads, TestFlight (`store-signing`, to follow), pricing, in-app purchases, subscriptions.
- Keyword research or ASO data. This skill checks the keywords field's rules, not which keywords win.
- Driving any web console. Steam, itch.io and every form with no API get a checklist, and the agent stops there.

## When to use

- An app already on the stores: start from its live listing (pull it, import it, decide what to keep).
- Setting up a listing for a new app, or importing one a project already has (fastlane, Triple-T, Expo).
- Changing the words: description, subtitle, keywords, promotional text, What's New, Play's title and short
  description, in any locale.
- Before a submission: "check our listing", "will this pass?", "what would change?".
- Sending the listing, or answering what a store needs (Steam, itch.io, App Privacy, Data safety, ratings).

## Inputs

| Input | Where | Notes |
|---|---|---|
| `store-listing.json` | the user's project (`--config`, default `./store-listing.json`) | Paths inside are relative to it. Every field: [references/config.md](references/config.md) |
| Screenshots | `<screenshots.folder>/<locale>/<screen>/<shot>.png` | Any tool's PNGs or JPEGs at the store's exact pixel sizes |
| Apple API key | `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY` | Only for `push.py`. The key: a `.p8` path, its text, or base64. Role: App Manager or Admin (`pull apple --public` needs none) |
| Google service account | `GOOGLE_PLAY_SERVICE_ACCOUNT` | Only for `push.py`. JSON key path, text or base64. Play Console permission: Manage store presence |
| App Review contact | `APPLE_REVIEW_FIRST_NAME`, `…_LAST_NAME`, `…_PHONE`, `…_EMAIL` | Named in the config, never written in it |

Prerequisites: Python 3.8+ (stdlib only), `openssl` (signing the stores' tokens), Google Chrome or Chromium for
`preview --png` (`CHROME` overrides where it's found).

## Workflow

The scripts are in this skill's `scripts/` folder; run them with `python3`, from the user's project.

1. **Start from what's live.** If the app is on the stores already, its live listing is the baseline: read it
   before writing a word ([references/existing.md](references/existing.md)).
   - **Pull it:** `push.py pull apple` and `push.py pull google` with the keys (`--id` or the config's `app.ids`
     name the app). Without Apple's key, `push.py pull apple --public [--country us,de]` reads what the App Store
     shows anyone, its screenshots at the uploads' own size (the App Store's re-encoded copies; `--thumbnails` for the
     page's small ones). Say what that lacks: the subtitle, keywords and promotional text aren't public. Google has no
     public API: it needs the key, or the user pastes the words. `pull` only reads (on Google it opens an edit and
     deletes it).
   - **Import it as the draft:** `listing.py import --from live existing/`. It never overwrites a value the config
     already has, and prints a summary of what's live (locales, lengths, pictures per slot), naming a store it
     didn't pull and what a listing there still needs.
   - **Look at it with the user and decide what to keep** before changing anything: read the words back, open the
     pictures. The live screenshots (`existing/<store>/screenshots/`) are the current set: hand them to the
     screenshots work as the starting point. The import lists the slots holding the store's own copies in
     `stores.<store>.keep`, so a plan leaves them alone: take a slot out once its pictures are the new set.
   - **Before any plan,** `listing.py diff --existing existing/` shows the user what the new listing changes, field
     by field (unchanged, changed before → after, only live, only ours).
   - **No live listing and no config:** if the project has `fastlane/metadata`, Triple-T's `play/` folder or Expo's
     `store.config.json`, run `listing.py import --from fastlane|supply|triple-t|expo <path>`
     ([references/importing.md](references/importing.md)). Otherwise write one from the user's answers and
     [references/config.md](references/config.md). Leave ids `null` until the user gives them; never invent them.
   - Read the config, the rules files' `checked` dates and which rules are `unverified`. Ask which stores and
     platforms the app ships on if the config doesn't say.
   - **Primary locale and locales:** each store has its own primary (it may not be `en-US`) and its own
     languages: `stores.apple.primaryLocale`, `stores.google.defaultLanguage` and `stores.<store>.locales`. Write
     to the store's primary locale; don't give a store a language it has no listing in unless the user wants one.
   - **Per platform:** App Store Connect keeps a version's words (description, keywords, promotional text, What's
     New, URLs) per Apple platform. Where one platform needs its own (Apple TV's controller sentence), write it in
     `locales.<loc>.apple.platforms.<P>` rather than changing every platform's words.
2. **Check:** `listing.py check [--stores apple,google]`. Errors stop everything after. **A failing check means
   editing the config (the words, the pictures), not the rule.** Only if the store's cited page now says
   otherwise does a rule change, and then upstream with its source and date
   ([references/rules-data.md](references/rules-data.md)). A rule the user decides not to follow goes in
   `rules.relax` with their reason, by their choice. Field-by-field guidance: [references/words.md](references/words.md).
3. **Build:** `listing.py build [--out out]` writes `out/`: fastlane `deliver` and `supply` layouts, every
   picture in its store slot, `out/listing.json` (what `push.py` reads) and `out/checklist.md`.
4. **Preview and look:** `listing.py preview --png`, then open every `out/preview/*.png` and read it as a
   shopper would: words cut off, the wrong locale, a picture in the wrong slot, a first shot that doesn't sell.
   Report what you see; don't fix taste without the user.
5. **Plan:** `push.py plan apple` and/or `push.py plan google` (one store per plan). Show the user the plan's
   `actions` (each `summary`), what's `unchanged` and the `notes`, and stop. `plan` only reads; on Google it
   opens an edit and deletes it, never commits.
6. **Apply only when the user says so,** for the store they named: `push.py apply plan-<store>.json`. Report
   each action's result. If it refuses because the store or `out/listing.json` changed, plan again and show the
   new plan; never work around the refusal. Never add `--cancel-review` unless the user chose it after being told
   it cancels what's in review. Detail: [references/sending.md](references/sending.md).
7. **Checklists:** print `out/checklist.md` for every form with no API (App Privacy, Play's content rating,
   target audience, ads, category and tags…) with the drafted answers from the config's `forms`. Steam and
   itch.io have no listing API: give their checklist ([references/sending.md](references/sending.md#stores-with-no-api))
   and stop. Forms: [references/forms.md](references/forms.md).
8. **Report:** what was checked, built, planned or applied (per store); every unverified or stale rule that
   applied; pictures that fell back to another locale; what's left for the user to do by hand. Don't commit;
   say what's ready to commit (the config, the pictures used), never `out/`.

## Agent rules

The short form; the reasons are in [references/agent-rules.md](references/agent-rules.md).

1. Look first; the user sends. `apply` only on the user's word, one store at a time.
2. Fix the listing, not the rule. A rule changes only with its store's page, source and date.
3. Pass a store's error on exactly as it came. Retry only what's known to be transient (the scripts do).
4. Never claim a console form was changed. Say which form to change, with the drafted answer.
5. Stores with no API get a checklist; don't drive their web consoles.
6. Ask before anything that can't be undone (deleting a store asset, a free app on Play, making a version,
   cancelling a review).
7. Keys, tokens and App Review's contact come from environment variables; never write them in the config,
   the output, a commit or the chat.
8. Flag other people's names, marks and platforms in the words or pictures; the user decides.
9. Say what's stale or unverified. A store page read on a date can have changed since.
10. Start from what's live: pull, import and show it, decide with the user what to keep, and diff before planning.

## Validation

- `listing.py check` exits 0 (warnings allowed, each read and either fixed or accepted by the user).
- `out/listing.json` exists and is newer than the config and every picture it lists.
- The preview PNGs were opened and looked at.
- For an app already on the stores, the live listing was pulled and looked at before new words were written, and a
  `diff` was shown before planning.
- A plan was shown before any apply; `apply` reported every action, or stopped with the store's own error.
- `--json` on `check` gives machine-readable findings (`rule_id`, `severity`, `where`, `message`, `source`,
  `status`) for scripted use.

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `check` fails on a limit or word | the words break a store rule | change the words; see [words.md](references/words.md) |
| A rule seems wrong for the store today | the store may have changed | open its `source`; if it changed, propose a rules-data update; meanwhile `rules.relax` with a reason, if the user agrees |
| `apply` refuses: the store changed | someone or something edited the store since the plan | plan again, show it, wait for the user |
| Google: `CHANGES_ALREADY_IN_REVIEW` | something is in review; the commit was held | tell the user; `--cancel-review` only by their choice |
| Google: "This edit has expired" / edit conflicts | another tool opened an edit on the same app | run one sender at a time; plan again |
| Apple: no version in preparation | most fields change only with one | `plan --new-version X.Y.Z` (ask first); promotional text changes any time |
| 401/403 from a store | key, role or API not set up | [pitfalls.md](references/pitfalls.md#keys-and-permissions) names each cause |
| Chrome not found | `preview --png` can't render | install Chrome/Chromium or set `CHROME`; the HTML preview still works |
| `pull apple` without a key | App Store Connect can't be read | `pull apple --public`, saying what isn't public; or set the key |
| `pull google --public` | Play has no public listing API | the key, or the user pastes the words |
| `pull` exits 1: not downloaded | a picture didn't come (or was on another host) | the words were written; `existing/<store>/README.md` lists what's missing; pull again |

## References

| File | What's in it |
|---|---|
| [config.md](references/config.md) | every field of `store-listing.json`, fallbacks, the folder layout, secrets |
| [rules-data.md](references/rules-data.md) | the rules files' format, statuses, relaxing, updating a rule |
| [apple.md](references/apple.md) | App Store: slots, what's app-level vs per version, the API, roles, quirks |
| [google.md](references/google.md) | Google Play: slots and graphics, edits, permissions, quirks |
| [words.md](references/words.md) | limits and how each counts, price words by field, other platforms, What's New |
| [forms.md](references/forms.md) | App Privacy, Data safety, age and content ratings: the stores' definitions, quoted and dated |
| [sending.md](references/sending.md) | plan and apply, retries, Play's one open edit, review in progress, stores with no API |
| [existing.md](references/existing.md) | starting from what's live: `pull` (keys or `--public`), `existing/`, import, `diff` |
| [importing.md](references/importing.md) | from fastlane `deliver`/`supply`, Triple-T, Expo, and what `pull` wrote |
| [pitfalls.md](references/pitfalls.md) | what went wrong before, and how to avoid it |
| [agent-rules.md](references/agent-rules.md) | the agent's rules with their reasons |
