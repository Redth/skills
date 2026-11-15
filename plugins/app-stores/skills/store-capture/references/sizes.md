# Which device renders which store size

Exact sizes come from the device, never from resizing. This file says which simulator, emulator profile or
viewport renders each store size natively. The stores' accepted sizes themselves are in the rules
(`rules/apple.json`'s `slots`, `rules/google.json`'s `slots`: dated and sourced, the same files `store-listings`
checks against), and a device's `width`×`height` in the plan comes from there.

> **Device names lie.** A device being *listed* in a store's size class doesn't mean it *renders* that class's
> pixels. The iPhone 11 is in Apple's 6.5" list but its simulator renders 828×1792, which the App Store doesn't
> take. Every capture's PNG header is read and compared with the size the plan promised; a mismatch is `failed`.
> Check the first capture of a new device type before trusting the table.

Read 2026-11-14 against Apple's screenshot specifications, the Android SDK's device definitions and current Xcode.
New devices arrive every year: add them as data, and check the first capture.

## Apple simulators → App Store slots

**Required** (the rules' `required`): iPhone 6.3"/6.1" (Dynamic Island, medium display), iPad 13" when the app runs
on iPad, and the Mac, Apple TV and Vision Pro slots for apps on those platforms. Apple scales the largest set down
for smaller classes when the UI is the same.

**For a designed set** (`store-screenshots`), capture the largest iPhone (6.9", 1320×2868) and give the design a
6.3" *target* (1206×2622): it renders the required slot from the same capture, so a 6.3" simulator isn't needed.
**For captures sent as they are**, capture the required 6.3" (or 6.1") device too. `check_captures.py --rules
apple` notes a required display type no device fills.

| Simulator device type | Native pixels (portrait) | Slot (rules id) | Accepted? |
|---|---|---|---|
| iPhone 17 Pro Max, 16 Pro Max | 1320×2868 | `APP_IPHONE_67` (6.9") | yes |
| iPhone Air | 1260×2736 | `APP_IPHONE_67` | yes |
| iPhone 16 Plus, 15 Pro Max, 15 Plus, 14 Pro Max | 1290×2796 | `APP_IPHONE_67` | yes |
| iPhone 17 Pro, 17, 16 Pro | 1206×2622 | `APP_IPHONE_61` (6.3", **required**) | yes |
| iPhone 16, 15, 15 Pro, 14 Pro | 1179×2556 | `APP_IPHONE_61` (**required**) | yes |
| iPhone Duo | inner 2007×2853, outer 1398×2034 | `IPHONE_DUO_INNER`, `IPHONE_DUO_OUTER` | yes: two devices in the plan, each with `target.display` |
| iPhone 14 Plus, 13 Pro Max, 12 Pro Max | 1284×2778 | `APP_IPHONE_65` (6.5") | yes |
| iPhone 11 Pro Max, Xs Max | 1242×2688 | `APP_IPHONE_65` | yes |
| **iPhone 11, iPhone Xʀ** | **828×1792** | listed in 6.5" | **no**: not an accepted size |
| iPhone 17e, 16e, 14, 13, 13 Pro, 12, 12 Pro | 1170×2532 | `APP_IPHONE_58` | yes |
| iPhone 11 Pro, Xs, X | 1125×2436 | `APP_IPHONE_58` | yes |
| iPhone 13 mini, 12 mini | 1080×2340 | `APP_IPHONE_58` | yes, but avoid: a red banner in the status bar on recent Xcodes |
| iPhone 8 Plus | 1242×2208 | `APP_IPHONE_55` (5.5") | yes (check: the panel itself is 1080×1920) |
| iPhone SE (2nd, 3rd gen), 8 | 750×1334 | `APP_IPHONE_47` | yes |
| iPad Pro 13-inch (M4, M5) | 2064×2752 | `APP_IPAD_PRO_3GEN_129` (13", **required**) | yes |
| iPad Air 13-inch, iPad Pro 12.9" (3rd–6th gen) | 2048×2732 | `APP_IPAD_PRO_3GEN_129` | yes |
| iPad Pro 11-inch (M4, M5) | 1668×2420 | `APP_IPAD_PRO_3GEN_11` | yes |
| iPad Pro 11" (1st–4th gen) | 1668×2388 | `APP_IPAD_PRO_3GEN_11` | yes |
| iPad Air 11-inch, iPad (A16), iPad (10th gen) | 1640×2360 | `APP_IPAD_PRO_3GEN_11` | yes |
| iPad mini (A17 Pro), mini (6th gen) | 1488×2266 | `APP_IPAD_PRO_3GEN_11` | yes |
| Apple TV 4K | 3840×2160 | `APP_APPLE_TV` | yes |
| Apple TV 4K (at 1080p) | 1920×1080 | `APP_APPLE_TV` | yes |
| Apple Vision Pro | 3840×2160 expected | `APP_APPLE_VISION_PRO` | check the first capture |
| Apple Watch Ultra 4/3 · Ultra 2/1 · Series 12/11/10 · 9/8/7 · 6/5/4/SE · 3 | 422×514 · 410×502 · 416×496 · 396×484 · 368×448 · 312×390 | `APP_WATCH_*` | yes; the same size across all locales |
| (Mac: no simulator) | a window or the app's own render | `APP_DESKTOP`: 1280×800, 1440×900, 2560×1600, 2880×1800 (16:10) | [desktop.md](desktop.md) |

Landscape shots are the same sizes turned: `width` and `height` swapped in the plan, the app rotated.

## Android emulator profiles → Google Play

Play has no device classes: any picture within its rules is accepted. The hard rules: 320–3840 px a side, the
longest side at most twice the shortest (phones); tablets in the rules data 16:9 or 9:16, 1080–7680 px; Wear OS 1:1,
at least 384. Apps need at least 4 shots at 1080 px or more, 9:16 portrait or 16:9 landscape, to show in Play's
recommendation formats; games, three 16:9 at 1920×1080 or more.

| Profile id | Pixels | Ratio | As captured? | Do |
|---|---|---|---|---|
| `medium_phone` | 1080×2400 | 2.22 | **no** (over 2:1) | `wmSize: "1080x1920"` |
| `pixel_10`, `pixel_10a`, `pixel_9` | 1080×2424 | 2.24 | **no** | `wmSize: "1080x1920"` |
| `pixel_10_pro` | 1280×2856 | 2.23 | **no** | `wmSize: "1080x1920"` |
| `pixel_10_pro_xl`, `pixel_9_pro_xl` | 1344×2992 | 2.23 | **no** | `wmSize: "1080x1920"` |
| `small_phone` | 720×1280 | 9:16 | passes, but under 1080 | prefer a phone at `wmSize 1080x1920` |
| `small_tablet` (7") | 1920×1200 | 16:10 | not 16:9 | `wmSize: "1920x1080"` |
| `medium_tablet`, `pixel_tablet` (10") | 2560×1600 | 16:10 | not 16:9 | `wmSize: "2560x1440"` |
| `pixel_10_pro_fold` (inner) | 2076×2152 | about 1:1 | not 16:9 | `wmSize`, and `screencap -d` for the display |
| `desktop_large` | 1920×1080 | 16:9 | yes (Chromebook) | |
| `desktop_medium` | 3840×2160 | 16:9 | yes | |
| `desktop_small` | 1366×768 | about 16:9 | **no** (under 1080) | |
| `tv_1080p`, `tv_4k` | 1920×1080, 3840×2160 | 16:9 | yes (Android TV) | |
| `tv_720p` | 1280×720 | 16:9 | passes, small | prefer `tv_1080p` |
| `automotive_portrait`, `automotive_1024p_landscape` | 800×1280, 1024×768 | | yes: exactly Play's | |
| `wearos_*` | square | 1:1 | yes, at least 384 | no mask, no transparency |
| `xr_headset_device` | 2560×2558 | about 1:1 | **no**: Android XR wants 8:5 (3840×2400) | |

The simplest consistent Play set: every phone at `wmSize 1080x1920`, every tablet at a 16:9 `wmSize`. Apple TV's
3840×2160 captures can double as Android TV ones when the UI is the same.

## Web viewports → any store size

Viewport × device scale factor ([web.md](web.md)): iPhone 6.9" 440×956 @3; 6.3" 402×874 @3; iPad 13" 1032×1376 @2;
Mac 1440×900 @2; Play phone 360×640 @3; a 16:9 tablet 1280×720 @2. The layout is the web's, with no system bars.

## Engines → any size

Render targets of the exact size ([engines.md](engines.md)).

## When the size is wrong

Pick another device type or profile, set `wmSize`, or change the viewport. **Never resize, crop or pad the
picture.** The one exception is a preview video, whose sizes are the store's own: `video.py encode` scales within
the same aspect ([video.md](video.md)).
