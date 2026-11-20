# Start from the current set

Most apps already have a listing. Its screenshots are the best first draft there is: the screens someone chose, in an
order someone chose, with words that may already work, in a look people may already know. So before any design, read
the set the app has now, shot by shot, and decide with the user what to keep. The storyboard starts from what they
keep; the look is one example among the ones they like, to keep or to move away from.

Skip this only for an app with no listing yet (and say so).

## Where the current set comes from

| Where | Layout | How it gets there |
|---|---|---|
| The live listing | `existing/<store>/screenshots/<locale>/<slot>/<NN>.<ext>` | `store-listings`' `push.py pull` (it reads, never writes, the stores) |
| A folder in the repo | anything, e.g. `assets/screenshots/<device>/Screenshot-NN.png` | already there |
| Pictures the user saved | a folder they name | the user (the scripts fetch nothing) |

`sheet.py --current <folder>` takes any of them. Pictures are grouped by the folder they're in and put in order by
the number in their names (`Screenshot-2` before `Screenshot-10`); a pulled listing's groups are its store, locale
and slot, App Store first, and pictures elsewhere in it (an icon, a feature graphic) are left out. PNG, JPEG and WebP.
Read the primary locale's set first; another locale's set matters only where its words or screens differ.

## The sheet and `design/current.json`

```sh
sheet.py --current existing --png       # or: --current assets/screenshots
```

The first run writes a skeleton `design/current.json` (every picture, its group and its order; the rest empty) and
`design/sheets/current.png`: each group's first three at about search-row size, then every shot beside its analysis.
Open each picture at full size, fill the file in, and run `sheet.py --current --png` again (without a folder it reads
`current.json`'s `source`); the sheet now shows what you wrote, for the user to correct.

```json
{
  "version": 1,
  "source": "existing",
  "shots": [
    { "file": "apple/screenshots/en-US/APP_IPHONE_67/01.png", "group": "apple/en-US/APP_IPHONE_67", "order": 1,
      "screen": "this week's meal plan", "capture": "plan", "caption": "Plan a week of meals\nin minutes",
      "layout": "framed-bleed", "traits": { "captionWeight": "heavy", "background": "brand-colour" },
      "verdict": "keep", "notes": "the words customers quote back in reviews" },
    { "file": "apple/screenshots/en-US/APP_IPHONE_67/02.png", "group": "apple/en-US/APP_IPHONE_67", "order": 2,
      "screen": "settings", "capture": null, "caption": "Customise everything", "layout": "framed",
      "traits": {}, "verdict": "drop", "notes": "a settings screen sells nothing" }
  ],
  "summary": {
    "traits": { "captionPosition": "top", "captionWeight": "heavy", "device": "realistic", "mood": "bold" },
    "look": "evolve",
    "whatWorks": ["one bold line a shot", "the brand's green"],
    "whatDoesnt": ["shot 2 is settings", "the captions are 8 pt in search"],
    "notes": null,
    "confirmedByUser": true
  }
}
```

The schema is `$defs/current` in `schema/screenshot-style.schema.json` (it shares the traits vocabulary).

| Field | What goes in it | Whose |
|---|---|---|
| `screen` | which screen of the app it shows, in plain words; `null` for art with no app in it | the agent's reading |
| `capture` | the capture screen id that shows that screen now (once the captures exist) | the agent's |
| `caption` | the words on it, read off the picture exactly (a second line after `\n`); `null` for none | the agent's reading |
| `layout` | the nearest of the skill's layouts ([layouts.md](layouts.md)); a plain screenshot with no words or frame is `gameplay`; `null` and a note when none is near | the agent's |
| `traits` | the look in the vocabulary ([style.md](style.md)) | the agent's |
| `verdict` | `keep` (this screen and these words), `change` (the screen or the words), `drop` | **the user's** |
| `summary.whatWorks`, `whatDoesnt` | what the agent sees and the user says, in plain words | both |
| `summary.look` | `keep` the look, `evolve` it, or `replace` it | **the user's** |
| `summary.confirmedByUser` | set only when the user agrees the reading | **the user's** |

Read with the shopper's eyes too: are shots 1 to 3 the core value in real UI? Do the captions reach about 11 pt in
search (the sheet's strip shows them at that size)? Does anything break a store's rules now (a price, an award, a
device frame on Play)? Write those in `whatDoesnt`; they're reasons to change, not the user's verdicts.

## What it feeds

- **The brief.** The current captions say what the team thought the core value was; ask whether it still is.
- **The storyboard.** Start from the shots kept, in their order, with their captions as they are (a caption the user
  likes is kept word for word; rewrite only the ones marked `change`). Fill the dropped slots with the screens the
  brief says are missing. Show the table with a column for where each row came from (kept, changed, new).
- **Inspiration.** The current set is one example on the board (`sheet.py --inspiration` shows it first when
  `current.json` exists). With `look: keep`, one direction is the current look written as a style (the nearest
  starting style, its numbers moved to what the set measures), rendered beside the others so the user compares like
  for like; with `replace`, its traits are what to move away from.
- **Live and new, side by side.** Once something is rendered, `sheet.py --compare current --png` (or `--compare
  <the live folder>`) puts each new shot beside the live one it replaces: the live set's pictures as they are (no
  render report needed), the target matched to the live group of its slot or device (a pulled listing's display
  type, else a folder named for it, else the same kind of device), each shot paired by the screen it shows
  (`current.json`'s `capture` or `screen`), else by its place. The live words and the user's verdict are under each
  pair. Groups come App Store first, iPhone before iPad.
- **Updates later.** None: once a baseline is approved, the baseline is the reference ([baseline.md](baseline.md)).

## Rules

- The verdicts and the look are the user's. Propose them ("I'd keep 1 and 3, drop the settings shot"), never decide
  them; leave `verdict` `null` and `confirmedByUser` false until they say.
- Read the words off the pictures as they are; don't tidy them. A caption you can't read at full size is a finding.
- The current set is the user's own: its words and art may be reused. Someone else's set is inspiration only.
- Pulled files stay where the pull put them; never edit or re-upload them from here.
