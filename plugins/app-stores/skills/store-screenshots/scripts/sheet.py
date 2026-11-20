#!/usr/bin/env python3
"""sheet.py: the rendered set at the size the stores show it, for judging legibility (and a contact sheet).

    sheet.py [--config store-screenshots.json] [--report render-report.json | --out DIR] [--listing ...] [--png]
    sheet.py --inspiration [--design design] [--png]
    sheet.py --directions design/explore/a,design/explore/b [--png]
    sheet.py --compare design/baseline [--png]
    sheet.py --compare current | existing/apple/screenshots/en-US | assets/screenshots [--png]
    sheet.py --current [existing/apple/screenshots/en-US | assets/screenshots] [--png]
    sheet.py --styles [--png]

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
  (or a previous render), with what drifted past the style's tolerances under the pair; or, when the folder has no
  render report (the live set: a pulled listing or any folder of screenshots; ``current`` for ``current.json``'s
  source), each new shot beside the live one it replaces, paired by the screen it shows, else by its place;
- ``--current [folder]``: ``<design>/sheets/current.png``, the app's current set (a live listing pulled to
  ``existing/<store>/screenshots/<locale>/<slot>/<NN>.<ext>``, or any folder of screenshots, e.g.
  ``assets/screenshots/<device>/Screenshot-NN.png``) laid out by store and device in order, each shot beside its
  analysis from ``<design>/current.json``; with no ``current.json`` yet it writes a skeleton of one (every file,
  its group and order, the rest for the agent to fill and the user to confirm). Without a folder it reads
  ``current.json``'s ``source``;
- ``--styles``: ``<design>/sheets/styles.png``, every starting style in the skill's ``styles/`` rendered on the
  same made-up app (neutral screens drawn by ``samples.py``, never committed), first three shots each, so a user
  can pick by eye. Renders through Chrome whether or not ``--png`` is given (into
  ``<design>/sheets/styles-preview/``, safe to delete).

``--draft`` (with ``--directions`` or ``--styles``) heads the page "Drafts for you to correct": what the agent
rendered before the user agreed the brief and storyboard. Nothing on it is approved.

With ``--png`` each page is rendered through headless Chrome to ``<out>/sheets/<name>.png`` (the whole page), for
an agent to look at. ``--out design/explore/<name>`` (or ``--report`` there) shows an exploration: its sheets go
in its own ``sheets/``. Targets come App Store first, phones before foldables, tablets and the rest. Every mock is an approximation of the store, labelled as such; the sizes are derived, not
measured on devices. App name, subtitle and icon come from ``store-listing.json`` when it's there.

Exit codes: 0 done; 3 usage or environment (no config, no render report, no Chrome with --png).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import string
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check  # noqa: E402
import frames  # noqa: E402
import render  # noqa: E402
import samples  # noqa: E402
import styles  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
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
        for tid in self.inputs.ordered_targets():
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
        for tid in self.inputs.ordered_targets():
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
        for tid in self.inputs.ordered_targets():
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


DRAFT_BANNER = ('<div class="draft"><b>Drafts for you to correct.</b> The agent rendered these before you agreed the '
                'brief and the storyboard, from its first reading of them (and of the current set, if there is one). '
                'Nothing here is chosen or approved: say what is wrong (the story, the words, the order, the look), '
                'pick a direction or none, and only then does anything get iterated or locked.</div>')


def _page(title, lede, body, css="design.css", draft=False):
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>%s</title>\n'
            '<link rel="stylesheet" href="%s">\n</head>\n<body>\n<h1>%s</h1>\n%s<p class="lede">%s</p>\n%s\n</body>\n'
            '</html>\n' % (_esc(title), css, _esc(title) + (" (drafts)" if draft else ""),
                            DRAFT_BANNER if draft else "", lede, body))


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
    current = current_card(design)
    if not os.path.isfile(path):
        if current is None:
            raise check.UsageError("no %s: put the user's examples in %s and describe them there first" % (
                path, folder))
        data = {"version": 1, "examples": [], "summary": {}}
    else:
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
    body = (current or "") + head + '<div class="examples">%s</div>' % "".join(cards)
    lede = ("The examples the user gave, with what they like (+) and don't (&minus;) in each and its traits%s. "
            "Examples inform the style only: never their marks, illustrations or trade dress." % (
                ", and the app's current set as one of them (to keep or move away from)" if current else ""))
    return sheets, [("inspiration", _page("Inspiration", lede, body), (INSPIRATION_WIDTH, 2))]


def _load_out(folder):
    path = os.path.join(folder, "render-report.json")
    if not os.path.isfile(path):
        raise check.UsageError("no render report in %s (render it first: render.py --style ... --out %s)" % (
            folder, folder))
    report = jsonio.load(path)
    return report, [f for f in report.get("files") or [] if isinstance(f, dict)]


def _direction_card(folder, sheets, where, extra=""):
    """One rendered folder's first three shots of one target: at Apple's search-row size with each caption's size
    in points, then at the product page's size, under the style's name, ``where`` and its traits."""
    report, files = _load_out(folder)
    style = report.get("style") or {}
    name = style.get("name") or os.path.basename(os.path.normpath(folder))
    if not files:
        return '<section class="card"><h2>%s</h2>%s<p class="muted">nothing rendered</p></section>' % (
            _esc(name), extra)
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
                         '<div class="name">%s</div></div>' % (
                             src, large, large * h / float(w),
                             _esc(f.get("shot") + (" (%s)" % f["role"] if f.get("role") else "")
                                  + (": %s" % f["layout"] if f.get("layout") else ""))))
    return ('<section class="card"><h2>%s <small>%s &middot; %s &middot; %s</small></h2>%s%s<div class="direction">'
            '<div><p class="row-label">In search (%d pt a shot)</p><div class="search-frame"><div class="strip">%s'
            '</div></div></div><div><p class="row-label">On the product page (%d pt a shot)</p>'
            '<div class="strip large">%s</div></div></div></section>' % (
                _esc(name), _esc(where), _esc(target), _esc(locale), extra, _chips(style.get("traits")),
                round(shown), "".join(small_row), large, "".join(large_row)))


def directions_page(design, folders, draft=False):
    """Each explored direction's first three shots of one target: at Apple's search-row size with the caption's
    size in points, then at the product page's size, labelled with the direction's name and traits."""
    sheets = os.path.join(design, "sheets")
    cards = [_direction_card(folder, sheets, _rel(folder, os.path.dirname(design))) for folder in folders]
    lede = ("Each direction's first shots as a shopper meets them: in Apple's search row (three a row, each caption's "
            "size in points; under 11 pt is hard to read) and on the product page. Sizes are derived, not measured "
            "on a device. Pick one with the user; open the files themselves for full size.")
    return sheets, [("directions", _page("Directions", lede, "".join(cards), draft=draft), (DESIGN_WIDTH, 2))]


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
    for tid in inputs.ordered_targets():
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


def is_render_folder(folder):
    """True when a folder holds a render (a baseline or a previous render): its render-report.json."""
    return os.path.isfile(os.path.join(folder, "render-report.json"))


def _match_group(inputs, tid, groups):
    """The current set's group a target's new shots replace: a pulled listing's slot (Apple's display type for
    the target's size, Play's slot for it), else a folder named for the target, else one of the same kind of
    device, else the nearest shape."""
    store = inputs.target_store(tid)
    size = inputs.target_size(tid) or (1, 2)
    want = inputs.slot_for(store, tid) if store in check.STORES else None
    pulled = [g for g in groups if g["store"] == store]
    for g in pulled:
        if want and g["slot"] == want:
            return g, "the listing's %s" % want
    if pulled and store == "apple":
        kind = inputs.slot_kind("apple", want)
        for g in pulled:
            if kind and inputs.slot_kind("apple", g["slot"]) == kind:
                return g, "the listing's %s (the same kind of device)" % g["slot"]
    for g in groups:
        if g["id"] == tid or os.path.basename(g["id"]) == tid:
            return g, "the folder %s" % g["id"]
    kind = frames.device_kind(tid, inputs.targets.get(tid))
    others = [g for g in groups if _group_store(g) == store] + [g for g in groups if _group_store(g) is None]

    def shape(g):
        sz = image_size(os.path.join(g["dir"], os.path.basename(g["files"][0]))) or (1, 2)
        return sz
    for g in others:
        w, h = shape(g)
        if frames.device_kind(g["id"], {"width": w, "height": h}) == kind:
            return g, "%s (the same kind of device)" % g["id"]
    if others:
        best = min(others, key=lambda g: abs(shape(g)[0] / float(shape(g)[1]) - size[0] / float(size[1])))
        return best, "%s (the nearest shape)" % best["id"]
    return None, None


def compare_current_pages(inputs, folder, current):
    """Pairs per target: the current (live) set's picture on the left, the new render on the right. Each target's
    shots are paired with the live group it replaces (``_match_group``), shot by shot by the screen they show
    (``current.json``'s ``capture`` against the shot's capture, or its ``screen`` against the shot's id), else by
    order. No render report is needed on the left: it's the pictures as they are."""
    groups = current_groups(folder)
    if not groups:
        raise check.UsageError("no pictures (%s) under %s to compare with" % (", ".join(IMAGE_EXTS), folder))
    sheets = os.path.join(inputs.out, "sheets")
    shots_cfg = dict((s["id"], s) for s in inputs.shots)
    by_group = {}
    for sh in (current or {}).get("shots") or []:
        by_group.setdefault(sh.get("group"), []).append(sh)
    pages = []
    for tid in inputs.ordered_targets():
        cur = [f for f in inputs.files if f.get("target") == tid and f.get("locale") == inputs.primary] or \
            [f for f in inputs.files if f.get("target") == tid]
        if not cur:
            continue
        cur.sort(key=lambda f: inputs.shot_order().get(f.get("shot"), 1 << 20))
        group, why = _match_group(inputs, tid, groups)
        live = list(group["files"]) if group else []
        notes = dict((sh.get("file"), sh) for sh in by_group.get(group["id"], [])) if group else {}
        # First every shot that shows a screen the live set shows (by current.json), then the rest by place.
        pairs = {}
        used = set()
        for f in cur:
            shot = shots_cfg.get(f.get("shot")) or {}
            for rel in live:
                sh = notes.get(rel) or {}
                if rel in used:
                    continue
                if (sh.get("capture") and sh["capture"] == shot.get("capture")) or (
                        sh.get("screen") and sh["screen"] in (f.get("shot"), shot.get("capture"))):
                    pairs[id(f)] = (rel, "the same screen (%s)" % (sh.get("capture") or sh.get("screen")))
                    used.add(rel)
                    break
        for n, f in enumerate(cur):
            if id(f) in pairs:
                continue
            rest = [rel for rel in live if rel not in used]
            pick = live[n] if n < len(live) and live[n] not in used else (rest[0] if rest else None)
            if pick:
                pairs[id(f)] = (pick, "its place in the set (#%d)" % (live.index(pick) + 1))
                used.add(pick)
        cards = []
        for f in cur:
            match, how = pairs.get(id(f), (None, None))
            right = '<img src="%s" alt="">' % _esc(_rel(inputs.path(f.get("path") or ""), sheets))
            found = []
            if match is None:
                left = '<div class="missing">nothing live in its place</div>'
                found.append('<li class="note">new: the live set has no shot here</li>')
            else:
                left = '<img src="%s" alt="">' % _esc(_rel(os.path.join(folder, match), sheets))
                found.append('<li class="note">paired by %s</li>' % _esc(how))
                sh = notes.get(match) or {}
                if sh.get("caption"):
                    found.append('<li class="note">live words: &ldquo;%s&rdquo;</li>'
                                 % _esc(sh["caption"]).replace("\n", " "))
                if sh.get("verdict"):
                    found.append('<li class="note">the user said: %s</li>' % _esc(sh["verdict"]))
            cap = f.get("caption") if isinstance(f.get("caption"), dict) else None
            if cap and cap.get("text"):
                found.append('<li class="note">new words: &ldquo;%s&rdquo;</li>' % _esc(cap["text"]))
            cards.append('<div class="pair"><h3>%s <small>%s</small></h3><div class="sides"><div class="side">'
                         '<p class="row-label">Live now</p>%s</div><div class="side"><p class="row-label">New</p>%s'
                         '</div></div><ul class="findings">%s</ul></div>' % (
                             _esc(f.get("shot")), _esc(f.get("locale")), left, right, "".join(found)))
        left_over = [rel for rel in live if rel not in used]
        lede = ("The live set on the left (%s, from %s), the new render of %s on the right, each new shot beside the "
                "live one it replaces (by the screen it shows, else by its place). Judge them together with the "
                "user: the story, the words, the look.%s" % (
                    _esc(why or "no live group matched"), _esc(_rel(folder, os.path.dirname(sheets))), _esc(tid),
                    " Live but not in the new set: %s." % _esc(", ".join(os.path.basename(x) for x in left_over))
                    if left_over else ""))
        pages.append(("compare-%s" % tid, _page("Live and new: %s" % tid, lede, '<div class="pairs">%s</div>' %
                                                "".join(cards)), (COMPARE_WIDTH, 2)))
    return sheets, pages


# ---------------------------------------------------------------------------------------------------------
# The current set: what the app's listing shows now, read shot by shot before anything is designed.

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
CURRENT_NAME = "current.json"
CURRENT_WIDTH = 1240
CURRENT_SHOT_W = 250
STORE_ORDER = ("apple", "google")


def _natural(name):
    """A sort key that puts Screenshot-2 before Screenshot-10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def image_size(path):
    """A picture's (width, height) from its header (PNG, JPEG or WebP), else ``None``."""
    try:
        meta = png.info(path)
        return meta.width, meta.height
    except (png.ImageError, OSError, struct.error):
        pass
    try:
        with open(path, "rb") as f:
            data = f.read(64)
    except OSError:
        return None
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        b = data[21:25]
        return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
    if kind == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    return None


def _pulled(parts):
    """``(store, locale, slot)`` when a folder's path ends ``<store>/screenshots/<locale>/<slot>`` (the layout
    store-listings' ``push.py pull`` writes), else ``None``."""
    if len(parts) >= 4 and parts[-3] == "screenshots":
        return parts[-4], parts[-2], parts[-1]
    return None


def current_groups(folder):
    """The current set's pictures, grouped by the folder each is in and ordered by name (the number in it):
    ``[{"id", "store", "locale", "slot", "dir", "files": [path relative to folder]}]``. A pulled listing's groups
    are ``store/locale/slot`` (App Store first, then Play); any other folder's are its subfolders' paths. When some
    folders are a pulled listing's, pictures elsewhere in it (an icon, a feature graphic) are left out."""
    folder = os.path.abspath(folder)
    found = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("sheets", "__pycache__"))
        pics = sorted((n for n in names if n.lower().endswith(IMAGE_EXTS) and not n.startswith(".")), key=_natural)
        if pics:
            found.append((root, pics))
    groups = []
    for root, pics in found:
        parts = os.path.normpath(root).split(os.sep)
        rel = os.path.relpath(root, folder)
        pulled = _pulled(parts)
        if pulled:
            gid = "/".join(pulled)
        else:
            gid = os.path.basename(folder) if rel == "." else rel.replace(os.sep, "/")
        groups.append({"id": gid, "store": pulled[0] if pulled else None, "locale": pulled[1] if pulled else None,
                       "slot": pulled[2] if pulled else None, "dir": root,
                       "files": [os.path.relpath(os.path.join(root, n), folder).replace(os.sep, "/") for n in pics]})
    if any(g["store"] for g in groups):
        groups = [g for g in groups if g["store"]]

    def key(g):
        store = STORE_ORDER.index(g["store"]) if g["store"] in STORE_ORDER else len(STORE_ORDER)
        return (0 if g["store"] else 1, store, g["store"] or "", g["locale"] or "", _group_rank(g),
                _natural(g["slot"] or g["id"]))
    groups.sort(key=key)
    return groups


def _slot_order(store):
    """A store's slots in its rules' order (the App Store's largest iPhone first, then the other iPhones, the
    Duo, the iPads, the watches...; Play's phone first)."""
    try:
        data = jsonio.load(os.path.join(SKILL_DIR, "rules", "%s.json" % store))
    except (OSError, jsonio.JsonError):
        return []
    return [k for k in (data.get("slots") or {}) if not k.startswith("$")]


def _group_rank(g):
    """Where a current-set group comes: a pulled listing's by its store's slot order, any other folder's by the
    device its name and pictures suggest (phones first)."""
    if g["store"]:
        order = _slot_order(g["store"])
        return (0, order.index(g["slot"]) if g["slot"] in order else len(order) + 1)
    size = image_size(os.path.join(g["dir"], os.path.basename(g["files"][0])))
    w, h = size or (1, 2)
    store = {"apple": 0, "google": 1}.get(_group_store(g), 2)
    return (store, frames.DEVICE_RANK.get(frames.device_kind(g["id"], {"width": w, "height": h}), 3))


def _group_store(g):
    """The store a group's pictures are for: a pulled listing's, else the one its folder's name suggests."""
    if g.get("store"):
        return g["store"]
    words = set(re.split(r"[^a-z0-9]+", g["id"].lower()))
    if words & {"apple", "ios", "iphone", "ipad", "mac", "macos", "appletv", "tvos", "watchos", "duo"}:
        return "apple"
    if words & {"android", "google", "play", "pixel", "galaxy", "wear", "chromebook"}:
        return "google"
    return None


def current_skeleton(source, groups):
    """A ``current.json`` with every picture listed (its group and order) and the rest for the agent to fill."""
    shots = []
    for g in groups:
        for n, rel in enumerate(g["files"], 1):
            shots.append({"file": rel, "group": g["id"], "order": n, "screen": None, "capture": None,
                          "caption": None, "layout": None, "traits": {}, "verdict": None, "notes": None})
    return {"version": 1, "source": source, "shots": shots,
            "summary": {"traits": {}, "look": None, "whatWorks": [], "whatDoesnt": [], "notes": None,
                        "confirmedByUser": False}}


def load_current(design):
    """``<design>/current.json`` validated, or ``None`` when there's none; raise ``UsageError`` on problems."""
    path = os.path.join(design, CURRENT_NAME)
    if not os.path.isfile(path):
        return None
    data = jsonio.load(path)
    problems = styles.validate_current(data)
    if problems:
        raise check.UsageError("%s doesn't match the current set's shape:\n  %s" % (path, "\n  ".join(problems)))
    return data


def _field(label, value, hint):
    if value in (None, "", [], {}):
        return '<div class="field empty"><span>%s</span><em>%s</em></div>' % (_esc(label), _esc(hint))
    return '<div class="field"><span>%s</span>%s</div>' % (_esc(label), value)


VERDICTS = {"keep": "keep", "change": "change", "drop": "drop"}


def current_page(design, base, folder=None):
    """The current set laid out by store and device, in order, each shot beside its analysis. Returns
    ``(sheets folder, pages, notes)``; writes a skeleton ``current.json`` when there's none."""
    data = load_current(design)
    if folder is None:
        if not data:
            raise check.UsageError("say which folder holds the current set (sheet.py --current existing/apple/"
                                   "screenshots/en-US, or assets/screenshots): there's no %s yet" % os.path.join(
                                       design, CURRENT_NAME))
        folder = _resolve_dir(data["source"], base)
    if not os.path.isdir(folder):
        raise check.UsageError("no folder %s: pull the live listing first (store-listings' push.py pull writes "
                               "existing/<store>/screenshots/<locale>/<slot>/) or name the folder the set is in" % folder)
    groups = current_groups(folder)
    if not groups:
        raise check.UsageError("no pictures (%s) under %s" % (", ".join(IMAGE_EXTS), folder))
    source = os.path.relpath(folder, base).replace(os.sep, "/")
    notes = []
    path = os.path.join(design, CURRENT_NAME)
    if data is None:
        data = current_skeleton(source, groups)
        os.makedirs(design, exist_ok=True)
        jsonio.dump(data, path)
        notes.append("wrote a skeleton %s: fill in each shot's screen, caption, layout and traits from the pictures, "
                     "then go through it with the user (verdicts and the summary are theirs)" % path)
    elif os.path.normpath(_resolve_dir(data["source"], base)) != os.path.normpath(folder):
        notes.append("%s describes %s, not %s: shots are matched by file name relative to the folder shown" % (
            path, data["source"], source))
    by_file = dict((s["file"], s) for s in data.get("shots") or [])
    shown_files = set()
    sheets = os.path.join(design, "sheets")
    summary = data.get("summary") or {}
    confirmed = summary.get("confirmedByUser") is True
    look = summary.get("look")
    lists = "".join('<li class="like">%s</li>' % _esc(x) for x in summary.get("whatWorks") or []) + \
        "".join('<li class="dislike">%s</li>' % _esc(x) for x in summary.get("whatDoesnt") or [])
    head = ('<section class="card"><h2>The set as a whole <small>the summary</small></h2>%s%s%s'
            '<p class="look">%s</p><p class="confirmed %s">%s</p></section>' % (
                _chips(summary.get("traits")),
                '<ul class="notes">%s</ul>' % lists if lists else
                '<p class="muted">What works and what doesn\'t: not written yet.</p>',
                '<p class="muted">%s</p>' % _esc(summary["notes"]) if summary.get("notes") else "",
                {"keep": "The new set keeps this look.", "evolve": "The new set evolves this look: keep what works, "
                 "fix what doesn't.", "replace": "The new set moves away from this look."}.get(
                     look, "Keep, evolve or replace the look: not decided yet (the user's call)."),
                "yes" if confirmed else "no",
                "Confirmed by the user." if confirmed else "Not confirmed yet: go through it with the user before the "
                "storyboard; it starts from the shots they keep."))
    cards = []
    for g in groups:
        sizes = [image_size(os.path.join(folder, rel)) for rel in g["files"]]
        size_text = sorted(set("%dx%d" % s for s in sizes if s))
        if g["store"]:
            title = "%s <small>%s &middot; %s &middot; %d shot%s &middot; %s</small>" % (
                _esc(check.STORE_NAMES.get(g["store"], g["store"])), _esc(g["locale"]), _esc(g["slot"]),
                len(g["files"]), "" if len(g["files"]) == 1 else "s", _esc(", ".join(size_text) or "size unknown"))
        else:
            title = "%s <small>%d shot%s &middot; %s</small>" % (
                _esc(g["id"]), len(g["files"]), "" if len(g["files"]) == 1 else "s",
                _esc(", ".join(size_text) or "size unknown"))
        first = []
        for rel, size in list(zip(g["files"], sizes))[:check.SEARCH_SHOTS]:
            w, h = size or (1, 2)
            shown = check.search_shot_points(w, h)
            first.append('<img src="%s" style="width:%.1fpx;height:%.1fpx" alt="">' % (
                _esc(_rel(os.path.join(folder, rel), sheets)), shown, shown * h / float(w)))
            if w > h:
                break
        rows = []
        for n, (rel, size) in enumerate(zip(g["files"], sizes), 1):
            shown_files.add(rel)
            shot = by_file.get(rel)
            w, h = size or (1, 2)
            pic = '<img src="%s" style="width:%dpx;height:%.1fpx" alt="">' % (
                _esc(_rel(os.path.join(folder, rel), sheets)), CURRENT_SHOT_W, CURRENT_SHOT_W * h / float(w))
            tags = ['<span class="tag">#%d</span>' % n]
            if n <= check.SEARCH_SHOTS:
                tags.append('<span class="tag first">first three</span>')
            if shot is None:
                tags.append('<span class="tag bad">not in current.json</span>')
                shot = {}
            verdict = shot.get("verdict")
            tags.append('<span class="tag verdict %s">%s</span>' % (
                VERDICTS.get(verdict, "open"), _esc(verdict or "verdict: the user's")))
            fields = "".join([
                _field("Screen", _esc(shot.get("screen")) if shot.get("screen") else None,
                       "which screen of the app it shows"),
                _field("Caption", "&ldquo;%s&rdquo;" % _esc(shot["caption"]).replace("\n", "<br>")
                       if shot.get("caption") else None, "the words on it, read off the picture (null for none)"),
                _field("Layout", _esc(shot.get("layout")) if shot.get("layout") else None,
                       "the nearest of: " + ", ".join(styles.style_schema()["$defs"]["layout"]["enum"])),
                _field("Capture", _esc(shot.get("capture")) if shot.get("capture") else None,
                       "the capture screen id that shows it now"),
                _field("Traits", _chips(shot.get("traits")) if shot.get("traits") else None,
                       "its look in the traits vocabulary"),
                _field("Notes", _esc(shot.get("notes")) if shot.get("notes") else None, "what works, what doesn't"),
            ])
            rows.append('<div class="current-shot %s"><div class="pic">%s</div><div class="analysis"><div class="tags">'
                        '%s</div><h3>%s <small>%s</small></h3>%s</div></div>' % (
                            VERDICTS.get(verdict, "open"), pic, "".join(tags), _esc(os.path.basename(rel)),
                            _esc("%dx%d" % size if size else "size unknown"), fields))
        cards.append('<section class="card"><h2>%s</h2><p class="row-label">Shots 1 to 3 at about search-row size'
                     '</p><div class="search-frame"><div class="strip">%s</div></div><div class="current-shots">%s'
                     '</div></section>' % (title, "".join(first), "".join(rows)))
    gone = [f for f in by_file if f not in shown_files]
    if gone:
        notes.append("%s lists %d file%s not in the folder: %s" % (
            CURRENT_NAME, len(gone), "" if len(gone) == 1 else "s", ", ".join(gone)))
    lede = ("The set the app shows now, from %s, by store and device in its order, each shot beside what "
            "current.json says about it: the screen it shows, its words, its layout and look, and the user's verdict "
            "(keep, change, drop). The storyboard starts from the shots kept, in this order; the inspiration step "
            "treats the set as one example, to keep or move away from. Open each picture at full size to read its "
            "words." % _esc(source))
    body = head + "".join(cards)
    if notes:
        body = '<section class="card warn">%s</section>' % "".join('<p>%s</p>' % _esc(n) for n in notes) + body
    return sheets, [("current", _page("The current set", lede, body), (CURRENT_WIDTH, 2))], notes


def current_card(design):
    """The current set as one example on the inspiration board (``None`` without a ``current.json``)."""
    data = load_current(design)
    if not data:
        return None
    summary = data.get("summary") or {}
    kept = [s for s in data.get("shots") or [] if s.get("verdict") == "keep"]
    look = summary.get("look")
    notes = "".join('<li class="like">%s</li>' % _esc(x) for x in summary.get("whatWorks") or []) + \
        "".join('<li class="dislike">%s</li>' % _esc(x) for x in summary.get("whatDoesnt") or [])
    return ('<section class="card current"><h2>The current set <small>%s &middot; one example among the others'
            '</small></h2>%s<ul class="notes">%s</ul><p class="look">%s</p><p class="muted">%d shot%s, %d kept as '
            'they are. See current.png for each shot.</p></section>' % (
                _esc(data.get("source")), _chips(summary.get("traits")), notes,
                {"keep": "Keep this look.", "evolve": "Evolve it: keep what works, fix what doesn't.",
                 "replace": "Move away from it."}.get(look, "Keep, evolve or replace it: not decided yet."),
                len(data.get("shots") or []), "" if len(data.get("shots") or []) == 1 else "s", len(kept)))


# ---------------------------------------------------------------------------------------------------------
# The starting styles, rendered on one made-up app so a user can pick by eye.

PREVIEW_SIZE = (660, 1434)  # the 6.9-inch iPhone's shape at half its size: enough for the sheet's sizes
PREVIEW_DIR = "styles-preview"
PREVIEW_WORDS = {
    "app": [("Your week, *planned*", "Sample app", "Made-up words and screens"), ("Every step, *clearly*", None, None),
            ("Find it in *seconds*", None, None)],
    "game": [("Go *further*", None, None), ("Build your *world*", None, None), ("Race your *friends*", None, None)],
}
GAME_ROLES = ("gameplay", "key-art", "banner")


def _is_game(style):
    return any(r in (style.get("roles") or {}) for r in GAME_ROLES)


def preview_roles(style):
    """The three roles a style's preview shows: its roles in order (each no more often than its ``maxPerSet``),
    topped up with the first that may repeat; a continuous background shows its strip across shots 2 and 3.
    Returns ``(roles, panorama)``."""
    roles = [(k, v) for k, v in (style.get("roles") or {}).items() if not k.startswith("$") and isinstance(v, dict)]
    if not roles:
        return [], False
    names = [k for k, _ in roles]
    if (style.get("traits") or {}).get("background") == "continuous" and "strip" in names:
        return [names[0] if names[0] != "strip" else "strip", "strip", "strip"], True
    counts = {}
    picked = []

    def room(name, spec):
        most = spec.get("maxPerSet")
        return most is None or counts.get(name, 0) < most

    for name, spec in roles:
        if len(picked) == check.SEARCH_SHOTS:
            break
        if room(name, spec):
            picked.append(name)
            counts[name] = counts.get(name, 0) + 1
    while len(picked) < check.SEARCH_SHOTS:
        more = next(((n, s) for n, s in roles if room(n, s)), None)
        if more is None:
            break
        picked.append(more[0])
        counts[more[0]] = counts.get(more[0], 0) + 1
    return picked, False


def preview_config(style):
    """The made-up app's config for one style's preview: one Apple phone target, three shots in the style's
    roles, sample words."""
    game = _is_game(style)
    roles, pano = preview_roles(style)
    screens = samples.GAME_SCREENS if game else samples.APP_SCREENS
    words = PREVIEW_WORDS["game" if game else "app"]
    shots, strings = [], {}
    for i, role in enumerate(roles):
        cap, kicker, proof = words[i]
        shot = {"id": "shot%d" % (i + 1), "capture": screens[i], "role": role, "caption": "cap.%d" % (i + 1),
                "callout": {"rect": [0.06, 0.3, 0.88, 0.12], "scale": 1.3}, "pair": screens[(i + 1) % 3]}
        strings[shot["caption"]] = cap
        if kicker and (style.get("roles") or {}).get(role, {}).get("layout") == "hero":
            shot["kicker"], shot["proof"] = "cap.kicker", "cap.proof"
            strings["cap.kicker"], strings["cap.proof"] = kicker, proof
        shots.append(shot)
    w, h = PREVIEW_SIZE
    return {"version": 1, "captures": "../captures", "out": "render", "primaryLocale": "en-US", "locales": ["en-US"],
            "theme": {}, "targets": {"iphone": {"store": "apple", "width": w, "height": h, "capture": "phone"}},
            "shots": shots, "panorama": {"shots": [s["id"] for s in shots[1:]]} if pano else None,
            "stores": {}, "strings": {"en-US": strings}}


def _suits(style):
    """The ``Suits ...`` sentence of a starting style's ``$comment``."""
    m = re.search(r"Suits[^.]*\.", style.get("$comment") or "")
    return m.group(0) if m else ""


def styles_page(design, browser=None, draft=False, log=None):
    """Render every starting style on the made-up app into ``<design>/sheets/styles-preview/`` and lay them out;
    return ``(sheets folder, pages)``. Needs Chrome."""
    sheets = os.path.join(design, "sheets")
    root = os.path.join(sheets, PREVIEW_DIR)
    w, h = PREVIEW_SIZE
    cap_dir = os.path.join(root, "captures", "en-US", "phone")
    os.makedirs(cap_dir, exist_ok=True)
    for kind in samples.APP_SCREENS:
        samples.write(os.path.join(cap_dir, kind + ".png"), samples.app_screen(kind, w, h))
    for kind in samples.GAME_SCREENS:
        samples.write(os.path.join(cap_dir, kind + ".png"), samples.game_screen(kind, w, h))
    found = styles.starting_styles()
    own = browser is None
    if own:
        try:
            chrome.find_chrome()
        except chrome.ChromeNotFound as e:
            raise render.EnvironmentProblem(str(e))
        browser = chrome.Chrome()
    cards = []
    try:
        for name, (path, data) in found.items():
            folder = os.path.join(root, name)
            os.makedirs(folder, exist_ok=True)
            config = os.path.join(folder, "store-screenshots.json")
            jsonio.dump(preview_config(data), config)
            lines = []
            code, _ = render.run(config, browser=browser, log=lines.append, style=path)
            problems = [x for x in lines if x.startswith(("error", "warning"))]
            extra = '<p class="muted"><b>styles/%s.json</b> &middot; %s</p>' % (_esc(name), _esc(_suits(data)))
            if problems:
                extra += '<p class="muted warn-text">%s</p>' % "<br>".join(_esc(p) for p in problems)
            cards.append(_direction_card(os.path.join(folder, "render"), sheets, "styles/%s.json" % name, extra))
            if log:
                log("%s: %s" % (name, "rendered" if code == 0 else "rendered with problems"))
    finally:
        if own:
            browser.close()
    lede = ("Every starting style in the skill's styles/, rendered on the same made-up app (neutral grey screens and "
            "sample words, drawn for this sheet) so you can compare them by eye: its first three shots in Apple's "
            "search row and on the product page. The colours are the styles' own; a direction made from one takes "
            "your brand's colours, fonts and words. On Google Play the app styles' hero becomes the app's own screen "
            "(Play wants UI in the first three). Point at one or two, or say what to mix.")
    return sheets, [("styles", _page("Starting styles", lede, "".join(cards), draft=draft), (DESIGN_WIDTH, 2))]


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
        folder, pages = directions_page(design, dirs, draft=args.draft)
        prefixes = ["directions"]
    elif args.current is not None:
        folder, pages, notes = current_page(design, base, _resolve_dir(args.current, base) if args.current else None)
        for n in notes:
            sys.stdout.write("note: %s\n" % n)
        prefixes = ["current"]
    elif args.styles:
        folder, pages = styles_page(design, draft=args.draft, log=lambda m: sys.stdout.write("  %s\n" % m))
        prefixes = ["styles"]
    else:
        inputs = check.Inputs(args.config, args.listing, report_path=check.report_path_for(args))
        target = args.compare
        if (target == "current" and not os.path.isdir(_resolve_dir(target, base))) or target.endswith(CURRENT_NAME):
            # The current (live) set, from current.json's source (design/current.json, or the one named).
            path = os.path.join(design, CURRENT_NAME) if target == "current" else _resolve_dir(target, base)
            if not os.path.isfile(path):
                raise check.UsageError("no %s: read the current set first (sheet.py --current <folder>)" % path)
            current = jsonio.load(path)
            folder, pages = compare_current_pages(inputs, _resolve_dir(current["source"], base), current)
        else:
            where = _resolve_dir(target, base)
            if is_render_folder(where):
                folder, pages = compare_pages(inputs, where)
            elif os.path.isdir(where):
                folder, pages = compare_current_pages(inputs, where, load_current(design))
            else:
                raise check.UsageError("no folder %s to compare with" % where)
        prefixes = ["compare-"]
    return folder, _write_pages(folder, pages, prefixes)


def parser():
    """The argument parser."""
    p = argparse.ArgumentParser(prog="sheet.py", description="Mock the stores' pages at real size from the rendered "
                                "screenshots, and a contact sheet of the set. Offline.")
    p.add_argument("--config", default="store-screenshots.json", help="the design config (default: %(default)s)")
    p.add_argument("--report", help="the render report (default: <out>/render-report.json)")
    p.add_argument("--out", help="a rendered folder to show instead of the config's out (an exploration: "
                   "design/explore/<name>), relative to the config; its sheets go in <it>/sheets")
    p.add_argument("--listing", help="store-listing.json, for the app's name and icon (default: beside the config)")
    p.add_argument("--png", action="store_true", help="render the pages to PNG through headless Chrome")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--inspiration", action="store_true", help="the inspiration board (<design>/inspiration)")
    mode.add_argument("--directions", metavar="DIRS", help="explored render folders, comma-separated, side by side")
    mode.add_argument("--compare", metavar="DIR", help="pair the current render with a baseline or previous render "
                      "folder (the drift under each pair), or with the live set: a folder of its pictures (a pulled "
                      "listing, assets/screenshots), 'current' or a current.json (its source)")
    mode.add_argument("--current", metavar="DIR", nargs="?", const="",
                      help="the app's current set (a pulled listing's existing/<store>/screenshots/..., or any folder "
                      "of screenshots) beside its analysis in <design>/current.json; without DIR, current.json's source")
    mode.add_argument("--styles", action="store_true", help="every starting style rendered on one made-up app, to pick "
                      "by eye (needs Chrome)")
    p.add_argument("--draft", action="store_true", help="with --directions or --styles: head the page as drafts for "
                   "the user to correct (rendered before they agreed the brief and storyboard)")
    p.add_argument("--design", help="the design folder (default: the config's 'design', else design/)")
    return p


def main(argv=None):
    """Write the sheets (and with --png render them); return the exit code."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    try:
        if args.inspiration or args.directions or args.compare or args.current is not None or args.styles:
            folder, pages = design_main(args)
            render_with = lambda: render_pages(folder, pages)  # noqa: E731
        else:
            inputs = check.Inputs(args.config, args.listing, report_path=check.report_path_for(args))
            sheets = Sheets(inputs)
            pages = sheets.write()
            folder = sheets.folder
            render_with = lambda: sheets.render(pages)  # noqa: E731
    except (check.UsageError, jsonio.JsonError, rules.RulesError, render.UsageError, styles.StyleError) as e:
        sys.stderr.write("sheet.py: %s\n" % e)
        return EXIT_USAGE
    except render.EnvironmentProblem as e:
        sys.stderr.write("sheet.py: the starting styles need Chrome to render: %s\n" % e)
        return EXIT_USAGE
    except chrome.ChromeError as e:
        sys.stderr.write("sheet.py: Chrome couldn't render: %s\n" % e)
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
    if args.inspiration or args.directions or args.compare or args.current is not None or args.styles:
        sys.stdout.write("Open every picture above at full size, and show the user.\n")
    else:
        sys.stdout.write("Open every picture above at full size. They're approximations of the stores' pages, sized "
                         "from derived numbers, not the stores' own rendering.\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
