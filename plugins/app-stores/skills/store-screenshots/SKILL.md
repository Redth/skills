---
name: store-screenshots
description: >
  Use this skill to design App Store or Google Play screenshots for our app, add captions, a device frame,
  a tilt, a callout or a panorama to our screenshots, make one screenshot design come out at every iPhone,
  iPad and Android size and in every language, translate or fit our screenshot captions (German, Japanese,
  Arabic), check whether our screenshots read in App Store search results, say what each store allows in a
  screenshot (frames, awards, prices, text), plan which shots go first and what each one says, or make a
  game's gameplay screenshots for the stores. Takes real captures (or PNGs from any design tool) and renders
  them with HTML templates in headless Chrome. Do not use for capturing screenshots from a simulator,
  emulator or device (store-capture), writing the listing's words, checking the listing or sending it to a
  store (store-listings), app icons, website or marketing images, preview videos, or building a screenshot
  editor.
license: MIT
---

# store-screenshots

Designs and renders store screenshots from an app's real captures: one design, every store, size and locale.
The user agrees the story first; the scripts render it through HTML/CSS templates in headless Chrome, check it
against each store's rules, and draw mock-ups of each store's first impression for the agent to look at. The
output is the folder `store-listings` reads.

## Purpose

- **The story before the pixels:** a brief (who it's for, the one core value, what each store allows) and a
  storyboard (shots 1 to N, one message each), agreed with the user before anything renders.
- **One design, every size and locale:** a `store-screenshots.json` (schema `schema/store-screenshots.schema.json`)
  names the layouts, captions, theme and targets; `render.py` lays each shot out in units of the slot's width, so
  a 0.46 iPhone, a 4:3 iPad and a 9:16 Play phone come from the same design.
- **One set per store:** each store's rules (`rules/<store>.json`, dated and sourced) decide what its set may
  carry: frames, words, awards, prices. Play is frameless by default.
- **Drawn frames only:** generic phone, tablet, laptop, desktop, TV and watch frames drawn for this skill. No
  maker's device art is shipped, fetched or modified.
- **Judged as a shopper sees it:** `sheet.py` places the rendered files in mock-ups of Apple's search row, the
  product page and Play's listing at real display size, and a contact sheet of every file.

## Non-goals

- **Capturing the app.** That's `store-capture` (or any tool that writes PNGs in its folder layout).
- **The listing's words, checks of the whole listing, or sending.** That's `store-listings`; this skill hands it a
  folder.
- **An interactive editor.** Others do that well. A set made in a design tool or screenshot editor comes in as
  PNGs: as captures for a layout, or as finished files `store-listings` takes directly.
- **Conversion claims.** Every "+X%" is a hypothesis; the stores' own experiments are the test
  ([references/evidence.md](references/evidence.md)).
- **Preview videos, app icons, iOS 27's search and header assets and Play's feature graphic.** Not version 0.1's
  layouts; [references/store-rules.md](references/store-rules.md) has their sizes.

## When to use

- "Make App Store / Play screenshots for our app", "put captions / a frame / a tilt on our screenshots".
- "Our screenshots don't work in search", "which shot should go first?", "what should each one say?".
- "Make the German / Japanese / Arabic screenshots", "this caption doesn't fit in German".
- "Can we put Editor's Choice / our price / an iPhone frame in the Play screenshots?"
- "Make our game's store screenshots."

## Inputs

| Input | Where | Notes |
|---|---|---|
| The brief | the conversation | who the app is for, its one core value, which stores and devices, the app's look (fonts, colours) |
| Captures | `<captures>/<locale>/<capture device id>/<capture screen id>.png` | `store-capture`'s layout; any tool's PNGs renamed into it. At least the size they're shown at |
| `store-screenshots.json` | beside `store-listing.json` usually (`--config`) | every field: [references/config.md](references/config.md) |
| Fonts | files the config's `theme.fonts` names | the app's own, with the user's right to use them; one that covers every locale's script |
| A frame of the user's own (optional) | a file the config points at | Apple's bezels only as they are: [references/frames.md](references/frames.md) |

Prerequisites: Python 3.8+ (stdlib only) and Google Chrome or Chromium (`CHROME` overrides where it's found).
No network: nothing is fetched, fonts and frames included.

## Workflow

The scripts are in this skill's `scripts/` folder; run them with `python3`, from the user's project.

1. **Brief.** Ask, or read from the project: who the app is for, the one thing it does better than anything
   else (its core value, in the user's words), which stores and devices it ships on, its look (fonts, colours,
   dark mode), and any claims the user can back up. Read what each target store allows
   ([references/store-rules.md](references/store-rules.md)): Apple takes captions and drawn frames but no
   prices, URLs or Apple-designated awards; Play prefers no frames, words under 20% of the picture, no awards,
   rankings or calls to action; Wear OS takes the interface only.
2. **Storyboard, agreed before rendering.** Propose shots 1 to N as a short table: the capture each uses, its
   one message (a caption of 2 to 5 words, a benefit or a verb), its layout, and which stores it goes to. Shots
   1 to 3 carry the core value in real UI, because they're what search shows and most people never swipe
   ([references/principles.md](references/principles.md)). Offer two or three options where taste decides (the
   order, the tone, a hero or not, a tilt or not) and let the user choose. **Don't render until the user has
   agreed the storyboard.** For games: [references/games.md](references/games.md).
3. **Captures in.** Check the captures exist for every shot, device and locale the storyboard needs, are big
   enough for their targets, and show the moment each message needs. Look at each one at full size: transient UI
   (a toast, a banner, a spinner, a permission prompt), test or real people's data, a messy status bar, other
   platforms' names or glyphs. If they're missing or wrong, capture first (`store-capture`, or the user's own
   tool) and come back.
4. **Write `store-screenshots.json`** from the storyboard ([references/config.md](references/config.md)): the
   targets at each store's exact pixel sizes with ids that are `store-listing.json`'s screen names, the shots in
   order with ids that are its shot ids, the captions as string keys per locale, the theme, and per-store
   overrides (`"stores": { "google": { "frame": "none" } }`). Layouts:
   [references/layouts.md](references/layouts.md).
5. **Render:** `render.py [--config store-screenshots.json] [--locales …] [--targets …] [--shots …] [--force]`.
   It writes `<out>/<locale>/<target>/<shot>.png` (opaque RGB, exact size) and `<out>/render-report.json`, and
   re-renders only what changed (`--force` for everything). Exit 1 means a render failed or a caption couldn't fit
   at its floor: fix the words, not the floor ([references/legibility.md](references/legibility.md)).
6. **Look.** `sheet.py [--config …] --png` renders the mock-ups to `<out>/sheets/*.png`. Open every sheet, then
   every rendered file at full size, and go through the visual checklist
   ([references/checklist.md](references/checklist.md)): does each of shots 1 to 3 say what the app is in the
   search-row mock, at the caption size it reports in points? Words over the app's own UI, a caption cut or badly
   broken, transient UI, a frame or callout covering what the shot is about, a seam through something that
   matters, the wrong locale's UI, content unfit for all ages, others' names and marks. Report what you see,
   shot by shot.
7. **Check:** `check.py [--config …] [--json]`: sizes, alpha and counts per store, caption fit, floor, lines and
   words, Play's text share, frames per store, forbidden words in captions, missing glyphs, seams, contrast,
   upscaled captures and fallbacks, plus the checklist items a person must judge. Exit 1 on any error. **A
   failing check means changing the design or the words, not the rule.**
8. **Iterate** on the config, the strings or the captures (never the PNGs by hand), render again, and repeat
   steps 6 and 7 until the check passes and the sheets look right. Show the user the sheets; taste calls are
   theirs.
9. **Hand to `store-listings`.** The config's `out` is `store-listing.json`'s `screenshots.folder`; target ids are
   its `screens`; shot ids and order are its `screenshots.shots`. Say so, and that `listing.py check` is next.
   Report every fallback (a locale showing the primary's caption or UI), every rule that's unverified, and every
   checklist item left to the user (Play's alt text per screenshot is typed in Play Console).
10. **Suggest a test.** The first shot is the decision that matters most and the evidence is weak: propose
    testing it (or the first three) with Apple's product page optimisation or Play's store listing experiments,
    and checking retention after the install before keeping a winner
    ([references/evidence.md](references/evidence.md)).

## Agent rules

1. **Taste is the user's.** Agree the storyboard (which shots, in what order, what each says) before rendering;
   offer options for brand art, colours and fonts, don't pick them. *Why:* a set rendered on a guess gets thrown
   away, and the brand isn't the agent's.
2. **Look at every picture at full size, and every sheet,** before saying a set is done. An exit code of 0 says
   the sizes and words passed; it can't see a caption over a button, a toast left in a capture or a first shot
   that doesn't sell.
3. **One set per store,** from that store's own rules and the app's rating there, never one set for all.
4. **Fix the design, not the rule.** A caption that doesn't fit gets fewer words, never a floor below the one the
   check enforces. A rule changes only when its store's page says otherwise, upstream, with its source and date;
   relaxing one is the user's choice, with a reason.
5. **Drawn frames only.** Never ship, download, modify, tilt, crop or overlap a maker's device art. A user's own
   Apple bezel goes on an Apple set as it is, or not at all; never on Play.
6. **Flag others' intellectual property; never decide it.** Names, logos, characters, likenesses, awards, press
   quotes, photos and fonts readable in a shot go to the user, with who owns them.
7. **Real UI, invented data.** Shots show the app in use with fictional accounts; nobody's real data, no
   unverifiable claims, nothing a store bans for that store.
8. **Every "+X%" is a hypothesis.** Don't promise a conversion lift; suggest the stores' experiments.
9. **Say what fell back or is unverified:** a locale with the primary's caption or captures, a rule marked
   `unverified`, a store page read long ago.
10. **Don't commit unless asked.** Say what's ready: the config, strings, fonts the user may commit, and the
    rendered folder `store-listings` reads.

## Validation

- The storyboard was agreed by the user before the first `render.py`.
- `render.py` exited 0; `<out>/render-report.json` lists every target × locale × shot the config asks for.
- `check.py` exits 0; each warning was read and either fixed or accepted by the user.
- Every sheet in `<out>/sheets/` and every rendered file was opened and looked at, and what was seen is reported.
- In the search-row mock, each of shots 1 to 3 says what the app is, and its caption's size in points is reported.
- The handoff names the folder, the screens and shot ids `store-listing.json` must have, and every fallback.

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `render.py` exits 1: a caption doesn't fit at its floor | too many words for the slot (often a translation) | shorten the string ([localisation.md](references/localisation.md)); never lower the floor to fit |
| `render.py` or `sheet.py` exits 3: Chrome not found | no Chrome or Chromium | install one or set `CHROME`; nothing renders without it |
| check: size doesn't match | a target's `width`/`height` isn't one the store takes | use the store's exact size ([store-rules.md](references/store-rules.md)) |
| check: capture upscaled | the capture is smaller than it's shown | capture on a bigger device or at a higher scale; never resize |
| check: missing glyphs | the font doesn't cover a locale's script | add a font that does to `theme.fonts` (licensed for it) |
| check: contrast under 4.5:1 | the caption's ink against the pixels behind it | change the palette, add a plate or move the caption off busy UI |
| check: Play text share over 20% | the words cover too much of the picture | fewer words, a smaller caption box, or `caption: false` on Play's tablets |
| check: frame warning on Play | Google discourages device imagery | `stores.google.frame: "none"`, or keep it by the user's choice |
| check: an Apple bezel tilted, cropped or overlapped | the layout breaks Apple's terms for its art | `framed` with the bezel as it is, or a drawn frame |
| check: a forbidden word in a caption | a price, ranking, award or other platform | rewrite the string; relax only by the user's choice with a reason |
| report: `captureFallback` / `stringFallback` | a locale showed the primary's capture or caption | capture or translate it, or tell the user it ships that way |
| A file didn't change after an edit | the cache saw no change in its inputs | `render.py --force` |

## References

| File | What's in it |
|---|---|
| [principles.md](references/principles.md) | the design principles, each with its evidence grade (A to D) and why |
| [store-rules.md](references/store-rules.md) | what the App Store, Google Play, Steam and itch.io allow in screenshots, sourced and dated |
| [layouts.md](references/layouts.md) | each layout, when to use it, its options, who uses the pattern |
| [frames.md](references/frames.md) | why the frames are drawn; the makers' device art and its licences; a user's own Apple bezels |
| [panoramas.md](references/panoramas.md) | a picture across several slots: when, how it renders, seams, risks |
| [localisation.md](references/localisation.md) | text expansion, CJK, right-to-left, fallbacks, captures per locale |
| [legibility.md](references/legibility.md) | thumbnail sizes, the caption-size rule and how to check it, contrast, text share |
| [checklist.md](references/checklist.md) | the pre-ship list: what `check.py` decides and what a person judges |
| [evidence.md](references/evidence.md) | what the conversion evidence is and isn't; how to run a real test |
| [config.md](references/config.md) | every field of `store-screenshots.json` |
| [games.md](references/games.md) | what games do differently |
