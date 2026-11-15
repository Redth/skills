# What's live on App Store

Pulled by `push.py pull apple` on 2026-11-14T09:00:00Z from App Store Connect. Read-only: nothing was sent to the store.

```
App Store, App Store Connect, pulled 2026-11-14T09:00:00Z
  app com.example.samplerecipes (1234567890), primary language en-US
  categories: FOOD_AND_DRINK, LIFESTYLE
  locales: en-US, de-DE
  en-US
    name: 'Sample Recipes' (14 characters, 2 words)
    subtitle: 'Recipes and meal plans' (22 characters, 4 words)
    IOS description: 110 characters, 20 words
    IOS keywords: 25 characters, 3 keywords
    IOS promotionalText: 39 characters, 8 words
    IOS whatsNew: 27 characters, 4 words
    TV_OS description: 152 characters, 29 words
    TV_OS keywords: 25 characters, 3 keywords
    TV_OS promotionalText: 39 characters, 8 words
    TV_OS whatsNew: 27 characters, 4 words
  de-DE
    name: 'Sample Recipes' (14 characters, 2 words)
    subtitle: 'Rezepte und Essenspläne' (23 characters, 3 words)
    IOS description: 46 characters, 7 words
    IOS keywords: 26 characters, 3 keywords
    IOS promotionalText: (none)
    IOS whatsNew: 17 characters, 1 word
  IOS: version 1.3 (READY_FOR_DISTRIBUTION)
  TV_OS: version 1.3 (READY_FOR_DISTRIBUTION)
  pictures: none pulled
```

## Notes

- App Store Connect also has app information in PREPARE_FOR_SUBMISSION: the pull read the READY_FOR_DISTRIBUTION one (what's live)
- IOS also has version 1.4 in preparation: its words may differ from what's live (the pull read version 1.3, on sale)
- (eval fixture: the pictures were left out of this copy)

## Next

- `listing.py import --from live existing/` turns this into a draft `store-listing.json` (it never overwrites what the config already says).
- `listing.py diff --existing existing/` shows what a new listing would change, field by field.
- `screenshots/` is the current set: the starting point for new screenshots.
- This folder is a snapshot: pull again to refresh it. Don't edit it; edit the config.
