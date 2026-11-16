# app-stores

**Take an app's store presence from one config to the stores it's on.** The words for every locale, the
screenshots for every device, checked offline against each store's rules (kept as dated, sourced data), previewed
as each store's page, and sent through the stores' own APIs only after you've read a plan of what will change.
Stores and forms with no API get a checklist with the answers drafted. Any app, any stack; games are one case.

- 🗂️ **One config** (`store-listing.json`, with a JSON Schema) for the App Store (iPhone, iPad, Mac, Apple TV,
  Vision Pro) and Google Play (phone, tablets, TV, Wear), with checklists for Steam and itch.io.
- 📏 **Rules as data:** every limit, size, count and banned word has the store page it came from, the date it was
  checked and a status. An unverified rule only warns.
- 👀 **Look first:** `push.py plan` reads the store and writes what would change; `push.py apply` does exactly
  that plan, and refuses if the store changed since.
- 🔌 **No dependencies:** stdlib Python 3.8+ and `openssl`. No Ruby, Node, vendor account or telemetry. Reads and
  writes fastlane's `deliver` and `supply` layouts, so a project on fastlane can start from what it has.

## The skills

| Skill | Status | What it does | Issue |
|---|---|---|---|
| [`store-listings`](./skills/store-listings/) | 0.1.0 | starting from the live listing (pulled read-only, or from Apple's public lookup without keys), the config and its importers (fastlane, Triple-T, Expo); the words and their checks; building each store's output; page previews; plan and apply for Apple and Google; forms with no API as drafted answers; checklists for Steam and itch.io | [#11](https://github.com/Redth/skills/issues/11) |
| `store-screenshots` | proposed | the design brief and storyboard; templates and drawn device frames; every size and locale rendered through headless Chrome; mocks of each store's search row and page; screenshot checks | [#12](https://github.com/Redth/skills/issues/12) |
| `store-capture` | proposed | screenshots and previews from any stack: `simctl`, `adb` and headless Chrome drivers, importers for fastlane snapshot and screengrab, Maestro, Playwright and others | [#13](https://github.com/Redth/skills/issues/13) |
| `store-signing` | to follow | signing, notarising and uploading builds to TestFlight, Play, Amazon, Steam and itch.io | [#14](https://github.com/Redth/skills/issues/14) |
| `game-achievements` | to follow, if it earns its place | Game Center and Play Games achievements from one list | [#15](https://github.com/Redth/skills/issues/15) |

Each hands the next a folder: capture writes the captures, screenshots renders them into store sizes, listings
checks and sends them. Each works alone: `store-listings` takes PNGs from any tool.

## For consumers: using it

**Claude Code:**

```text
/plugin marketplace add Redth/skills
/plugin install app-stores@redth-skills
```

**Any agent:** ask in your own words:

> Set up our App Store and Google Play listing.
>
> Check our listing against the store rules before we submit.
>
> What would change on Play if we sent it?
>
> Import our fastlane metadata.
>
> What does Steam need for our store page?

The usual flow, which the skill walks an agent through:

```sh
python3 <skill>/scripts/push.py pull apple [--public]                 # on the stores already? read what's live first
python3 <skill>/scripts/listing.py import --from live existing        # ...as the draft (or --from fastlane, or by hand)
python3 <skill>/scripts/listing.py diff                               # what the new listing would change
python3 <skill>/scripts/listing.py check                             # offline; errors stop everything after
python3 <skill>/scripts/listing.py build                             # out/: fastlane layouts, listing.json, checklist.md
python3 <skill>/scripts/listing.py preview --png                     # each store's page, to look at
python3 <skill>/scripts/push.py plan google                          # reads the store, writes plan-google.json
python3 <skill>/scripts/push.py apply plan-google.json               # only when you say so
```

### Prerequisites

- **Python 3.8+** (stdlib only), on macOS or Linux.
- **`openssl`**, to sign the stores' API tokens (only `push.py` needs it).
- **Google Chrome or Chromium**, for `preview --png` (set `CHROME` to point at it). The HTML preview works
  without it.
- To send: an **App Store Connect API key** (App Manager or Admin) in `ASC_KEY_ID`, `ASC_ISSUER_ID` and
  `ASC_PRIVATE_KEY`, and/or a **Google Play service account** with Manage store presence in
  `GOOGLE_PLAY_SERVICE_ACCOUNT`. Keys may be a path, the text, or base64.

### Network and privacy

- **No network by default.** `import`, `check`, `build`, `preview` and `diff` work offline.
- **Only `push.py` reaches a network,** only the stores' own hosts (`api.appstoreconnect.apple.com` and the
  upload hosts Apple names, `oauth2.googleapis.com`, `androidpublisher.googleapis.com`; for `pull`, Apple's public
  `itunes.apple.com`, its `*.mzstatic.com` CDN and Play's image hosts), and **only `push.py apply` writes.**
  `plan` and `pull` only read (on Google they open an edit to read, and delete it).
- **Secrets never go in the config.** Keys and App Review's contact come from environment variables; the plan
  masks the contact's phone number. Nothing is sent anywhere else: no telemetry, no account.
- The agent never sends without your go-ahead, never claims a console form was changed, and stops at a
  checklist for stores with no API.

## For authors and contributors: updating the rules

The stores change their rules without notice, so the rules are data, and keeping them current is the most
useful contribution.

- The rules live once in [`shared/rules/`](./shared/rules/) (`apple.json`, `google.json`; one file a store),
  with their schema `rules.schema.json`. Each rule has an `id` that never changes, a `source` URL, the date it was
  `checked`, and a `status` (`verified`, `observed`, `unverified`). The format is in
  [`CONTRACT.md` §3](./CONTRACT.md) and the skill's `references/rules-data.md`.
- **To update a rule:** read the store's page, change the rule, its `source` and its `checked` date together, set
  its `status`, and say what changed in the pull request. A rule only a secondary source supports is
  `unverified`; one seen in the store's behaviour but not written down is `observed`.
- **Shared code and data are copied, never linked:** skills reference only files inside their own folder, so
  `python3 plugins/app-stores/tools/sync_shared.py` copies `shared/appstores_lib` and `shared/rules` into each
  skill that uses them, and `tools/test_sync_shared.py` fails when a copy drifts. Edit `shared/`, then sync; never
  edit a skill's copy.
- **Before a pull request:** `bash tools/validate.sh` and `python3 tools/validate_marketplace.py` from the
  repository root (they run every `test_*.py`, including the scripts' tests against recorded store answers in
  each skill's `evals/files/`). Examples and fixtures use only the invented app "Sample Recipes" by Example
  Studio (`com.example.samplerecipes`, `example.com`).
- Each skill's `VERSION` starts at `0.1.0`; the repository's `CHANGELOG.md` gets an `app-stores` entry per pull
  request. [`CONTRACT.md`](./CONTRACT.md) is the single source of truth for names, paths and data shapes: change
  it first if one must change.

## License

[MIT](../../LICENSE)
