# Primitives

The components nearly every hybrid desktop app needs, with the rule that matters for each. Build them once, on
tokens, and use them everywhere; a page that restyles one inline is a bug. Names here are generic: use the app's
own prefix.

| Primitive | Rule |
|---|---|
| **Select** (dropdown) | Never the native `<select>`: it renders as a different control in each engine and can't be themed. A custom trigger plus a menu positioned by script (escapes `overflow: hidden`, clamps to the viewport), with icons, descriptions, groups, search for long lists, and full keyboard support |
| **Action menu** (`⋯`) | Secondary, conditional and destructive row actions go in it, so rows keep one or two aligned primary actions |
| **Tabs** | A hairline rail with an accent underline for page tabs; a compact variant for inspectors |
| **Segmented control** | Two to four mutually exclusive modes; a recessed track with an elevated active segment |
| **Switch** | For settings that apply immediately; a checkbox for choices submitted with a form |
| **Page header** and **section header** | Title, optional description, actions on the right; more space above a section heading than below |
| **Grouped list** and **row** | One outer surface with inset 1px hairlines between rows; row anatomy: icon well, title and status, quiet subtitle, right-aligned actions. Never cards inside cards |
| **Expandable group** | The body steps into a recessed well with indented child rows |
| **Skeleton** | Shown until the first load completes; an empty state only after a load confirms zero items |
| **Empty state** | Icon well, title, one line of guidance, at most one action |
| **Banner** | Info, success, warning, danger: tinted fill, matching border, ink; no thick coloured side stripes |
| **Toast** | Theme-aware popover surface; never overlapping other floating controls |
| **Console** | Logs, terminals, command previews: a dark framed block in both themes, monospace, selectable, tabular timestamps |
| **Form field** | Label, control, one line of help or error; grids that collapse to one column on narrow widths; disclosures for advanced options |
| **Input group** | A path or secret input joined with copy, reveal and browse buttons in one focusable frame |
| **Data grid** | Sticky header, hairline dividers, tabular numbers, contained scrolling, virtualised for long lists |
| **Selection mode** | A Select button in the list's heading row that swaps in place for the selection controls, so the list never shifts; clicking anywhere on a row toggles it |
| **Filter pill** | "12 of 80" beside the title only while a search or filter is active |

## Across all of them

- Focus is visible (`:focus-visible`, 2px accent ring), and keyboard use works without a mouse.
- Icon-only buttons have a label; decorative icons are hidden from assistive technology.
- Hover, pressed, disabled and focused states come from tokens, in both themes.
- Dialogs are not a web primitive in this architecture: the frame is native (`maui-desktop-dialogs`). Inline
  popovers and menus stay web.
