# Ailoha

Ailoha (https://ailoha.dev) gives an agent eyes and hands in native apps: an agent inside the app's debug build
serves its UI tree, actions (tap, type, scroll, navigate) and screenshots over HTTP on the local machine, on real
native views, with no browser or WebDriver. The same protocol across stacks: .NET MAUI, native Android, Flutter,
React Native, Expo, WinUI 3, WPF and Swift on Apple platforms (check ailoha.dev for the current list and each
stack's setup; the CLI's `--platform` takes `ios`). The CLI is `ailoha` (npm: `@ailoha/cli`),
which is also an MCP server.

Use the `ailoha` driver when the app already has the agent. It's one technique for many stacks: Flutter and React
Native apps, whose views are hard for outside tools to find, are where it helps most.

## In the app (debug builds only)

| Stack | Package | Started by |
|---|---|---|
| .NET MAUI | NuGet `Ailoha.Agent.Maui` | `builder.AddMauiDevFlowAgent();` in `MauiProgram.cs`, inside `#if DEBUG` |
| Android (Kotlin) | `debugImplementation("com.ailoha:ailoha-android-agent:<version>")` (and `-compose`, `-okhttp`, `-timber` add-ons), and `releaseImplementation` of `ailoha-android-agent-noop`; Compose ids from `Modifier.testTag` | `AilohaAndroidAgent.start(application = this, options = AilohaAgentOptions(appName = "Sample Recipes"))` in `Application.onCreate`, inside `if (BuildConfig.DEBUG)` |
| Flutter | `flutter pub add ailoha_agent`; ids from `ValueKey<String>` | `await initAgent();` early in `main()`, inside `if (kDebugMode)` |
| React Native | `npm install @ailoha/react-native` | `initAgent({ port: 9233 })` from `App.tsx`, inside `if (__DEV__)` (the guard tree-shakes it from release bundles) |
| Expo | the same `@ailoha/react-native` (autolinked by prebuild; not an `expo.plugins` entry) | as React Native; needs a development build (`expo prebuild` + `expo run:ios`/`run:android`, or an EAS development build), not Expo Go |
| Swift (iOS and other Apple platforms) | Swift Package `AilohaAgent` from `https://github.com/Redth/ailoha-releases` (a binary package) | `try? await Agent.shared.start()` from a `.task`, inside `#if DEBUG` |
| WinUI 3, WPF | the native agents in ailoha.dev's guides | |

The guards keep the agent out of store builds; flag one that isn't guarded (agent rule 8). Give the controls
stable ids: `AutomationId`, a resource id or test tag, `testID`, a Flutter `Key` or semantics identifier.

## The CLI

```sh
npm install -g @ailoha/cli          # or ailoha.dev's install script
ailoha init                         # detects the project's framework, wires in the agent's skills
ailoha agent list --json            # running apps with an agent
ailoha agent wait                   # until the app's agent answers
ailoha ui tree --depth 2
ailoha ui tap --automationId "search"                      # or --text "Search", or an element id
ailoha ui fill --automationId "search-field" "pasta"
ailoha ui query --automationId "recipe-title" --wait-until exists --timeout 10   # --selector for CSS
ailoha ui scroll --element <element id>                    # into view; or --dy -400
ailoha ui swipe 540 1500 540 500 --duration 300
ailoha ui navigate --back
ailoha ui wait-for-idle --timeout-ms 2000                  # pending frames and animations
ailoha ui screenshot --output ./shot.png --scale native --overwrite
ailoha diagnose                                            # when the agent isn't found
```

Global options: `--agent-port` (`-ap`; else the environment or project selection, then the broker, then 9233),
`--agent-host` (`-ah`; `AILOHA_AGENT_HOST`, else 127.0.0.1), `--platform` (`-p`: `maui`, `flutter`,
`react-native`, `expo`, `android`, `ios`, `maccatalyst`, `winui`, `wpf`; **default `maccatalyst`**, so name it for
anything else), `--json`. Also there: `ui navigate --reset <route>`, `ui fill --append`, `ui debug-overlays
'{"…": false}'` (turn the framework's debug overlays off), `agent select`, and `batch` (JSON lines on stdin).
`ailoha --help` gives the rest on the user's version.

## Where the agent listens

- `localhost`, port **9233** by default, falling back through **9238** if taken; a local broker (port 19323)
  registers agents so clients can find them. The CLI resolves an app by explicit arguments, then
  `AILOHA_AGENT_HOST` / `AILOHA_AGENT_PORT` (or the project's `.devflow` selection), then the broker, then the
  default port.
- The protocol is DevFlow's (ailoha.dev's protocol page): `GET /api/v1/agent/status`, `GET
  /api/v1/agent/capabilities`, `GET /api/v1/ui/tree` (`depth`, `layer` = `framework` | `native` | `render`,
  `rootId`), `GET /api/v1/ui/screenshot`, `POST /api/v1/ui/actions/tap` (`elementId`), `POST
  /api/v1/ui/actions/fill` (`elementId`, `text`), `POST /api/v1/ui/actions/scroll`, `POST
  /api/v1/ui/actions/navigate`; elements by `GET /api/v1/ui/elements?strategy=accessibility-id|css-selector|type|
  text|xpath&value=…`, and screenshots also as `format=png|jpeg` (the driver asks for PNG).
- **Android:** the CLI's discovery forwards the port; if it doesn't find the agent, `adb -s <serial> forward
  tcp:9233 tcp:9233`. A forward the driver adds is removed after.

## Which agent

As with DevFlow ([devflow.md](devflow.md#which-agent-pinned-to-the-app-on-the-device-it-owns)), the driver pins the
agent of the plan's app on the device it owns: it lists the agents (`ailoha agent list --json`), reads each one's
status (`/api/v1/agent/status`: device, package, process) and passes `--agent-port` on every command; on Android
the CLI runs with `ANDROID_SERIAL` set to the device's serial, so the forwards it makes go there. An agent that
can't be told apart (an older agent with no status) needs `target.agentPort`, checked by hand with `ailoha agent
list`. A tap the agent answers `success: false` fails the step.

## The plan

```json
{ "id": "flutter-android", "platform": "android", "kind": "phone", "driver": "ailoha", "width": 1080, "height": 1920,
  "target": { "systemImage": "system-images;android-36;google_apis;arm64-v8a", "profile": "medium_phone",
              "wmSize": "1080x1920", "agentPlatform": "flutter" } }
```

```json
{ "id": "recipe", "steps": [
    { "launch": { "args": { "ScreenshotScreen": "plan" } } },
    { "tap": { "text": "Lemon pasta" } },
    { "wait": { "id": "recipe-title" } },
    { "settle": true } ] }
```

**The device has a host**, as for DevFlow ([devflow.md](devflow.md#the-plan)): `simctl` or `adb` boots the
dedicated device, installs the debug build, sets the locale, appearance and clean status bar, launches the app and
opens deep links, and resets it all after (`wmSize` for Play's 2:1 limit; [adb.md](adb.md)). The agent's own
`target` fields are the same: `agentPort`, `agentPlatform` (set it for Flutter, React Native and Expo apps),
`appName`, `agentTimeout` (default 90 s), `cli`, `host`, `screenshot`.

After each `launch` the driver waits for the agent and runs the steps through it. Elements by `id` (the automation
id, resource id, test id or key the agent reports), `text`, `css` or `xpath`; not `label`. Element ids are the
agent's own and go stale when the screen changes; the driver finds each element again for every step. `settle` first asks
the agent to wait for idle (pending frames and animations), then waits for two identical frames.

## The picture

With a host, the picture is the host's: the device's whole framebuffer, status bar included, at its native size.
Without one (a WinUI or WPF app), or with `target.screenshot: "agent"`, it's the agent's `ui screenshot --scale
native`: the app's window, without the system's bars. Check the size and the top edge either way.

## Debug builds look different

Flutter's debug banner (`debugShowCheckedModeBanner: false`), React Native's LogBox and dev menu, Expo's dev-client
overlay: hide them in the screenshot mode, and check every capture.
