# Game engines: Unity, Godot, Unreal

A game shouldn't be screenshotted through a window. **Render each picture in the engine at its exact size, with
the UI laid out for that size, supersampled, with time held still**, then import the folder
([importing.md](importing.md)). The engine knows the game's state; a simulator only sees pixels.

## The pattern

A test or an editor command (in the game's own code) that:

1. **Stages each moment by name.** Loads a level or a save, places the players, sets the score, opens the menu:
   the moment the shot is for (`title`, `match-goal`, `shop`). Seeded, so every run gives the same picture.
2. **Lays out for the size.** Each device kind (phone portrait, tablet, TV, desktop) gets its own pass: the UI
   pointed at a render target of the picture's exact size, given a frame or two to lay out, so the HUD is placed
   for that shape, not stretched from another.
3. **Freezes time.** The simulation stepped to the moment and held (a fixed delta, physics paused), so motion blur,
   particles and animation are the same every run.
4. **Renders bigger, then down.** Draw at 2× and downsample to the size for clean edges; read back as RGB (no
   alpha).
5. **Writes the layout this skill reads:** `<out>/<locale>/<device id>/<screen id>.png`, the plan's ids. Then
   `import_captures.py --from folder <out>` checks and reports it like any other capture, or point the plan's
   `out` at it.
6. **Counts what it made.** Staged moments break as the game changes (a level renamed, a menu moved). The command
   should report each moment taken or not, and fail loudly when one isn't, rather than silently producing fewer
   pictures. Keep the previous picture of a missed one, and say it's stale.

Ship this as a test or an editor menu item in the game's repository; run it in batch mode with a GPU (most engines
can't render headless without one).

## Unity

- A PlayMode test (or an editor script) per device kind; the moment staged in code.
- Render: a camera into a `RenderTexture` of the exact size (or 2× and blit down), UI canvases in Screen Space –
  Camera on that camera so they lay out at the size; `Texture2D` with `TextureFormat.RGB24`, `ReadPixels`,
  `EncodeToPNG`.
- Time: `Time.captureDeltaTime` fixes the step; pause what shouldn't move.
- Simpler, less exact: `ScreenCapture.CaptureScreenshot(path, superSize)` captures the Game view at a multiple of
  the window size, so the Game view must already be the right aspect.
- Batch mode with `-nographics` can't render: run `-batchmode` with a GPU. Video: Unity Recorder (editor), or
  `captureDeltaTime` and frame dumps encoded with `video.py encode`.

## Godot

- A still: `get_viewport().get_texture().get_image().save_png(path)` after the moment is staged and a frame drawn.
- Exact size: set the window or viewport size in the capture script; with `viewport` stretch mode the project's
  viewport size is used, so set it for each device kind.
- Video, deterministic: Movie Maker mode, `godot --path <project> --write-movie out.avi --fixed-fps 30 --resolution
  1920x1080` (the resolution override works with `disabled` or `canvas_items` stretch; the window is clamped to the
  display). Outputs AVI (MJPEG), OGV or a PNG sequence with WAV. Leave `transparent_bg` off, or the PNGs carry alpha.
  Scaling 3D above 1.0 supersamples.

## Unreal

- `HighResShot 2880x1800` (or a multiplier, `HighResShot 2`) writes to `Saved/Screenshots`; drive it from a
  console command in an automation test or a level script after the moment is staged.
- Movie Render Queue for video (fixed frame rate, high quality).
- Reported limits: high-res shots in editor or standalone builds; large multipliers can run out of memory.

## Games on phones and TV

Render in the engine at the store sizes (no status bar; games run immersive). Running the build on a simulator or
emulator and capturing with `simctl`/`adb` works too, but gives up supersampling and staged moments: fine for a
menu, poor for gameplay.

What a game's store shots should show (gameplay, not key art alone; no other platforms' buttons) is
`store-screenshots`' games reference.
