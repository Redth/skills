---
name: store-screenshots
description: >
  Use this skill to design App Store or Google Play screenshots for our app, add captions, a device frame,
  a tilt, a callout or a panorama, render one design at every iPhone, iPad and Android size and in every
  language, fit or translate screenshot captions, check whether our screenshots read in search results, say
  what each store allows in a screenshot, plan which shots go first and what each says, make a game's
  screenshots for the stores, find a look from screenshots we like, redo or refresh the screenshots our
  listing has now, or keep this release's screenshots consistent with last time's. Takes real captures (or any tool's PNGs) and renders them with HTML templates
  in headless Chrome. Do not use for capturing from a simulator, emulator or device (store-capture), the
  listing's words or sending it to a store (store-listings), app icons, website images, preview videos, or
  building a screenshot editor.
license: MIT
---

# store-screenshots

Designs and renders store screenshots from an app's real captures: one design, every store, size and locale.
The user agrees the story first; the scripts render it through HTML/CSS templates in headless Chrome, check it
against each store's rules, and draw mock-ups of each store's first impression for the agent to look at. The
output is the folder `store-listings` reads.

## Purpose

- **Start from what's live:** most apps have a listing already. Its current set (pulled by `store-listings`, or a
  folder in the repo) is read shot by shot first: which screen each shows, its words, its look, and what the user
  keeps. The storyboard starts from the shots kept; the look is one example, to keep or move away from.
- **The story before the pixels:** a brief (who it's for, the one core value, what each store allows) and a
  storyboard (shots 1 to N, one message each), agreed with the user before anything renders.
- **One design, every size and locale:** a `store-screenshots.json` (schema `schema/store-screenshots.schema.json`)
  names the layouts, captions, theme and targets; `render.py` lays each shot out in units of the slot's width, so
  a 0.46 iPhone, a 4:3 iPad and a 9:16 Play phone come from the same design.
- **One set per store:** each store's rules (`rules/<store>.json`, dated and sourced) decide what its set may
  carry: frames, words, awards, prices. Play is frameless by default.
- **Drawn frames only:** generic phone, tablet, laptop, desktop, TV and watch frames drawn for this skill. No
  maker's device art is shipped, fetched or modified.
- **Taste first, then kept:** the user's examples, two to four rendered directions, one iterated with them, then an
  approved baseline: a locked `screenshot-style.json` that every later update renders in and is checked against.
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
- "I like how Headspace's screenshots look", "here are some sets we like: make ours feel like that".
- "Redo our App Store screenshots", "our screenshots are old: refresh them", "show me a few directions".
- "Make our screenshots match the ones we did last time", "we added a feature: update the screenshots".

## Inputs

| Input | Where | Notes |
|---|---|---|
| The current set (if the app has a listing) | `existing/<store>/screenshots/<locale>/<slot>/<NN>.<ext>` (`store-listings`' `push.py pull`) or any folder of them in the project, one subfolder per device | read first: [references/current-set.md](references/current-set.md) |
| The brief | the conversation | who the app is for, its one core value, which stores and devices, the app's look (fonts, colours) |
| Captures | `<captures>/<locale>/<capture device id>/<capture screen id>.png` | `store-capture`'s layout; any tool's PNGs renamed into it. At least the size they're shown at |
| `store-screenshots.json` | beside `store-listing.json` usually (`--config`) | every field: [references/config.md](references/config.md) |
| Fonts | files the config's `theme.fonts` names | the app's own, with the user's right to use them; one that covers every locale's script |
| Examples the user likes (and one or two they don't) | `design/inspiration/` | any apps' or games' screenshots they saved; for the style only |
| `screenshot-style.json` | beside the config (its `"style"`) | the look: [references/style.md](references/style.md); starting points in `styles/` |
| A frame of the user's own (optional) | a file the config points at | Apple's bezels only as they are: [references/frames.md](references/frames.md) |

Prerequisites: Python 3.8+ (stdlib only) and Google Chrome or Chromium (`CHROME` overrides where it's found).
No network: nothing is fetched, fonts and frames included.

## Workflow

The scripts are in this skill's `scripts/` folder; run them with `python3`, from the user's project. A first set
goes through all the steps; an update to an approved set is step 8. The design files live under `design/`
([references/baseline.md](references/baseline.md)).

0. **Start from the current set.** If the app has a listing, read its screenshots before designing anything: pull
   them (`store-listings`' `push.py pull` writes `existing/<store>/screenshots/<locale>/<slot>/`) or find the folder
   they're in (a project folder, one subfolder per device). `sheet.py --current <folder> --png` lays them out by store and device, in
   order, and writes a skeleton `design/current.json`. Open each picture at full size and fill in what it shows
   (screen, the caption read off it word for word, the nearest layout, its traits), then what works and what
   doesn't; run `sheet.py --current --png` again and show `design/sheets/current.png`. **The user says** which shots
   to keep, change or drop and whether the look is kept, evolved or replaced; set `confirmedByUser` only on their
   word ([references/current-set.md](references/current-set.md)). No listing yet: say so and start at 1.
1. **Brief.** Ask, or read from the project: who the app is for, the one thing it does better than anything
   else (its core value, in the user's words), which stores and devices it ships on, its look (fonts, colours,
   dark mode), and any claims the user can back up. Read what each target store allows
   ([references/store-rules.md](references/store-rules.md)): Apple takes captions and drawn frames but no
   prices, URLs or Apple-designated awards; Play prefers no frames, words under 20% of the picture, no awards,
   rankings or calls to action; Wear OS takes the interface only.
2. **Inspiration: examples before any design.** Ask for 3 to 6 sets the user likes and 1 or 2 they don't (pictures
   they saved, of any app or game: the scripts fetch nothing). Put them in `design/inspiration/`, describe each in
   `inspiration.json` with what they like and dislike and its traits in the vocabulary
   ([references/style.md](references/style.md)), summarise what they share, and show
   `sheet.py --inspiration --png` (`design/sheets/inspiration.png`). Ask whether the summary is right; set
   `confirmedByUser` only when they say so. The current set (step 0) is one example on the board: to keep, to
   evolve or to move away from, as the user said. If the user has no examples, show them the starting points:
   `sheet.py --styles --png` (`design/sheets/styles.png`) renders every style in `styles/` on one made-up app,
   so they can point at one rather than imagine it.
3. **Storyboard, agreed before rendering.** Propose shots 1 to N as a short table: the capture each uses, its
   one message (a caption of 2 to 5 words, a benefit or a verb), its role or layout, and which stores it goes to.
   With a current set, start from it: the shots kept, in their order, their captions word for word unless marked
   `change`, new shots only where one was dropped or the brief says something's missing, and a column saying which
   rows are kept, changed or new.
   Shots 1 to 3 carry the core value in real UI, because they're what search shows and most people never swipe
   ([references/principles.md](references/principles.md)); on Play that means a UI shot first (the starting
   styles turn their `hero` into the app's screen there). **Don't render until the user has agreed the
   storyboard** (or, asked for directions up front, render drafts: below). For games: [references/games.md](references/games.md).
4. **Captures in.** Check the captures exist for every shot, device and locale the storyboard needs, are big
   enough for their targets, and show the moment each message needs. Look at each one at full size: transient UI
   (a toast, a banner, a spinner, a permission prompt), test or real people's data, a messy status bar, other
   platforms' names or glyphs. If they're missing or wrong, capture first (`store-capture`, or the user's own
   tool) and come back. Then write `store-screenshots.json` ([references/config.md](references/config.md)): the
   targets at each store's exact pixel sizes with ids that are `store-listing.json`'s screen names, the shots in
   order with roles (`hero`, `feature`, `detail`, `accent`), the captions as string keys per locale.
5. **Directions: offer two to four, render only their first shots.** From the confirmed summary, pick 2 to 4
   starting points in `styles/` (or write fresh ones) into `design/directions/<name>/screenshot-style.json`, each
   with the brand's colours and fonts, and render each on one target:
   `render.py --style design/directions/<name>/screenshot-style.json --out design/explore/<name> --shots <first 3>
   --targets <one>`. Show `sheet.py --directions design/explore/a,design/explore/b,... --png`
   (`design/sheets/directions.png`): each direction in the search row with its captions' size in points, and at the
   product page's size. With a current look the user wants kept or evolved, one direction is that look written as
   a style. **The user picks** (or mixes); write the choice in `design/decisions.md`.
6. **Iterate, one change a round.** Copy the chosen style to `screenshot-style.json` beside the config, name it
   there (`"style"`) and take the theme out of the config. Render the whole set: `render.py [--force]`. Each round
   change one thing, render, and show `sheet.py --compare <the previous render> --png` beside the store mocks
   (`sheet.py --png`). Look at every sheet and every file at full size and go through the visual checklist
   ([references/checklist.md](references/checklist.md)); run `check.py` until it has no errors (**a failing check
   means changing the design or the words, not the rule**). Log each decision in `decisions.md`: the date, what,
   and why in the user's own words.
7. **Approve the baseline, when the user approves the set.** `baseline.py approve --note "<their words>"` copies the
   renders, the report and the style into `design/baseline/`, locks the style and logs it. It refuses a render
   report that isn't current, a set with check errors, or a config theme that contradicts the style: fix that, render,
   show the user, approve.
8. **Updates (every later release).** Change the captures, strings, shots or locales, never the locked style.
   `render.py` renders in the locked style; `check.py` compares with the baseline by itself (drift in caption size,
   position and lines, the device's box, frame and tilt, text share, colours, background); `sheet.py --compare
   design/baseline --png` pairs every shot with its baseline; `baseline.py status` says what changed. Show the user
   the compare sheets and every drift warning; they decide which drift is fine. A new look is a new approval: the
   user's reason, `baseline.py unlock --reason "..."`, steps 5 to 7 again.
9. **Hand to `store-listings`.** The config's `out` is `store-listing.json`'s `screenshots.folder`; target ids are
   its `screens`; shot ids and order are its `screenshots.shots`. Say so, and that `listing.py check` is next.
   Report every fallback (a locale showing the primary's caption or UI), every rule that's unverified, and every
   checklist item left to the user (Play's alt text per screenshot is typed in Play Console). Then suggest testing
   the first shot (or the first three) with Apple's product page optimisation or Play's store listing experiments,
   checking retention after the install before keeping a winner ([references/evidence.md](references/evidence.md)).

**When the user asks for directions up front** ("show me a few looks and I'll pick", or a first message that gives
the app, the stores and what they like), don't make them wait three round trips. In one turn: read the current set
(step 0) and write `current.json` with every verdict `null`; draft the brief and the storyboard from it (kept shots in
their order, their captions as they are); write the config's shots from that draft; render 2 or 3 directions for
the first three shots on one target (step 5); show `sheet.py --directions ... --draft --png`, whose page is headed
"Drafts for you to correct". Say plainly what you assumed (the core value, which shots to keep, each caption, the
directions' colours) and ask the user to correct it. It's a draft, not a decision: nothing goes in `decisions.md`,
no direction is chosen, no `confirmedByUser` is set and nothing is iterated, approved or locked until the user has
answered. Their corrections come first in the next round; then steps 5 to 7 as usual.

Exit codes: `render.py` 0, 1 (a render failed or a caption won't fit at its floor: fix the words, not the floor,
[references/legibility.md](references/legibility.md)), 3 (usage, no Chrome); `check.py` 0, 1 (errors), 3;
`sheet.py` 0, 3; `baseline.py` 0, 1 (`status`: the locked style changed), 2 (refused), 3.

## Agent rules

1. **Taste is the user's.** Agree the storyboard (which shots, in what order, what each says) before rendering
   the set; offer options for brand art, colours and fonts, don't pick them. *Why:* a set rendered on a guess gets
   thrown away, and the brand isn't the agent's. The one exception is the batched path: draft directions for the
   first three shots, labelled drafts (`--draft`), when the user asked for directions up front; still nothing is
   chosen, logged, approved or locked without them.
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
10. **Don't commit unless asked.** Say what's ready: the config, strings, fonts the user may commit, the
    `design/` folder (the baseline goes in with the project), and the rendered folder `store-listings` reads.
11. **Ask for examples before designing.** The user's taste comes from sets they point at, not the agent's
    guess; with none, the starting points in `styles/` serve as examples, shown as pictures (`sheet.py --styles`).
12. **Offer directions, not one take.** Two to four, rendered only as far as their first shots on one target, side
    by side on the directions sheet. **The user picks**; the agent may recommend, with a reason.
13. **Log decisions in the user's words.** Each choice (a direction, a change, an approval, an unlock) goes in
    `design/decisions.md` with its date, quoting or closely paraphrasing them, so the next update knows why.
14. **Never edit a locked style unasked.** A request that would change the look (a bigger caption, another colour,
    a new layout) on a locked style is a new approval: say so, ask whether they want a new look, and only on their
    yes `baseline.py unlock --reason "<their reason>"`, explore, and approve again. Never unlock on your own
    judgement, or to make a check pass.
15. **On every update, run the baseline check and show the compare sheet.** Report each drift warning and let the
    user decide; never hide drift by loosening the style's `drift` tolerances without them.
16. **Start from the current set.** When the app has a listing, read its screenshots (`sheet.py --current`) before
    proposing a storyboard or directions; keep what the user keeps: a caption they like stays word for word, a
    kept screen stays in its place. Propose verdicts, never set them for the user. *Why:* the live set holds
    decisions someone already made; starting blank throws them away.
17. **Treat the current look as one example.** It goes on the inspiration board beside the user's others; whether
    the new set keeps, evolves or replaces it is the user's call (`summary.look`).
18. **Examples inform the style only.** Describe what an example does in the traits vocabulary; never copy its
    logos, marks, illustrations, characters, photos, wording or trade dress, and never put another app's name or
    art in the user's set. The starting styles name public apps only as where a pattern was seen.

## Validation

- With a listing, the current set was read first (`design/current.json`, `design/sheets/current.png`), each shot's
  verdict and the look came from the user, and the storyboard started from the shots kept.
- The user was asked for examples (or shown the starting points, `sheet.py --styles`) before any design, and
  confirmed the summary.
- Directions rendered before the storyboard was agreed were shown as drafts (`--draft`) and nothing was chosen
  from them without the user.
- Two to four directions were rendered (first shots only) and the user picked one; the choice is in
  `design/decisions.md`.
- The storyboard was agreed by the user before the first `render.py` of the set.
- The approved set has a baseline (`design/baseline/baseline.json`) and a locked style; on an update, `check.py`
  compared with it and the compare sheets were shown.
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
| `baseline.py approve` exits 2: report not current | the config, style, strings or captures changed since the render, or a file changed on disk | render again, show the user, approve |
| check: the locked style changed | someone edited the approved look | put it back (`design/baseline/screenshot-style.json`), or a new approval with the user |
| check: a config theme key against a locked style | the config sets what the style owns | remove it from the config |
| check: baseline drift | a caption shrank, ran longer or moved; the device moved; a colour changed | show the compare sheet; fix the words, or the user accepts it |
| check: Play's UI first, on a `hero` | a brand-and-claim shot among Play's first three | give the style's hero role a Play layout (`roles.hero.stores.google.layout`, as the starting styles do), or start Play's set with a UI shot |
| `sheet.py --current`: no pictures | the folder is empty or holds another format | pull the listing first, or name the folder the PNG/JPEG/WebP files are in |
| `sheet.py --current`: current.json doesn't match | a field outside the vocabulary (a layout, a trait, a verdict) | use the words in the schema; `null` for not known yet |
| `sheet.py --styles` exits 3 | no Chrome | install one or set `CHROME`; the styles are rendered, not shipped as pictures |
| render: a role the style doesn't have | the shot's role isn't in the style's `roles` | use one of its roles, or give the shot a layout |

## References

| File | What's in it |
|---|---|
| [current-set.md](references/current-set.md) | reading the listing's current set first: `sheet.py --current`, `current.json`, what it feeds |
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
| [style.md](references/style.md) | the style file, the traits vocabulary, the starting points in `styles/` and the numbers behind them |
| [baseline.md](references/baseline.md) | inspiration, directions, decisions, approving a baseline, the drift check and its tolerances |
| [games.md](references/games.md) | what games do differently |
