# Forms: App Privacy, Data safety, age and content ratings

Answer from the stores' own definitions, not intuition: they're narrower or wider than they sound. Quotes are
from the pages named, read 2026-11-14. Pages change: when an answer turns on a definition, re-read it.

**Never claim a console form was changed.** Most of these forms have no API: draft the answers in the config's
`forms`, print them in the checklist, and tell the user which form to change by hand.

## Which forms have an API

| Store | Form | API? | How |
|---|---|---|---|
| Apple | App Privacy ("privacy nutrition label") | **no** | checklist; answers can change any time, no new version needed |
| Apple | Age rating | **yes** | `stores.apple.ageRating`, sent with `push.py plan apple --age-rating` |
| Apple | EU trader status, content rights, regulated medical device, Made for Kids | no | checklist |
| Google | Data safety | **yes, as a CSV** | fill it once in Play Console, export the CSV, keep it as `stores.google.dataSafetyCsv`; sending it **overwrites all answers** |
| Google | Content rating (IARC), target audience, ads, Sign-in details, health, financial features, government apps, permissions | no | checklist |
| Google | Category, tags | no | checklist |

## Drafting answers in `forms`

`forms` is free-form; the checklist prints it. A shape that works:

```json
"forms": {
  "apple.appPrivacy": {
    "checked": "2026-11-14",
    "answers": { "Contact Info > Email Address": { "collected": true, "linked": true, "tracking": false,
                 "purposes": ["App Functionality"] } },
    "why": "Sign-in keeps the account email in our backend.",
    "decidedBy": "the user, 2026-11-14"
  },
  "google.contentRating": { "answers": { "Violence": "No" }, "why": "…" }
}
```

Mark which answers the user has decided and which are drafts. Keep the privacy policy, the forms and what the app
does in step: a new SDK, ads, purchases, accounts, chat or a crash reporter changes all three. When the app's data
flows change, update the drafted answers and tell the user which console forms to change.

## Apple: App Privacy

Source: https://developer.apple.com/app-store/app-privacy-details/ (checked 2026-11-14).

- **Collect:** "'Collect' refers to transmitting data off the device in a way that allows you and/or your
  third-party partners to access it for a period longer than what is necessary to service the transmitted
  request in real time."
- **On device:** "Data that is processed only on device is not 'collected' and does not need to be disclosed."
- **Served and discarded:** "if an authentication token or IP address is sent on a server call and not retained,
  or if data is sent to your servers then immediately discarded after servicing the request, you do not need to
  disclose this."
- **IP addresses that are kept:** "Declare the relevant data types based on how you use IP address, such as
  precise location, coarse location, device ID, or diagnostics."
- **Third parties count:** "You need to identify all of the data you or your third-party partners collect";
  "third-party partners" are "analytics tools, advertising networks, third-party SDKs, or other external vendors
  whose code you've added to your app."
- **Optional disclosure** needs **all** of: not used for tracking; not used for third-party advertising, your
  advertising or marketing, or other purposes; collected only in infrequent cases outside the app's primary
  functionality and optional for the user; and provided by the user in a form where it's clear what's
  collected, their name is shown, and they choose to send it each time.
- **Updating:** "You may update your answers at any time, and you do not need to submit an app update in order
  to change your answers."

Consequences people get wrong:

- A sign-in email kept by the app's backend is **collected**, even when the backend is the sign-in provider's
  service acting for you: you and your partners can read it later.
- An analytics or crash SDK's identifiers and diagnostics are collected, because the SDK is a third-party partner.
- A relay that only passes traffic through and keeps nothing doesn't collect what passes through it.

## Google Play: Data safety

Source: https://support.google.com/googleplay/android-developer/answer/10787469 (checked 2026-11-14).

- **Every app** on a closed, open or production track completes it: "Even developers with apps that do not
  collect any user data must complete this form."
- **Collect:** transmitting data from your app off a user's device.
- **Share:** transferring collected user data to a third party. **Not sharing:** transfers to a service provider
  that processes data "on behalf of the developer and based on the developer's instructions", transfers for
  legal reasons, and anonymised data. A service provider keeps data out of "shared", **not** out of "collected".
- **Ephemeral processing:** using data only in memory and keeping it no longer than the real-time request
  needs. It's still disclosed as collected, but can be marked as processed ephemerally.
- **End-to-end encrypted** data that is "unreadable by you or anyone other than the sender and recipient" isn't
  collected.
- **SDKs count:** it "includes data collected and handled through any third-party libraries or SDKs used in their
  apps."
- **IP addresses:** no standalone rule; approximate location worked out from an IP address must be disclosed as
  location.
- **Account deletion:** an app that lets users make an account needs an in-app path and a web link that delete
  the account and its data (entered in Data safety). Source:
  https://support.google.com/googleplay/android-developer/answer/13327111 (checked 2026-11-14).
- **The advertising ID:** an analytics SDK can add Android's `AD_ID` permission. Declare it, or turn its
  collection off and remove the permission in the manifest; the form has to match the build.

## Apple: age rating

Source: https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions
(checked 2026-11-14).

- Ratings: 4+, 9+, 13+, 16+, 18+ and Unrated (which can't be published). Some regions add their own (Australia,
  Brazil, Korea, Vietnam).
- **Contests:** "Events that allow users to compete with one another for rankings, rewards, or the achievement of
  personal goals. May include: skill-based competitions, trivia quizzes, or sport or fitness contests."
  Infrequent: 4+; frequent: 13+. Not only sweepstakes: leaderboards and sports games can count.
- **Cartoon or fantasy violence:** "Physical conflict or harm of an exaggerated or fantastical nature that can
  easily be distinguished from real life." Infrequent 9+, frequent 13+.
- "Infrequent" and "frequent" aren't defined: answer for what a reviewer will see in normal play, and let the
  user decide close calls.
- A rating covers everything the app can show, switched off or not: parental controls don't lower it.
- The config uses App Store Connect's attribute names (`violenceCartoonOrFantasy`, `contests`, `lootBox`,
  `socialMedia`, `ageAssurance`, `userGeneratedContent`, …) and values (`NONE`, `INFREQUENT_OR_MILD`,
  `FREQUENT_OR_INTENSE`, booleans). Send them only once settled (`--age-rating`): they're the whole app's.

## Google Play: content rating and target audience

- **Content rating** is IARC's questionnaire in Play Console: violence, fear, sexuality, language, controlled
  substances, crude humour, gambling, users interacting or sharing content, shared location, digital purchases,
  unrestricted internet. An unrated app is removed; answer again when content changes. Source:
  https://support.google.com/googleplay/android-developer/answer/9898843 (checked 2026-11-14).
- **Target audience:** age groups 5 and under, 6–8, 9–12, 13–15, 16–17, 18+. Any group under 13 brings the
  Families policy (only self-certified ads SDKs; the advertising ID becomes a problem). Art that appeals to
  children in a listing not for them can be rejected. Source:
  https://support.google.com/googleplay/android-developer/answer/9867159 (checked 2026-11-14).
- **App content** (every app): privacy policy, ads, Sign-in details (credentials for anything behind a login),
  health, financial features, government apps, permissions. Source:
  https://support.google.com/googleplay/android-developer/answer/9859455 (checked 2026-11-14).

## Answering a question about a form

1. Find the store's definition above (or on its page, if it's not here) and quote it with its date.
2. Ask what the app actually does with the data: where it goes, who can read it, how long it's kept, which SDKs
   are in the build.
3. Draft the answer with the reason, in `forms`. Close calls are the user's decision.
4. Say which console form to change, and that you haven't changed it.
