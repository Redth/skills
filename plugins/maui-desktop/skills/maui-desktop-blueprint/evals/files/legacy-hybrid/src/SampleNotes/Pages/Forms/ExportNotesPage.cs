namespace SampleNotes.Pages.Forms;

public record ExportResult(string Path);

// An older draft was: public class ExportDraftPage : HybridFormPage<int>
public sealed class ExportNotesPage : HybridFormPage<ExportResult>
{
}
