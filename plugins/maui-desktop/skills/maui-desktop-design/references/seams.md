# Seams

The places native chrome and web content meet. Each line is something users notice when it's wrong. Check them
in light and dark, on every platform the app ships, at every web view: the main window, each dialog body, each
extra window.

## Colour and paint

- [ ] The web view is transparent over the native window, or its blank-page colour equals the window's. No
      lighter or darker band at its edge.
- [ ] Native chrome takes its colours from the generated C# (`<P>Tokens.Get`), never from a hex literal.
- [ ] The window background is pushed to `--bg` at run time where the OS decides it (macOS window background,
      Mica on Windows), with the static token as the fallback.
- [ ] A dialog's native frame (title row, button row, separators) and its web body use the same surface role.
- [ ] Separators drawn natively and in CSS use the same role and thickness (1px).

## First paint

- [ ] Each web view stays hidden behind a native placeholder (the window colour, a native spinner) until the
      content has rendered, then fades in.
- [ ] A timeout reveals it anyway (about 15 seconds), so a startup error shows the error rather than a blank
      window.
- [ ] `data-platform` and `data-theme` are on the root before the first paint, in every web view.
- [ ] The saved theme is applied at startup, before the first window shows.
- [ ] `#app` (or the mount point) and its ancestors have an explicit height, so no window background shows below
      short content.

## Behaviour

- [ ] Text isn't selectable outside inputs, code, logs and content meant to be copied.
- [ ] Reload keys, pinch zoom, back/forward gestures, the default context menu and link and image dragging are off.
- [ ] Links to the web open in the user's browser, never inside the app.
- [ ] Nested scroll regions set `overscroll-behavior: contain`; a dialog has one scroll region, with its header and
      footer pinned.
- [ ] Nothing loads from the network at start: fonts, icons, editors and scripts are bundled.
- [ ] A JavaScript error and a .NET exception both surface somewhere visible in Debug builds (an error banner, a
      log), not only in a console no one opens.

## Typography and geometry

- [ ] The content's base size and font match the platform's (13px SF Pro on macOS, 14px Segoe UI Variable on
      Windows, 14px on GNOME).
- [ ] Native buttons and web buttons beside each other (a dialog footer and its body) share height and radius.
- [ ] Content clears the title bar and toolbar by the inset the head reports, not a hard-coded number.

## Theme changes

- [ ] Switching the OS appearance repaints native chrome and every open web view in the same frame.
- [ ] Switching the app's own theme setting does the same, and persists.
- [ ] Popovers and menus drawn in the web content follow the theme (they're often the last thing still light).
