# Pitfalls

What has gone wrong before when sending listings to the stores, and how to avoid it. Each is written so it can
happen to any app.

## Locales

- **The store's primary language isn't the one you wrote.** A listing written as `en-US` went to an app whose
  App Store primary language was `en-CA`, while Play's default was `en-US`. Writing to a locale nobody sees, or
  creating a new one, is easy to miss. Read each store's primary locale (the `plan` notes a mismatch) before
  writing copy; it's set per store. Set `stores.apple.primaryLocale`, `stores.google.defaultLanguage` and each
  store's `locales` to match, so the build sends neither store a language it doesn't have.
- **One Apple platform's words overwritten with another's.** App Store Connect keeps a version's description per
  platform; an Apple TV description saying a controller is needed (Guideline 2.4.3) became the iPhone one in a
  single-description config. Keep a platform's own words in `locales.<loc>.apple.platforms.<P>`.
- **A new Apple localisation copies everything but the description and keywords.** Check both after adding a
  locale.
- **A localised screenshot that isn't there falls back to the primary's.** The check reports fallbacks: read
  them, so a shot meant to be translated isn't quietly in the primary language.

## Counting

- **Bytes versus characters.** A release notes check counting bytes read 487 characters as 511 (every `•` is 3
  bytes) and warned falsely. Apple's keywords (100) and review notes (4,000) really are bytes; everything else
  counts characters. The unit is part of each rule's data.
- **Run the check before committing copy changes,** not only before sending. A promotional text went over 170
  characters in a wording change and was caught only at the next build.

## Keys and permissions

- **Keys arrive in more than one shape.** A `.p8` stored base64-encoded by a secret manager and written to disk
  as it was made `openssl` fail to sign, in three different scripts. The scripts accept a path, the PEM text, or
  base64 of either; if signing fails, check what the variable actually holds (without printing it).
- **Apple:** the key's role must be App Manager or Admin. A 401 is usually the key, issuer or a clock far off; a
  403 is the role.
- **Google, two different 403s:** `accessNotConfigured` / `SERVICE_DISABLED` means the Google Play Android
  Developer API isn't enabled in the service account's Cloud project. "The caller does not have permission" means
  the service account lacks the Play Console permission (Manage store presence; Manage policy declarations for
  Data safety) or wasn't invited for this app. Enabling an API and granting a permission are separate steps.
- **Personal details in logs.** App Review's phone number appeared in CI logs from a look-only diff. The plan
  shows only its last digits; don't paste it anywhere either.

## Sending

- **Two senders, one Play app.** A listing run opened an edit while a release was uploading a bundle; the release
  failed with "This edit has expired". Opening an edit only to look counts. Serialise everything that opens a Play
  edit.
- **Play's default commit cancels what's in review,** a release included, and resubmits everything. The scripts
  ask for `ERROR_IF_IN_REVIEW`; `--cancel-review` is the user's choice.
- **Cleanup hid the real error.** Play answered 503 to the delete of an uncommitted edit, and that error replaced
  the one that had stopped the push. The original error must be reported first.
- **Apple's upload servers time out on a part now and then** (a 504 on a large preview's part, after the
  screenshots had gone through). Parts are retried; a failure after the retries is reported as Apple gave it.
- **Most Apple fields change only with a version in preparation.** Screenshots, description and keywords wait for
  one; promotional text changes any time. Plan with `--new-version` only when the user wants a new version.
- **A step can succeed without delivering.** A release notes field was silently dropped by an upload step for
  weeks. After an apply, plan again: no actions means it arrived.
- **Code that hasn't run against the real store yet should say so.** A fix tested only against recorded answers
  is a guess until its first real run.

## Forms

- **The forms drift from the app.** The forms' drafted answers said "no crash reporter" a month after one was
  added, while the privacy policy had been updated. When the app's data flows change, update the policy and the
  drafted answers together, and tell the user which console forms to change.
- **Definitions that surprise:** a sign-in email kept by the provider's backend is collected; Apple's "Contests"
  include sport and fitness contests and rankings, not only sweepstakes. Read the definitions in
  [forms.md](forms.md) before answering.
- **Data safety's CSV overwrites every answer** when sent. Export it from Play Console after any change made there,
  or the next send undoes it.

## Pictures

- **A device's size class doesn't promise its pixels.** One simulator in a store's size class renders a size the
  store won't take. Read each PNG's size; the check does.
- **Alpha:** some capture tools add an alpha channel. Apple refuses screenshots with one; Play refuses alpha in
  screenshots, the feature graphic and the TV banner.
- **Never resize to fit a slot.** Capture or render at the size; a stretched UI is obvious and can be refused.
- **Stores show different things.** What one store's rating allows, another's screenshot rules may not (Apple's
  screenshots must suit 4+ whatever the rating). Decide each store's set from its own rules.

## The skill itself

- **A skill that isn't kept up goes stale.** One store's workflow gained an import step, edit locking and new
  form fields over a month while its skill stayed as it was. Update the references in the same change as the
  workflow, and re-read a rule's source when it matters and was checked long ago.
