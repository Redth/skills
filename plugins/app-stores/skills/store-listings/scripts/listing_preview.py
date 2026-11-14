"""``listing.py preview``: each store's page drawn from ``out/listing.json``, as HTML and (``--png``) pictures.

The pages are honest approximations, labelled as such: App Store search results (the first three portrait
screenshots, or one landscape), the top of the product page (name, subtitle, the screenshots, the description's
first lines with "more") and Google Play's listing (icon, title, feature graphic, screenshots, short
description). They're drawn from the built output, so what's previewed is what ``push.py`` sends. Templates are
in the skill's ``templates/preview/``.
"""

from __future__ import annotations

import collections
import html
import os
import shutil
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import rules  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
TEMPLATES = os.path.join(SKILL_DIR, "templates", "preview")
RULES_DIR = os.path.join(SKILL_DIR, "rules")

# Viewports: (CSS width, CSS height, scale). Phones at 2x; desktop pages at 1x.
PHONE = (390, 1500, 2)
PLAY_PHONE = (412, 1500, 2)
DESKTOP = (1280, 1100, 1)
PLAY_DESKTOP = (1280, 1500, 1)
WIDE_PLATFORMS = ("MAC_OS", "TV_OS", "VISION_OS")


def _esc(value):
    return html.escape(value if isinstance(value, str) else "", quote=True)


def _template(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as f:
        return string.Template(f.read())


def _size(out, rel):
    """(width, height) of a built picture, or None."""
    try:
        info = png.info(os.path.join(out, rel))
        return info.width, info.height
    except (png.ImageError, OSError, ValueError):
        return None


def _img(rel, cls="", alt=""):
    return '<img class="%s" src="../%s" alt="%s">' % (_esc(cls), _esc(rel), _esc(alt))


def _placeholder(name, px, radius):
    letter = (name or "?").strip()[:1].upper() or "?"
    return ('<div class="placeholder-icon" style="width:%dpx;height:%dpx;border-radius:%dpx;font-size:%dpx">%s</div>'
            % (px, px, radius, px // 2, _esc(letter)))


def _play_icon(manifest, code=None):
    """A Play icon from the build (this locale's, else any), for the App Store pages too (its own comes from
    the build)."""
    images = (manifest.get("google") or {}).get("images") or {}
    order = [code] if code in images else []
    order += [c for c in images if c not in order]
    for c in order:
        icons = (images.get(c) or {}).get("icon") or []
        if icons:
            return icons[0]["file"]
    return None


def _apple_slot_order(platform):
    """Apple's display types for a platform, in the rules file's order, phones first."""
    try:
        slots = rules.load("apple", RULES_DIR).slots
    except rules.RulesError:
        return []
    mine = [(k, v) for k, v in slots.items() if v.get("platform") == platform and v.get("displayType")]
    phones = [v["displayType"] for k, v in mine if v.get("kind") == "phone"]
    return phones + [v["displayType"] for k, v in mine if v.get("kind") != "phone"]


def apple_page(manifest, out, platform, code):
    """The App Store page for a platform and locale, as HTML."""
    apple = manifest["apple"]
    app_loc = (apple.get("app") or {}).get("localizations", {}).get(code) or {}
    plat = apple["platforms"][platform]
    words = (plat.get("localizations") or {}).get(code) or {}
    shots_by_type = (plat.get("screenshots") or {}).get(code) or {}
    chosen_type, shots = None, []
    for display in _apple_slot_order(platform) + list(shots_by_type):
        if shots_by_type.get(display):
            chosen_type, shots = display, shots_by_type[display]
            break
    name = app_loc.get("name") or ""
    subtitle = app_loc.get("subtitle") or ""
    icon_rel = _play_icon(manifest)
    if icon_rel:
        icon_64, icon_118 = _img(icon_rel, "icon-64", "icon"), _img(icon_rel, "icon-118", "icon")
        icon_note = "Play's icon is shown in its place"
    else:
        icon_64, icon_118 = _placeholder(name, 64, 14), _placeholder(name, 118, 26)
        icon_note = "a placeholder is shown in its place"
    sizes = [_size(out, s["file"]) for s in shots]
    landscape = bool(sizes and sizes[0] and sizes[0][0] > sizes[0][1])
    if not shots:
        search = '<p class="missing">No screenshots for %s in %s: the search result shows none.</p>' % (
            _esc(platform), _esc(code))
        carousel = '<p class="missing">No screenshots: the product page shows none.</p>'
    else:
        first = shots[:1] if landscape else shots[:3]
        search = '<div class="search-shots%s">%s</div>' % (
            " landscape" if landscape else "", "".join(_img(s["file"], "", "screenshot") for s in first))
        carousel = ('<div class="carousel%s">%s</div><p class="device-note">%s: %d screenshot%s</p>' % (
            " landscape" if landscape else "", "".join(_img(s["file"], "", "screenshot") for s in shots),
            _esc(chosen_type), len(shots), "" if len(shots) == 1 else "s"))
    promo = words.get("promotionalText") or ""
    description = words.get("description") or ""
    text = (promo + "\n" + description) if promo else description
    category = ((apple.get("app") or {}).get("categories") or {}).get("primary") or "-"
    return _template("apple.html").safe_substitute(
        lang=_esc(code), page_title=_esc("%s - App Store (%s, %s)" % (name, platform, code)),
        platform=_esc(platform), locale=_esc(code), icon_note=_esc(icon_note),
        search_term=_esc(name.split(":")[0] if name else "search"),
        icon_64=icon_64, icon_118=icon_118, name=_esc(name), subtitle=_esc(subtitle),
        search_shots=search, carousel=carousel, description=_esc(text),
        whats_new=_esc(words.get("whatsNew") or "(none: a first version has no What's New)"),
        category=_esc(category.replace("_", " ").title()))


def google_page(manifest, out, code):
    """Google Play's listing for a locale, as HTML."""
    g = manifest["google"]
    words = (g.get("listings") or {}).get(code) or {}
    images = (g.get("images") or {}).get(code) or {}
    title = words.get("title") or ""
    feature = images.get("featureGraphic") or []
    feature_html = _img(feature[0]["file"], "feature", "feature graphic") if feature else \
        '<div class="feature-missing">No feature graphic (required)</div>'
    icon = images.get("icon") or []
    icon_html = _img(icon[0]["file"], "icon", "icon") if icon else _placeholder(title, 72, 14)
    phone = images.get("phoneScreenshots") or []
    shots = '<div class="shots">%s</div>' % "".join(_img(s["file"], "", "screenshot") for s in phone) if phone else \
        '<p class="missing">No phone screenshots.</p>'
    tablets = (images.get("tenInchScreenshots") or []) or (images.get("sevenInchScreenshots") or [])
    tablet_html = ""
    if tablets:
        tablet_html = ('<p class="tablet-label">On tablets:</p><div class="shots tablet">%s</div>'
                       % "".join(_img(s["file"], "", "tablet screenshot") for s in tablets))
    return _template("google.html").safe_substitute(
        lang=_esc(code), page_title=_esc("%s - Google Play (%s)" % (title, code)), locale=_esc(code),
        feature=feature_html, icon=icon_html, title=_esc(title), developer=_esc(g.get("package") or ""),
        shots=shots, tablet_shots=tablet_html, short_description=_esc(words.get("shortDescription") or ""),
        full_description=_esc(words.get("fullDescription") or ""))


def write_previews(out):
    """Write ``out/preview/*.html``; return ``[(page file, viewport, png name)]`` for rendering."""
    path = os.path.join(out, "listing.json")
    manifest = jsonio.load(path)
    folder = os.path.join(out, "preview")
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    shutil.copyfile(os.path.join(TEMPLATES, "preview.css"), os.path.join(folder, "preview.css"))
    pages = []
    apple = manifest.get("apple")
    if apple:
        for platform in apple.get("platforms") or {}:
            codes = list(((apple["platforms"][platform].get("localizations")) or {}))
            for code in codes:
                name = "apple-%s-%s" % (platform, code)
                with open(os.path.join(folder, name + ".html"), "w", encoding="utf-8") as f:
                    f.write(apple_page(manifest, out, platform, code))
                view = DESKTOP if platform in WIDE_PLATFORMS else PHONE
                pages.append((name + ".html", view, name + ".png"))
    google = manifest.get("google")
    if google:
        for code in google.get("listings") or {}:
            name = "google-%s" % code
            with open(os.path.join(folder, name + ".html"), "w", encoding="utf-8") as f:
                f.write(google_page(manifest, out, code))
            pages.append((name + ".html", PLAY_PHONE, name + "-phone.png"))
            pages.append((name + ".html", PLAY_DESKTOP, name + "-desktop.png"))
    return manifest, pages


def write_index(out, manifest, pages, rendered):
    """``out/preview/index.html``: a link to each page, and its pictures when rendered."""
    folder = os.path.join(out, "preview")
    links = []
    seen = set()
    for page, _, _ in pages:
        if page not in seen:
            seen.add(page)
            links.append('<li><a href="%s">%s</a></li>' % (_esc(page), _esc(page[:-5])))
    thumbs = ['<figure><img src="%s" alt=""><figcaption>%s</figcaption></figure>' % (_esc(p), _esc(p))
              for p in rendered]
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(_template("index.html").safe_substitute(
            built_at=_esc(manifest.get("builtAt") or ""), links="\n".join(links), thumbs="\n".join(thumbs)))


def render(out, pages):
    """Render each page to ``out/preview/<name>.png`` through headless Chrome; return the names."""
    folder = os.path.join(out, "preview")
    done = []
    with chrome.Chrome() as browser:
        for page, (w, h, scale), name in pages:
            browser.render(os.path.join(folder, page), w * scale, h * scale, os.path.join(folder, name), scale=scale)
            done.append(name)
    return done


def main(args):
    """``listing.py preview``: returns the exit code."""
    import listing
    if not os.path.isfile(os.path.join(args.out, "listing.json")):
        raise listing.UsageError("%s has no listing.json: run listing.py build --out %s first (the preview draws "
                                 "what was built)" % (args.out, args.out))
    manifest, pages = write_previews(args.out)
    rendered = []
    if args.png:
        try:
            chrome.find_chrome()
        except chrome.ChromeNotFound as e:
            write_index(args.out, manifest, pages, [])
            raise listing.UsageError("the HTML preview is in %s, but no PNGs: %s" % (
                os.path.join(args.out, "preview"), e))
        try:
            rendered = render(args.out, pages)
        except chrome.ChromeError as e:
            write_index(args.out, manifest, pages, [])
            raise listing.UsageError("Chrome couldn't render the preview: %s" % e)
    write_index(args.out, manifest, pages, rendered)
    folder = os.path.join(args.out, "preview")
    sys.stdout.write("Wrote %s (%d page%s).\n" % (os.path.join(folder, "index.html"), len(set(p for p, _, _ in pages)),
                                                  "" if len(pages) == 1 else "s"))
    for name in rendered:
        sys.stdout.write("  %s\n" % os.path.join(folder, name))
    if rendered:
        sys.stdout.write("Open every picture above and read it as a shopper would. These are approximations, "
                         "not the stores' own rendering.\n")
    return listing.EXIT_OK
