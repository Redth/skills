# Recording takes and picking frames

## Recording

A **take** is one screen of `store-capture`'s plan recorded while its steps run: the same app, staging and devices
as the screenshots, a few takes instead of the stills.

```sh
python3 <store-capture>/scripts/capture.py --plan preview-plan.json --devices iphone-6.9 --screens take-plan --record
```

- **One take, one beat or two.** Short takes are easy to redo when the app changes.
- **Let it settle.** Start each take with a second or two on the settled screen and end with one; holds come from
  those frames.
- **Type at a person's pace:** a `type` or `fill` step with `rate` 4 to 6 keys a second. A value put in at once
  reads as a jump.
- **Drag with a hold:** a slider or handle often needs the finger down before it moves (`swipe` with `hold`, in
  ms); without it the gesture scrolls the page instead.
- **Fresh data:** seed right before recording; data seeded hours earlier shows "2 days ago" where the stills said
  "today".
- **Keep the user's devices out of it:** the plan's own `appstores-*` simulators and emulators, and their own
  automation ports.

## Dumping frames

`store-capture`'s `video.py frames` writes every recorded frame, in order, as `frame-00001.jpg`, … (simulator
recordings' timestamps don't follow the clock, so nothing here cuts by time):

```sh
python3 <store-capture>/scripts/video.py frames raw/iphone-take-plan.mov frames/iphone-take-plan --width 886
```

Dump at the width the footage shows at, or the stage's width (886 for an iPhone preview); the edit's `footage.w`
and `h` are the dumped frames' size. A foldable's open display recorded rotated may come out squeezed: force its
landscape shape with `--size` ([devices.md](devices.md)).

## Picking

Open the frames around each beat (a contact sheet of every 10th frame finds them fast, then each frame near a
change) and write down:

- the **settled frame** to hold before the moment (the screen still, nothing loading);
- the **first and last frame** of each motion: the tap's reaction, the transition, the typing, the scroll;
- **dead stretches** to cut: hold the frame before and resume after, or `play` with a `step` (1.5 to 2) through a
  long uneventful scroll; never step through typing or a tap's reaction.

Then the segment's ops:

```json
{"frames": "frames/iphone-take-plan", "ops": [
  ["mark", "open"], ["hold", 1, 2.6],
  ["mark", "plan"], ["play", 1, 150],
  ["mark", "drag"], ["play", 151, 240], ["hold", 240, 1.2]
]}
```

`hold` repeats one frame for that many seconds; `play` shows frames a to b one an output frame (30 a second, as
recorded), or every `step`-th; `mark` names the time reached, for the overlays and the camera to refer to.

## Marks

Times in the edit are seconds or `@mark`, `@mark+0.4`, `@mark-0.6`. Prefer marks: when a hold changes length,
everything after it moves with it. A mark inside a segment that follows a transition counts from the overlap, so
`@recipe` is when the recipe screen's first frame starts sliding in.

## Measuring

- **A touch point:** the pixel centre of the control in the dumped frame where the press happens (footage
  pixels, not the UI tree's points, which differ by the screen's scale).
- **A spotlight's rect and radius:** find the element's edges in the frame (a contact sheet with a grid, or an
  image tool's cursor): `[x, y, w, h]` of the card itself and its own corner radius `r`. `pad` adds an even margin.
  Measure on the frame the spotlight shows; re-measure after a new take.

## After the app changes

Record the takes again, dump them again, and **re-pick every frame number** (the moments move); the headlines,
marks and camera keys usually stay. `compose.py --dry-run` catches numbers past a take's end, not wrong moments:
look at the stills.
