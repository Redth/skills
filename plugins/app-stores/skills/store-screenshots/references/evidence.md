# The evidence on conversion, and how to get your own

**What's known for certain is what the stores show and what they allow. What converts, for a given app, is known
only by testing it.** Every "+X%" in a blog post is a hypothesis.

## What's published

Read 2026-11-14. "Vendor" means a tool or agency selling testing or design, with no method published.

| Claim | Source | Data | Strength |
|---|---|---|---|
| Visitors spend about 7 s on a listing; 13% scroll the screenshots (9% portrait, 5% landscape, 17% of gamers); 3% enlarge one; under 1% expand the description | An agency's tests, 2017 | 25,000 visitors, 7 iOS tests on store-imitating pages, mostly paid traffic | Weak to moderate and dated, but the only one with a stated method |
| About 60% of visitors are "decisive", seeing only the first screen | Vendor | "500M users" mentioned, no method | A marketing number |
| A landscape gallery +42% from search, for one game; a new feature first hurt conversion | Vendor | none published | A marketing number |
| Portrait beat landscape for one game; characters with a coloured frame won, +13% | Vendor case study | no sample, no dates | Weak |
| Reordering +6.4%, a custom background +4.4%, lifestyle photos worst | Vendor, 2015 | about 1,200 paid visitors in total, on imitation store pages | Weak |
| 3-word captions, bolder art and characters: +10% | Vendor case study | sample not given, many changes at once | Can't attribute |
| Localised screenshots +33% | Vendor | not opened | A lead, not a fact |
| Variant screenshots +14% in Play's experiments | A publisher on Google's blog, 2015 | real Play experiments, few details | Old, official-hosted |
| "+30% for panoramas" | traced by one vendor to other vendors' posts | no study | None |
| A higher store conversion can bring worse users | A 2026 article | illustrative numbers | A sound caution |

No peer-reviewed study turned up.

## What it supports

1. **Strong enough to act on:** the first frames carry the decision. The behavioural data and the stores' own
   layouts agree.
2. **Plausible, weakly supported:** fewer, shorter caption words; the core value before a new feature; real content
   and characters over abstract lifestyle photos; localised captions.
3. **Unknown:** frame or no frame, tilt, panoramas, dark or light, awards. Every figure found changes several things
   at once or has no method.

So the skill designs to the stores' rules and the first-impression principle, and doesn't claim a lift for any
style. When a user cites a number, say where such numbers come from, design what they want if the rules allow it,
and propose testing it.

## How to run a real test

**Apple: product page optimisation** (https://developer.apple.com/app-store/product-page-optimization/):

- Up to three treatments against the original product page, for up to 90 days, with a share of traffic you choose.
- Results are reported with a confidence level (Apple uses 90%); a treatment's screenshots go through review;
  alternate icons must be in the binary.
- Test screenshots (and the order), previews and icons. Apple suggests trying seasonal content there.

**Google Play: store listing experiments** (https://support.google.com/googleplay/android-developer/answer/6227309):

- Variants of one asset (the screenshots, the icon, the feature graphic, the short description) against the current
  listing, for a share of visitors, for at least a week; measured on installs (and retained installs). Read the
  Help page for the current number of variants and the options.

**How to make the test mean something:**

- **One change at a time:** shot 1's message, or shot 1's layout, not both. A set that changes everything can win
  without telling you why.
- **Test the first impression:** shot 1, or the order of shots 1 to 3. That's where most visitors decide.
- **Run it long enough** to cover a full week's cycle, and don't stop it the day it looks good.
- **Check after the install** before keeping a winner: retention, a first session that finishes, a purchase. A
  promise the app doesn't keep can raise installs and lower everything after.
- **Watch the season:** a holiday or a feature on the store moves the baseline.

`store-screenshots` makes the variants: a second config (or the same one with different shots) rendered to its own
out folder. Setting up the experiment is in each store's console; no API here does it.
