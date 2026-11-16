# Web apps and PWAs: `chrome`

The `chrome` driver loads the app in headless Chrome (or Chromium; `CHROME` overrides where it's found) at a
viewport and device scale factor whose product is the store size, and captures the page. It's the same Chrome
`store-screenshots` renders with, driven over the DevTools protocol by the shared stdlib client: no Node, no
Playwright.

## Exact pixels: viewport × scale

| Store size | Viewport (CSS px) | Scale | Pixels |
|---|---|---|---|
| iPhone 6.9" | 440×956 | 3 | 1320×2868 |
| iPhone 6.3" | 402×874 | 3 | 1206×2622 |
| iPad 13" | 1032×1376 | 2 | 2064×2752 |
| Mac | 1440×900 | 2 | 2880×1800 |
| Play phone | 360×640 | 3 | 1080×1920 |
| Play tablet / Chromebook, 16:9 | 1280×720 | 2 | 2560×1440 |

```json
{ "id": "web-iphone", "platform": "web", "driver": "chrome", "width": 1320, "height": 2868,
  "target": { "scale": 3, "mobile": true } }
```

The page is laid out at `width/scale` × `height/scale` CSS px with a device scale factor of `scale` (`target.scale`,
default 1), so the picture is exactly the device's size; `viewport: [w, h]` in CSS px instead sets the scale from
its width.
`mobile` (default on for phone and tablet platforms) turns on a mobile viewport and touch; `reducedMotion`
(default on) asks the page for reduced motion. Do the sum before running: a size that doesn't divide comes out
wrong and fails. The layout is the web's, at that viewport; there are no system bars, which suits designed shots
(`store-screenshots` adds a frame or none).

## Reaching screens

- `launch` opens the app's URL (`app.web.url`) with `ScreenshotSeed` and the screen's `args` as query parameters
  (`clean` clears the origin's storage first); `url` and `deepLink` open a URL, relative ones against the app's.
  The app's screenshot mode reads the query ([screenshot-mode.md](screenshot-mode.md#web)).
- `tap`, `type`, `wait`, `scroll` find elements in the page through `Runtime.evaluate`: `css` (a selector), `id`
  (`data-testid`, then the `id` attribute), `text` (visible text), `label` (`aria-label`, `alt`, `title`) or
  `xpath`. A tap is a real mouse press at the element's middle; typing is `Input.insertText`; `back` is
  `history.back()`.
- Opening a page waits for its load event, its fonts (`document.fonts.ready`) and two animation frames; `settle`
  then waits for two identical screenshots in a row.

## State

- Locale: `Emulation.setLocaleOverride`, `Accept-Language` and `navigator.language` from the plan's locale.
- Appearance: `prefers-color-scheme` emulated from `appearance`; reduced motion on.
- Clock: a fixed "now" from the app's screenshot mode (`?now=…`); the browser's clock isn't changed.
- A fresh temporary profile every run (no cookies, storage or service-worker cache from the last), sRGB colour
  (`--force-color-profile=srgb`), scroll bars hidden, an opaque background.

## Local only

The app is served on this machine (`http(s)` to `localhost` or `127.0.0.1`, or `file:` and `data:` URLs): a dev
server or a static build; anything else is refused. A public site is out of scope: its content isn't fixed, and
fetching it is a network call. Linux: install CJK, Arabic and emoji fonts, or other scripts render as boxes.

## Video

`video.py record` uses Chrome's screencast at the viewport × scale; see [video.md](video.md).

## Playwright or Puppeteer already in the project

Import their screenshots ([importing.md](importing.md)). For reference, Playwright's equivalents:
`browser.newContext({ viewport: { width: 440, height: 956 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true,
locale: 'de-DE', timezoneId: 'Europe/Berlin', colorScheme: 'dark', reducedMotion: 'reduce' })`,
`page.clock.setFixedTime(...)`, `page.screenshot({ path, animations: 'disabled', caret: 'hide', scale: 'device' })`
(`scale: 'css'` would give 440×956).
