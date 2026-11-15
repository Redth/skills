"""appstores_lib: the code the app-stores skills share.

Stdlib Python 3.8+ only. The package lives once in ``plugins/app-stores/shared/appstores_lib`` and is copied
into each skill's ``scripts/appstores_lib`` by ``plugins/app-stores/tools/sync_shared.py``: edit the shared copy,
then run the sync.

Modules:

- ``jsonio``: plain JSON in and out (errors name the file and line; atomic writes).
- ``text``: counting characters, graphemes and bytes; emoji; whole-word matching.
- ``png``: PNG and JPEG headers, and decoding 8-bit PNGs.
- ``chrome``: headless Chrome over the DevTools pipe, for rendering pages to pictures.
- ``schema``: the JSON Schema subset the configs use.
- ``locales``: BCP 47 to and from each store's locale codes.
- ``rules``: the stores' rules data and the evaluators for word rules.
- ``web``: requests with retries, through a hook tests replace.
- ``jwt``: ES256 and RS256 tokens signed by ``openssl``.

Scripts import it by putting their own folder on ``sys.path`` and ``from appstores_lib import png``.
"""

__all__ = ["chrome", "jsonio", "jwt", "locales", "png", "rules", "schema", "text", "web"]
