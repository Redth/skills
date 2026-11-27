namespace SampleNotes.MacOS;

// Builds the window: a FlyoutPage whose flyout becomes the native sidebar.
public sealed class MacApp
{
    FlyoutPage? _flyout;

    void AddMenuItems()
    {
        var mainMenu = NSApplication.SharedApplication.MainMenu;
        mainMenu.AddItem(new NSMenuItem("Export…"));
    }

    void RestoreFrame(NSWindow window) => window.SetFrameAutosaveName("SampleNotesMain");
}
