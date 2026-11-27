# CSS across three web engines

One stylesheet runs in WKWebView (tied to the macOS version), WebView2 (current Chromium) and WebKitGTK (varies by
distribution). The oldest engine the app supports sets the baseline. Data from MDN's browser compatibility data,
read 2026-11-27; WebKitGTK's parity with Safari versions is an estimate, so guard newer features with `@supports`.

| Engine | Version range to expect |
|---|---|
| WKWebView | macOS 14 ≈ Safari 17; 15 ≈ 18; 26 ≈ 26; 27 ≈ 27 |
| WebView2 | evergreen Chromium |
| WebKitGTK | 2.52 (Ubuntu 24.04 updates, 26.04) to 2.54 (Fedora 43/44) |

## Safe on every supported target (macOS 14+)

`:has()`, container size queries, `color-mix()`, cascade layers, `@property`, subgrid, CSS nesting, the `popover`
attribute, `inset`, `aspect-ratio`, `gap` in flex, `overscroll-behavior`, `prefers-color-scheme`,
`prefers-reduced-motion`, `prefers-contrast`.

## Needs a fallback

| Feature | First in WKWebView | Fallback |
|---|---|---|
| `light-dark()`, `@starting-style`, `text-wrap: balance` | macOS 14.5 (Safari 17.5) | theme blocks from the generator; plain wrapping |
| View transitions, relative colour syntax, style queries, `content-visibility` | macOS 15 (Safari 18) | no transition; a token per colour |
| `scrollbar-width`, `scrollbar-gutter` | Safari 18.2 | `::-webkit-scrollbar` as the common base |
| Anchor positioning | macOS 26 | position popovers with script (measure, place, clamp to the viewport) |
| `scrollbar-color`, `field-sizing`, full `accent-color` | Safari 26.2 | `::-webkit-scrollbar`; script-sized text areas |
| `@scope` | Safari 26.4 | scoped component styles (`.razor.css`) |

## Always write both

- `backdrop-filter` and `-webkit-backdrop-filter`.
- `user-select` and `-webkit-user-select`.

## Not available in WebKit

`corner-shape: squircle` (not in a shipping WKWebView yet), `prefers-reduced-transparency`, `interpolate-size`,
`scroll-state()` queries, `app-region`. Use them only as enhancements, and push reduced transparency from the
head.

## Fonts

`system-ui` everywhere for interface text. Core Text, DirectWrite and FreeType produce different metrics and
weights: design for a range, not a pixel. `ui-monospace` isn't supported in Chromium: list named monospace fonts
after it.

## The OS accent

The `AccentColor` system colour keyword could not be confirmed to return the user's OS accent in any of the three
engines. When `look.accent` is `system`, the head pushes it as a run-time override.
