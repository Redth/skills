namespace SampleMonitor.Core.Shell;

public sealed record DialogRequest(string Title, string Body);

public sealed class DialogSession
{
    public DialogSession(DialogRequest request) => Request = request;

    public DialogRequest Request { get; }
}
