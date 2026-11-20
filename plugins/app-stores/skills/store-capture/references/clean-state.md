# Clean state: demo data, the clock, the status bar, locale, appearance

A store screenshot shows the app at its best, in a state anyone could be in, the same on every device. What the
drivers set, what the app must provide, and what to look for. Which screens, who's signed in and what data each
shows is agreed with the user first and recorded in the plan's `staging`: [staging.md](staging.md).

## One state, every device, one pass

Every device of the plan captures the same moment: one `seed`, one `clock`, one data set, in one run. The phone
and tablet sets then tell the same story, and `store-screenshots` can line them up. Don't capture the iPhone set
on Monday with live data and the iPad set on Friday.

## Demo data (the app's job)

- **Seeded and fictional.** The app's screenshot mode (or a fixture the driver installs, like
  `simctl install_app_data`) loads demo content for the plan's `seed`. Nobody real: invented names, faces from a
  generator or licensed stock, emails and sites on `example.com`/`.org`/`.net` (reserved for examples),
  phone numbers in the fictional 555-01xx range, addresses that don't exist.
- **Never a real account**, the user's contacts or photos, a tester's name, a customer's data, or a staging account
  with real people's content. A demo account on a staging backend, reset before each run, its sign-in only in
  environment variables (`staging.account.env`), or (better) a guest mode, a debug bypass or an offline fixture
  mode ([staging.md](staging.md)).
- **Without a screenshot mode**, seed the app's own data file before launch (`staging.seed`: a `command`, or a
  `file` copied into its data container): [staging.md](staging.md#net-maui-without-a-screenshot-mode).
- **Translated with the locale.** A German shot full of English recipe names looks wrong; so does a US date format
  in Japan. Demo data per locale, or neutral content that reads in every one.
- **No one else's marks:** no other apps' logos or names, real brands, other platforms' names or devices (Apple's
  guideline 2.3.10), copyrighted art the user hasn't cleared. Flag anything readable to the user.
- **Content right for every store's audience:** Apple asks every screenshot to suit 4+, whatever the app's rating.
- **Offline.** Fixtures served locally: no spinners waiting on a network, no rate limits, the same every run.
- **In use.** Each screen as someone mid-task sees it: forms partly filled with believable values (typed with
  `fill`, never saved unless that's the point), lists populated, no empty states or placeholder-only fields. Agreed
  per screen (`inUse`), and the user's rule for all of them in `staging.inUse` ([staging.md](staging.md#looking-in-use)).

## The clock

- The **status bar's time** is the plan's `clock` (`09:41` by default, the time Apple's own pictures show; any
  fixed time on Android).
- The **app's "now"** must agree: "2 minutes ago", today's date, a calendar, a greeting ("Good morning"), a
  streak, an expiry. The simulator's clock follows the Mac's and can't be set; the app takes "now" from its
  screenshot mode (`ScreenshotNow`, [screenshot-mode.md](screenshot-mode.md)).
- **No screenshot mode?** Then on-screen times show the real clock ("9:30 PM" under a "9:41" status bar). Say so to
  the user, and either pick screens that show no time, shift the seed so relative times read well and accept the
  absolute ones, or add `ScreenshotNow`. Record the choice in `staging.clock`.
- Avoid dates that age the shot: seasons, holidays, a year in a footer.

## The status bar

| Platform | How | Detail |
|---|---|---|
| iOS, iPadOS | `simctl status_bar <udid> override --time 9:41 --batteryState charged --batteryLevel 100 …`, after every boot | [simctl.md](simctl.md#status-bar) |
| Android | SystemUI demo mode broadcasts | [adb.md](adb.md#status-bar-systemui-demo-mode) |
| Apple TV, Vision Pro, Android TV, Wear, web, Mac windows, games | none to clean | `statusBar` is `none` |

- **Verify it.** Overrides have failed silently on some iOS runtimes, vanish on reboot or erase, and some Android
  makers' skins ignore demo mode. The report's `statusBar` says `verified` (iOS: read back; Android: its pixels
  followed demo mode's clock), `unverified` (failed, or couldn't be confirmed) or `overridden` (the check turned
  off); look at the icons at the top of every picture regardless.
- The same time on every device and locale.
- Play: no carrier, no notifications; battery, Wi-Fi and signal full.

## Locale

- **The app's language** (a launch argument, `cmd locale set-app-locales`, the browser's `Accept-Language`) is
  enough when only the app shows.
- **The device's language** is needed when system UI shows: an alert, a permission prompt, the keyboard, the share
  sheet, the date in an iPad's status bar. The drivers set it per locale (a reboot on Apple simulators) and put it
  back.
- Right-to-left locales mirror the layout: capture them, don't flip an English shot.
- Long German words and CJK text break layouts at unusual shapes: look at each locale's shots.
- Install fonts for every script on Linux hosts (web), or text renders as boxes.

## Appearance

`appearance` sets light or dark for the run (`simctl ui … appearance`, `cmd uimode night`, `prefers-color-scheme`).
A set is all light or all dark unless the user wants a shot of each. Dynamic Type / font scale stays at the
default (`content_size large`, `font_scale 1.0`) unless a shot is about accessibility.

## Nothing transient

| What | How to keep it out |
|---|---|
| Permission prompts | grant before launch: `staging.permissions` (the drivers run `simctl privacy … grant`, `pm grant`), Maestro's `permissions`, Appium's `autoGrantPermissions` |
| Onboarding, "rate this app", what's new, tooltips, cookie notices | the screenshot mode skips them; or the app's data marks them seen |
| Toasts, snackbars, banners | wait for them to go (`wait`, `settle`), or don't trigger them |
| Spinners, skeletons | offline fixtures; `wait` for the content's element, then `settle` |
| Animations mid-way | animations off (`UIView.setAnimationsEnabled(false)`, the animation scales at 0, reduced motion); `settle` |
| Scroll bars | `settle` after a scroll (they fade) |
| The keyboard | decide per shot; usually a filled, unfocused field looks better: fill forms with `fill` (it closes the keyboard and clears the focus), or end the steps with `hideKeyboard` and add `{ "keyboard": "hidden" }` to `verify`. Android: back, only while the keyboard is up; iOS through Appium: the keyboard's Done or Return, then **the app's own Done** (a number pad has no key that closes it: the app's accessory or floating Done/Close button does; give it as `done` when it isn't named Done or Close); a tap outside the field only last (many apps don't close the keyboard for it); an iOS app driven by an agent: `{ "hideKeyboard": { "done": <the app's Done>, "tap": <a label outside the field> } }`; never iOS's `back`, which navigates. A screen that types nothing is checked for it anyway ([config.md](config.md#the-keyboard-focus-and-forms)) |
| A text caret | closing the keyboard doesn't clear the field's focus (Android's back leaves it focused), and a shot lands with the caret on or off: `unfocus` after typing (`fill` does it): on Android Escape while a field has the focus, checked; else `{ "unfocus": { "tap": … } }` |
| A form scrolled mid-way | typing scrolls a long form: `fill`'s `"scrollTo": "top"` or a `scroll {"to": "top"}` step after the keyboard is down |
| Touch indicators | `show_touches 0`, `pointer_location 0` |
| Focus rings | only where wanted (TV shots want one on a meaningful item) |
| Notifications arriving | demo mode's `notifications visible false`; the dedicated simulator has none |

## No debug UI

Flutter's debug banner (`debugShowCheckedModeBanner: false`, or a profile build), React Native's LogBox and dev
menu, Expo's dev client overlay, FPS counters, "BETA" or build-number watermarks, the in-app agents' own overlays
(if any), test accounts' names, a staging environment's label. A release-like screenshot build avoids most of it.

## Reset

Everything changed is put back in `finally`: the status bar, demo mode, `wm size` and density, locale, appearance,
animation scales, touch indicators, permissions granted for the run. On a dedicated simulator or emulator, erasing
it is the reset; on a device the user named, each value goes back to what it was before.
