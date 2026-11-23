---
name: store-previews
description: >
  Use this skill to make an App Store app preview or a Google Play promo video for our app from real
  recordings of it: plan the storyboard (which moments, in what order, what each says), record the takes,
  pick the frames, and compose the video with headlines, touch hotspots, a spotlight on one element, a
  drawn device frame, slides and dissolves, and an end card with the account and subscription disclosure;
  make one for every iPhone and iPad size, a foldable folded and open, or check a preview against Apple's
  rules (15 to 30 seconds, sizes, what may be shown). Renders every frame in headless Chrome from an edit
  file, then encodes it to spec. Do not use for still screenshots (store-screenshots), capturing stills
  (store-capture), the listing's words or sending it (store-listings), a marketing film with filmed
  hands or devices, music, or a video editor.
license: MIT
---

# store-previews

Composes store preview videos from an app's real recordings. The user agrees a storyboard first; `store-capture`
records each take (`capture.py --record`) and dumps its frames (`video.py frames`); an edit file
(`schema/preview-edit.schema.json`) says which frames show when and what moves over them; `compose.py` draws every
frame in headless Chrome as a pure function of its number and joins them into a master; `store-capture`'s
`video.py encode` and `check` bring it to each store's spec.

## Purpose

- **The story before the frames:** one idea per beat, the app's core value in the first seconds, a poster frame
  that sells on its own, the disclosure at the end; agreed with the user before anything is recorded
  ([storyboard.md](references/storyboard.md)).
- **Only the app, shown honestly:** real captures of the app in use, with the overlays Apple allows: headlines,
  touch hotspots, a spotlight, simple transitions; nothing the app doesn't do
  ([apple-previews.md](references/apple-previews.md)).
- **Calm motion that reads:** the screen floats on the background for each headline and pushes in for hands-on
  moments (never past the whole device), slides sideways between parts, eases every move; headlines rise through
  masks and leave faster ([motion.md](references/motion.md)).
- **Cut by frame, not by time:** simulator recordings' timestamps don't follow the clock, so every take is dumped
  to numbered frames and the edit names frames: held, played, stepped, marked ([editing.md](references/editing.md)).
- **The screenshots' look:** the locked `screenshot-style.json` from `store-screenshots` gives the palette, font
  and background, and the same drawn device frames, so the video and the stills match.
- **Every device the store shows:** iPhone, iPad, and a foldable's cover and open displays in one video, panned a
  pane at a time ([devices.md](references/devices.md)).
- **Looked at, not assumed:** stills of the key frames first, then the whole video watched through, then
  `video.py check` ([checking.md](references/checking.md)).

## Non-goals

- **Still screenshots.** That's `store-screenshots`.
- **Recording or encoding.** That's `store-capture` (`capture.py --record`, `video.py frames|encode|check`); this
  skill composes between the two.
- **Filmed hands, devices, people, or a marketing film.** Apple's previews show the app; a brand film is another
  job.
- **Music or narration.** The master is silent; `video.py encode` adds the silent track Apple wants. A soundtrack
  the user brings and licenses can be muxed on after; say so, don't pick one.
- **An interactive editor.** The edit is a JSON file the agent and the user change together, looking at stills.
- **Sending.** `store-listings` puts previews on the listing.

## When to use

- "Make an App Store preview / app preview video / Play promo video for our app."
- "Our preview is old / the app changed: redo it." "Make one for the iPad / the foldable too."
- "Add a headline / a tap / a highlight / an end card to our preview." "The zoom is too much." "It's choppy."
- "Does our preview meet Apple's rules?" "What may a preview show?"

## Inputs

- The app, with a screenshot mode or staged demo data (the same staging `store-capture` uses: an invented account
  and data that looks in use).
- `store-capture`'s plan, with the takes as screens recorded with `--record`, and their typing `rate`.
- The screenshots' locked style (`design/baseline/screenshot-style.json`), or colours, a font and a background
  from the user.
- The app's icon or mark for the end card, and the disclosure's facts: whether an account is required and which
  features are in a subscription.
- Chrome or Chromium; ffmpeg and ffprobe.

## Workflow

1. **Read the rules and the current preview.** What's live (a listing's `existing/` from `store-listings pull`),
   Apple's rules ([apple-previews.md](references/apple-previews.md)) and which slots need a preview. A preview
   is optional; say what it costs to keep up.
2. **Storyboard with the user** ([storyboard.md](references/storyboard.md)): three to five beats in 15 to 30 s,
   each one idea and one headline (2 to 5 words), the moment it shows, and what moves; the poster frame; the end
   card's words and disclosure. Show it as a table and **stop for agreement**.
3. **Record the takes** with `store-capture`: one screen per take in the capture plan, recorded with
   `capture.py --record --devices <id> --screens <take>`, typing at a person's pace (`rate` 4 to 6 keys a second),
   drags with a `hold`. Dump each take: `video.py frames <take>.mov frames/<device>-<take> --width <stage width>`
   (a foldable's open display: `--size` its landscape shape) ([devices.md](references/devices.md)).
4. **Pick the frames** ([editing.md](references/editing.md)): open the frames around each beat, note the settled
   frame to hold and the first and last frame of each motion; measure the spotlight's element from the pixels.
5. **Write the edit** (`edit.json`, [edit.md](references/edit.md); start from `examples/sample-edit.json`):
   segments with `hold`/`play`/`mark`, slides between parts, the camera and pan keys, the overlays at marks, the
   end card. `compose.py edit.json --dry-run` until its length is in 15 to 30 s and every frame is found.
6. **Look at stills first:** `compose.py edit.json --frames <the first frame, each beat's key frame, each
   transition's middle, the end card> --stills`, and open each at full size. Show the user; change the edit.
7. **Render and encode:** `compose.py edit.json` (every frame, then `<out>/<name>-master.mp4`), then `video.py encode
   <master> --slot APP_IPHONE_67 --out preview-iphone.mp4` (or `--size 886x1920`) and `video.py check`.
8. **Watch it through** at full speed ([checking.md](references/checking.md)) and send the user the encoded file
   with stills of the key moments. Their approval decides; nothing is uploaded here.

## Agent rules

1. **The story is the user's.** Agree the storyboard (beats, headlines, the poster frame, the end card's words)
   before recording; offer options, don't pick. *Why:* a preview recorded on a guess is recorded again.
2. **Only the app, as it is.** No filmed hands, devices or people; no features, data or speed the app doesn't
   have; nothing from another app. Overlays explain; they never mock up UI. *Why:* App Review rejects previews that
   show more than the app (Guideline 2.3.4).
3. **Invented data, staged as in use.** The same rules as the screenshots: no real person's account or data, no
   prices, dates or seasonal words in a headline; times in the app look recent.
4. **Disclose.** An account requirement and subscription features go on the end card in plain words; never hide
   them in a blur or a flash.
5. **Never past the whole device.** A push-in stops where the device's frame still fits the stage (`full` about 0.8
   for a phone at the stage's width); no zoom into a detail. *Why:* Apple advises against zooming, and a cropped
   frame reads as a cheap cut.
6. **Cut by frame index, never by a recording's time.** Dump every take with `video.py frames` and name frames.
7. **Measure from pixels.** A spotlight's rect and a touch's point come from the dumped frames, not the UI tree's
   points or a guess; re-measure after a new take.
8. **Stills before the render, the whole video after.** An exit code of 0 says every frame was drawn; it can't see a
   headline over the app, a touch off its button or a jump between takes.
9. **Re-pick frames after any new take.** The moments move; an old edit on a new take shows the wrong frames.
10. **Don't upload or commit unless asked.** Say what's ready: the edit, the master, the encoded files, the stills.

## Validation

- The storyboard was agreed by the user before recording; the poster frame (5 s unless set) shows a beat that
  sells.
- `compose.py --dry-run` exits 0: 15 to 30 s, every frame found, every mark resolved.
- Stills of the first frame, each beat and each transition were opened at full size and shown to the user.
- `video.py check` exits 0 for each slot's file; the encoded file was watched through at full speed.
- The end card discloses the account and subscription facts the user gave.
- No real names, prices or dates on screen; the data is the invented demo data.

## Failure modes

| Symptom | Meaning | Do |
|---|---|---|
| `compose.py` exits 3: frame files missing | the take wasn't dumped, the folder or `framePattern` differs, or a frame number is past the take's end | dump with `video.py frames`; check `framePattern`; re-pick numbers |
| exits 3: no mark named … | a time names a mark no segment sets (or a typo) | add the `["mark", name]` or fix the name |
| exits 3: keys must run forward | a camera or pan key resolves earlier than the one before | reorder, or move the marks' offsets |
| `--dry-run` warns: outside 15–30 s | the edit is too short or long | change holds; `video.py encode` refuses it otherwise |
| exits 3: Chrome not found / no ffmpeg | missing tools | install them, or set `CHROME` / `FFMPEG` |
| a hold jumps or a beat shows the wrong moment | a recording cut by time, or an old edit on a new take | dump frames; re-pick the numbers from the new frames |
| typing appears all at once or jerks | a `type` step without `rate`, or frames stepped through typing | record with `rate` 4–6; `play` typing with step 1 |
| a drag doesn't happen in the take | the automation's drag didn't hold first | a `hold` before the move in the capture step ([editing.md](references/editing.md)) |
| the screen's corners leak or flicker while it moves | corners clipped with `border-radius` + `overflow` | the template clips with `clip-path`; keep it if you change the template |
| the spotlight's hole is off the element | the rect was guessed or measured on another take | measure from the dumped frame's pixels; `pad` for the margin |
| the spotlight's margin looks uneven at the corners | the hole's radius isn't the element's radius plus `pad` | set `r` to the element's own radius; compose.py adds `pad` |
| a foldable's open display looks squeezed | a rotated recording dumped at its portrait size | `video.py frames --size <landscape WxH>` |
| a headline wraps or is tiny | one line too long for the stage | fewer words per line; every headline shares the size the longest allows |
| the recording stops early | something rebooted or shut down the simulator mid-take | record with `capture.py --record` (it records only while the steps run) |
| a "2 days ago" or stale time in a take | demo data seeded long before recording | re-seed right before recording |

## References

| File | What's in it |
|---|---|
| [apple-previews.md](references/apple-previews.md) | Apple's preview rules and specs, Play's promo video, sourced and dated |
| [storyboard.md](references/storyboard.md) | beats, headlines, the poster frame, the end card, a worked storyboard |
| [motion.md](references/motion.md) | the camera, transitions, headline and spotlight animation, timing numbers and why |
| [editing.md](references/editing.md) | recording takes for an edit, dumping frames, picking and measuring, marks |
| [edit.md](references/edit.md) | every field of the edit file |
| [devices.md](references/devices.md) | sizes per slot, drawn frames per device class, iPad, foldables folded and open |
| [checking.md](references/checking.md) | stills, watching it through, `video.py check`, what a person judges |
