# Google Play (phone, tablets, TV, Wear)

What `push.py` sends to Google Play, the slots and graphics, permissions and quirks. Store pages read on
2026-11-14; the rules data (`rules/google.json`) has each limit with its source and date.

## What's sent

Everything goes through one **edit** (Play's transaction):

| Part | API | Fields |
|---|---|---|
| Details | `edits.details` | default language, contact email, website, phone |
| Listing, per language | `edits.listings` | title, short description, full description, video (a YouTube URL) |
| Images, per language | `edits.images` | `phoneScreenshots`, `sevenInchScreenshots`, `tenInchScreenshots`, `tvScreenshots`, `wearScreenshots`, `icon`, `featureGraphic`, `tvBanner` |
| Data safety | `applications.dataSafety` (outside the edit) | the CSV Play Console exports |

Then the edit is validated and committed. Release notes go with a release on a track, not the listing (500
characters a language): this skill doesn't send releases.

**No API:** the category, tags (up to 5), content rating, target audience, ads declaration, Sign-in details
(formerly "App access"), the other App content declarations, custom store listings, store listing experiments,
alt text, and screenshots for Chromebook, Android XR and Automotive. Those go in the checklist.

## Slots and graphics

| Slot | Config | Rule (requirement) | Recommended |
|---|---|---|---|
| Phone | `slots.phone` | at least 2 screenshots across device types to publish; up to 8 a type; JPEG or 24-bit PNG, no alpha; each side 320–3840 px; long side at most 2× the short | apps: 4+ at ≥1080 px (16:9 or 9:16) to be featured; games: 3+ |
| 7" tablet, 10" tablet | `slots.tablet7`, `slots.tablet10` | sides 1080–7680 px, 16:9 or 9:16 | 4 or more (a recommendation, not a requirement) |
| TV | `slots.tv` | at least 1 with TV opted in, plus the TV banner | at least one **unaltered** screenshot (no captions) |
| Wear OS | `slots.wear` | at least 1; 1:1; ≥384×384; the app's UI only: no frames, extra text or backgrounds | a Tiles shot if it has Tiles |
| Icon | `graphics.icon` | 512×512, 32-bit PNG, ≤1024 KB, a full square (Play rounds it) | no ranking, price or Play program badges |
| Feature graphic | `graphics.featureGraphic` | **required**; 1024×500, JPEG or 24-bit PNG, no alpha | alt text up to 140 characters (Console only) |
| TV banner | `graphics.tvBanner` | 1280×720, JPEG or 24-bit PNG, no alpha | |

Screenshots and the feature graphic: no "Best", "#1", "Top", "New", "Free", "Discount", "Sale", "Million
Downloads", awards, testimonials, prices or calls to action; captions at most 20% of the image; frames and added
backgrounds are discouraged (they affect promotion) except on Wear OS, where they're not allowed. Panoramas are
allowed. Every current Android phone emulator is taller than 2:1: set the device's size before capturing.

Source: https://support.google.com/googleplay/android-developer/answer/9866151 (checked 2026-11-14).

## How `push.py` talks to Play

- **Token:** an RS256 JWT for the service account, exchanged at `oauth2.googleapis.com` for an access token
  (scope `androidpublisher`), signed with `openssl`.
- **One edit a run.** `plan` opens one to read (the API needs it) and deletes it before returning; it never
  commits. `apply` opens one, makes the planned changes, validates and commits.
- **Listings:** the whole listing for a language is replaced only when a field differs.
- **Images:** a type whose SHA-256 list (in order) matches the store's is left alone. Otherwise all of that type
  are deleted and the new ones uploaded in order, inside the edit, so nothing is public until the commit.
- **Commit** uses `changesInReviewBehavior=ERROR_IF_IN_REVIEW`. Play's default (`CANCEL_IN_REVIEW_AND_SUBMIT`)
  cancels whatever is in review, a release too, and resubmits everything. With something in review the commit
  fails with `CHANGES_ALREADY_IN_REVIEW`, nothing is committed and `apply` deletes the edit; `--cancel-review` uses the default, only by the
  user's choice. Source: https://developers.google.com/android-publisher/api-ref/rest/v3/edits/commit (checked
  2026-11-14).
- **An uncommitted edit is deleted** when the run stops, and if that delete fails too, the original error is the
  one reported.
- **Retries:** 5xx, 408, 429 and dropped connections, with backoff. Anything else fails at once, with Google's
  error as it came.
- **Quota:** 3,000 queries a minute. Source: https://developers.google.com/android-publisher/quotas (checked
  2026-11-14).

## One open edit an app

"Each user may have only a single edit open at a time"; opening a new edit invalidates the user's open one, and
**any commit or any Play Console change invalidates every other edit for the app**. So never run two senders
against one app at once: a CI release uploading a bundle and a listing push collide ("This edit has expired").
Serialise everything that opens an edit, looking included. Changes can take hours to show. Source:
https://developers.google.com/android-publisher/edits (checked 2026-11-14).

## Service account and permissions

1. In Google Cloud: a project with the **Google Play Android Developer API** enabled, and a service account with
   a JSON key.
2. In Play Console ▸ Users and permissions: invite the service account's email, for the app, with **Manage store
   presence** (the listing) and, to send Data safety, **Manage policy declarations**.
3. Export `GOOGLE_PLAY_SERVICE_ACCOUNT` (the JSON key's path, text or base64).

The API is off: 403 `accessNotConfigured` / `SERVICE_DISABLED`. The permission is missing: "The caller does not
have permission". They're different fixes. The API can't create an app or send its first bundle: both by hand in
Play Console.

## Locales

86 listing languages; a language you haven't translated gets an automatic machine translation with a note.
Graphics localise per language; without them the default language's show. Character limits count full-width and
half-width characters as one each. Source: https://support.google.com/googleplay/android-developer/answer/9844778
(checked 2026-11-14).

## Things to know

- **Free is forever:** a free app on Play can never become paid. Ask before setting a price model.
- **New personal developer accounts** (made after 2023-11-13) need a closed test with at least 12 testers
  opted in for 14 days in a row before production. Finish the listing and App content forms before the test.
  Source: https://support.google.com/googleplay/android-developer/answer/14151465 (checked 2026-11-14).
- **Android TV** is an opt-in form factor with its own review. Its description must mention "Android TV".
- **The video** is one YouTube URL: a single video, public or unlisted, ads off, embeddable, not age-restricted.
