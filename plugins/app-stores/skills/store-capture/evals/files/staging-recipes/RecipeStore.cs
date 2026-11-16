// Sample Recipes: the local cache every page reads first (SQLite), filled from the API after sign-in.
namespace SampleRecipes.Data;

public sealed class RecipeStore
{
    // FileSystem.CacheDirectory: Library/Caches on iOS, cache/ on Android.
    public static string DatabasePath => System.IO.Path.Combine(FileSystem.CacheDirectory, "recipes", "recipes.db");

    public RecipeStore(IEnvironmentInfo env) { /* opens DatabasePath with Microsoft.Data.Sqlite */ }
    public void Upsert(System.Collections.Generic.IEnumerable<Recipe> recipes) { }
    public void Upsert(System.Collections.Generic.IEnumerable<PlanDay> days) { }
}
