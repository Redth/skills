// Sample Recipes: hooks only the Debug build honours (UI tests and screenshots).
namespace SampleRecipes;

public static class DebugHooks
{
#if DEBUG
    // A fake signed-in session: no server sign-in at all.
    public static string? FakeSession => Read("SampleRecipesFakeSession");
    // Point the API somewhere else (a closed port makes the app use its local cache only).
    public static string? ApiOverride => Read("SampleRecipesApi");

    static string? Read(string key)
    {
#if IOS || MACCATALYST
        return Foundation.NSUserDefaults.StandardUserDefaults.StringForKey(key)
            ?? System.Environment.GetEnvironmentVariable(key);
#elif ANDROID
        return Microsoft.Maui.ApplicationModel.Platform.CurrentActivity?.Intent?.GetStringExtra(key);
#else
        return System.Environment.GetEnvironmentVariable(key);
#endif
    }
#else
    public static string? FakeSession => null;
    public static string? ApiOverride => null;
#endif
}
