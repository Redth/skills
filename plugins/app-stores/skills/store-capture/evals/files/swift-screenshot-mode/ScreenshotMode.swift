import Foundation

/// Launch with `-ScreenshotScreen <plan|recipe|shopping|profile>` (and optionally `-ScreenshotSeed <name>`) to open a
/// screen with demo data. Compiled into Debug builds only.
struct ScreenshotMode {
    let screen: String
    let seed: String

    static var current: ScreenshotMode? {
        #if DEBUG
        let defaults = UserDefaults.standard
        guard let screen = defaults.string(forKey: "ScreenshotScreen") else { return nil }
        return ScreenshotMode(screen: screen, seed: defaults.string(forKey: "ScreenshotSeed") ?? "demo")
        #else
        return nil
        #endif
    }
}
