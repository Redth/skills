"""mauidesktop_lib: the code the maui-desktop skills share (CONTRACT.md section 6).

Stdlib Python 3.8+ only. The package lives once in ``plugins/maui-desktop/shared/mauidesktop_lib`` and is
copied into each skill's ``scripts/mauidesktop_lib`` by ``plugins/maui-desktop/tools/sync_shared.py``: edit the
shared copy, then run the sync.

Modules:

- ``jsonio``: plain JSON in and out (errors name the file and line; atomic writes).
- ``schema``: the JSON Schema subset the plugin's files use.
- ``findings``: what a check reports, printed for people or as JSON, and the exit code.
- ``msbuild``: reading project files, central package versions and ``global.json`` without MSBuild; walking
  the project tree.
- ``detect``: what a MAUI desktop project already has, with evidence (``scan(root)``).
- ``blueprint``: ``desktop-blueprint.json``: defaults by kind, drafting, consistency rules, the decisions
  log and the interview's questions.

Scripts import it by putting their own folder on ``sys.path`` and ``from mauidesktop_lib import blueprint``.
"""

__all__ = ["blueprint", "detect", "findings", "jsonio", "msbuild", "schema"]
