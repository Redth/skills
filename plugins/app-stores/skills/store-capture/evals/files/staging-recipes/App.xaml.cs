namespace SampleRecipes;

public partial class App : Application
{
    protected override Window CreateWindow(IActivationState? activationState)
    {
        // First launch: onboarding (three pages), then sign-in. After the third launch, a rating prompt.
        var page = Preferences.Get("onboarded", false) ? (Page)new AppShell() : new OnboardingPage();
        if (DebugHooks.FakeSession is null && !Session.SignedIn)
            page = new SignInPage();   // email + password against api.samplerecipes.example
        return new Window(page);
    }
}
