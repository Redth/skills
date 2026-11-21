# Preview videos: record, trim, encode, check

`video.py` records from a simulator, emulator or Chrome, encodes to a store's preview spec with **ffmpeg**, and
checks the result with **ffprobe** against the rules data (`rules/apple.json`'s `apple.previews.*`). ffmpeg and
ffprobe are found at run time (`FFMPEG` and `FFPROBE`, then `PATH`); they're never bundled, and without them
`video.py` exits 3 with how to install them.

```sh
# record a screen's steps (the moments to show) on the plan's device: captures/<locale>/<device>/<screen>.mov|.mp4
python3 scripts/capture.py --record --devices iphone-6.9 --screens tour
# or record by time: simctl io recordVideo, adb shell screenrecord, or Chrome's screencast
python3 scripts/video.py record --from simctl --device <udid> --out raw.mov --seconds 30
python3 scripts/video.py record --from adb --device <serial> --out raw.mp4 --seconds 30
python3 scripts/video.py record --from chrome --url "http://localhost:8080/?screenshot=tour" \
  --width 440 --height 956 --scale 3 --out raw.mp4

# encode: to a slot's preview sizes (from the rules), or an explicit size; --end at the report's flush.at
python3 scripts/video.py encode captures/en-US/iphone-6.9/tour.mov --slot APP_IPHONE_67 --end 21.4 \
  --out preview-iphone.mp4
python3 scripts/video.py encode raw-tv.mov --size 1920x1080 --out preview-tv.mp4

# check: ffprobe against the rules' video rules
python3 scripts/video.py check preview-iphone.mp4 --slot APP_IPHONE_67

# frames: every recorded frame, in order, numbered, for an edit by frame index
python3 scripts/video.py frames raw.mov frames/ --width 1320
```

- `capture.py --record`: records each screen's steps as it captures it (next section).
- `record`: `--during` runs a command while recording and `--tail` keeps recording a second after it (not
  `capture.py`: see below); `--display` picks a simulator's display; `--size` is `screenrecord`'s; `--dry-run`
  prints the commands.
- `encode`: the size comes from the slot's preview sizes in the rules (or `--size`); the picture is scaled and
  centre-cropped only when its aspect is within 2 % of the target's (further off, choose `--fit crop` or
  `--fit pad`), and never scaled up without `--allow-upscale` (don't, unless the user accepts a softer preview).
  `--fps` (30), `--bitrate` (11M), `--codec h264|prores`, `--json`.
- `frames`: every frame of the recording, in the order recorded, as `frame-00001.jpg` on in an empty folder,
  with the count and size printed; `--width` scales keeping the aspect, `--size WxH` forces a size, `--format
  jpg|png`, `--quality` (jpg: ffmpeg's `-q:v`, 1 best to 31; default 2), `--json`, `--dry-run`. Why, and the
  edit that follows: [Editing a simulator recording by frame index](#editing-a-simulator-recording-by-frame-index).
- Exit codes: 0; 1 a check error, or an encode that can't meet the spec; 3 usage, or ffmpeg/ffprobe missing.

## What the stores take

**App Store** (App preview specifications, read 2026-11-14):

- 15 to 30 seconds; at most 30 fps; up to 3 a display type and locale; at most 500 MB.
- H.264 (`.mov`, `.m4v`, `.mp4`; 10–12 Mbps, progressive, up to High Profile Level 4.0) or ProRes 422 HQ (`.mov`).
- Stereo audio, 44.1 or 48 kHz: AAC 256 kbps (or PCM with ProRes).
- **Preview sizes are their own, not the screenshots':** iPhone (Face ID and Dynamic Island models) 886×1920 or
  1920×886; iPad 1200×1600 or 1600×1200; Mac and Apple TV 1920×1080 (landscape only); Vision Pro 3840×2160
  (landscape only). The rules data has each slot's list.
- Only screen captures of the app itself: narration and overlays are fine; no hands, devices or other footage
  (guideline 2.3.4). Nothing else in it: no other platforms, prices or web addresses.
- **Unverified but cheap to follow:** uploads without an audio track are reported to fail ("unsupported or
  corrupted audio"); `encode` always adds a silent stereo track when there's none.
- The poster frame defaults to 5 s; processing takes up to a day.

**Google Play** takes a YouTube URL, not a file (encode with `--size WxH`, no store's limits applied): public or unlisted, embeddable, ads off, not age-restricted, the
real experience in the first 10 seconds (only the first 30 autoplay), no black bars on a portrait video. Encode it
as YouTube likes (H.264, AAC, the capture's size, constant frame rate); the upload is the user's.

**Steam and itch.io:** H.264/AAC MP4 trailers, up to 1920×1080 on Steam.

## Recording

| Source | Command | What to know |
|---|---|---|
| Apple simulator | `xcrun simctl io <udid> recordVideo --codec=h264 --mask=ignored --force raw.mov` | the default codec is HEVC; "Recording started" goes to stderr when the first frame is in (wait for it); stop with SIGINT, and simctl exits once the file is finished. Frames come only when the screen changes: a **variable** frame rate. No audio |
| Android | `adb -s <serial> shell screenrecord --bit-rate 20000000 --time-limit <s> [--size WxH] /sdcard/raw.mp4`, then `adb pull` and `adb shell rm` | H.264 MP4 at the native size (or `wm size`); older versions stop at 180 s (`--time-limit 0` lifts it on recent ones); no audio; rotation mid-recording cuts the picture; some devices can't encode their native size: `--size` |
| Chrome | the DevTools screencast (`Page.startScreencast`, each frame acknowledged) at viewport × scale | frames come as the page paints, timed by their timestamps and joined by ffmpeg into a constant-rate H.264 file |
| Mac | `screencapture -v -V 30 -R x,y,w,h raw.mov` | Screen Recording permission; record a 16:9 window for the Mac's 1920×1080 preview |
| Game engines | Godot's `--write-movie … --fixed-fps 30`, Unity Recorder, Unreal's Movie Render Queue | deterministic, the best quality ([engines.md](engines.md)) |

## Recording a screen's steps: `capture.py --record`

The moments a preview shows are a screen's steps: the plan already launches the app staged, taps, types and
scrolls to them. `capture.py --record` (with `--devices` and `--screens` as usual) records each screen it captures,
from just before its first `launch` (after the device is prepared, any seed has run, and any reboot a locale change
needs is over) until a second after its last step, then stops before the `verify`, the screenshot and the reset. The
recording goes beside the picture, `<out>/<locale>/<device>/<screen>.mov` from a simulator or `.mp4` from Android,
and the report's `recording` says its `path`, `seconds`, `by`, `from` (the step it started at), `display` and
`flush`. A shot that isn't taken drops its recording.

- **Simulators** (`simctl`, and `appium`, `xcuitest`, `devflow`, `ailoha` or `maestro` on one): `xcrun simctl io
  <udid> recordVideo --codec=h264 --mask=ignored [--display=N] --force <file>`, on the display the screenshots
  take (the iPhone Duo's cover or inner one: `target.display`, the one a posture made active, or the one of the
  device's size), started when "Recording started" says its first frame is in, stopped with SIGINT.
- **Android** (`adb`, `uiautomator`, and the drivers `adb` hosts): `screenrecord --bit-rate 20000000 --time-limit
  180 [--display-id N]` on the device, stopped with `pkill -INT screenrecord`, pulled, and deleted from the device.
  It stops by itself at 180 s; steps that take longer get a warning, and the recording ends there.
- Anything else (`chrome`, `macos`, an agent or Appium on a Mac or Windows app, a device with `target.host:
  "none"`) is refused before anything runs (exit 3): record a web page with `video.py record --from chrome`, a Mac
  window with `screencapture -v`.

**Why not `video.py record --during "capture.py …"`.** The recorder starts first, then `capture.py` prepares the
device: on its own simulator it writes the language and reboots it (shutdown, boot), which ends the recording (and
an Appium session); and at the end its reset shuts the simulator down, which ends any recording too. What's left is
the boot, or nothing. `--record` starts after the reboot and stops before the reset.

**The flush, and trimming it.** simctl writes a frame only when the screen changes, and holds the last one back
until the next change: a recording stopped while the screen stands still loses its settled final frames (the
moment the steps worked to reach). So a second after the last step `--record` changes the status bar for a moment
(`simctl status_bar <udid> override --batteryLevel 99`), waits a second, stops, and puts the battery back (100 %,
or the status bar cleared when it wasn't overridden; the reset clears it too). That change forces the held frames
out, and is itself the recording's last second: trim it with `video.py encode … --end <flush.at>` (the report's
`recording.flush.at`, also in the log line). A tvOS, watchOS or visionOS simulator has no status bar to change: no
flush, and a warning that the last frame may be missing. Android's `screenrecord` needs none (`flush` is `null`).

**The steps' `wait`s set the pacing.** A recording runs as fast as the steps do: a launch, a tap, the next tap. Give
each moment the time a viewer needs to read it with a `wait` step (`{"wait": {"ms": 1500}}`) after it, in the
screen's steps or a `stepsPatch` for the device that's recorded; a `settle` waits only until the screen is still.
A preview is 15 to 30 s: count the waits, and trim with `--start`/`--end`.

Record each Apple size natively (an iPhone recording for the iPhone preview, an iPad one for the iPad) rather
than cropping one master: the layouts differ. The status bar override and demo mode apply to recordings too; set
them first, as for screenshots.

**Script the moments, then count them.** A preview that depends on staging (a level, a state, a sequence of taps)
breaks when the app changes. Drive it with the same steps as the screenshots, mark the moments by name rather than
by time in the file, and check each one happened.

**Type at a person's pace.** A `type` or `fill` puts its value in at once, which reads as a jump on video: give the
take's typing steps a `rate` (keys a second; 4 to 6 reads naturally) so each key lands on camera
([config.md](config.md#typing-at-a-persons-pace)). Screenshots don't need it.

## Editing a simulator recording by frame index

A preview is rarely one take: a settled screen held for a beat, then the motion that matters at full speed.
Cutting a simulator recording by time lands on the wrong moments, because **its timestamps don't follow the wall
clock**. `simctl io recordVideo` writes a frame only when the screen changes, and in a real trial (iOS 27
simulators, ffmpeg 7 and 8) idle stretches came out compressed and some frames shared a timestamp, out of order in
`showinfo`. So:

- seeking with `-ss`, converting with `fps=30` or retiming with `setpts` picked the wrong frames: a 5-second hold
  collapsed into 0.3 s, and 154 recorded frames became 382 or 16;
- writing images straight from the recording dropped frames: the `image2`/`image2pipe` muxers and the mjpeg
  encoder reject the clashing timestamps ("non monotonically increasing dts", "Invalid pts").

`frames` sidesteps the timestamps. It decodes the recording once to raw RGB with every frame passed through as it
is (`-f rawvideo -pix_fmt rgb24 -fps_mode passthrough`) and pipes that into a second ffmpeg that reads it as a
plain sequence (`-f rawvideo -s WxH -r 30 -i -`) and writes numbered images: every frame, in order, numbered
afresh. It prints how many; when the stream's own frame count differs, it says so.

Then edit by index, not by time: look at the frames, pick the ones each beat needs, hold a settled frame for as
long as the beat lasts (seconds × 30 copies of it) and play motion frames one each, at 30 fps:

```sh
python3 scripts/video.py frames raw.mov frames/ --width 1320
mkdir -p edit; i=0
put() { i=$((i+1)); ln -f "frames/frame-$(printf %05d "$1").jpg" "edit/$(printf %05d "$i").jpg"; }
for n in $(seq 150); do put 12; done          # frame 12 held for 5 s
for f in $(seq 40 95); do put "$f"; done      # the tap and its animation, as recorded
for n in $(seq 90); do put 95; done           # the result held for 3 s
ffmpeg -framerate 30 -i edit/%05d.jpg -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
  -c:v libx264 -crf 12 -pix_fmt yuv420p edit.mp4
python3 scripts/video.py encode edit.mp4 --slot APP_IPHONE_67 --out preview-iphone.mp4
```

The edit's length is the frame count over 30; `encode` still checks it's 15–30 s and adds the silent track.

**A rotated recording that comes out squeezed.** A file can store its picture on its side with a rotation for
the player (a display matrix); ffmpeg turns the picture upright as it decodes. In a real trial a two-screen
simulator's open inner display (simctl's `--display` of that screen) recorded a 2006×2852 stream with a −90°
rotation, and the landscape picture came out squeezed into a portrait frame: text upright but narrow. Forcing the
output back to the display's landscape shape (2853×2007, or a scale of it) fixed it. `frames` writes a rotated
recording at its turned size and says so when ffprobe reports a rotation; look at a frame, and if the picture is
still squeezed, force the display's shape with `--size WxH`. A `--size` whose shape (portrait or landscape) isn't
the picture's is warned about, as is one that stretches it.

## Encoding

What `encode` does for an iPhone portrait preview from a 1320×2868 simulator recording, as ffmpeg:

```sh
ffmpeg -ss 00:00:02.0 -to 00:00:27.0 -i raw.mov \
  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
  -vf "scale=886:1920:force_original_aspect_ratio=increase,crop=886:1920,setsar=1,fps=30" \
  -c:v libx264 -profile:v high -level:v 4.0 -pix_fmt yuv420p \
  -b:v 11M -maxrate 12M -bufsize 24M \
  -c:a aac -b:a 256k -ar 48000 -ac 2 -shortest -movflags +faststart \
  preview-iphone.mp4
```

- **Constant 30 fps** (`fps=30`): simulator recordings are variable, screen recordings often 60; "frame rate too
  high" is a common rejection.
- **The exact size by fill and centre-crop, never a stretch.** 1320×2868 is 0.4603, 886:1920 is 0.4615: the crop
  takes a few pixels. iPad 2752×2064 to 1600×1200 and Apple TV 3840×2160 to 1920×1080 are exact scales. This is the
  one place a picture is scaled: a preview's sizes are the store's, not a device's, and scaling down within the same
  aspect is what Apple's own fallback does.
- **A silent stereo track** (`anullsrc`) when the recording has none; the user's own soundtrack (licensed) mixed
  instead when there is one.
- `yuv420p`, High Profile, Level 4.0, 10–12 Mbps: what the spec lists.
- **Vision Pro's 3840×2160 can't fit H.264 Level 4.0** (it allows 8,192 macroblocks a frame; 4K needs 32,400):
  `encode` writes it at Level 5.1 and says so, or ProRes 422 HQ in `.mov` (`--codec prores`: `-c:v prores_ks
  -profile:v 3`, PCM audio), the spec's other option. Unverified which Apple accepts in practice; the check flags
  it.
- **Use the `medium` preset or anything down to `veryfast`, never `ultrafast`**: x264's `ultrafast` writes
  Constrained Baseline whatever `-profile:v` says (`--preset`, default `medium`).
- `encode` refuses a length outside 15–30 s before encoding (trim with `--start`/`--end`), and runs ffmpeg with
  `-nostdin`, `-fps_mode cfr` and `format=yuv420p`.
- If an exact size isn't provided, App Store Connect scales a preview from the next larger display size.

## Checking

```sh
ffprobe -v error -of json \
  -show_entries format=duration,size:stream=codec_type,codec_name,profile,level,width,height,pix_fmt,r_frame_rate,avg_frame_rate,channels,sample_rate,bit_rate \
  preview-iphone.mp4
```

`check` compares it with the rules: duration 15–30 s; width×height in the slot's preview sizes; `avg_frame_rate`
at most 30 and equal to `r_frame_rate` (constant); the codec, profile and level; one stereo AAC (or PCM) stream at
44.1 or 48 kHz; at most 500 MB.

Then **watch it through** at full size, with sound: transient UI, a stutter where the recording dropped frames,
the status bar, content that dates it (seasons, "today"), anything that isn't the app.
