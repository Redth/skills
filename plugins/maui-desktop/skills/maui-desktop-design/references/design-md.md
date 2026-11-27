# DESIGN.md

The written design language, at the project root, from `templates/DESIGN.md`. It is the document a person or an
agent reads before touching the UI; the tokens are its executable half. Keep it binding and short enough to read.

## Sections

1. **Front matter**: name, one-line description, and the headline tokens (a few colours, the type scale, radii,
   spacing). Agents and tools read it.
2. **Overview**: the character in a sentence or two ("calm, legible, fast to scan; the tool disappears into the
   task"), and three to five key characteristics.
3. **Colours**: the surface ladder, inks, accent strategy, status colours, and the rules that go with them
   ("accent marks primary actions, selection and focus only"). The palette tables are generated.
4. **Typography**: the font stack and base size per platform, the hierarchy (page title, section title, row
   title, body, label, mono), where monospace and tabular numbers apply.
5. **Layout**: the spacing scale, section rhythm, list row anatomy, how forms collapse on narrow widths.
6. **Elevation and depth**: flat or layered at rest, what gets a shadow (popovers, dialogs), focus rings.
7. **Shapes**: the radius scale per platform and the nesting rule (inner radius = outer radius − padding).
8. **Components**: the primitives the app uses ([primitives.md](primitives.md)), each with its rule.
9. **Platform matrix** (generated): every token that differs by platform, in one table.
10. **Seams**: a table of surfaces with native or web per platform and what must match across the boundary
    ([seams.md](seams.md)).
11. **Do and don't**: the short list a reviewer checks.
12. **Surface inventory**: every page, dialog and window, grouped. Update it when one is added, renamed or
    removed; check every group on a design or theme change.

## Generated tables

`tokens.py build` replaces the content between these markers and nothing else:

```markdown
<!-- generated:palette-light:start -->
<!-- generated:palette-light:end -->
<!-- generated:palette-dark:start -->
<!-- generated:palette-dark:end -->
<!-- generated:platform-matrix:start -->
<!-- generated:platform-matrix:end -->
```

and `palette-<platform>-<theme>` for any platform that overrides colours. The two `palette-<theme>` pairs are
required when `outputs.design` is set.

## Writing rules

- State rules as rules ("Never nest a rounded card inside another"), each with its reason when it isn't obvious.
- Name tokens and components exactly as the code does.
- No hex values in prose: refer to roles. The generated tables carry the values.
- When a rule exists because of a bug that happened, say so in one line; it stops the next person undoing it.
