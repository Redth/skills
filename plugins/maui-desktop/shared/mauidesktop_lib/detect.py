"""Detection: what a .NET MAUI desktop project already has, read from its files (CONTRACT.md section 7.1).

``scan(root) -> dict`` walks the project once (``msbuild.walk``: no ``bin``, ``obj``, ``node_modules``,
``.git``, vendored ``wwwroot/lib`` or ``wwwroot/vendor``; symlinks noted, never followed), reads the project
files and greps the sources. It never runs ``dotnet`` and never writes. Every claim it makes comes with
evidence lines, ``"<relative path>: <the matching text, at most 120 characters>"``, with ``/`` separators.

Top-level keys: ``root``, ``solution``, ``dotnet``, ``projects``, ``heads``, ``backends``, ``sharing``,
``shell``, ``dialogs``, ``design``, ``integrations``, ``distribution``, ``tests``, ``agentDocs`` (the
contract's), plus ``app`` (name, id, namespace and minimum OS versions from the heads), ``stack`` (content
technology and component library), ``engineering`` (DevFlow, crash reporting, gallery),
``integrationPlatforms`` (each integration's platforms, ``"*"`` for shared code) and ``deepLinkSchemes``.

``integrations`` maps each integration to its evidence lines (empty: not found). Besides the contract's
eight it reports ``badge``, ``progress``, ``fileTypes``, ``fileDrop`` and ``contextMenus`` (native APIs only).
"""

from __future__ import annotations

import json
import os
import re

from . import msbuild

PLATFORMS = ("macos", "windows", "linux")
HEAD_ORDER = ("macos", "windows", "linux", "maccatalyst", "ios", "android")
EVIDENCE_LIMIT = 120
MAX_EVIDENCE = 12

CODE_EXTS = (".cs", ".razor", ".cshtml", ".xaml", ".plist", ".csproj", ".props", ".targets", ".appxmanifest",
             ".manifest", ".desktop", ".entitlements")
STYLE_EXTS = (".css", ".razor")
LINK_ITEM_KINDS = ("Compile", "RazorComponent", "BundleResource", "Content", "EmbeddedResource", "MauiAsset",
                   "MauiImage", "MauiFont", "MauiIcon", "MauiSplashScreen", "None", "AdditionalFiles")
TEST_PACKAGES = ("microsoft.net.test.sdk", "xunit", "xunit.v3", "nunit", "mstest", "mstest.testframework")
UI_TEST_PACKAGES = ("appium.webdriver", "microsoft.playwright", "selenium.webdriver", "bunit",
                    "microsoft.playwright.nunit", "microsoft.playwright.mstest")
AGENT_DOCS = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "DESIGN.md", "PRODUCT.md", ".github/copilot-instructions.md",
              ".cursorrules", ".windsurfrules")
BACKEND_PACKAGES = {
    "macos": ("Microsoft.Maui.Platforms.MacOS",),
    "linux": ("Microsoft.Maui.Platforms.Linux.Gtk4",),
    "windows": ("Microsoft.Maui.Controls",),
}
COMPONENT_LIBRARIES = (
    ("mudblazor", "MudBlazor"), ("radzen.blazor", "Radzen"), ("microsoft.fluentui.aspnetcore.components", "Fluent UI Blazor"),
    ("antdesign", "Ant Design Blazor"), ("bootstrapblazor", "BootstrapBlazor"), ("blazorise.bootstrap", "Blazorise"),
    ("blazorise.bootstrap5", "Blazorise"), ("blazorise.fluentui2", "Blazorise"), ("syncfusion.blazor", "Syncfusion"),
    ("telerik.ui.for.blazor", "Telerik"), ("devexpress.blazor", "DevExpress"), ("havit.blazor.components.web.bootstrap", "Havit"),
    ("blazorbootstrap", "BlazorBootstrap"), ("masa.blazor", "MASA Blazor"),
)
CRASH_PACKAGES = (("sentry", "sentry"), ("microsoft.appcenter.crashes", "appcenter"), ("bugsnag", "bugsnag"),
                  ("mindscape.raygun4net", "raygun"), ("microsoft.applicationinsights", "application-insights"),
                  ("raygun", "raygun"))
PLATFORM_SUFFIX = re.compile(r"\.(MacOS|Mac|macOS|Windows|Win|WinUI|LinuxGtk|Linux|Gtk|Gtk4|Desktop|MacCatalyst)$")


def _rx(pattern, flags=0):
    return re.compile(pattern, flags | re.MULTILINE)


# --- signals --------------------------------------------------------------------------------------------

NAV_MANIFEST = _rx(r"\b(?:class|record|interface)\s+\w*Nav(?:igation)?Manifest\b")
NAV_LINK = _rx(r"<NavLink\b")
SIDEBAR_NATIVE = _rx(r"\bFlyoutPage\b|\bNavigationView\b|\bNSSplitView(?:Controller)?\b|\bNSOutlineView\b"
                     r"|\b\w*Sidebar\w*(?:Item|Handler|Host|Page)\b|\bclass\s+\w*Sidebar\w*|\bNavigationSplitView\b"
                     r"|\bAdw\.\w*Split\w*|\bGtk\.ListBox\b|\bStackSidebar\b")
TOOLBAR_DECLARED = _rx(r"\b(?:record|class)\s+(?:PageChrome|ChromeAction)\b")
TOOLBAR_IMPERATIVE = _rx(r"\binterface\s+I\w*ToolbarService\b|\b(?:record|class)\s+ToolbarAction\b"
                         r"|\bToolbarItems\.Add\s*\(|\bnew\s+ToolbarItem\b|\bNSToolbar\b")
TOOLBAR_WEB = _rx(r"""class\s*=\s*["'][^"']*\btoolbar\b|<\w*Toolbar\b""")
MENU_MACOS = _rx(r"\bMainMenu\b|\bMenuBarItems?\b|SharedApplication\.Menu\b")
MENU_WINDOWS = _rx(r"\bMenuBarItems?\b|<MenuBar\b|\bnew\s+MenuBar\b")
MENU_LINUX = _rx(r"\bPopoverMenuBar\b|\bGtk\.MenuBar\b|\bSetMenubar\b|\bset_menubar\b|\bMenuBarItems?\b")
COMMAND_PALETTE = _rx(r"\b\w*CommandPalette\w*\b")
MULTI_WINDOW = _rx(r"\bOpenWindow\s*\(|\bnew\s+Window\s*\(")
OPEN_WINDOW = _rx(r"\bOpenWindow\s*\(")
CREATE_WINDOW = _rx(r"\bCreateWindow\s*\(")
DIALOG_SESSION = _rx(r"\b(?:class|record)\s+(?:DialogSession|DialogRequest)\b|\binterface\s+IDialogSession\b")
DIALOG_REQUEST_USE = _rx(r"\bnew\s+DialogRequest\b")
DIALOG_SUBCLASS = _rx(r"^[^\n]*\bclass\s+(\w+)\s*(?:<[^>{\n]*>)?\s*:\s*(\w*(?:FormPage|DialogPage|ModalPage|SheetPage)\w*)\b")
WEB_OVERLAY = _rx(r"""class\s*=\s*["'][^"']*\bmodal-overlay\b|<dialog\b|class\s*=\s*["']modal\b""")
ALERTS = _rx(r"\bDisplayAlert(?:Async)?\b|\bDisplayActionSheet(?:Async)?\b|\bNSAlert\b|\bContentDialog\b"
             r"|\bMessageDialog\b|\bAlertDialog\b")
PLATFORM_SELECTOR = _rx(r"""\.platform-(macos|windows|linux)\b|\[data-platform\s*=\s*["']?(macos|windows|linux)\b""")
HEX = re.compile(r"(?<![\w&#-])(?<!url\()#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")
CSS_DECL = re.compile(r"[\w-]+\s*:\s*([^;{}]*)")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
RAZOR_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
RAZOR_STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
GENERATED_HEAD = re.compile(r"auto-generated|<auto-generated|generated by|do not edit|@generated", re.IGNORECASE)
ICON_SOURCES = (
    ("sf-symbols", _rx(r"\bSfSymbol\b|\bSFSymbol\b|\bSystemSymbol\w*|GetSystemSymbol|systemSymbolName")),
    ("font-awesome", _rx(r"\bfa-(?:solid|regular|brands)\b|\bFontAwesome\b")),
    ("fluent-glyphs", _rx(r"\bFontIcon\b|\bFluentIcons?\b|Segoe Fluent Icons|Segoe MDL2")),
    ("gtk-icon-names", _rx(r"""["'][a-z0-9]+(?:-[a-z0-9]+)*-symbolic["']""")),
)
GALLERY = _rx(r"""@page\s+["']/(?:gallery|components|storybook)\b""", re.IGNORECASE)

# (integration, pattern, platform or None, flags). A hit's platform is the signal's, else its head's.
INTEGRATION_SIGNALS = (
    ("tray", r"\bNSStatusItem\b|\bNSStatusBar\b", "macos"),
    ("tray", r"\bShell_NotifyIcon\b|\bH\.NotifyIcon\b|\bTaskbarIcon\b|\bNotifyIcon\b", "windows"),
    ("tray", r"\bStatusNotifierItem\b|\bAppIndicator\b|\bayatana\b", "linux"),
    ("notifications", r"\bUNUserNotificationCenter\b|\bNSUserNotificationCenter\b", "macos"),
    ("notifications", r"\bAppNotificationManager\b|\bToastNotificationManager\b|\bAppNotificationBuilder\b", "windows"),
    ("notifications", r"org\.freedesktop\.Notifications|\bSendNotification\s*\(\s*\"[^\"\n]*\"\s*,|\bGNotification\b"
                      r"|\bGio\.Notification\b", "linux"),
    ("badge", r"\bDockTile\b[^\n]*\bBadgeLabel\b|\bBadgeLabel\b", "macos"),
    ("badge", r"\bBadgeNotificationManager\b|\bBadgeUpdateManager\b|\bSetOverlayIcon\b", "windows"),
    ("badge", r"com\.canonical\.Unity\.LauncherEntry", "linux"),
    ("progress", r"\bITaskbarList3\b|\bSetProgressValue\b|\bSetProgressState\b|\bTaskbarItemInfo\b", "windows"),
    ("progress", r"\bDockTile\.ContentView\b|\bNSDockTile\b[^\n]*\bProgress", "macos"),
    ("singleInstance", r"\bAppInstance\.FindOrRegisterForKey\b|\bRedirectActivationToAsync\b", "windows"),
    ("singleInstance", r"""\bnew\s+Mutex\s*\([^)\n]*["']""", None),
    ("singleInstance", r"\bLSMultipleInstancesProhibited\b", "macos"),
    ("deepLinks", r"\bCFBundleURLTypes\b|\bCFBundleURLSchemes\b|\bOpenUrls\b|\bkAEGetURL\b|\bHandleGetUrlEvent\b", "macos"),
    ("deepLinks", r"\buap:Protocol\b|\bwindows\.protocol\b|\bExtendedActivationKind\.Protocol\b|URL Protocol", "windows"),
    ("deepLinks", r"\bx-scheme-handler\b", "linux"),
    ("fileTypes", r"\bCFBundleDocumentTypes\b", "macos"),
    ("fileTypes", r"\buap:FileTypeAssociation\b|\bwindows\.fileTypeAssociation\b|\bExtendedActivationKind\.File\b", "windows"),
    ("launchAtLogin", r"\bSMAppService\b|\bSMLoginItemSetEnabled\b|\bLaunchAgents\b", "macos"),
    ("launchAtLogin", r"\bStartupTask\b|CurrentVersion\\{1,2}Run\b", "windows"),
    ("launchAtLogin", r"[\"'/]autostart\b|\bX-GNOME-Autostart\b|\bRequestBackground\b", "linux"),
    ("globalHotkey", r"\bRegisterHotKey\b", "windows"),
    ("globalHotkey", r"\bRegisterEventHotKey\b|\bAddGlobalMonitorForEventsMatchingMask\b", "macos"),
    ("globalHotkey", r"\bGlobalShortcuts\b", "linux"),
    ("autoUpdate", r"(?i)\bvelopack\b|\bNetSparkle\b", None),
    ("autoUpdate", r"\bSparkle\b|\bSUFeedURL\b|\bSPUStandardUpdaterController\b|\bSUUpdater\b", "macos"),
    ("autoUpdate", r"\bWinSparkle\b|\bSquirrel\b", "windows"),
    ("autoUpdate", r"api\.github\.com/repos/[^\s\"']*/releases", None),
    ("windowState", r"\bSetFrameAutosaveName\b|\bFrameAutosaveName\b", "macos"),
    ("windowState", r"\bGetWindowPlacement\b|\bSetWindowPlacement\b|\bWINDOWPLACEMENT\b", "windows"),
    ("windowState", r"""(?i)["'][\w.:-]*window[_.:-]?(?:width|height|size|bounds|frame|position|placement|maximi[sz]ed|left|top)(?![a-z])[\w.:-]*["']""", None),
    ("fileDrop", r"@ondrop\b|\bDropGestureRecognizer\b|\bRegisterForDraggedTypes\b|\bAllowDrop\b|\bDropTarget\b", None),
    ("contextMenus", r"\bContextMenuRequested\b|\bPopUpContextMenu\b|\bMenuForEvent\b|\bOnContextMenu\b|[\x27\x22]context-menu[\x27\x22]", None),
)
INTEGRATIONS = ("tray", "notifications", "singleInstance", "deepLinks", "launchAtLogin", "globalHotkey",
                "autoUpdate", "windowState", "badge", "progress", "fileTypes", "fileDrop", "contextMenus")
_INTEGRATION_RX = [(k, re.compile(p, re.MULTILINE), plat) for k, p, plat in INTEGRATION_SIGNALS]
SCHEME_PLIST = re.compile(r"<key>\s*CFBundleURLSchemes\s*</key>\s*<array>\s*<string>\s*([^<\s]+)\s*</string>")
SCHEME_DESKTOP = re.compile(r"x-scheme-handler/([a-z][a-z0-9+.-]*)")
SCHEME_APPX = re.compile(r"""<uap:Protocol\b[^>]*\bName\s*=\s*["']([a-z][a-z0-9+.-]*)["']""")

# Distribution: (platform, tag, pattern, flags).
DISTRIBUTION_SIGNALS = (
    ("macos", "codesign", r"\bcodesign\b", 0),
    ("macos", "notarize", r"\bnotarytool\b|altool[ \t]+--notarize|\bnotariz(?:e|ation)\b", re.IGNORECASE),
    ("macos", "dmg", r"\bhdiutil\b|\bcreate-dmg\b|\.dmg\b", 0),
    ("macos", "homebrew", r"\bhomebrew\b|\bbrew[ \t]+(?:tap|bump|install[ \t]+--cask)|^[ \t]*cask[ \t]+[\"']", re.IGNORECASE),
    ("macos", "mac-app-store", r"\bproductbuild\b|altool[ \t]+--upload|\biTMSTransporter\b|\bmac-app-store\b", re.IGNORECASE),
    ("windows", "signing", r"\bsigntool\b|\bAzureSignTool\b|trusted-signing|\bsigncode\b", re.IGNORECASE),
    ("windows", "inno-setup", r"\bISCC\b|Inno Setup|\.iss\b", 0),
    ("windows", "winget", r"\bwinget\b", re.IGNORECASE),
    ("windows", "msix", r"\bmsix(?:bundle)?\b|\bmakeappx\b|WindowsPackageType>\s*MSIX", re.IGNORECASE),
    ("windows", "wix", r"\bwix\b|\.wxs\b|\bWixToolset\b", re.IGNORECASE),
    ("windows", "velopack", r"\bvelopack\b|\bvpk[ \t]+pack\b", re.IGNORECASE),
    ("windows", "microsoft-store", r"\bmsstore\b|\bmicrosoft-store\b|Microsoft Store|Partner Center", re.IGNORECASE),
    ("linux", "deb", r"CreateDeb(?:=|>)[ \t]*true\b|\bdpkg-deb\b", re.IGNORECASE),
    ("linux", "rpm", r"CreateRpm(?:=|>)[ \t]*true\b|\brpmbuild\b", re.IGNORECASE),
    ("linux", "appimage", r"CreateAppImage(?:=|>)[ \t]*true\b|\bappimagetool\b|\blinuxdeploy\b", re.IGNORECASE),
    ("linux", "flatpak", r"CreateFlatpak(?:=|>)[ \t]*true\b|flatpak-builder[ \t]+-|flatpak[ \t]+build-bundle", re.IGNORECASE),
    ("linux", "snap", r"\bsnapcraft\b", re.IGNORECASE),
)
_DIST_RX = [(p, t, re.compile(rx, f | re.MULTILINE)) for p, t, rx, f in DISTRIBUTION_SIGNALS]
DIST_SCRIPT_EXTS = (".sh", ".ps1", ".psm1", ".cmd", ".bat", ".py", ".mjs", ".js", ".cake", ".yml", ".yaml",
                    ".iss", ".wxs", ".rb", ".csproj", ".props", ".targets")
DIST_DIRS = ("build", "eng", "scripts", "packaging", "installer", "installers", "deploy", "dist", "Casks", "winget")


# --- helpers --------------------------------------------------------------------------------------------

def trim(text, at=0, limit=EVIDENCE_LIMIT):
    """``text`` cut to ``limit`` characters around position ``at`` (``…`` marks a cut)."""
    if len(text) <= limit:
        return text
    start = max(0, min(at - 30, len(text) - limit))
    piece = text[start:start + limit]
    if start > 0:
        piece = "…" + piece[1:]
    if start + limit < len(text):
        piece = piece[:-1] + "…"
    return piece


def evidence_line(rel, text, start):
    """``"<rel>: <the stripped line holding position start, trimmed to 120 characters>"``."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end].rstrip("\r")
    stripped = line.strip()
    offset = max(0, start - line_start - (len(line) - len(line.lstrip())))
    return "%s: %s" % (rel, trim(stripped, offset))


_HASH_COMMENT_EXTS = (".yml", ".yaml", ".sh", ".ps1", ".psm1", ".py", ".rb", ".desktop", ".toml")
_XML_EXTS = (".csproj", ".fsproj", ".vbproj", ".props", ".targets", ".plist", ".xml", ".xaml", ".appxmanifest",
             ".manifest", ".entitlements", ".wxs", ".html")
_BLOCK_XML = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_RAZOR = re.compile(r"@\*.*?\*@|<!--.*?-->", re.DOTALL)
_BLOCK_CSS = re.compile(r"/\*.*?\*/", re.DOTALL)
_SPANS = {}


def is_comment(rel, line):
    """True when a (stripped) line is a line comment in the file's language."""
    low = rel.lower()
    if low.endswith(_HASH_COMMENT_EXTS):
        return line.startswith("#")
    if low.endswith(_XML_EXTS):
        return line.startswith("<!--")
    return line.startswith(("//", "/*", "*", "@*", "<!--"))


def _block_spans(rel, text):
    """``(start, end)`` of the block comments a file's language makes unambiguous: XML ``<!-- -->``, Razor
    ``@* *@`` and ``<!-- -->``, CSS ``/* */``. (C#'s ``/* */`` isn't tracked: a glob string such as
    ``"**/*.cs"`` would open one; its doc-comment lines start with ``*`` or ``//`` and are caught by line.)"""
    key = (rel, len(text), hash(text))
    if key in _SPANS:
        return _SPANS[key]
    low = rel.lower()
    if low.endswith(_XML_EXTS):
        rx = _BLOCK_XML
    elif low.endswith((".razor", ".cshtml")):
        rx = _BLOCK_RAZOR
    elif low.endswith(".css"):
        rx = _BLOCK_CSS
    else:
        rx = None
    spans = [(m.start(), m.end()) for m in rx.finditer(text)] if rx else []
    if len(_SPANS) > 4096:
        _SPANS.clear()
    _SPANS[key] = spans
    return spans


def _commented(rel, text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    line = text[line_start:line_end if line_end >= 0 else len(text)].strip()
    if is_comment(rel, line):
        return True
    for a, b in _block_spans(rel, text):
        if a <= pos < b:
            return True
        if a > pos:
            break
    return False


def search(rx, rel, text):
    """The first match of ``rx`` in ``text`` that isn't in a comment, or ``None``: a comment naming an API
    (often to say why it isn't used) is never evidence that the app uses it."""
    for m in rx.finditer(text):
        if not _commented(rel, text, m.start()):
            return m
    return None


def finditer(rx, rel, text):
    """Every match of ``rx`` in ``text`` that isn't in a comment."""
    for m in rx.finditer(text):
        if not _commented(rel, text, m.start()):
            yield m


def _add(bucket, line, limit=MAX_EVIDENCE):
    if line not in bucket and len(bucket) < limit:
        bucket.append(line)


class _Tree(object):
    """The walked project: files, symlinks and a cache of their text."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.files = []
        self.links = []
        self._abs = {}
        self._text = {}
        for rel, full, is_link in msbuild.walk(self.root):
            if is_link:
                try:
                    target = os.readlink(full)
                except OSError:
                    target = "?"
                self.links.append((rel, target.replace("\\", "/")))
            else:
                self.files.append(rel)
                self._abs[rel] = full

    def abspath(self, rel):
        return self._abs.get(rel) or os.path.join(self.root, *rel.split("/"))

    def text(self, rel):
        if rel not in self._text:
            self._text[rel] = msbuild.read_text(self.abspath(rel), limit=2 * 1024 * 1024)
        return self._text[rel]

    def with_ext(self, exts):
        exts = tuple(e.lower() for e in exts)
        return [f for f in self.files if f.lower().endswith(exts)]

    def exists(self, rel):
        return rel in self._abs


def _is_generated(rel, text):
    name = rel.rsplit("/", 1)[-1].lower()
    if ".g." in name or name.endswith(".min.css") or name.endswith(".designer.cs"):
        return True
    return bool(GENERATED_HEAD.search(text[:400]))


def _placeholder_link(tree, rel):
    """A git symlink checked out as a plain file (``core.symlinks=false``, the Windows default): at most 260
    bytes, one line, a relative path (``../…``) to something that exists. Returns the target, or ``None``."""
    try:
        if os.path.getsize(tree.abspath(rel)) > 260:
            return None
    except OSError:
        return None
    text = tree.text(rel)
    target = (text or "").strip()
    if not target or "\n" in target or not target.startswith(("../", "..\\")):
        return None
    target = target.replace("\\", "/")
    base = os.path.dirname(tree.abspath(rel))
    if os.path.exists(os.path.normpath(os.path.join(base, *target.split("/")))):
        return target
    return None


# --- projects -------------------------------------------------------------------------------------------

def _head_platforms(p):
    plats = set(msbuild.tfm_platform(t) for t in p.target_frameworks)
    ids = [i.lower() for i in p.package_ids()]
    maui = p.has_true("UseMaui")
    out = []
    if ("macos" in plats and maui) or "microsoft.maui.platforms.macos" in ids:
        out.append("macos")
    if "windows" in plats and maui:
        out.append("windows")
    if any(i.startswith("microsoft.maui.platforms.linux") for i in ids):
        out.append("linux")
    for plat in ("maccatalyst", "ios", "android"):
        if plat in plats and maui:
            out.append(plat)
    return out


def _base_role(p, rel, razor_count):
    ids = [i.lower() for i in p.package_ids()]
    sdks = [s.lower() for s in p.sdks]
    if p.has_true("IsTestProject") or any(i in TEST_PACKAGES for i in ids) or "mstest.sdk" in sdks:
        return "tests"
    heads = _head_platforms(p)
    if heads:
        return "head-" + heads[0]
    if p.has_true("PackAsTool"):
        return "tool"
    exe = any((v or "").strip().lower() in ("exe", "winexe") for v in p.values("OutputType"))
    if "microsoft.net.sdk.web" in sdks:
        return "web"  # settled in the second pass: devhost or tool
    if "microsoft.net.sdk.razor" in sdks and not exe and razor_count:
        return "ui"
    if not exe:
        name = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if re.search(r"(?:^|\.)(?:Core|Shared|Common|Abstractions|Domain)(?:$|\.)", name):
            return "core"
        return "other"
    return "tool"


def _owner_map(projects):
    dirs = sorted(((p["dir"], p) for p in projects), key=lambda x: -len(x[0]))

    def owner(rel):
        for d, p in dirs:
            if d == "" or rel == d or rel.startswith(d + "/"):
                return p
        return None
    return owner


def _resolve_include(project_dir, include):
    """The static part of an include (before any wildcard), as a root-relative ``/`` path, or ``None`` when it
    leaves the root."""
    static = re.split(r"[*?]", include, maxsplit=1)[0]
    joined = os.path.normpath(os.path.join(project_dir or ".", *static.replace("\\", "/").split("/")))
    joined = joined.replace(os.sep, "/")
    if joined.startswith("..") or os.path.isabs(joined):
        return None
    return "" if joined == "." else joined


def _line_containing(rel, text, needle):
    if text is None:
        return "%s: %s" % (rel, trim(needle))
    i = text.find(needle)
    if i < 0:
        return "%s: %s" % (rel, trim(needle))
    return evidence_line(rel, text, i)


def _read_projects(tree, root):
    projects = []
    raw = {}
    razor_files = tree.with_ext((".razor",))
    for rel in sorted(f for f in tree.files if f.lower().endswith(msbuild.PROJECT_EXTS)):
        try:
            p = msbuild.read_project(tree.abspath(rel), msbuild.central_versions_for(tree.abspath(rel), root))
        except OSError:
            continue
        d = rel.rsplit("/", 1)[0] if "/" in rel else ""
        raw[rel] = p
        projects.append({"path": rel, "dir": d, "_p": p})
    owner = _owner_map(projects)
    razor_count = {}
    for f in razor_files:
        o = owner(f)
        if o is not None:
            razor_count[o["path"]] = razor_count.get(o["path"], 0) + 1
    for info in projects:
        p = info["_p"]
        info["role"] = _base_role(p, info["path"], razor_count.get(info["path"], 0))
        info["razor"] = razor_count.get(info["path"], 0)
        info["platforms"] = _head_platforms(p) if info["role"].startswith("head-") else []
    by_path = {i["path"]: i for i in projects}
    for info in projects:
        info["refs"] = []
        for ref in info["_p"].project_refs:
            target = _resolve_include(info["dir"], ref)
            if target in by_path:
                info["refs"].append(target)
    for info in projects:
        if info["role"] == "web":
            refs_ui = any(by_path[r]["role"] == "ui" for r in info["refs"])
            info["role"] = "devhost" if (refs_ui or info["razor"]) else "tool"
    return projects, owner


def _packages(p):
    out = {}
    for pid, ver, _cond in p.package_refs:
        if pid not in out or (out[pid] is None and ver):
            out[pid] = ver
    return out


# --- sections -------------------------------------------------------------------------------------------

def _sharing(tree, projects, owner):
    heads = [i for i in projects if i["role"].startswith("head-")]
    symlinks = []
    for rel, target in tree.links:
        _add(symlinks, "%s -> %s" % (rel, target))
    for rel in tree.files:
        if len(symlinks) < MAX_EVIDENCE:
            target = _placeholder_link(tree, rel)
            if target:
                _add(symlinks, "%s -> %s (a symlink checked out as a file)" % (rel, target))
    links = []
    linked_into = set()
    for info in heads:
        p = info["_p"]
        text = tree.text(info["path"])
        for kind in LINK_ITEM_KINDS:
            for include, attrs in p.items.get(kind, []):
                if not include.startswith("..") and "/.." not in include:
                    continue
                target = _resolve_include(info["dir"], include)
                if target is None:
                    continue
                other = owner(target + "/x") if target else None
                if other is None or other is info:
                    continue
                linked_into.add(other["path"])
                raw = attrs.get("Include") or attrs.get("Update") or include
                _add(links, _line_containing(info["path"], text, raw))
    for rel, target in tree.links:
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        dest = _resolve_include(base, target)
        if dest is not None:
            other = owner(dest + "/x")
            if other is not None and other is not owner(rel):
                linked_into.add(other["path"])
    rcl = []
    for info in heads:
        for ref in info["refs"]:
            target = next((i for i in projects if i["path"] == ref), None)
            if target is not None and target["role"] == "ui":
                text = tree.text(info["path"])
                name = ref.rsplit("/", 1)[-1]
                _add(rcl, _line_containing(info["path"], text, name))
    if symlinks:
        kind = "symlinks"
    elif links:
        kind = "links"
    elif rcl:
        kind = "rcl"
    elif len(heads) == 1:
        kind = "single"
    else:
        kind = "unknown"
    return {"kind": kind, "evidence": symlinks + links + rcl}, linked_into, bool(links)


def _source_files(tree, projects, owner, exts=CODE_EXTS):
    """The non-test source files with the given extensions."""
    out = []
    for rel in tree.with_ext(exts):
        top = rel.split("/", 1)[0].lower()
        if top in ("tests", "test"):
            continue
        o = owner(rel)
        if o is not None and o["role"] == "tests":
            continue
        out.append(rel)
    return out


def _first_hits(tree, files, rx, limit=MAX_EVIDENCE):
    """One evidence line a file for the first match of ``rx`` (at most ``limit`` lines), and the number of
    files that matched."""
    lines, count = [], 0
    for rel in files:
        text = tree.text(rel)
        if not text:
            continue
        m = search(rx, rel, text)
        if m:
            count += 1
            _add(lines, evidence_line(rel, text, m.start()), limit)
    return lines, count


def _head_files(files, owner, info, code_only=True):
    out = []
    for rel in files:
        if owner(rel) is info and (not code_only or not rel.lower().endswith((".razor", ".cshtml"))):
            out.append(rel)
    return out


def _shell(tree, heads, owner, sources):
    razor = [f for f in sources if f.lower().endswith(".razor")]
    cs = [f for f in sources if not f.lower().endswith(".razor")]
    manifest, _ = _first_hits(tree, cs, NAV_MANIFEST)
    navlinks, _ = _first_hits(tree, razor, NAV_LINK)
    sidebar, sidebar_ev, native_heads = {}, [], 0
    menubar, menubar_ev = {}, []
    menu_rx = {"macos": MENU_MACOS, "windows": MENU_WINDOWS, "linux": MENU_LINUX}
    for plat in PLATFORMS:
        info = heads.get(plat)
        if info is None:
            sidebar[plat] = None
            menubar[plat] = None
            continue
        files = _head_files(cs, owner, info)
        hits, _ = _first_hits(tree, files, SIDEBAR_NATIVE, 3)
        if hits:
            sidebar[plat] = "native"
            native_heads += 1
            for h in hits:
                _add(sidebar_ev, h)
        else:
            sidebar[plat] = "web" if navlinks else "none"
        mhits, _ = _first_hits(tree, files, menu_rx[plat], 3)
        if mhits:
            menubar[plat] = "custom-items"
            for h in mhits:
                _add(menubar_ev, h)
        else:
            menubar[plat] = "default" if plat == "macos" else "none"
    sidebar["web"] = "web" if navlinks else None
    if manifest:
        nav = {"kind": "manifest", "evidence": manifest}
    elif native_heads:
        nav = {"kind": "per-head", "evidence": list(sidebar_ev)}
    elif navlinks:
        nav = {"kind": "web", "evidence": navlinks[:6]}
    else:
        nav = {"kind": "unknown", "evidence": []}
    declared, _ = _first_hits(tree, sources, TOOLBAR_DECLARED)
    imperative, imperative_files = _first_hits(tree, cs, TOOLBAR_IMPERATIVE)
    webbar, _ = _first_hits(tree, razor, TOOLBAR_WEB, 6)
    if declared:
        toolbar = {"kind": "declared", "evidence": declared}
    elif imperative:
        toolbar = {"kind": "imperative", "evidence": imperative}
    elif webbar:
        toolbar = {"kind": "web", "evidence": webbar}
    else:
        toolbar = {"kind": "none", "evidence": []}
    palette, _ = _first_hits(tree, sources, COMMAND_PALETTE, 4)
    for rel in sources:
        if "commandpalette" in rel.lower().rsplit("/", 1)[-1]:
            _add(palette, "%s: (file)" % rel, 4)
    # ``new Window(...)`` inside an app's ``CreateWindow`` override is the main window, not a second one.
    windows = []
    for rel in cs:
        text = tree.text(rel)
        if not text:
            continue
        rx = OPEN_WINDOW if CREATE_WINDOW.search(text) else MULTI_WINDOW
        m = search(rx, rel, text)
        if m:
            _add(windows, evidence_line(rel, text, m.start()), 4)
    return {
        "navigation": nav,
        "toolbar": toolbar,
        "sidebar": sidebar,
        "sidebarEvidence": sidebar_ev,
        "menuBar": menubar,
        "menuBarEvidence": menubar_ev,
        "commandPalette": palette,
        "multiWindow": windows,
    }


def _dialogs(tree, sources):
    razor = [f for f in sources if f.lower().endswith(".razor")]
    cs = [f for f in sources if f.lower().endswith(".cs")]
    session, _ = _first_hits(tree, cs, DIALOG_SESSION)
    requests, request_files = _first_hits(tree, sources, DIALOG_REQUEST_USE)
    subclasses, sub_ev = set(), []
    for rel in cs:
        text = tree.text(rel)
        if not text:
            continue
        for m in finditer(DIALOG_SUBCLASS, rel, text):
            line = m.group(0)
            if re.search(r"\babstract\b", line.split("class", 1)[0]):
                continue
            if m.group(1) in subclasses:
                continue
            subclasses.add(m.group(1))
            _add(sub_ev, evidence_line(rel, text, m.start(1)))
    overlays, overlay_files = _first_hits(tree, razor, WEB_OVERLAY)
    alerts, alert_files = _first_hits(tree, sources, ALERTS, 6)
    if session:
        kind, count, ev = "session", request_files, session + requests
    elif subclasses:
        kind, count, ev = "page-subclass", len(subclasses), sub_ev
    elif overlay_files:
        kind, count, ev = "web", overlay_files, overlays
    elif alert_files:
        kind, count, ev = "alerts-only", alert_files, alerts
    else:
        kind, count, ev = "none", 0, []
    if kind != "web":
        for line in overlays[:4]:
            _add(ev, line)
    return {"kind": kind, "count": count, "webOverlays": overlay_files, "evidence": ev[:MAX_EVIDENCE]}


def _find_named(tree, name):
    """``name`` at the root, else the shallowest file of that relative tail anywhere, or ``None``."""
    if tree.exists(name):
        return name
    hits = sorted((f for f in tree.files if f == name or f.endswith("/" + name)), key=lambda f: (f.count("/"), f))
    return hits[0] if hits else None


def hex_count(rel, text):
    """The raw hex colours in a stylesheet's declarations, or in a Razor file's ``<style>`` blocks and
    ``style`` attributes (so ``href="#top"`` and "issue #123" in markup don't count)."""
    if rel.lower().endswith(".css"):
        chunks = [text]
    else:
        chunks = [m.group(1) for m in RAZOR_STYLE_BLOCK.finditer(text)]
        chunks += [m.group(1) or m.group(2) or "" for m in RAZOR_STYLE_ATTR.finditer(text)]
    n = 0
    for chunk in chunks:
        for m in CSS_DECL.finditer(CSS_COMMENT.sub("", chunk)):
            n += len(HEX.findall(m.group(1)))
    return n


def _design(tree, sources, owner, projects):
    design_md = _find_named(tree, "DESIGN.md")
    tokens = _find_named(tree, "design/tokens.json")
    icons = _find_named(tree, "design/icons.json")
    styles = [f for f in tree.with_ext(STYLE_EXTS)
              if f.split("/", 1)[0].lower() not in ("tests", "test") and
              (owner(f) is None or owner(f)["role"] != "tests")]
    raw_hex, per_file = 0, []
    selectors = {"macos": 0, "windows": 0, "linux": 0}
    for rel in styles:
        text = tree.text(rel)
        if not text or _is_generated(rel, text):
            continue
        n = hex_count(rel, text)
        if n:
            raw_hex += n
            per_file.append((n, rel))
        for m in finditer(PLATFORM_SELECTOR, rel, text):
            selectors[m.group(1) or m.group(2)] += 1
    evidence = ["%s: (present)" % p for p in (design_md, tokens, icons) if p]
    for n, rel in sorted(per_file, key=lambda x: (-x[0], x[1]))[:5]:
        evidence.append("%s: %d raw hex colour%s" % (rel, n, "" if n == 1 else "s"))
    icon_sources = {}
    icon_ev = []
    for tag, rx in ICON_SOURCES:
        hits, count = _first_hits(tree, sources + [s for s in styles if s.endswith(".css")], rx, 2)
        if count:
            icon_sources[tag] = count
            for h in hits:
                _add(icon_ev, h)
    token_platforms = []
    if tokens:
        text = tree.text(tokens) or ""
        try:
            data = json.loads(text)
            plats = data.get("platforms") if isinstance(data, dict) else None
            if isinstance(plats, dict):
                token_platforms = sorted(k for k in plats if not k.startswith("$"))
        except ValueError:
            pass
    return {
        "designMd": bool(design_md), "tokensJson": bool(tokens), "iconsJson": bool(icons),
        "rawHex": raw_hex, "platformSelectors": selectors,
        "paths": {"designMd": design_md, "tokensJson": tokens, "iconsJson": icons},
        "tokenPlatforms": token_platforms,
        "iconSources": icon_sources, "iconEvidence": icon_ev,
        "evidence": evidence,
    }


def _integrations(tree, sources, owner):
    found = {k: [] for k in INTEGRATIONS}
    plats = {k: set() for k in INTEGRATIONS}
    schemes = []
    for rel in sources:
        text = tree.text(rel)
        if not text:
            continue
        o = owner(rel)
        head = None
        if o is not None and len(o["platforms"]) == 1 and o["platforms"][0] in PLATFORMS:
            head = o["platforms"][0]
        for key, rx, plat in _INTEGRATION_RX:
            m = search(rx, rel, text)
            if not m:
                continue
            _add(found[key], evidence_line(rel, text, m.start()))
            plats[key].add(plat or head or "*")
        for rx in (SCHEME_PLIST, SCHEME_DESKTOP, SCHEME_APPX):
            for m in rx.finditer(text):
                s = m.group(1).strip()
                if s and s not in schemes and "$(" not in s:
                    schemes.append(s)
    order = {p: i for i, p in enumerate(PLATFORMS + ("*",))}
    platforms = {k: sorted(v, key=lambda p: order.get(p, 9)) for k, v in plats.items() if v}
    return found, platforms, schemes


def _distribution(tree, projects):
    workflows = sorted(f for f in tree.files
                       if (f.startswith(".github/workflows/") and f.lower().endswith((".yml", ".yaml")))
                       or ("/" not in f and (f.startswith("azure-pipelines") or f == ".gitlab-ci.yml")))
    files = list(workflows)
    for f in tree.files:
        top = f.split("/", 1)[0]
        if top in DIST_DIRS and f.lower().endswith(DIST_SCRIPT_EXTS) and f not in files:
            files.append(f)
    for info in projects:
        if info["role"].startswith("head-") and info["path"] not in files:
            files.append(info["path"])
    for f in tree.files:
        if "/" not in f and f.lower().endswith((".props", ".targets")) and f not in files:
            files.append(f)
    tags = {"macos": [], "windows": [], "linux": []}
    evidence = []
    for rel in files:
        text = tree.text(rel)
        if not text:
            continue
        for plat, tag, rx in _DIST_RX:
            m = search(rx, rel, text)
            if m and tag not in tags[plat]:
                tags[plat].append(tag)
                _add(evidence, evidence_line(rel, text, m.start()), 20)
    for f in tree.files:
        low = f.lower()
        if low.endswith(".iss") and "inno-setup" not in tags["windows"]:
            tags["windows"].append("inno-setup")
            _add(evidence, "%s: (an Inno Setup script)" % f, 20)
        if low.endswith(".wxs") and "wix" not in tags["windows"]:
            tags["windows"].append("wix")
            _add(evidence, "%s: (a WiX source)" % f, 20)
        if low.rsplit("/", 1)[-1] in ("snapcraft.yaml", "snapcraft.yml") and "snap" not in tags["linux"]:
            tags["linux"].append("snap")
            _add(evidence, "%s: (a snap recipe)" % f, 20)
    for info in projects:
        for v in info["_p"].values("WindowsPackageType"):
            if v.strip().lower() == "msix" and "msix" not in tags["windows"]:
                tags["windows"].append("msix")
                _add(evidence, "%s: <WindowsPackageType>%s</WindowsPackageType>" % (info["path"], v), 20)
    out = {"workflows": workflows}
    out.update({p: sorted(t) for p, t in tags.items()})
    out["evidence"] = evidence
    return out


def _application_id(info):
    aid = info["_p"].prop("ApplicationId")
    return aid.strip().lower() if aid and "$(" not in aid else None


def _mark_other_apps(projects):
    """A head whose ApplicationId differs from the desktop heads' is a different app in the same repository (a
    sample, a test host, a companion app): give it the role ``other-app`` so it isn't reported as a head."""
    desktop = ("head-macos", "head-windows", "head-linux")
    ids = [_application_id(i) for i in projects if i["role"] in desktop]
    ids = [a for a in ids if a]
    if not ids:
        return
    primary = max(set(ids), key=ids.count)
    for info in projects:
        aid = _application_id(info)
        if info["role"].startswith("head-") and aid and aid != primary:
            info["role"] = "other-app"
            info["platforms"] = []


def _app(projects, solutions):
    heads = [i for i in projects if i["role"].startswith("head-")]
    order = {("head-" + p): n for n, p in enumerate(HEAD_ORDER)}
    heads.sort(key=lambda i: (order.get(i["role"], 9), i["path"]))
    name = app_id = namespace = None
    minimums = {}
    for info in heads:
        p = info["_p"]
        title = p.prop("ApplicationTitle")
        if not name and title and "$(" not in title:
            name = title
        aid = p.prop("ApplicationId")
        if not app_id and aid and "$(" not in aid:
            app_id = aid
        ns = p.prop("RootNamespace")
        if not namespace and ns and "$(" not in ns:
            namespace = PLATFORM_SUFFIX.sub("", ns)
        for plat in info["platforms"]:
            if plat in ("macos", "windows") and plat not in minimums:
                for v in p.values("SupportedOSPlatformVersion") + p.values("TargetPlatformMinVersion"):
                    if v and "$(" not in v and re.match(r"^\d+(\.\d+)*$", v.strip()):
                        minimums[plat] = v.strip()
                        break
    if not namespace and solutions:
        base = solutions[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        namespace = re.sub(r"[^A-Za-z0-9_.]", "", base) or None
    if not name and namespace:
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", namespace.split(".")[-1])
    return {"name": name, "id": app_id, "namespace": namespace, "minimums": minimums}


def _stack(tree, projects, sources):
    razor = any(f.lower().endswith(".razor") for f in sources)
    ids = set()
    for info in projects:
        for pid in info["_p"].package_ids():
            ids.add(pid.lower())
    blazor = razor or any(i.endswith("blazorwebview") or i == "microsoft.aspnetcore.components.webview.maui" for i in ids)
    library = None
    for pid, label in COMPONENT_LIBRARIES:
        if pid in ids or any(i.startswith(pid + ".") for i in ids):
            library = label
            break
    if projects:
        content = "blazor" if blazor else "other"
    else:
        content = None
    if library is None and content == "blazor":
        library = "custom"
    return {"content": content, "componentLibrary": library}


def _engineering(tree, projects, sources, heads):
    devflow, crash = [], None
    for info in projects:
        if info["role"] == "tests":
            continue
        for pid in info["_p"].package_ids():
            if pid.lower().startswith("microsoft.maui.devflow"):
                _add(devflow, "%s: %s" % (info["path"], pid), 6)
            if crash is None:
                for prefix, label in CRASH_PACKAGES:
                    if pid.lower() == prefix or pid.lower().startswith(prefix + "."):
                        crash = label
                        break
    gallery, _ = _first_hits(tree, [f for f in sources if f.lower().endswith(".razor")], GALLERY, 4)
    return {"devflow": devflow, "crashReporting": crash, "gallery": gallery, "devHost": heads.get("devhost")}


def scan(root):
    """Read the project under ``root`` and return the detection dict (module docstring; CONTRACT.md 7.1).

    Raises ``NotADirectoryError`` when ``root`` isn't a folder.
    """
    if not os.path.isdir(root):
        raise NotADirectoryError("not a folder: %s" % root)
    _SPANS.clear()
    abs_root = os.path.abspath(root)
    tree = _Tree(abs_root)
    solutions = msbuild.solution_files(abs_root)
    projects, owner = _read_projects(tree, abs_root)
    _mark_other_apps(projects)

    head_infos = {}
    for plat in HEAD_ORDER:
        primary = [i for i in projects if i["role"] == "head-" + plat]
        serving = [i for i in projects if plat in i["platforms"]]
        if primary or serving:
            head_infos[plat] = (primary or serving)[0]
    heads = {k: (head_infos[k]["path"] if k in head_infos else None) for k in HEAD_ORDER}
    devhosts = [i for i in projects if i["role"] == "devhost"]
    heads["devhost"] = devhosts[0]["path"] if devhosts else None
    backends = {}
    for plat in PLATFORMS:
        path = heads.get(plat)
        backends[plat] = None
        if not path:
            continue
        p = head_infos[plat]["_p"]
        for pid in BACKEND_PACKAGES[plat]:
            ver = p.package(pid)
            if ver is not None:
                backends[plat] = ("%s %s" % (pid, ver)).strip()
                break

    sharing, linked_into, _has_links = _sharing(tree, projects, owner)
    for info in projects:
        if info["role"].startswith("head-"):
            refs_ui = any(next((j for j in projects if j["path"] == r), {}).get("role") == "ui" for r in info["refs"])
            if info["path"] in linked_into or (info["razor"] and not refs_ui):
                info["alsoUi"] = True

    sources = _source_files(tree, projects, owner)
    shell = _shell(tree, head_infos, owner, sources)
    integrations, integration_platforms, schemes = _integrations(tree, sources, owner)

    tfms = set()
    for info in projects:
        tfms.update(info["_p"].target_frameworks)
    tests = [i["path"] for i in projects if i["role"] == "tests"]
    ui_tests = [i["path"] for i in projects if i["role"] == "tests"
                and any(pid.lower() in UI_TEST_PACKAGES for pid in i["_p"].package_ids())]
    agent_docs = [d for d in AGENT_DOCS if tree.exists(d)]

    out_projects = []
    for info in projects:
        entry = {"path": info["path"], "role": info["role"], "tfms": list(info["_p"].target_frameworks),
                 "packages": _packages(info["_p"])}
        if info.get("alsoUi"):
            entry["alsoUi"] = True
        if len(info["platforms"]) > 1:
            entry["platforms"] = list(info["platforms"])
        if info["_p"].error:
            entry["error"] = info["_p"].error
        out_projects.append(entry)

    return {
        "root": root.replace("\\", "/"),
        "solution": solutions,
        "dotnet": {"sdk": msbuild.sdk_version(abs_root), "tfms": sorted(tfms)},
        "projects": out_projects,
        "heads": heads,
        "backends": backends,
        "sharing": sharing,
        "shell": shell,
        "dialogs": _dialogs(tree, sources),
        "design": _design(tree, sources, owner, projects),
        "integrations": integrations,
        "integrationPlatforms": integration_platforms,
        "deepLinkSchemes": schemes,
        "distribution": _distribution(tree, projects),
        "tests": {"projects": tests, "ui": ui_tests},
        "agentDocs": agent_docs,
        "app": _app(projects, solutions),
        "stack": _stack(tree, projects, sources),
        "engineering": _engineering(tree, projects, sources, heads),
    }


def dotnet_version(detection):
    """``major.minor`` of the .NET the project uses: ``global.json``'s SDK, else the highest target
    framework, else ``None``."""
    sdk = (detection.get("dotnet") or {}).get("sdk")
    if sdk:
        m = re.match(r"^(\d+)\.(\d+)", sdk)
        if m:
            return "%s.%s" % (m.group(1), m.group(2))
    best = None
    for tfm in (detection.get("dotnet") or {}).get("tfms") or []:
        parsed = msbuild.parse_tfm(tfm)
        if parsed and (best is None or parsed[:2] > best):
            best = parsed[:2]
    return "%d.%d" % best if best else None
