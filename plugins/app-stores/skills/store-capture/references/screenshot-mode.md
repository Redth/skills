# Adding a screenshot mode to an app

The cheapest way to capture any stack: the app itself, told by a launch argument, an intent extra, a deep link or
a URL query, opens a named screen with seeded demo data and a fixed clock. Then `simctl`, `adb`, `chrome` or
`macos` capture it with no taps, no element ids and no test framework, on every device size in one pass.

A code change in the user's app: propose it, show the diff, and let them decide (agent rule 9).

## What the mode does

At launch, if (and only if) it's switched on:

1. **Reads three values:** `ScreenshotScreen` (which screen, by the plan's screen id or the app's own route),
   `ScreenshotSeed` (which demo data; the drivers pass the plan's `seed` under this name) and, optionally,
   `ScreenshotNow` (an ISO 8601 date-time to use as "now", e.g. `2026-06-01T09:41:00Z`; the app shows it in the
   device's time zone, so set that too or pass the offset that makes the clock read 9:41).
2. **Loads demo data** from the app's own fixtures for that seed: fictional people, `example.com` addresses,
   generated avatars, content translated per locale. Offline: no network calls, no spinners
   ([clean-state.md](clean-state.md)).
3. **Fixes "now"** through whatever clock the app reads (inject one if it calls the system clock directly), so
   "2 minutes ago", calendars and greetings come out the same every run and agree with the status bar's 9:41.
4. **Removes what shouldn't show:** onboarding, "rate this app", what's-new sheets, tooltips, cookie notices,
   debug banners and menus, build numbers, sign-in (it's signed in as the demo account).
5. **Turns off animations** where the platform lets it, so the first settled frame is the final one.
6. **Opens the screen,** through the app's own navigation, the same route a deep link would take.

## Keeping it out of store builds

Compile it in only for debug or a screenshot build: a compilation condition (`SCREENSHOTS`, or `DEBUG`), a build
type or flavour (`screenshots`), a `--dart-define`, `__DEV__`. A release build that ignores the arguments is the
safe default. Some stacks show debug UI in debug builds (Flutter's banner, React Native's LogBox): a release-like
screenshot build is better there.

## How launch values arrive, per platform

| Platform | Sent by | Read with |
|---|---|---|
| iOS, iPadOS, tvOS, watchOS, visionOS | `xcrun simctl launch <udid> <bundle id> -ScreenshotScreen plan -ScreenshotSeed demo` | `UserDefaults.standard.string(forKey: "ScreenshotScreen")` (a `-Key value` pair lands in the arguments domain) or `ProcessInfo.processInfo.arguments` |
| iOS, environment | `SIMCTL_CHILD_SCREENSHOT_SCREEN=plan` in the caller's environment | `ProcessInfo.processInfo.environment["SCREENSHOT_SCREEN"]` |
| Android | `adb shell am start -W -n com.example.samplerecipes/.MainActivity --es ScreenshotScreen plan --es ScreenshotSeed demo` | `intent.getStringExtra("ScreenshotScreen")` |
| Deep link, iOS | `xcrun simctl openurl <udid> 'samplerecipes://screenshot/plan?seed=demo'` | the app's URL handling |
| Deep link, Android | `adb shell am start -W -a android.intent.action.VIEW -d 'samplerecipes://screenshot/plan?seed=demo' com.example.samplerecipes` | the activity's intent data |
| Web | `http://localhost:8080/?screenshot=plan&seed=demo` | the URL's query |
| Mac | `open -a SampleRecipes --args -ScreenshotScreen plan` or launching the binary with arguments | as iOS |

Launch arguments are better than deep links for the first screen: a deep link arrives after launch (a frame of
the home screen can show first), and some apps reject unknown links. Deep links are good for the screens after.

## Sketches

Each is the shape, not a library: route names, the fixture loader and the clock are the app's own.

### SwiftUI

```swift
struct ScreenshotMode {
    let screen: String?
    let seed: String
    let now: Date?

    static let current: ScreenshotMode? = {
        #if DEBUG || SCREENSHOTS
        let d = UserDefaults.standard
        guard let screen = d.string(forKey: "ScreenshotScreen") else { return nil }
        let now = d.string(forKey: "ScreenshotNow").flatMap { ISO8601DateFormatter().date(from: $0) }
        return ScreenshotMode(screen: screen, seed: d.string(forKey: "ScreenshotSeed") ?? "demo", now: now)
        #else
        return nil
        #endif
    }()
}

@main
struct SampleRecipesApp: App {
    @State private var model: AppModel

    init() {
        if let mode = ScreenshotMode.current {
            UIView.setAnimationsEnabled(false)
            _model = State(initialValue: AppModel(store: .demo(seed: mode.seed),
                                                  clock: .fixed(mode.now ?? .demoNow),
                                                  route: Route(mode.screen ?? "plan")))
        } else {
            _model = State(initialValue: AppModel())
        }
    }

    var body: some Scene {
        WindowGroup { RootView().environment(model) }
    }
}
```

### UIKit

```swift
func application(_ application: UIApplication,
                 didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
    #if DEBUG || SCREENSHOTS
    if let screen = UserDefaults.standard.string(forKey: "ScreenshotScreen") {
        UIView.setAnimationsEnabled(false)
        AppEnvironment.current = .screenshots(seed: UserDefaults.standard.string(forKey: "ScreenshotSeed") ?? "demo")
        Router.shared.startAt(screen)          // skips onboarding and sign-in
    }
    #endif
    return true
}
```

### Jetpack Compose / Android

```kotlin
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val screen = if (BuildConfig.SCREENSHOTS) intent.getStringExtra("ScreenshotScreen") else null
        val env = if (screen != null) {
            AppEnvironment.screenshots(
                seed = intent.getStringExtra("ScreenshotSeed") ?: "demo",
                now = intent.getStringExtra("ScreenshotNow")?.let(LocalDateTime::parse) ?: DemoData.NOW,
            )
        } else AppEnvironment.live(this)
        setContent { SampleRecipesApp(env, startRoute = screen ?: "plan") }
    }
}
```

`BuildConfig.SCREENSHOTS` from a build type: `buildTypes { create("screenshots") { initWith(getByName("release"));
buildConfigField("boolean", "SCREENSHOTS", "true"); signingConfig = signingConfigs.getByName("debug") } }` (and
`false` in the others). Animations: the `adb` driver sets the global animation scales to 0.

### .NET MAUI

```csharp
public static class ScreenshotMode
{
    public static string? Screen { get; private set; }
    public static string Seed { get; private set; } = "demo";

    public static void Read()
    {
#if DEBUG || SCREENSHOTS
#if IOS || MACCATALYST
        var d = Foundation.NSUserDefaults.StandardUserDefaults;
        Screen = d.StringForKey("ScreenshotScreen");
        Seed = d.StringForKey("ScreenshotSeed") ?? Seed;
#elif ANDROID
        var intent = Microsoft.Maui.ApplicationModel.Platform.CurrentActivity?.Intent;
        Screen = intent?.GetStringExtra("ScreenshotScreen");
        Seed = intent?.GetStringExtra("ScreenshotSeed") ?? Seed;
#endif
#endif
    }
}

// App.xaml.cs
protected override Window CreateWindow(IActivationState? activationState)
{
    ScreenshotMode.Read();
    if (ScreenshotMode.Screen is { } screen)
    {
        DemoData.Load(ScreenshotMode.Seed);          // fixtures behind the app's services
        Dispatcher.Dispatch(async () => await Shell.Current.GoToAsync($"//{screen}"));
    }
    return new Window(new AppShell());
}
```

Register the demo services in `MauiProgram.cs` when the mode is on, so pages resolve fixtures instead of the live
API. Set `AutomationId` on the controls a driver may need: DevFlow, Ailoha, Appium and Maestro all find them (on
the element that has the tap gesture, not a label inside it: DevFlow's taps reach only that).

Without a screenshot mode yet, a MAUI app's local data file can be written before launch instead (a console tool
using the app's own store class, then `staging.seed` `file`): [staging.md](staging.md#net-maui-without-a-screenshot-mode).
For Android, build the Debug APK with `-p:EmbedAssembliesIntoApk=true` so it runs after `adb install`.

### Flutter

Dart can't see iOS launch arguments or Android extras directly. Two ways:

```dart
// 1. A screenshot build: flutter build ios --dart-define=SCREENSHOT_SCREEN=plan --dart-define=SCREENSHOT_SEED=demo
//    (one build, the screen named at launch by a deep link instead, is usually better)
const screenshotScreen = String.fromEnvironment('SCREENSHOT_SCREEN');

// 2. A small channel that hands Dart the launch values.
const _channel = MethodChannel('com.example.samplerecipes/screenshot');

Future<Map<String, String>> launchValues() async =>
    Map<String, String>.from(await _channel.invokeMethod('launchValues') ?? {});

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final values = kReleaseMode && !const bool.fromEnvironment('SCREENSHOTS') ? {} : await launchValues();
  final screen = values['ScreenshotScreen'];
  runApp(SampleRecipesApp(
    env: screen == null ? AppEnv.live() : AppEnv.screenshots(seed: values['ScreenshotSeed'] ?? 'demo'),
    initialRoute: screen ?? '/plan',
  ));
}
```

The native halves: iOS `UserDefaults.standard` values for the keys; Android `intent.getStringExtra` for each, in a
`MethodChannel` handler on the `FlutterEngine`. `MaterialApp(debugShowCheckedModeBanner: false)` hides the debug
banner; a profile or release-like build hides the rest. Deep links: with Flutter's deep linking on, a
`go_router` route like `/screenshot/:screen` takes `simctl openurl` and `am start -d` as they are.

### React Native and Expo

```tsx
// Bare React Native: react-native-launch-arguments reads iOS arguments and Android extras.
import { LaunchArguments } from 'react-native-launch-arguments';
type Launch = { ScreenshotScreen?: string; ScreenshotSeed?: string };
const launch = LaunchArguments.value<Launch>();

export default function App() {
  const screen = SCREENSHOTS ? launch.ScreenshotScreen : undefined;   // SCREENSHOTS from the build's env
  return (
    <DataProvider source={screen ? demoData(launch.ScreenshotSeed ?? 'demo') : liveData()}>
      <NavigationContainer initialState={screen ? stateFor(screen) : undefined}>{/* … */}</NavigationContainer>
    </DataProvider>
  );
}
```

Expo (and any app with a URL scheme): use a deep link, `samplerecipes://screenshot/plan?seed=demo`, read with
`Linking.getInitialURL()` or Expo Router's routes. Capture a release-like build: no LogBox, dev menu, "Downloading
bundle" banner or dev-client overlay.

### Web

```ts
const params = new URLSearchParams(location.search);
const screen = import.meta.env.MODE !== 'production' || import.meta.env.VITE_SCREENSHOTS
  ? params.get('screenshot') : null;
if (screen) {
  installDemoData(params.get('seed') ?? 'demo');   // fixtures in place of fetch
  freezeClock(params.get('now') ?? '2026-06-01T09:41:00');
  document.documentElement.classList.add('no-motion');   // CSS: * { animation: none !important; transition: none !important; }
  router.replace(`/${screen}`);
}
```

## Then the plan

```json
{ "id": "plan", "steps": [ { "launch": { "args": { "ScreenshotScreen": "plan" }, "clean": true } },
                           { "wait": { "id": "plan-title", "timeout": 10 } } ] }
```

`clean: true` reinstalls or clears the app's data first; `seed` is added to the launch values by the driver. On
`chrome` the same screen is `{ "url": "http://localhost:8080/?screenshot=plan" }`.
