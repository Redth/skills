# Staging for the store captures

Generated from `capture-plan.json` by `capture.py --write-staging`: edit the plan's `staging` and screens, then write this again. Agreed with the user before the first capture; reused on every later one.

**Confirmed** on `plan` (iphone-6.9), 2026-11-18.

## Signing in

- A debug sign-in bypass.
- How: the Debug build's SampleRecipesFakeSession

## Data

- Kind: file
- File: `store/demo/recipes.db` into the app's data at `cache/recipes.db` (android), `Library/Caches/recipes.db` (ios)
- When: before every screen

## Every launch gets

- `SampleRecipesFakeSession` = `demo` (args)
- `SampleRecipesFakeSession` = `demo` (env)

## Date and time

- The status bar: 09:41

## Network

- offline

## Looking in use

- The rule: generally most screens we capture should look like they're somewhat filled out, in use (the user, in chat, 2026-11-18)
- Believable values: a family cooking for four: everyday dinners, metric amounts, invented names
- Saved: no: forms are captured filled, before they're saved

## Postures and layouts

- `fold-open`: open, the wide layout

## Screens

| Screen | Shows | In use | Reached by | Checked |
|---|---|---|---|---|
| `plan` | this week's plan, five invented dinners | the week planned, Tuesday's dinner ticked off | launch → wait {id: plan-title} | text `Lemon Pasta` |
| `add-recipe` | the new-recipe form | half written: a name, servings and two ingredients, not saved; typed: id `recipe-name` = `Lemon Pasta`, id `servings` = `4`, id `ingredient-1` = `300 g spaghetti`, id `ingredient-2` = `2 lemons` | launch → tap {id: add-recipe} → fill recipe-name, servings, ingredient-1, ingredient-2 (in recipe-form, then to top) | id `recipe-name` containing `Lemon Pasta`, the keyboard hidden |
