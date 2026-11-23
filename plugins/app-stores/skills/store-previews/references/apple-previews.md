# What the stores allow in a preview

Read 2026-11-20. Rules change: re-read the sources before a release and update this page (with the date) when
they say otherwise. `store-capture`'s `video.py check` checks the file's technical spec against its rules data;
what's *in* the video is checked by a person, against this page.

Sources:

- App previews (Apple's guidance): https://developer.apple.com/app-store/app-previews/
- App Review Guidelines, 2.3.4: https://developer.apple.com/app-store/review/guidelines/
- App preview specifications: https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications

## Apple: what may be in it

| Allowed | Not allowed |
|---|---|
| Screen captures of the app itself, in use | Filmed hands, people or devices (a drawn frame around the capture is not a filmed device; Apple doesn't mention frames either way, see below) |
| Text overlays and narration that explain what's shown | Other apps' or platforms' content; features the app doesn't have; sped-up or faked UI |
| Graphics such as touch hotspots, to show an interaction | Prices, dates, or words that go out of date (seasonal, "new") |
| Simple transitions (dissolves, fades) that don't imply features | Content not suitable for the app's age rating |
| An end card naming the app | Web addresses, calls to download from elsewhere |

- **Disclose:** if the app needs an account, or features need a subscription or in-app purchase, the preview says
  so (Guideline 2.3.4 and the guidance's "be clear about" points). The end card's fine print is the usual place.
- **Zoom:** Apple's guidance advises against zooming into the app; the camera here pushes in only to the whole
  device ([motion.md](motion.md)).
- **Device frames and backgrounds** are not mentioned either way. A drawn frame (no maker's details) around real
  captures on a plain or brand background is common in approved previews; it's a judgement, not a rule. Say so
  to the user, and keep the frame generic.
- **Autoplay muted:** previews play without sound in search and on the product page, so headlines carry the
  story; narration and music are extras, never the only explanation.
- **Poster frame:** the still shown before play and where video doesn't play. It defaults to the frame at 5 s and
  can be set in App Store Connect. Plan a beat that sells at 5 s ([storyboard.md](storyboard.md)).

## Apple: the spec

- 15 to 30 seconds; at most 30 fps; up to 3 previews a display type and locale; at most 500 MB.
- H.264 or ProRes 422 HQ; stereo audio (a silent track is added by `video.py encode` when there's none).
- Sizes: iPhone (Face ID and Dynamic Island models, every current slot) **886×1920** or 1920×886, the iPhone Duo
  included; iPad 1200×1600 or 1600×1200; Mac and Apple TV 1920×1080; Vision Pro 3840×2160. Older iPhone slots
  have their own sizes in the rules data. A preview's size is not the screenshots' size.
- One preview serves every size of its slot family; App Store Connect scales the 6.9" preview for smaller iPhones.

## Google Play

Play takes a **YouTube URL**, not a file: public or unlisted, embeddable, ads off, not age-restricted. The real
experience belongs in the first seconds; only the first 30 seconds autoplay (muted) on the listing. Portrait
videos show with no black bars when uploaded at their own shape. Play has no overlay rules beyond its metadata
policy (no misleading content, no other apps' trademarks, no ranking claims). Compose at the capture's own shape
and encode with `video.py encode --size WxH`; the upload is the user's.

The template is tuned for a portrait stage (headline sizes and the end card's layout); a landscape stage works
but look at its stills closely.
