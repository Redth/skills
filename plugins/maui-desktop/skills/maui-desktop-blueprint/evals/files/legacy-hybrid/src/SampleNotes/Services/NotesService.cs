namespace SampleNotes.Services;

public sealed class NotesService
{
    public void SaveWindowSize(double width) => Preferences.Set("window_width", width);
}
