namespace SampleMonitor.Core.Shell;

public sealed record ChromeAction(string Id, string Label, string Icon);

public sealed record PageChrome(string Title, IReadOnlyList<ChromeAction> Actions);
