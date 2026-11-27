# Icons

`design/icons.json` names every icon once, with what each platform calls it. Shared code uses the generated
`IconRef`; each head resolves it to its own vocabulary. The contract is the plugin's `CONTRACT.md` §5.

## Why one file

Putting a platform's icon names in shared code (an SF Symbol string in a toolbar record) forces every other
platform to keep a translation table, which drifts: a missing entry is a blank button on one platform that no one
notices until a user does. With one file, a missing mapping fails `icons.py build`.

## Each icon

| Key | Platform | What it is |
|---|---|---|
| `sf` | macOS chrome | an SF Symbol name (`arrow.clockwise`). Check it in Apple's SF Symbols app, and its minimum macOS version |
| `gtk` | Linux chrome | an icon-theme name, normally `*-symbolic` (`view-refresh-symbolic`), from the Adwaita set. Check it exists in the theme the app targets, or ship the SVG and add the folder to the icon theme's search path |
| `fluent` | Windows chrome, when `meta.windows` is `fluent` | a Segoe Fluent Icons codepoint in hex (`E72C`), rendered with a `FontIcon` so it stays sharp at any scale |
| `svg` | web content, and Windows chrome when `meta.windows` is `svg` | the geometry inside a `<symbol>`, on the shared `geometry` (viewBox, stroke width, caps, joins), stroked with `currentColor` |
| `marks` | anywhere the app's own mark appears | an SVG only; on macOS also a template image for a status item or dock menu |

## Using it

- **Web content**: `<svg class="icon" aria-hidden="true"><use href="#i-refresh"/></svg>` with the generated
  `IconSprite` component mounted once per document. Inline symbols, because WebKit doesn't resolve a `<use>`
  that points into another file.
- **macOS**: `NSImage.GetSystemSymbol(Icons.SfSymbol(icon), null)`; size and weight with a symbol configuration.
- **Windows**: `new FontIcon { Glyph = Icons.FluentGlyph(icon) }`, or render `Icons.Svg(icon, stroke)` with the
  stroke colour from the generated palette for the current theme.
- **Linux**: `Gtk.Image.NewFromIconName(Icons.GtkName(icon))`.

Decorative icons are hidden from assistive technology (`aria-hidden`); an icon-only button has a label
(`aria-label`, a tooltip, and the native control's accessibility label).

## Keeping it honest

- One icon set in web content: the sprite. Don't mix in an icon font for "just these few".
- The geometry is the app's own drawing; SF Symbols and Adwaita icons are each platform's. They won't match
  exactly and shouldn't: chrome looks native, content looks like the app.
- Trim the template to what the app uses; an unused icon still costs review.
