# Wiring references

To wire reflection into an author skill:

1. Locate the author skill's `SKILL.md` under the plugin root.
2. Read `skills/skill-reflect/templates/improve-this-skill.md` from the Redth/skills source checkout or from the vendored `skills/skill-reflect/templates/` copy.
3. If the file already contains `<!-- BEGIN skill-reflect nudge -->`, do not duplicate it.
4. Append the exact block to the end of the author skill's `SKILL.md`.
5. Add the skill name to `skill-reflect.config.json` `scope.skills` if absent.
6. Add the same skill name to `.skill-reflect-vendor.json` `scope` if the pin exists.
7. Run doctor to verify the block is present.

This maintainer skill is always excluded from reflection and should never be included in scope.
