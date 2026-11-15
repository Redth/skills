#!/usr/bin/env python3
"""sheet.py: the rendered set at the size the stores show it, for judging legibility (and a contact sheet).

    sheet.py [--config store-screenshots.json] [--report render-report.json] [--listing store-listing.json] [--png]

Writes ``<out>/sheets/``:

- ``search-row-<locale>.html``: Apple's search result on an iPhone, the first three portrait shots (or one
  landscape) of an Apple phone target at their real width in points, each caption's size in points computed and
  anything under 11 pt flagged;
- ``product-page-<locale>-<target>.html``: the top of Apple's product page for each Apple target, with the end
  of the first screen marked;
- ``play-listing-<locale>.html``: Google Play's listing on a phone with the phone screenshots' row;
- ``contact-sheet.html``: every target x locale x shot, panoramas' seams shown as red gutters, fallbacks and
  caption problems badged.

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
                if name.endswith((".html", ".png", ".css")):
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


def parser():
    """The argument parser."""
    p = argparse.ArgumentParser(prog="sheet.py", description="Mock the stores' pages at real size from the rendered "
                                "screenshots, and a contact sheet of the set. Offline.")
    p.add_argument("--config", default="store-screenshots.json", help="the design config (default: %(default)s)")
    p.add_argument("--report", help="the render report (default: <out>/render-report.json)")
    p.add_argument("--listing", help="store-listing.json, for the app's name and icon (default: beside the config)")
    p.add_argument("--png", action="store_true", help="render the pages to PNG through headless Chrome")
    return p


def main(argv=None):
    """Write the sheets (and with --png render them); return the exit code."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    try:
        inputs = check.Inputs(args.config, args.listing, report_path=args.report)
    except (check.UsageError, jsonio.JsonError, rules.RulesError) as e:
        sys.stderr.write("sheet.py: %s\n" % e)
        return EXIT_USAGE
    sheets = Sheets(inputs)
    pages = sheets.write()
    sys.stdout.write("Wrote %d page%s in %s.\n" % (len(pages), "" if len(pages) == 1 else "s", sheets.folder))
    if not args.png:
        for page, _, _ in pages:
            sys.stdout.write("  %s\n" % os.path.join(sheets.folder, page))
        return EXIT_OK
    try:
        chrome.find_chrome()
    except chrome.ChromeNotFound as e:
        sys.stderr.write("sheet.py: the HTML is written, but no PNGs: %s\n" % e)
        return EXIT_USAGE
    try:
        done = sheets.render(pages)
    except chrome.ChromeError as e:
        sys.stderr.write("sheet.py: Chrome couldn't render the sheets: %s\n" % e)
        return EXIT_USAGE
    for path in done:
        sys.stdout.write("  %s\n" % path)
    sys.stdout.write("Open every picture above at full size. They're approximations of the stores' pages, sized from "
                     "derived numbers, not the stores' own rendering.\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
