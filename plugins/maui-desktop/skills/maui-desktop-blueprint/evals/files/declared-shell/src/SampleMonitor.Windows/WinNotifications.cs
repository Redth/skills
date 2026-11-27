namespace SampleMonitor.Windows;

public sealed class WinNotifications
{
    public void Show(string title) => AppNotificationManager.Default.Show(new AppNotificationBuilder().AddText(title).BuildNotification());
}
