namespace SampleNotes.Pages.Forms;

// A native page with a web view inside, presented modally; each dialog subclasses it.
public abstract class HybridFormPage<TResult> : ContentPage
{
    public Task<TResult?> ShowAsync() => Task.FromResult(default(TResult));
}
