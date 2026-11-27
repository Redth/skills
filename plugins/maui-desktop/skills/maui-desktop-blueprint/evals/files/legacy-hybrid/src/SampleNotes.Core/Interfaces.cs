namespace SampleNotes.Core;

public record ToolbarAction(string Id, string Label, string SfSymbol, bool IsPrimary = true);

public interface IToolbarService
{
    void SetItems(params ToolbarAction[] items);
}
