namespace SampleMonitor.MacOS;

// UNUserNotificationCenter needs a signed app, so this head posts no notifications yet.
public sealed class StatusItem
{
    readonly NSStatusItem _item = NSStatusBar.SystemStatusBar.CreateStatusItem(NSStatusItemLength.Variable);
}
