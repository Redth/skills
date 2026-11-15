#!/usr/bin/env python3
"""sheet.py: the rendered set at the size the stores show it, for judging legibility (and a contact sheet).

    sheet.py [--config store-screenshots.json] [--report render-report.json] [--listing store-listing.json] [--png]
    sheet.py --inspiration [--design design] [--png]
    sheet.py --directions design/explore/a,design/explore/b [--png]
    sheet.py --compare design/baseline [--png]

Writes ``<out>/sheets/``:

- ``search-row-<locale>.html``: Apple's search result on an iPhone, the first three portrait shots (or one
  landscape) of an Apple phone target at their real width in points, each caption's size in points computed and
  anything under 11 pt flagged;
- ``product-page-<locale>-<target>.html``: the top of Apple's product page for each Apple target, with the end
  of the first screen marked;
- ``play-listing-<locale>.html``: Google Play's listing on a phone with the phone screenshots' row;
- ``contact-sheet.html``: every target x locale x shot, panoramas' seams shown as red gutters, fallbacks and
  caption problems badged.

The design sheets, for choosing and keeping a look (references/baseline.md):

- ``--inspiration``: ``<design>/sheets/inspiration.png``, the user's examples from ``<design>/inspiration/`` with
  what they like and don't, each one's traits and the summary for the user to confirm;
- ``--directions a,b,c``: ``<design>/sheets/directions.png``, each explored render folder's first three shots at
  Apple's search-row size (each caption's size in points) and the product page's, with the direction's name and
  traits;
- ``--compare <folder>``: ``<out>/sheets/compare-<target>.png``, each shot beside its counterpart in the baseline
  (or a previous render), with what drifted past the style's tolerances under the pair.

With ``--png`` each page is rendered through headless Chrome to ``<out>/sheets/<name>.png`` (the whole page), for
an agent to look at. Every mock is an approximation of the store, labelled as such; the sizes are derived, not
measured on devices. App name, subtitle and icon come from ``store-listing.json`` when it's there.

Exit codes: 0 done; 3 usage or environment (no config, no render report, no Chrome with --png).
"""

from __future__ import annotations

import argparse
import html
import os
import shutil
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check  # noqa: E402
import styles  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import rules  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
MOCKS = os.path.join(SKILL_DIR, "mocks")

EXIT_OK = 0
EXIT_USAGE = 3

PHONE_SCALE = 3
MAX_PAGE_HEIGHT = 16000

# Apple's product page by the target's kind: (screen width pt, screen height pt, portrait shot width pt,
# landscape shot width pt, device words). Derived from the stores' layouts, not measured: approximations.
PRODUCT_PAGE = {
    "phone": (402, 874, 226, 370, "iPhone"),
    "watch": (402, 874, 150, 150, "iPhone"),
    "tablet": (1032, 1376, 300, 520, "13-inch iPad"),
    "desktop": (1280, 800, 300, 560, "Mac"),
    "tv": (1280, 800, 300, 560, "Mac (the Apple TV's page is drawn on the Mac's)"),
    "xr": (1280, 800, 300, 560, "Mac (Vision Pro's page is drawn on the Mac's)"),
}

# Google Play's listing on a phone: the screen in dp and how tall the screenshots' row draws a shot.
PLAY_SCREEN_DP = 412
PLAY_SHOT_DP = 210

CONTACT_WIDTH = 1600
CONTACT_THUMB_H = 300


def _esc(value):
    return html.escape(value if isinstance(value, str) else ("" if value is None else str(value)), quote=True)


def _template(name):
    with open(os.path.join(MOCKS, name), encoding="utf-8") as f:
        return string.Template(f.read())


def _src(inputs, f):
    """A file's path as the sheets' pages see it (they're in ``<out>/sheets/``)."""
    return "../" + "/".join(f.get("path", "").split(os.sep))


class Sheets:
    """Builds the sheets' pages from a check's ``Inputs``."""

    def __init__(self, inputs):
        self.inputs = inputs
        self.folder = os.path.join(inputs.out, "sheets")
        self.order = inputs.shot_order()

    # -- what the pages show -----------------------------------------------------------------------

    def files_for(self, locale, target):
        """A target's files in a locale, in the set's order."""
        out = [f for f in self.inputs.files if f.get("locale") == locale and f.get("target") == target]
        out.sort(key=lambda f: self.order.get(f.get("shot"), 1 << 20))
        return out

    def size_of(self, f):
        """A file's (width, height): the report's, else its target's."""
        if f.get("width") and f.get("height"):
            return int(f["width"]), int(f["height"])
        return self.inputs.target_size(f.get("target")) or (1, 1)

    def apple_targets(self, kind=None):
        """Apple targets (of a kind), the larger display types first as the rules list them."""
        rs = self.inputs.rulesets.get("apple")
        order = list(rs.slots) if rs else []
        out = []
        for tid in self.inputs.targets:
            if self.inputs.target_store(tid) != "apple":
                continue
            slot = self.inputs.apple_slot(self.inputs.target_size(tid))
            k = self.inputs.slot_kind("apple", slot) if slot else None
            if kind is None or k == kind:
                out.append((order.index(slot) if slot in order else 1 << 20, tid, slot, k))
        out.sort(key=lambda x: x[0])
        return [(tid, slot, k) for _, tid, slot, k in out]

    def play_phone_target(self):
        """The target that fills Play's phone slot, or ``None``."""
        for tid in self.inputs.targets:
            if self.inputs.target_store(tid) == "google" and self.inputs.google_slot(tid)[0] == "phone":
                return tid
        return None

    def listing_word(self, locale, store, field):
        """A locale's word from ``store-listing.json`` (``locales.<loc>.<store>.<field>``), falling back to its
        primary locale."""
        listing = self.inputs.listing
        for loc in (locale, listing.get("primaryLocale")):
            value = check._get(listing, "locales", loc, store, field)
            if isinstance(value, str) and value:
                return value
        return None

    def app_name(self, locale, store):
        """The app's name for a store, from ``store-listing.json`` (else a placeholder)."""
        field = "name" if store == "apple" else "title"
        return (self.listing_word(locale, store, field) or check._get(self.inputs.listing, "app", "name")
                or "App name")

    def icon(self, size, radius, name):
        """The app's icon from ``store-listing.json``'s Play graphics, else a lettered placeholder."""
        rel = check._get(self.inputs.listing, "stores", "google", "graphics", "icon")
        if isinstance(rel, str) and self.inputs.listing_path:
            path = os.path.join(os.path.dirname(os.path.abspath(self.inputs.listing_path)), rel)
            if os.path.isfile(path):
                src = os.path.relpath(path, self.folder).replace(os.sep, "/")
                return '<img class="icon" src="%s" alt="" style="width:%dpx;height:%dpx;border-radius:%dpx">' % (
                    _esc(src), size, size, radius)
        letter = (name or "?").strip()[:1].upper() or "?"
        return ('<div class="placeholder-icon" style="width:%dpx;height:%dpx;border-radius:%dpx;font-size:%dpx">%s'
                '</div>' % (size, size, radius, size // 2, _esc(letter)))

    def shot_img(self, f, width_css):
        """An ``<img>`` of a rendered file drawn ``width_css`` CSS px wide (a placeholder when it's missing)."""
        w, h = self.size_of(f)
        height_css = width_css * h / float(w)
        if not os.path.isfile(self.inputs.path(f.get("path") or "")):
            return '<div class="missing-shot" style="width:%.1fpx;height:%.1fpx">%s<br>not rendered</div>' % (
                width_css, height_css, _esc(f.get("shot")))
        return '<img src="%s" alt="%s" style="width:%.1fpx;height:%.1fpx">' % (
            _esc(_src(self.inputs, f)), _esc(f.get("shot")), width_css, height_css)

    def sizes_table(self, rows, unit, shown_note):
        """The captions' sizes on the mock: ``rows`` of (shot, caption text or None, size or None)."""
        out = ['<div class="sizes"><h2>Caption size as shown</h2><table>']
        low = 0
        for shot, text, size in rows:
            if text is None or size is None:
                out.append('<tr><td>%s</td><td class="none">no caption</td><td class="num none">&mdash;</td></tr>'
                           % _esc(shot))
                continue
            flag = size < check.MIN_TEXT_PT
            low += flag
            out.append('<tr><td>%s</td><td>%s</td><td class="num %s">%.1f %s%s</td></tr>' % (
                _esc(shot), _esc(text), "low" if flag else "ok", size, unit, " &#9888; under 11" if flag else ""))
        out.append("</table><p>%s %s</p></div>" % (
            _esc(shown_note), "Every caption reaches 11 %s." % unit if not low else
            "%d under 11 %s: hard to read here; a bigger caption or fewer words." % (low, unit)))
        return "".join(out)

    # -- the pages ----------------------------------------------------------------------------------

    def search_row(self, locale):
        """Apple's search row for a locale, or ``None`` without an Apple phone target."""
        targets = self.apple_targets("phone")
        if not targets:
            return None
        tid = targets[0][0]
        files = self.files_for(locale, tid)
        if not files:
            return None
        w, h = self.size_of(files[0])
        landscape = w > h
        shown = check.search_shot_points(w, h)
        first = files[:1] if landscape else files[:check.SEARCH_SHOTS]
        rows = []
        for f in first:
            cap = f.get("caption") if isinstance(f.get("caption"), dict) and f["caption"].get("text") else None
            size = check.points_at(cap.get("fontPx"), self.size_of(f)[0], shown) if cap else None
            rows.append((f.get("shot"), cap["text"] if cap else None, size))
        name = self.app_name(locale, "apple")
        subtitle = self.listing_word(locale, "apple", "subtitle") or ""
        return _template("search-row.html").safe_substitute(
            lang=_esc(locale), title=_esc("Search row - %s - %s" % (locale, tid)), locale=_esc(locale),
            target=_esc(tid), screen_pt="%d" % check.SEARCH_SCREEN_PT, shot_pt="%d" % round(shown),
            query=_esc(name.split(":")[0]), icon=self.icon(64, 14, name), name=_esc(name), subtitle=_esc(subtitle),
            shots="".join(self.shot_img(f, shown) for f in first),
            sizes=self.sizes_table(rows, "pt", "Font size in the picture x %.0f pt / %d px." % (shown, w)))

    def product_page(self, locale, tid, kind):
        """The top of Apple's product page for one Apple target in a locale."""
        files = self.files_for(locale, tid)
        if not files:
            return None
        screen_w, screen_h, portrait_pt, landscape_pt, device = PRODUCT_PAGE.get(kind or "phone", PRODUCT_PAGE["phone"])
        w, h = self.size_of(files[0])
        shown = landscape_pt if w > h else portrait_pt
        rows = []
        for f in files:
            cap = f.get("caption") if isinstance(f.get("caption"), dict) and f["caption"].get("text") else None
            rows.append((f.get("shot"), cap["text"] if cap else None,
                         check.points_at(cap.get("fontPx"), self.size_of(f)[0], shown) if cap else None))
        name = self.app_name(locale, "apple")
        return _template("product-page.html").safe_substitute(
            lang=_esc(locale), title=_esc("Product page - %s - %s" % (locale, tid)), locale=_esc(locale),
            target=_esc(tid), device=_esc(device), screen_pt="%d" % screen_w, screen_h="%d" % screen_h,
            shot_pt="%d" % shown, icon=self.icon(118 if screen_w < 600 else 140, 26, name), name=_esc(name),
            subtitle=_esc(self.listing_word(locale, "apple", "subtitle") or ""),
            shots="".join(self.shot_img(f, shown) for f in files),
            sizes=self.sizes_table(rows, "pt", "Font size in the picture x %d pt / %d px." % (shown, w))), \
            (screen_w, screen_h)

    def play_listing(self, locale):
        """Google Play's listing on a phone for a locale, or ``None`` without a Play phone target."""
        tid = self.play_phone_target()
        if tid is None:
            return None
        files = self.files_for(locale, tid)
        if not files:
            return None
        rows = []
        imgs = []
        for f in files:
            w, h = self.size_of(f)
            shown_w = PLAY_SHOT_DP * w / float(h)
            imgs.append(self.shot_img(f, shown_w))
            cap = f.get("caption") if isinstance(f.get("caption"), dict) and f["caption"].get("text") else None
            rows.append((f.get("shot"), cap["text"] if cap else None,
                         check.points_at(cap.get("fontPx"), w, shown_w) if cap else None))
        name = self.app_name(locale, "google")
        developer = check._get(self.inputs.listing, "app", "copyright") or ""
        developer = developer.split(" ", 1)[1] if developer[:4].isdigit() and " " in developer else developer
        return _template("play-listing.html").safe_substitute(
            lang=_esc(locale), title=_esc("Play listing - %s - %s" % (locale, tid)), locale=_esc(locale),
            target=_esc(tid), screen_dp="%d" % PLAY_SCREEN_DP, shot_dp="%d" % PLAY_SHOT_DP,
            icon=self.icon(72, 16, name), name=_esc(name), developer=_esc(developer or "Developer"),
            shots="".join(imgs),
            sizes=self.sizes_table(rows, "dp", "Font size in the picture x the shot's width in dp / its width in px."))

    def badges(self, f):
        """A file's badges for the contact sheet."""
        out = []
        primary = self.inputs.primary
        if f.get("captureFallback"):
            out.append(("fallback", "capture: %s" % primary))
        if f.get("stringFallback"):
            out.append(("fallback", "words: %s" % primary))
        cap = f.get("caption") if isinstance(f.get("caption"), dict) else {}
        if cap.get("fits") is False:
            out.append(("bad", "doesn't fit"))
        elif cap.get("atFloor"):
            out.append(("warn", "caption at floor"))
        if isinstance(cap.get("lines"), int) and cap["lines"] > check.MAX_CAPTION_LINES:
            out.append(("bad", "%d lines" % cap["lines"]))
        if cap.get("missingGlyphs"):
            out.append(("bad", "missing glyphs"))
        scale = f.get("captureScale")
        if isinstance(scale, (int, float)) and scale > check.UPSCALE_TOLERANCE:
            out.append(("warn", "upscaled %.2fx" % scale))
        if not os.path.isfile(self.inputs.path(f.get("path") or "")):
            out.append(("bad", "not rendered"))
        return "".join('<span class="badge %s">%s</span>' % (cls, _esc(text)) for cls, text in out)

    def cell(self, f, thumb_h):
        w, h = self.size_of(f)
        width = thumb_h * w / float(h)
        if os.path.isfile(self.inputs.path(f.get("path") or "")):
            img = '<img src="%s" alt="" style="width:%.1fpx;height:%dpx">' % (_esc(_src(self.inputs, f)), width, thumb_h)
        else:
            img = '<div class="missing-shot" style="width:%.1fpx;height:%dpx">not rendered</div>' % (width, thumb_h)
        return '<div class="cell" style="width:%.1fpx">%s<div class="label">%s</div><div class="badges">%s</div></div>' % (
            width, img, _esc(f.get("shot")), self.badges(f))

    def contact_sheet(self):
        """Every target x locale x shot, panoramas' seams as red gutters."""
        pano = check._get(self.inputs.config, "panorama", "shots") or []
        rows = []
        for tid in self.inputs.targets:
            store = self.inputs.target_store(tid) or "?"
            size = self.inputs.target_size(tid)
            slot = self.inputs.slot_for(store, tid) if store in check.STORES else None
            head = '<h2>%s <small>%s &middot; %s%s</small></h2>' % (
                _esc(tid), _esc(check.STORE_NAMES.get(store, store)), _esc(check._size_text(size) if size else "?"),
                " &middot; " + _esc(slot) if slot else "")
            locs = []
            for loc in self.inputs.locales:
                files = self.files_for(loc, tid)
                have = set(f.get("shot") for f in files)
                for shot in self.inputs.shots_for(tid):
                    if shot not in have:
                        w, h = size or (1, 2)
                        files.append({"shot": shot, "path": "", "width": w, "height": h, "locale": loc})
                files.sort(key=lambda f: self.order.get(f.get("shot"), 1 << 20))
                parts = []
                i = 0
                while i < len(files):
                    if files[i].get("shot") in pano:
                        group = []
                        while i < len(files) and files[i].get("shot") in pano:
                            group.append(self.cell(files[i], CONTACT_THUMB_H))
                            i += 1
                        parts.append('<div class="pano">%s</div>' % ('<div class="seam" style="height:%dpx"></div>'
                                                                      % CONTACT_THUMB_H).join(group))
                    else:
                        parts.append(self.cell(files[i], CONTACT_THUMB_H))
                        i += 1
                locs.append('<div class="locale-row"><h3>%s</h3><div class="strip">%s</div></div>' % (
                    _esc(loc), "".join(parts)))
            rows.append('<section class="target">%s<div class="locales">%s</div></section>' % (head, "".join(locs)))
        return _template("contact-sheet.html").safe_substitute(
            title="Contact sheet", report=_esc(os.path.relpath(self.inputs.report_path, self.inputs.out)),
            thumb_h="%d" % CONTACT_THUMB_H, primary=_esc(self.inputs.primary), rows="\n".join(rows))

    # -- writing ------------------------------------------------------------------------------------

    def write(self):
        """Write every page and the stylesheet; return ``[(html name, (css width, css height, scale), png name)]``."""
        if os.path.isdir(self.folder):
            for name in os.listdir(self.folder):
                if name.endswith((".html", ".png")) and name.startswith(
                        ("search-row-", "product-page-", "play-listing-", "contact-sheet")):
                    os.unlink(os.path.join(self.folder, name))
        os.makedirs(self.folder, exist_ok=True)
        shutil.copyfile(os.path.join(MOCKS, "mocks.css"), os.path.join(self.folder, "mocks.css"))
        pages = []

        def put(name, text, view):
            with open(os.path.join(self.folder, name + ".html"), "w", encoding="utf-8") as f:
                f.write(text)
            pages.append((name + ".html", view, name + ".png"))

        for loc in self.inputs.locales:
            page = self.search_row(loc)
            if page:
                put("search-row-%s" % loc, page, (int(check.SEARCH_SCREEN_PT), 400, PHONE_SCALE))
            for tid, _slot, kind in self.apple_targets():
                result = self.product_page(loc, tid, kind)
                if result:
                    text, (w, h) = result
                    put("product-page-%s-%s" % (loc, tid), text, (w, 400, PHONE_SCALE if w < 600 else 1))
            page = self.play_listing(loc)
            if page:
                put("play-listing-%s" % loc, page, (PLAY_SCREEN_DP, 400, PHONE_SCALE))
        put("contact-sheet", self.contact_sheet(), (CONTACT_WIDTH, 400, 1))
        return pages

    def render(self, pages):
        """Render each page whole to ``<out>/sheets/<name>.png``; return the PNG paths."""
        done = []
        with chrome.Chrome() as browser:
            for page, (w, h, scale), name in pages:
                out = os.path.join(self.folder, name)
                browser.render(os.path.join(self.folder, page), w * scale, h * scale, out, scale=scale,
                               full_page=MAX_PAGE_HEIGHT)
                done.append(out)
        return done


# ---------------------------------------------------------------------------------------------------------
# The design sheets: the inspiration board, directions side by side, and before/after pairs.

DESIGN_WIDTH = 1240
INSPIRATION_WIDTH = 1040
COMPARE_WIDTH = 1240


def _page(title, lede, body, css="design.css"):
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>%s</title>\n'
            '<link rel="stylesheet" href="%s">\n</head>\n<body>\n<h1>%s</h1>\n<p class="lede">%s</p>\n%s\n</body>\n'
            '</html>\n' % (_esc(title), css, _esc(title), lede, body))


def _chips(traits):
    """Trait chips: ``name value`` for each trait (a list's values joined)."""
    if not isinstance(traits, dict) or not traits:
        return '<div class="chips"><span class="chip">no traits written down</span></div>'
    out = []
    for k, v in traits.items():
        if k.startswith("$"):
            continue
        value = " / ".join(v) if isinstance(v, list) else str(v)
        out.append('<span class="chip"><b>%s</b>%s</span>' % (_esc(k), _esc(value)))
    return '<div class="chips">%s</div>' % "".join(out)


def _rel(path, folder):
    return os.path.relpath(path, folder).replace(os.sep, "/")


def _write_pages(folder, pages, prefixes):
    """Write ``pages`` ([(name, html, (css width, scale))]) and design.css into ``folder``, after removing the
    old pages whose names start with one of ``prefixes``; return ``[(html name, view, png name)]``."""
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.endswith((".html", ".png")) and name.startswith(tuple(prefixes)):
            os.unlink(os.path.join(folder, name))
    shutil.copyfile(os.path.join(MOCKS, "design.css"), os.path.join(folder, "design.css"))
    out = []
    for name, text, (width, scale) in pages:
        with open(os.path.join(folder, name + ".html"), "w", encoding="utf-8") as f:
            f.write(text)
        out.append((name + ".html", (width, 400, scale), name + ".png"))
    return out


def render_pages(folder, pages):
    """Render written pages to PNG (the whole page); return the PNG paths."""
    done = []
    with chrome.Chrome() as browser:
        for page, (w, h, scale), name in pages:
            out = os.path.join(folder, name)
            browser.render(os.path.join(folder, page), w * scale, h * scale, out, scale=scale,
                           full_page=MAX_PAGE_HEIGHT)
            done.append(out)
    return done


def inspiration_page(design):
    """The inspiration board from ``<design>/inspiration/inspiration.json``: each example with its source, what
    the user likes and doesn't, its traits, and the summary for the user to confirm."""
    folder = os.path.join(design, "inspiration")
    path = os.path.join(folder, "inspiration.json")
    if not os.path.isfile(path):
        raise check.UsageError("no %s: put the user's examples in %s and describe them there first" % (
            path, folder))
    data = jsonio.load(path)
    problems = styles.validate_inspiration(data)
    if problems:
        raise check.UsageError("%s doesn't match the inspiration shape:\n  %s" % (path, "\n  ".join(problems)))
    sheets = os.path.join(design, "sheets")
    summary = data.get("summary") or {}
    confirmed = summary.get("confirmedByUser") is True
    head = ('<section class="card"><h2>What these have in common <small>the summary</small></h2>%s%s'
            '<p class="confirmed %s">%s</p></section>' % (
                _chips(summary.get("traits")),
                '<p class="muted">%s</p>' % _esc(summary["notes"]) if summary.get("notes") else "",
                "yes" if confirmed else "no",
                "Confirmed by the user." if confirmed else "Not confirmed yet: ask the user whether this is what they "
                "like before proposing directions."))
    cards = []
    for ex in data.get("examples") or []:
        verdict = ex.get("verdict") or ("dislike" if ex.get("dislikes") and not ex.get("likes") else "like")
        img_path = os.path.join(folder, ex["file"])
        pic = ('<img src="%s" alt="">' % _esc(_rel(img_path, sheets)) if os.path.isfile(img_path)
               else '<div class="missing-shot">%s<br>not found</div>' % _esc(ex["file"]))
        notes = "".join('<li class="like">%s</li>' % _esc(x) for x in ex.get("likes") or []) + \
            "".join('<li class="dislike">%s</li>' % _esc(x) for x in ex.get("dislikes") or [])
        cards.append('<div class="example %s"><div class="pic">%s</div><div class="verdict %s">%s</div><h3>%s</h3>'
                     '<p class="muted">%s</p><ul class="notes">%s</ul>%s</div>' % (
                         verdict, pic, verdict, "liked" if verdict == "like" else "not this",
                         _esc(ex["file"]), _esc(ex.get("source") or "source not noted"), notes, _chips(ex.get("traits"))))
    body = head + '<div class="examples">%s</div>' % "".join(cards)
    lede = ("The examples the user gave, with what they like (+) and don't (&minus;) in each and its traits. Examples "
            "inform the style only: never their marks, illustrations or trade dress.")
    return sheets, [("inspiration", _page("Inspiration", lede, body), (INSPIRATION_WIDTH, 2))]


def _load_out(folder):
    path = os.path.join(folder, "render-report.json")
    if not os.path.isfile(path):
        raise check.UsageError("no render report in %s (render it first: render.py --style ... --out %s)" % (
            folder, folder))
    report = jsonio.load(path)
    return report, [f for f in report.get("files") or [] if isinstance(f, dict)]


def directions_page(design, folders):
    """Each explored direction's first three shots of one target: at Apple's search-row size with the caption's
    size in points, then at the product page's size, labelled with the direction's name and traits."""
    sheets = os.path.join(design, "sheets")
    cards = []
    for folder in folders:
        report, files = _load_out(folder)
        style = report.get("style") or {}
        name = style.get("name") or os.path.basename(os.path.normpath(folder))
        if not files:
            cards.append('<section class="card"><h2>%s</h2><p class="muted">nothing rendered</p></section>'
                         % _esc(name))
            continue
        target = files[0].get("target")
        locale = files[0].get("locale")
        mine = [f for f in files if f.get("target") == target and f.get("locale") == locale][:check.SEARCH_SHOTS]
        w, h = int(mine[0].get("width") or 1), int(mine[0].get("height") or 1)
        landscape = w > h
        shown = check.search_shot_points(w, h)
        large = PRODUCT_PAGE["phone"][3 if landscape else 2]
        small_row, large_row = [], []
        for f in mine:
            src = _esc(_rel(os.path.join(folder, f.get("path") or ""), sheets))
            cap = f.get("caption") if isinstance(f.get("caption"), dict) and f["caption"].get("text") else None
            pt = check.points_at(cap.get("fontPx"), w, shown) if cap else None
            label = ('<div class="pt none">no caption</div>' if pt is None else '<div class="pt%s">%.1f pt%s</div>' % (
                " low" if pt < check.MIN_TEXT_PT else "", pt, " &#9888; under 11" if pt < check.MIN_TEXT_PT else ""))
            small_row.append('<div class="shot"><img src="%s" style="width:%.1fpx;height:%.1fpx" alt="">%s</div>' % (
                src, shown, shown * h / float(w), label))
            large_row.append('<div class="shot"><img src="%s" style="width:%dpx;height:%.1fpx" alt="">'
                             '<div class="name">%s</div></div>' % (src, large, large * h / float(w),
                                                                     _esc(f.get("shot"))))
        cards.append(
            '<section class="card"><h2>%s <small>%s &middot; %s &middot; %s</small></h2>%s<div class="direction">'
            '<div><p class="row-label">In search (%d pt a shot)</p><div class="search-frame"><div class="strip">%s'
            '</div></div></div><div><p class="row-label">On the product page (%d pt a shot)</p>'
            '<div class="strip large">%s</div></div></div></section>' % (
                _esc(name), _esc(_rel(folder, os.path.dirname(design))), _esc(target), _esc(locale),
                _chips(style.get("traits")), round(shown), "".join(small_row), large, "".join(large_row)))
    lede = ("Each direction's first shots as a shopper meets them: in Apple's search row (three a row, each caption's "
            "size in points; under 11 pt is hard to read) and on the product page. Sizes are derived, not measured "
            "on a device. Pick one with the user; open the files themselves for full size.")
    return sheets, [("directions", _page("Directions", lede, "".join(cards)), (DESIGN_WIDTH, 2))]


def compare_pages(inputs, folder):
    """Pairs per target x shot: ``folder``'s (a baseline or a previous render) on the left, the current on the
    right, with the drift past the style's tolerances written under each."""
    base_report, base_files = _load_out(folder)
    sheets = os.path.join(inputs.out, "sheets")
    meta_path = os.path.join(folder, "baseline.json")
    meta = jsonio.load(meta_path) if os.path.isfile(meta_path) else None
    base_style = None
    if os.path.isfile(os.path.join(folder, styles.STYLE_NAME)):
        base_style = jsonio.load(os.path.join(folder, styles.STYLE_NAME))
    tol = styles.drift_tolerances(inputs.style or base_style)
    pairs, _new, gone = check.match_baseline(inputs.files, base_files, inputs.primary)
    paired = dict((id(c), b) for c, b in pairs)
    label = "Baseline (%s)" % (meta.get("approvedAt") or "")[:10] if meta else "Before"
    pages = []
    order = inputs.shot_order()
    for tid in inputs.targets:
        cur = [f for f in inputs.files if f.get("target") == tid]
        if not cur:
            continue
        cur.sort(key=lambda f: (inputs.locales.index(f.get("locale")) if f.get("locale") in inputs.locales else 99,
                                order.get(f.get("shot"), 1 << 20)))
        cards = []
        drifted = 0
        for f in cur:
            b = paired.get(id(f))
            right = '<img src="%s" alt="">' % _esc(_rel(inputs.path(f.get("path") or ""), sheets))
            if b is None:
                left = '<div class="missing">no counterpart</div>'
                found = ['<li class="note">new since then, and nothing of its role or layout to compare with</li>']
            else:
                left = '<img src="%s" alt="">' % _esc(_rel(os.path.join(folder, b.get("path") or ""), sheets))
                messages = check.drift_messages(f, b, tol)
                found = ['<li>%s</li>' % _esc(m) for m in messages] or [
                    '<li class="ok">no drift past the tolerances</li>']
                if (b.get("shot"), b.get("locale")) != (f.get("shot"), f.get("locale")):
                    found.insert(0, '<li class="note">compared with %s/%s (its %s)</li>' % (
                        _esc(b.get("locale")), _esc(b.get("shot")), "role" if b.get("role") and
                        b.get("role") == f.get("role") else "layout"))
                drifted += bool(messages)
            cards.append('<div class="pair%s"><h3>%s <small>%s</small></h3><div class="sides"><div class="side">'
                         '<p class="row-label">%s</p>%s</div><div class="side"><p class="row-label">Now</p>%s</div>'
                         '</div><ul class="findings">%s</ul></div>' % (
                             " drift" if any(not x.startswith('<li class="ok') and not x.startswith('<li class="note')
                                             for x in found) else "",
                             _esc(f.get("shot")), _esc(f.get("locale")), _esc(label), left, right, "".join(found)))
        lede = ("%s on the left, the current render of %s on the right; under each pair what moved past the style's "
                "drift tolerances (caption size %.0f%%, caption position %.1fu, device box %.1fu, text share %.0f%%, "
                "colours delta E %.0f). Drift is for the user to decide on, not an error. %d of %d pairs drifted.%s" % (
                    _esc(label), _esc(tid), 100 * tol["captionSize"], 100 * tol["captionPosition"],
                    100 * tol["deviceBox"], 100 * tol["textShare"], tol["colour"], drifted, len(cur),
                    " In the baseline but gone now: %s." % _esc(", ".join(g for g in gone if g.startswith(tid + "/")))
                    if any(g.startswith(tid + "/") for g in gone) else ""))
        pages.append(("compare-%s" % tid, _page("Compare: %s" % tid, lede, '<div class="pairs">%s</div>' %
                                                "".join(cards)), (COMPARE_WIDTH, 2)))
    return sheets, pages


def _resolve_dir(value, base):
    if os.path.isabs(value) or os.path.isdir(value):
        return os.path.abspath(value)
    return os.path.normpath(os.path.join(base, value))


def design_main(args):
    """The --inspiration, --directions and --compare sheets."""
    base = os.path.dirname(os.path.abspath(args.config))
    raw = {}
    if os.path.isfile(args.config):
        try:
            raw = jsonio.load(args.config)
        except jsonio.JsonError as e:
            raise check.UsageError(str(e))
    design = _resolve_dir(args.design, base) if args.design else styles.design_dir(args.config, raw)
    if args.inspiration:
        folder, pages = inspiration_page(design)
        prefixes = ["inspiration"]
    elif args.directions:
        dirs = [_resolve_dir(d.strip(), base) for d in args.directions.split(",") if d.strip()]
        folder, pages = directions_page(design, dirs)
        prefixes = ["directions"]
    else:
        inputs = check.Inputs(args.config, args.listing, report_path=args.report)
        folder, pages = compare_pages(inputs, _resolve_dir(args.compare, base))
        prefixes = ["compare-"]
    return folder, _write_pages(folder, pages, prefixes)


def parser():
    """The argument parser."""
    p = argparse.ArgumentParser(prog="sheet.py", description="Mock the stores' pages at real size from the rendered "
                                "screenshots, and a contact sheet of the set. Offline.")
    p.add_argument("--config", default="store-screenshots.json", help="the design config (default: %(default)s)")
    p.add_argument("--report", help="the render report (default: <out>/render-report.json)")
    p.add_argument("--listing", help="store-listing.json, for the app's name and icon (default: beside the config)")
    p.add_argument("--png", action="store_true", help="render the pages to PNG through headless Chrome")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--inspiration", action="store_true", help="the inspiration board (<design>/inspiration)")
    mode.add_argument("--directions", metavar="DIRS", help="explored render folders, comma-separated, side by side")
    mode.add_argument("--compare", metavar="DIR", help="pair the current render with a baseline or previous render "
                      "folder, with the drift under each pair")
    p.add_argument("--design", help="the design folder (default: the config's 'design', else design/)")
    return p


def main(argv=None):
    """Write the sheets (and with --png render them); return the exit code."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    try:
        if args.inspiration or args.directions or args.compare:
            folder, pages = design_main(args)
            render_with = lambda: render_pages(folder, pages)  # noqa: E731
        else:
            inputs = check.Inputs(args.config, args.listing, report_path=args.report)
            sheets = Sheets(inputs)
            pages = sheets.write()
            folder = sheets.folder
            render_with = lambda: sheets.render(pages)  # noqa: E731
    except (check.UsageError, jsonio.JsonError, rules.RulesError) as e:
        sys.stderr.write("sheet.py: %s\n" % e)
        return EXIT_USAGE
    sys.stdout.write("Wrote %d page%s in %s.\n" % (len(pages), "" if len(pages) == 1 else "s", folder))
    if not args.png:
        for page, _, _ in pages:
            sys.stdout.write("  %s\n" % os.path.join(folder, page))
        return EXIT_OK
    try:
        chrome.find_chrome()
    except chrome.ChromeNotFound as e:
        sys.stderr.write("sheet.py: the HTML is written, but no PNGs: %s\n" % e)
        return EXIT_USAGE
    try:
        done = render_with()
    except chrome.ChromeError as e:
        sys.stderr.write("sheet.py: Chrome couldn't render the sheets: %s\n" % e)
        return EXIT_USAGE
    for path in done:
        sys.stdout.write("  %s\n" % path)
    if args.inspiration or args.directions or args.compare:
        sys.stdout.write("Open every picture above at full size, and show the user.\n")
    else:
        sys.stdout.write("Open every picture above at full size. They're approximations of the stores' pages, sized "
                         "from derived numbers, not the stores' own rendering.\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
