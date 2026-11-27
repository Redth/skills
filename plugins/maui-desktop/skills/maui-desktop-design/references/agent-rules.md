# Rules for the agent

Ranked by what breaking them costs. Each says why.

1. **Taste is the user's.** Propose a direction (character, neutrals, accent, density, how far each platform
   adapts) with reasons, and stop for agreement before writing tokens. *Why:* a palette is cheap to change before
   it's in every file and expensive after.
2. **Every colour, size and duration comes from `design/tokens.json`.** Never hand-write a value a generator owns,
   in CSS, Razor or native code. *Why:* two hand-kept copies drift; one reference app shipped a purple native title
   bar over a blue web accent because the token system stopped at the web view's edge.
3. **Fix the token, not the gate.** A failing contrast pair means a different token, or an exception the user
   agrees to with its reason and the control that compensates. Never lower a rule's minimum to pass. *Why:* a
   relaxed gate stops protecting anyone.
4. **Platform differences live in tokens and run-time overrides, never in page styles.** *Why:* a page-level
   platform hack is invisible to the next design change and to every other page.
5. **Use the real platform control in chrome; never imitate native chrome in web content.** *Why:* real controls
   follow the OS's redesigns for free; imitations age the day the OS changes.
6. **An existing app adopts by ratchet.** Capture what exists, swap the source, baseline the lint, then clean file
   by file. *Why:* a big-bang restyle can't be reviewed and blocks every other change.
7. **Validate in light and dark, on every platform the app ships, at the seams.** *Why:* the seams are where a
   hybrid app gives itself away, and each platform's web engine differs.
8. **Never edit a generated file.** Edit the source and regenerate. *Why:* the next build overwrites the edit, and
   `--check` fails until then.
9. **Check icon names.** SF Symbol and Adwaita names in the template are best-effort; confirm each one the app
   uses exists for the OS versions it supports. *Why:* a missing symbol renders nothing, silently.
10. **Don't commit unless asked.** Say what's ready: the sources, `DESIGN.md`, tracked generated outputs.
