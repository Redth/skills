# Motion

Calm beats clever. Every move eases in and out, nothing bounces, and nothing moves while a headline is being
read. The numbers here are the template's and `compose.py`'s defaults; they came from looking at many renders and
cutting what drew the eye away from the app.

## The camera

- **Two places only:** floating (`k` 0: the device at `float.scale`, centred at `float.cy`, the headline above
  it on the background) and pushed in (`k` 1: the device at `full`, centred on the stage). Keys are
  `[time, k]`; between keys `k` eases with an in-out quartic, so a move starts and lands softly.
- **Never past the whole device.** `full` keeps the frame's edges on the stage (about 0.8 for a phone at the
  stage's width). A push into a detail crops the frame and reads as a cut; use a spotlight instead.
- **Move between beats, not during them.** A push-in takes 0.8 to 1.2 s and lands before the interaction starts;
  the pull-back starts after it ends.
- **The background moves a little with the camera** (a 2% dolly when pushed in, a slow drift), so the stage
  never looks frozen; the device's shadow scales with it.

## Between parts

- **Slide** (`{"slide": 0.8 to 1.0}`): the outgoing screen holds its last frame and leaves left, the next arrives
  from the right, a small dip in depth (2%) and a touch of blur at the fastest point. Use it between beats: it
  says "and next".
- **Dissolve** (`{"dissolve": 0.3 to 0.6}`): the next frames fade in over the last ones on the same device. Use
  it inside a beat to cut dead time between two takes of the same screen.
- **A take's own motion is the best transition:** a tap that opens a screen, played as recorded, needs nothing.

## Headlines

- Each line rises out of its own mask (an out-expo ease over 0.9 s), de-blurring and settling its letter-spacing
  from slightly open to slightly tight; the second line follows 80 ms later.
- They leave up through the mask, faster (an in-cubic over 0.42 s); a leave starts 0.42 s before `out`.
- They sit on the background, never over the app; the device floats below them.

## The spotlight

- Dims everything but one element (`dim` 0.5 by default) with a hole the element's rect grown by an even margin
  `pad` all round, its corners concentric with the element's (radius `r + pad`), so the margin is the same along
  the edges and round the corners.
- It fades in over 0.8 s while the margin closes from 60 px wider, like a lens focusing, and fades out over the
  last 0.4 s before `out`.
- Only on a still or near-still moment; never on a panned screen.

## Touch hotspots

- A white ring that fades in over 0.2 s from `in` (a few tenths before `press`), shrinks a little on the press, sends out a wave, and lets go
  after `hold`. A drag moves it from `at` to `to` (`moveIn`, `moveFor`) with the finger down.
- Put the press on the frame the app reacts, not before; measure the point from the frames.

## The end

- At `endOut` the device sinks and fades (0.9 s); from `end.in` the end card builds on the background: the mark,
  then the name, the by-line and tag lines rising like headlines, the fine print last. Start `end.in` about
  halfway through the sink.
- Hold the finished card at least 1.5 s.
