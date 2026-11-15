# Design principles, with their evidence

What this skill designs to, and how sure anyone can be of each. Read 2026-11-14.

**Grades:**

- **A**: a store's own rule or documentation, or strong data.
- **B**: consistent observation of live listings, plus some data.
- **C**: practitioners' consensus.
- **D**: this skill's own opinion.

"Observed" below means a look at the first shots of 13 top apps and 13 top games on the US App Store, and six of
those apps on Play, on 2026-11-14 (named where they show a pattern). A small, US-only sample: a picture of what's
current and what passes review, not a census, and not evidence of what converts.

## 1. Shots 1 to 3 decide the first impression; each must sell alone at search size

**Grade A for what's shown; B for its weight.**

- Apple: "the first one to three images will appear in search results when no app preview is available",
  depending on orientation (https://developer.apple.com/app-store/product-page/).
- Play shows screenshots after the video, ordered for the device browsing, and asks you to "prioritize UI in the
  first three screenshots" (https://support.google.com/googleplay/android-developer/answer/9866151).
- Most visitors never swipe: 9% of portrait viewers scrolled the screenshots in one agency's 25,000-visitor tests
  (2017, mostly paid traffic, an older iOS layout); a vendor puts "decisive" visitors who see only the first
  screen at about 60% (no method published).

*So:* design shots 1 to 3 first, check them in `sheet.py`'s search-row mock, and treat the rest as a carousel few
people see. A landscape set shows only shot 1 in search.

## 2. Lead with the core value, in real UI

**Grade A for "app in use"; B for the order.**

- Apple 2.3.3: screenshots "should show the app in use, and not merely the title art, login page, or splash
  screen"; text and image overlays are allowed. Apple's guideline reference for 2.3.3 puts it as more than half of
  a set showing the app in use, the rest free for marketing art
  (https://developer.apple.com/help/app-review/guideline-reference/2-3-3-screenshots).
- A vendor reports that leading with a new feature rather than the core value hurt conversion (via search; no
  method).

*So:* shot 1 shows what the app does best, working. A brand or claim "hero" first is fine only with real UI in it
(the `hero` layout keeps a sliver of the app), and only where visitors already know the brand.

## 3. One message a shot: 2 to 5 words, at most two lines, a benefit or a verb

**Grade B.**

- Apple's asset guidance: "use a short phrase that enhances your visual rather than describes it" and localise it
  (https://developer.apple.com/app-store/asset-best-practices/).
- Observed: captions of 2 to 7 words, most 3 to 5, never more than two lines; games' 1 to 4.
- One vendor test cut captions to 3 words in its winning variant, among several other changes.

*So:* the check fails a caption over two lines and warns over six words.

## 4. Captions sized for the thumbnail

**Grade B (derived arithmetic on official type sizes).**

On a portrait phone in Apple's search row, a caption needs a font size of about 9% of the slot's width to read as
iOS's 11-point minimum. Most top apps' captions measure 5 to 9%: readable on the product page, marginal in search.
Check it on the mock at real size rather than trusting the number: [legibility.md](legibility.md).

## 5. One set per store, not one set for all

**Grade A.**

- Apple: frames and captions allowed; no prices, URLs, © or Apple-designated awards; every shot fit for 4+.
- Play: no frames by default, words at most 20% of the picture, no awards, rankings, testimonials, prices or
  calls to action, alt text, no extra text on tablet shots, Wear OS the interface only.
- Steam: gameplay only, no words. itch.io: gameplay.

Detail and sources: [store-rules.md](store-rules.md). The config's `stores` overrides do this from one design.

## 6. Drawn frames only

**Grade A.** Apple's bezels are licensed only for mock-ups of Apple-only software, as they are; Google says not to
use its device art on Play; Meta's device set bars commercial use without permission. This skill draws its own
generic frames, and uses a user's own Apple bezel only as it is: [frames.md](frames.md).

## 7. Real UI, invented content, a clean status bar, fit for all ages

**Grade A.** Apple 2.3.8 (4+ whatever the rating), 2.3.9 (rights to everything shown, fictional account
information), the marketing guidelines' clean status bar; Play's "actual in-app experience" and a notification bar
with no carrier name (https://developer.apple.com/app-store/review/guidelines/,
https://developer.apple.com/app-store/marketing/guidelines/).

## 8. No prices, discounts, URLs, ©, rankings or "#1"; awards only where allowed

**Grade A, with practice that differs.**

- Apple 2.3.7 bans prices in screenshots; the asset guidance asks for no "specific pricing, discounts, website
  URLs, copyright symbols", no unverifiable claims and no Apple-designated recognitions (Editors' Choice, App of
  the Day, Apple Design Award).
- Play's guidance: nothing suggesting "Google Play performance, ranking, accolades or awards… user testimonials,
  or price and promotional information".
- Steam: no awards or marketing copy in screenshots.
- Observed: 6 of 13 top apps show Apple-designated awards in their App Store screenshots, and one shows "Editor's
  Choice" on Play. Review evidently lets some through; that's evidence of what passes, not of what's allowed.

*So:* the check catches the words; real, verifiable third-party awards are the user's call on Apple, never on Play
or Steam. Flag, explain, let the user decide.

## 9. Off-edge devices, tilt and callouts are accents, not the system

**Grade C, partly D.** About 10 of 13 top apps cut the phone off at the bottom edge (it buys the UI size and gives
the caption the top third); 4 of 13 tilt one or two shots; 2 lift a piece of UI out of the frame. Tilt shrinks and
skews the UI, which hurts reading at thumbnail size. A tilt on one shot in a set at most; callouts only to enlarge
real UI.

## 10. Panoramas only where shot 1 still stands alone

**Grade A that Play allows them; C for the seams; the right-to-left order unverified.** Nothing that matters within
a seam margin, rebuilt per device size, checked in right-to-left storefronts: [panoramas.md](panoramas.md).

## 11. One visual system

**Grade A.** Apple: "Consider using similar visual style, such as color palette, iconography, fonts, message, and
tone." Every sampled app holds one caption style and place, one frame and one palette, changing only colour or
tilt as accents. A dark-mode shot if the app has dark mode (https://developer.apple.com/app-store/product-page/).

## 12. Localise with room to grow

**Grade A.** Short strings grow 200 to 300% in translation; shrink to a floor that fails the check, and capture per
locale where the UI sells: [localisation.md](localisation.md).

## 13. Nothing dated in screenshots

**Grade A.** Play: avoid "time-sensitive" content. Apple's screenshots change only with a new version, while iOS
27's search and header assets can change any time. Seasonal messages go in those, Steam's artwork overrides, or a
test.

## 14. Every "+X%" is a hypothesis

**Grade A for the tools; D for the advice.** The published conversion results are vendor case studies, usually
changing several things at once, with no method. The only trustworthy evidence for an app is its own test:
[evidence.md](evidence.md).

## 15. Games are different

**Grade B.** Most games open with key art or a logo, then show gameplay full-bleed, with no caption or a short verb
in a band. A caption plate over full-bleed gameplay is one layout among the rest: [games.md](games.md).
