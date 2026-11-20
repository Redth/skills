# Device frames

**This skill draws its own frames and never ships, fetches or modifies anyone else's device art.** The licensing
facts below were read 2026-11-14. They're a reading of public terms, not legal advice: when a user wants a maker's
art, tell them the terms and let them decide.

## The drawn frames

`frames/<name>.svg` with `frames/<name>.json` (the screen's rectangle and corner radius): `phone`,
`phone-landscape`, `tablet`, `tablet-landscape`, `laptop`, `desktop`, `tv`, `watch`. Pick one with `theme.frame`,
a target's or a store's `frame`; `"none"` for no frame.

They're generic on purpose: **no notch, Dynamic Island, Home button, camera bump, side buttons or brand shape.**
Apple's marketing guidelines say a generic device illustration must not carry "details that are unique to Apple
products, such as the iPhone Home button, sensor housing, Ring/Silent switch, or volume controls", and that "any
simulation of an Apple product" isn't permitted. A plain rounded rectangle simulates nobody's device, so it can be
tilted, cut off and overlapped freely, and it doesn't date the set when a new phone comes out.

The capture sits inside the frame's screen rectangle with the frame's corner radius; a capture whose shape differs
from the screen is fitted, never stretched.

## Per store

| Store | Frames | Source |
|---|---|---|
| Apple | drawn frames fine; Apple's own bezels only as they are (below) | https://developer.apple.com/app-store/marketing/guidelines/ |
| Google Play: phone, tablet, TV | discouraged: no device imagery ("can become obsolete quickly or alienate some users"). **The default is no frame**; `check.py` warns when one is used | https://support.google.com/googleplay/android-developer/answer/9866151 |
| Google Play: Wear OS | **none, required**: "do not use device frames", no backgrounds or masking | same |
| Steam, itch.io | none: gameplay, full-bleed | https://partner.steamgames.com/doc/store/assets/standard |

The rules files' `design` table holds this (`frames`, with `bySlot` for Wear OS, and `deviceArt`: Apple's
`ownAsIs`, Google's `none`); `check.py` reads it.

On Play, a user who wants frames anyway may keep them (some top apps do): it's their choice once they know Google
recommends against it and that the recommendation formats (large cards on Play's home) require the recommendations
to be met.

## The makers' device art

| Frames | Licence, as it reads | Ship them? | Can the user use them? |
|---|---|---|---|
| **Apple's product bezels** (Apple Design Resources: PSD, PNG, Keynote) | Apple Design Resources License: use "solely for creating mock-ups of user interfaces designed for use in software products that run only on Apple's macOS, iOS, watchOS, tvOS, and/or visionOS", including showing them in screenshots; no redistribution, no embedding in software, no modification or derivative works; recipients of mock-ups must be told the restrictions. https://developer.apple.com/design/resources/ and the licence, https://developer.apple.com/support/downloads/terms/apple-design-resources/Apple-Design-Resources-License-20230621-English.pdf | **No** | Yes, fetched themselves, for Apple-only apps, as they are |
| **Google's Device Art Generator** | "Do *not* use graphics created here in your feature image or screenshots for your Google Play store listing." https://developer.android.com/distribute/marketing-tools/device-art-generator | No | Not for Play listings |
| **Meta's device set** (where fastlane frameit's frames came from) | "may not be used for commercial purposes without express written permission"; for prototypes and mock-ups; device images may carry their makers' trademarks (read via a search summary, https://www.meta.com/design-at-meta/license/) | No | Doubtful for store listings |
| **fastlane `frameit-frames`** | Downloaded by frameit on first run; the repository states no licence (https://github.com/fastlane/frameit-frames) | No | At their own risk |
| **devices.css** | MIT, but its iPhone drawings copy Apple-only details | No (not the Apple ones) | Not the Apple ones |

## A user's own Apple bezel

A user may bring Apple's bezel, downloaded themselves from Apple Design Resources. Give `frame` the path to it
(relative to the config) with a `.json` beside it in the drawn frames' shape (`frames/phone.json` is an example:
the screen rectangle and its corner radius), with `"drawn": false` and `"maker": "apple"`, so the check holds it to
Apple's terms. Then:

- **As it is:** the `framed` layout only (or `pair` at true relative scale). Never `tilt` or `framed-bleed`, no
  `callout` out of it, no caption, plate or graphic over it, no shadow or reflection added. `check.py` fails an
  Apple bezel tilted, cropped or overlapped.
- **Apple sets only.** Never on Play (Google's guidance, and an Apple device on Play is another platform's).
- **Apple-only apps.** The licence covers mock-ups of software that runs *only* on Apple's systems. A strict
  reading excludes an app that's also on Android, Windows or the web. Say so; it's the user's decision.
- **Never committed by the agent, never copied into the skill,** never redistributed: the user keeps it where they
  put it. The latest generation of device, per Apple's guidelines.

When the user asks for Apple's bezel tilted or cut off (a common look on live listings), explain that Apple's terms
forbid exactly that for its art, and offer the two ways that work: the bezel whole in `framed`, or a drawn frame
tilted or cut off as they like.

## What the stores' rules data says

`store-listings`' Apple rules carry an `unverified` warning (`apple.screenshots.device_frames`) reading the
marketing guidelines strictly: Apple's bezels only, unmodified. The guidelines are written for "marketing
materials", App Review's guidelines don't repeat them, and tilted, cut-off phones are common in live App Store
screenshots, so whether review enforces them on screenshots is unverified. Generic drawn frames are this skill's
answer; the warning is a reminder to the user, not a reason to block.
