# The storyboard

Agree this with the user before anything is recorded. A preview is a 15 to 30 second story with the sound off:
what the app is, the one thing it does best, how it feels to use, and what it costs to start.

## Beats

Three to five beats, each **one idea**, shown by **one moment** of the app and said by **one headline**:

| Field | What it is |
|---|---|
| beat | a name for the edit's marks (`plan`, `recipe`, `shop`) |
| headline | 2 to 5 words over two short lines; one or two words in the accent colour (`[whole week]`) |
| moment | the screen and what happens on it: a tap, a drag, typing, a scroll, a result appearing |
| camera | floating (the headline reads) or pushed in (the hands-on moment reads) |
| emphasis | a touch hotspot, a spotlight on one element, or nothing |
| length | 3 to 7 seconds; the headline readable for at least 1.5 s |

- **The core value in the first beat.** Search shows the first seconds muted; most people never get to beat 4.
- **Open composed.** The first frame is a finished picture: the headline already in place (an overlay's `in`
  before 0, e.g. -1.0) and the app settled. It may be the first thing someone sees.
- **The poster frame (5 s by default) sells on its own:** put a beat's payoff there: a result, a highlighted
  element, a headline fully in. Check frame 150 (at 30 fps) as a still.
- **Real flows, real speed.** A beat is what a person does, at their pace: typing at 4 to 6 keys a second,
  scrolling as a thumb scrolls. Cut away dead time with holds and steps, not by speeding up motion.
- **One place per beat.** A headline over a moving screen is two ideas at once; move the camera between beats,
  not within one.
- **The end card** (2 to 3 s): the app's mark, its name, who makes it, a tag line, and the disclosure in plain
  words (an account requirement, what a subscription adds). Nothing to tap, no price.

## Headlines

- Benefit, not feature: "Plan the whole week", not "Weekly planner view".
- The same voice as the screenshots' captions; reuse one if it fits.
- Never a price, a date, "new", "#1", or another platform. No exclamation marks.
- Every headline gets one shared size: the largest at which every line of every headline fits on one line
  (`headSize` caps it). A long line shrinks them all, so keep lines short and even.

## A worked storyboard (Sample Recipes)

| # | beat | headline | moment | camera | emphasis | ~s |
|---|---|---|---|---|---|---|
| 1 | plan | Plan the [whole week] | the week's plan, a meal dragged to Thursday | float, then push in for the drag | touch hotspot on the drag | 0–10 |
| 2 | recipe | Every recipe, [step by step] | a recipe opens; the ingredients card | slide in, float, push a little | spotlight on the ingredients card | 10–19 |
| 3 | shop | The list [writes itself] | the shopping list fills as the week is planned | dissolve, push in | none | 19–23 |
| end | | A week of meals, [planned in minutes] | the mark, name, by, tag line, "Free to download. Sign-in required to sync. Premium features available by subscription." | screen sinks away | | 23–26 |

Poster frame: 5 s, beat 1 pushed in on the plan. `examples/sample-edit.json` is this storyboard as an edit.
