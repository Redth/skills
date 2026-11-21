# Checking a preview

## Before rendering every frame

`compose.py edit.json --dry-run`: the length (15 to 30 s), every mark's time, every frame file found.

Then stills, opened at full size:

- **frame 0:** the first frame is a composed picture (the headline in, the app settled);
- **frame 150:** the poster frame (5 s), which must sell alone;
- **each beat's key frame:** the headline fully in, the device where it should be, a touch on its control, a
  spotlight's margin even on every side and round the corners;
- **the middle of each transition:** both screens whole, no corner leaking, no blank frame;
- **the end card,** finished: the mark, the name, the tag line and the fine print all readable.

```sh
python3 scripts/compose.py edit.json --frames 0,150,320,345,520,700 --stills
```

## After rendering

Watch the encoded file through at full speed, sound off, on a phone-sized window, at least twice:

- every headline is readable before it leaves (about 1.5 s fully in);
- nothing jumps: a hold into a play starts on the same frame; a dissolve doesn't flash a different screen;
- typing lands key by key; scrolling looks like a thumb, not a cut;
- the camera never moves while a headline is being read, and never crops the device;
- nothing shows a real person's data, a price, a date that will go stale, or a notification;
- the disclosure is on screen long enough to read.

## The spec

```sh
python3 <store-capture>/scripts/video.py encode out/iphone-master.mp4 --slot APP_IPHONE_67 --out preview-iphone.mp4
python3 <store-capture>/scripts/video.py check preview-iphone.mp4 --slot APP_IPHONE_67
```

`check` decides the size, frame rate, length, codec and audio track. What's in the picture is a person's call,
against [apple-previews.md](apple-previews.md).

## What a person judges

- Does the first beat say what the app is, with the sound off, in five seconds?
- Is every claim true of the app as shipped?
- Is the story the one the user agreed?
