namespace SampleMonitor.Windows;

public sealed class WinTray
{
    [DllImport("shell32.dll")]
    static extern bool Shell_NotifyIcon(uint message, ref NotifyIconData data);
}
