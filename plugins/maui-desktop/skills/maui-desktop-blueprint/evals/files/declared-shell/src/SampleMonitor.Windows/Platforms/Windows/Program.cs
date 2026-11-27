namespace SampleMonitor.Windows;

public static class Program
{
    public static void Main()
    {
        var main = AppInstance.FindOrRegisterForKey("main");
    }
}
