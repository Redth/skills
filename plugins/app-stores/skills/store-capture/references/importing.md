# Importing another tool's screenshots

When the project already makes captures that work, keep its pipeline and bring the output into this skill's layout:
`<out>/<locale>/<device id>/<screen id>.png` and a `capture-report.json`, checked like any capture.

```sh
python3 scripts/import_captures.py --from fastlane-snapshot fastlane/screenshots --map capture-map.json \
  --plan capture-plan.json --dry-run          # what would be imported, and the names it would use
python3 scripts/import_captures.py --from fastlane-snapshot fastlane/screenshots --map capture-map.json \
  --plan capture-plan.json
python3 scripts/check_captures.py --plan capture-plan.json --rules apple
```

`--from` is one of `fastlane-snapshot`, `fastlane-screengrab`, `xcresult`, `maestro`, `flutter`, `detox`,
`playwright`, `folder`; the path is the tool's output folder (or an `.xcresult` bundle). `--out` defaults to the
plan's `out`, else `captures`; `--locale` and `--device` name what the source doesn't say.

**The mapping** says which of the other tool's names is which of the plan's ids; anything it doesn't name keeps its
own name, made an id (lower case, `[a-z0-9.-]`):

```json
{ "locales": { "de": "de-DE" },
  "devices": { "iPhone 17 Pro Max": "iphone-6.9", "iPad Pro 13-inch (M5)": "ipad-13" },
  "screens": { "01Plan": "plan", "02Recipe": "recipe" },
  "locale": "en-US", "device": "iphone-6.9", "onlyMapped": false }
```

With `screens` given and `onlyMapped` true, pictures it doesn't name are left out (and listed). `locale` and
`device` apply when the source doesn't say. Run `--dry-run` first: it shows each file's locale, device and screen
before anything's written.

**With `--plan`, each picture's size is checked against its device's promise**: any other size is `failed`, never
resized. Without a plan only the format is checked, so pass one (or run `check_captures.py --rules …` after). Every
picture is checked as `capture.py` checks its own: 8-bit RGB, sRGB, no alpha, not interlaced; one that isn't is
redrawn through headless Chrome and the fix listed. A device or locale the plan doesn't have is a warning. The
pictures go into a temporary folder and are moved into place at the end; `capture-report.json` gets an entry for
each (driver `import`), merged with the report already there.

An imported picture's status bar is always `unverified` (the importer can't know what the tool did, even with
fastlane's `override_status_bar(true)`): look at it.

Exit codes: 0; 1 a picture failed, or nothing was found; 2 refused (a capture is writing to the same folder); 3
usage or environment.

## From each tool

| `--from` | Where the tool writes | What the importer reads |
|---|---|---|
| `fastlane-snapshot` | `Snapfile`'s `output_directory` (default `fastlane/screenshots`): one folder a language, files named by device and `snapshot("…")` name, e.g. `en-US/iPhone 17 Pro Max-01Plan.png` | the language folder as the locale, the device name before the last `-` as the device, the rest as the screen |
| `fastlane-screengrab` | `fastlane/metadata/android/<locale>/images/<type>Screenshots/<name>_<timestamp>.png` (`phone`, `sevenInch`, `tenInch`, `tv`, `wear`) | the locale folder, the type as the device, `<name>` as the screen (the newest file of each) |
| `xcresult` | an `.xcresult` bundle from `xcodebuild test -resultBundlePath`, or a folder already exported | `xcrun xcresulttool export attachments` and its `manifest.json`: the attachment's name as the screen, the test's device as the device, its test plan configuration as the locale |
| `maestro` | `maestro test --test-output-dir <dir>` | every `takeScreenshot`: its path under the flow's screenshot folder is the screen |
| `flutter` | the folder the `integration_test` driver's `onScreenshot` writes to (`File('shots/$name.png')`) | the names as screens; device and locale from the mapping or `--device`/`--locale` |
| `detox` | the artifacts folder: `<configuration>.<time>/<test>/<name>.png` | the names as screens, the configuration as the device; Detox's own `testStart`/`testDone`/`testFailure` pictures left out |
| `playwright` | a folder of `page.screenshot({ path })` files | the files (visual-comparison `-actual`, `-diff`, `-expected` files left out); a project folder can name the device |
| `folder` | `<locale>/<device>/<screen>.png`, or anything | a path part that names a locale or device says so; the mapping or `--locale`/`--device` for the rest |

Notes per tool:

- **fastlane snapshot** device names can hold a `-` (`iPad Pro 13-inch (M5)`): the mapping's device names are
  matched first, else the name is split at the first `-` with no space after it. Its `screenshots.html` is
  ignored.
- **fastlane snapshot** sizes are the simulators' own: a `devices` list with a simulator that doesn't render a store
  size (an iPhone 11 is 828×1792) imports as `failed`. Change the `Snapfile`'s devices
  ([sizes.md](sizes.md)). `override_status_bar(true)` gives 9:41 and full bars; say `overridden` only when it's
  set.
- **fastlane screengrab** keeps every run's files unless `clear_previous_screenshots`: the importer takes the newest
  per name and reports the rest ignored.
- **xcresult**: only attachments the tests kept (`lifetime = .keepAlways`) are in the bundle.
- **Maestro**: an undefined variable in a `takeScreenshot` path writes `undefined.png`; the importer fails that
  file rather than guess.
- **Flutter**: what the driver's bytes contain (the Flutter surface only, or the whole screen with the status bar)
  varies; check the size and the top of the picture. On Android, `convertFlutterSurfaceToImage()` is needed before
  the shot.
- **xcresult**: the locale comes from the test plan configuration's name (`configurationName`; map it to a locale),
  the device from `deviceName`.
- **Detox** on iOS can set the status bar (`device.setStatusBar`, the same flags as `simctl status_bar`).
- **A game engine's folder**: write it in this layout from the start ([engines.md](engines.md)) and import with
  `--from folder --plan capture-plan.json` and no mapping.

## Then

`check_captures.py` (sizes against the plan and the stores' rules), then look at every picture at full size, as for
any capture (SKILL.md, step 7).
