# Games

What games' store sets do differently, from 12 top games on the US App Store on 2026-11-14 (a small sample of
what's current) and the stores' rules.

## What they do

- **Key art or a logo first** (7 of 12), then gameplay. Clash Royale opens with a key-art poster, then four wordless
  arena shots; Call of Duty a logo and a soldier, then gameplay with the HUD hidden; Monopoly GO a mascot, then
  gameplay under a ribbon of one-word verbs.
- **Gameplay big:** full-bleed (Clash Royale, Candy Crush, Royal Match, Call of Duty, Alto's Odyssey, Stardew
  Valley, Minecraft) or inset with characters breaking out of the frame (Brawl Stars, Genshin Impact, Pokémon GO,
  Marvel Snap). **No realistic device bezel in any of them.**
- **Captions:** none at all (4 of 12), or 1 to 4 word imperatives in heavy display type, mostly in a band at the
  bottom ("SAVE THE KING!", "BUILD ALMOST ANYTHING!"). A bottom band suits portrait games whose board sits
  mid-screen; put the words where the play isn't.
- **The HUD:** kept where it explains the game (an elixir bar, moves left, a toolbar), hidden where the view sells
  it.
- **Orientation follows the game:** portrait games show portrait shots; landscape games landscape.
- **A story by verbs:** "ROLL! BUILD! STEAL! ATTACK!" makes a set scannable at a glance.

## Layouts for games

- `fullbleed` with a 1 to 4 word caption, plate at the bottom (or the top if the HUD lives at the bottom).
- `gameplay` with no words: the purest, and what Steam wants.
- `hero` for a key-art first shot, with a sliver of real play in it.
- No `framed` or `tilt`: a frame shrinks the play, and no top game uses one.

## Rules games trip on

- **Apple 2.3.3:** "merely the title art" isn't a screenshot. A key-art first shot is fine only when more than half of
  the set is the game being played. iOS 27's header and search asset are the sanctioned place for key art.
- **Apple 2.3.8 and the asset guidance:** every shot fit for 4+, whatever the game's rating. Action yes; no gore, no
  weapons "pointed directly at a person or the audience". Choose the moment, or the camera angle, accordingly.
- **Play's "no calls to action":** no "Play now" (one top game's App Store set has one; Apple only asks not to fill
  a whole asset with them).
- **Play's featuring:** games are eligible for the large recommendation cards with 3 landscape 16:9 shots of at
  least 1920×1080, or 3 portrait 9:16 of at least 1080×1920. Make the Play target that size.
- **Characters and music art:** licensed characters, real players, real teams, brands in the game's world: flag each
  to the user (Play asks for permission for third-party characters; Apple 2.3.9 for rights to everything shown).
- **A drawn tutorial hand** is in-game UI, not a finger on a device: fine.

## Steam and itch.io

- **Steam:** at least 5 screenshots, 16:9, at least 1920×1080, gameplay only, no words, no awards; at least 4 flagged
  suitable for all ages. Hovering the capsule shows the first four: make them four parts of the core loop. These are
  the captures themselves (version 0.1 renders no Steam target): check them against
  [store-rules.md](store-rules.md#steam-for-reference-no-rules-data-yet) by eye.
- **itch.io:** gameplay, in the page's narrow right column; the cover (630×500) is the shot that's seen in browsing.

## Capturing a game

Staged moments (a goal, a combo, a boss) are worth the effort: one great frame beats five ordinary ones. They
break as the game changes, though: whatever stages them needs a way to tell it reached the moment, and the agent
must look at each capture before rendering (a menu, a loading screen or a paused overlay is easy to catch by mistake).
