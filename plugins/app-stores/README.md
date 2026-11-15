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
| [`store-listings`](./skills/store-listings/) | 0.1.0 | the config and its importers (fastlane, Triple-T, Expo); the words and their checks; building each store's output; page previews; plan and apply for Apple and Google; forms with no API as drafted answers; checklists for Steam and itch.io | [#11](https://github.com/Redth/skills/issues/11) |
| [`store-screenshots`](./skills/store-screenshots/) | 0.1.0 | the listing's current set read first (what to keep), the user's examples, two to four rendered directions, one iterated into an approved baseline that later updates are checked against; the brief and a storyboard agreed before rendering; layouts (full-bleed, band, framed, cut off, tilt, pair, callout, hero, gameplay) and drawn device frames; eight starting styles; every size and locale from one design through headless Chrome; mocks of Apple's search row, the product page and Play's listing; screenshot checks per store | [#12](https://github.com/Redth/skills/issues/12) |
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
>
> Design our App Store and Play screenshots from these captures.
>
> Make this release's screenshots match the ones we did last time.
>
> Our German captions don't fit: fix them.

The usual flow, which the skill walks an agent through:

```sh
python3 <skill>/scripts/listing.py import --from fastlane fastlane   # or write store-listing.json from scratch
python3 <skill>/scripts/listing.py check                             # offline; errors stop everything after
python3 <skill>/scripts/listing.py build                             # out/: fastlane layouts, listing.json, checklist.md
python3 <skill>/scripts/listing.py preview --png                     # each store's page, to look at
python3 <skill>/scripts/push.py plan google                          # reads the store, writes plan-google.json
python3 <skill>/scripts/push.py apply plan-google.json               # only when you say so
```

And for designed screenshots (`store-screenshots`), after you've agreed the storyboard with the agent:

```sh
python3 <skill>/scripts/sheet.py --inspiration --png        # your examples, described, for you to confirm
python3 <skill>/scripts/render.py --style design/directions/bold/screenshot-style.json --out design/explore/bold --shots plan,recipe,shop --targets iphone
python3 <skill>/scripts/sheet.py --directions design/explore/bold,design/explore/calm --png
python3 <skill>/scripts/render.py                # store-screenshots.json → screenshots/<locale>/<screen>/<shot>.png
python3 <skill>/scripts/sheet.py --png           # Apple's search row, the product page, Play, a contact sheet
python3 <skill>/scripts/check.py                 # sizes, caption fit and floor, words, frames, contrast, per store;
                                                 # drift from the approved baseline once there is one
python3 <skill>/scripts/baseline.py approve --note "what you approved"   # locks the look for later updates
python3 <skill>/scripts/sheet.py --compare design/baseline --png         # every update: baseline beside now
```

The rendered folder is `store-listing.json`'s screenshots folder: `listing.py check` takes it from there.

### Prerequisites

- **Python 3.8+** (stdlib only), on macOS or Linux.
- **`openssl`**, to sign the stores' API tokens (only `push.py` needs it).
- **Google Chrome or Chromium**, for `preview --png` (set `CHROME` to point at it; the HTML preview works
  without it) and for `store-screenshots`' rendering and sheets (required there).
- To send: an **App Store Connect API key** (App Manager or Admin) in `ASC_KEY_ID`, `ASC_ISSUER_ID` and
  `ASC_PRIVATE_KEY`, and/or a **Google Play service account** with Manage store presence in
  `GOOGLE_PLAY_SERVICE_ACCOUNT`. Keys may be a path, the text, or base64.

### Network and privacy

- **No network by default.** `import`, `check`, `build` and `preview` work offline, and so does all of
  `store-screenshots`: fonts and frames are files, nothing is fetched.
- **Only `push.py` reaches a network,** only the stores' own API hosts (`api.appstoreconnect.apple.com` and the
  upload hosts Apple names, `oauth2.googleapis.com`, `androidpublisher.googleapis.com`), and **only
  `push.py apply` writes.** `plan` only reads (on Google it opens an edit to read, and deletes it).
- **Secrets never go in the config.** Keys and App Review's contact come from environment variables; the plan
  masks the contact's phone number. Nothing is sent anywhere else: no telemetry, no account.
- The agent never sends without your go-ahead, never claims a console form was changed, and stops at a
  checklist for stores with no API.
- **Device art:** `store-screenshots` draws its own generic frames and never ships, fetches or modifies a maker's
  device art; your own Apple bezels are used only as they are, on Apple's set.

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
