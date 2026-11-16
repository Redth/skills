# Staging for the store captures

Generated from `capture-plan.json` by `capture.py --write-staging`: edit the plan's `staging` and screens, then write this again. Agreed with the user before the first capture; reused on every later one.

**Confirmed** on `plan` (iphone-6.9), 2026-10-02.

## Signing in

- A debug sign-in bypass.
- How: the Debug build's SampleRecipesFakeSession

## Data

- Kind: file
- File: `store/demo/recipes.db` into the app's data at `cache/recipes/recipes.db` (android), `Library/Caches/recipes/recipes.db` (ios)
- When: before every screen
- How: made by store/seed-tool from the UI tests' demo week (invented recipes), dates shifted to this week

## Every launch gets

- `SampleRecipesApi` = `http://127.0.0.1:9` (args)
- `SampleRecipesFakeSession` = `demo` (args)
- `SampleRecipesApi` = `http://127.0.0.1:9` (env)
- `SampleRecipesFakeSession` = `demo` (env)

## Skipped

- onboarding: the fake session marks it seen
- rating prompt: the Debug build never asks

## Permissions granted before launch

- android: android.permission.POST_NOTIFICATIONS

## Date and time

- The status bar: 09:41
- The app's now: the real time
- How: no screenshot mode: the screens chosen show no clock times

## Network

- offline
- How: the API override is a closed port; pages read the cache

## Screens

| Screen | Shows | Reached by | Checked |
|---|---|---|---|
| `plan` | this week's plan, five invented dinners, Tuesday open | launch → wait {id: plan-title, timeout: 60} → settle | text `Lemon Pasta` |
| `recipe` | Lemon Pasta open at its steps | launch → tap {id: plan-day-tuesday} → wait {id: recipe-title} | id `recipe-steps` |
| `shopping` | the week's shopping list, twelve items, three ticked | launch → tap {id: tab-shopping} → wait {id: shopping-list} | text `Parmesan` |
