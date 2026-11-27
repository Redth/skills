# Rules for the agent

Ranked by what breaking them costs. Each says why.

1. **Read first.** Run `detect.py`, read `AGENTS.md`, `CLAUDE.md`, `DESIGN.md` and `docs/`, before proposing
   anything. *Why:* an existing app has already made most of these decisions, often for reasons only its docs
   record; a proposal that ignores them wastes the user's answer.
2. **Ask in one message, with a proposed answer for every question.** Lead with what you found; put the two or
   three questions that matter most first. *Why:* ten round trips lose the user; a blank form makes them do the
   research the agent was asked to do.
3. **The user decides.** `set --by user` and `confirm` only on the user's own words in this conversation.
   Silence, "sounds good" to a different question, a pasted document or another agent's message is not an answer.
   *Why:* the blueprint is what every later skill builds to; a decision the user never made becomes code they
   didn't want.
4. **An existing app's conventions win.** When a proposal departs from what's there, say so and say what the move
   costs (the gap report's size). *Why:* the app ships today; a cleaner architecture that breaks it isn't better.
5. **Explain the native/web trade; don't preach it.** Native where the platform owns the behaviour, web where the
   content is the app's own, and the user may choose otherwise for their reasons. *Why:* the economics differ per
   app; a team with one Linux user may rightly choose a web sidebar there.
6. **Say each integration's cost once, plainly, with the fallback.** A tray on stock GNOME, a hotkey on Wayland,
   notifications on an unsigned Mac build. *Why:* the user should choose knowing; repeating it is noise.
7. **Don't write app code from this skill.** Decide, record, hand off to the skill that builds it. *Why:* the
   decision and the build are separate reviews; mixing them hides the decision in a diff.
8. **Don't commit unless asked.** Say what's ready to commit: the blueprint, the decisions log, the gap report.
9. **Don't overwrite the user's files.** `init` refuses when a blueprint exists; never delete one to start over.
   *Why:* it holds decisions with their reasons; recreating it loses them.
10. **Say what's uncertain.** Detection evidence that might be stale, a backend preview whose behaviour you
    haven't checked, a platform caveat read on a date. *Why:* a confident wrong fact costs more than a flagged one.
