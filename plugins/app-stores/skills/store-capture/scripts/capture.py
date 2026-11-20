#!/usr/bin/env python3
"""capture.py: capture an app's screens at exactly the sizes the stores want, by the plan's drivers.

    capture.py [--plan capture-plan.json] [--devices iphone-6.9,android-phone] [--screens plan,recipe]
               [--locales en-US,de-DE] [--keep-going] [--cleanup] [--dry-run] [--inspect]
    capture.py --write-staging [--plan …]       write staging.md (the plan's staging, readable) beside the plan
    capture.py --current [FOLDER]               list the current store screenshots to start the screen list from
    capture.py --changes [REVISION]             what changed in the app since the last capture, and which screens
                                                to re-check (git, in the plan's appSource)

For each device in the plan (CONTRACT.md 10.2) its driver prepares it (finds or creates and boots a dedicated
simulator, starts an emulator, opens a browser), then for each locale and each screen runs the screen's steps and
takes a screenshot, and always resets the device after (status bar, demo mode, display size, appearance, locale),
even when something failed. Each picture is checked: exactly the device's ``width`` x ``height`` (any other size is
``failed``, never resized), 8-bit RGB with no alpha, sRGB, not interlaced. One with an alpha channel (or 16 bits, a
colour profile other than sRGB, interlacing) is drawn again through headless Chrome onto the plan's ``flatten``
colour and the change listed in its ``fixes``.

Pictures are written into a temporary folder inside ``<out>`` and moved into place at the end:
``<out>/<locale>/<device id>/<screen id>.png``, with ``<out>/capture-report.json`` saying what was taken, missed
(``kept: previous`` when an older picture stays), failed or skipped, and why. A partial run (``--devices``, …)
keeps the report's entries for what it didn't run; entries for what the plan no longer has (a screen, device or
locale removed, or omitted) are dropped and named in the report's ``notes``.

**Staging** (the plan's ``staging``, agreed with the user first: ``references/staging.md``): its ``launch`` args and
env go into every ``launch`` step (the step's own win; ``${NAME}`` takes a variable ``staging.account.env``
names, from the environment, never logged); its ``seed`` runs before each screen (a ``command`` as a ``script``
step, a ``file`` as an ``appFile`` step); its ``permissions`` are granted before launch; the account's variables
must be set. A plan with ``staging`` captures more than one screen only once ``staging.confirmed`` says the user
saw one. Each screen's ``verify`` must be on screen before the shot, or the shot is ``missed`` ("wrong state").

**Updating** (``references/staging.md``, "Updating: when the app changed"): the report records the app's revision
(``app``: git's commit, whether the checkout had changes, an iOS build's version and build number; each taken
shot's ``appRevision``). ``--changes`` reads it and lists the commits and files changed since then in the paths the
plan's ``appSource`` and screens' ``sources`` name, and the screens whose files changed or whose steps' and
``verify``'s ids and texts are on changed lines; a run warns when the app moved since the shots it keeps.

``--dry-run`` prints each device's preparation and every step as its driver would run it, and runs nothing.
``--inspect`` also saves each screen's UI tree (after its steps, or where they stopped) to
``<out>/.inspect/<locale>/<device>/<screen>.txt``, for writing steps.
``--cleanup`` deletes the simulators and emulators this skill created (``appstores-<device id>``) when done.
Without ``--keep-going`` the run stops at the first shot that's missed or failed (the rest are reported as not
attempted).

Exit codes: 0 done; 1 a shot failed, or was missed or skipped with no previous picture kept; 2 refused (another
capture is writing to the same folder); 3 usage or environment (no plan, an invalid plan, a missing tool).
"""

from __future__ import annotations

import argparse
import copy
import datetime
import fnmatch
import os
import plistlib
import re
import shutil
import sys
import tempfile
import traceback

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import schema  # noqa: E402
import drivers  # noqa: E402
from drivers import base  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "capture-plan.schema.json")
REPORT_NAME = "capture-report.json"
LOCK_NAME = ".capture.lock"
STAGING_DOC = "staging.md"
INSPECT_DIR = ".inspect"
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
CREDENTIAL_KEY = re.compile(r"(?i)(password|passwd|passphrase|secret)")

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

# Settings a device and a screen may override (CONTRACT.md 10.2), and their defaults.
SETTINGS = ("appearance", "clock", "statusBar", "seed", "flatten", "posture")
DEFAULTS = {"locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean", "seed": None,
            "flatten": "#000000", "out": "captures", "posture": None}
# A platform with no app entry of its own uses its family's.
FAMILY = {"ipados": "ios", "tvos": "ios", "watchos": "ios", "visionos": "ios"}


class UsageError(Exception):
    """The plan can't be used: missing, not JSON, against the schema, or naming things that don't exist."""


class Refused(Exception):
    """The run won't start (another capture holds the output folder)."""


def log(message):
    """Progress, to stderr."""
    print(message, file=sys.stderr)


def _csv(value):
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def now():
    """The current UTC time (a hook for tests)."""
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# -- the plan -------------------------------------------------------------------------------------------------

def load_schema():
    """The plan's JSON schema."""
    return jsonio.load(SCHEMA_PATH)


def load_plan(path):
    """Read and validate a plan; return it. Raises ``UsageError`` naming every problem."""
    if not os.path.isfile(path):
        raise UsageError("no plan at %s (pass --plan, or write capture-plan.json: see the skill's SKILL.md)" % path)
    try:
        plan = jsonio.load(path)
    except jsonio.JsonError as e:
        raise UsageError(str(e)) from None
    problems = schema.validate(plan, load_schema())
    if not problems and isinstance(plan, dict):
        problems = check_plan(plan)
    if problems:
        raise UsageError("%s isn't a usable capture plan:\n  %s" % (path, "\n  ".join(problems)))
    return plan


def check_plan(plan):
    """What the schema can't say: unique ids, screens naming devices that exist. Returns messages."""
    problems = []
    seen = set()
    for d in plan["devices"]:
        if d["id"] in seen:
            problems.append("/devices: the id %s is used twice" % d["id"])
        seen.add(d["id"])
    screens = set()
    platforms = set(d["platform"] for d in plan["devices"])
    layouts = set(d["layout"] for d in plan["devices"] if d.get("layout"))
    for i, s in enumerate(plan["screens"]):
        if s["id"] in screens:
            problems.append("/screens/%d: the id %s is used twice" % (i, s["id"]))
        screens.add(s["id"])
        for name in s.get("devices") or []:
            if name not in seen:
                problems.append("/screens/%d/devices: no device %s" % (i, name))
        for name in s.get("overrides") or {}:
            if name not in seen and name not in platforms and name not in layouts:
                problems.append("/screens/%d/overrides: %s is neither a device id, a device's platform nor a "
                                "device's layout" % (i, name))
        problems.extend(step_name_problems(s.get("steps") or [], "/screens/%d/steps" % i))
    for d in plan["devices"]:
        try:
            screens_for(plan, resolve_device(plan, d))
        except PatchError as e:
            if str(e) not in problems:
                problems.append(str(e))
    problems.extend(check_staging(plan))
    return problems


class PatchError(ValueError):
    """An override's ``stepsPatch`` names a step that isn't there (renamed or removed in the base steps)."""


PATCH_OPS = ("prepend", "append", "remove", "replace", "before", "after")


def step_name_problems(steps, where):
    """Step names used twice in one list (a patch couldn't tell them apart)."""
    seen, out = set(), []
    for j, step in enumerate(steps):
        name = step.get("name") if isinstance(step, dict) else None
        if name in seen:
            out.append("%s/%d: the step name %s is used twice" % (where, j, name))
        if name:
            seen.add(name)
    return out


def _locate(steps, ref, where):
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 1 <= ref <= len(steps):
            return ref - 1
        raise PatchError("%s: there's no step %d (the steps are %d long here)" % (where, ref, len(steps)))
    for i, step in enumerate(steps):
        if isinstance(step, dict) and step.get("name") == ref:
            return i
    names = [st.get("name") for st in steps if isinstance(st, dict) and st.get("name")]
    raise PatchError("%s: no step named %s (named here: %s)" % (where, ref, ", ".join(names) or "none"))


def patch_steps(steps, patch, where="stepsPatch"):
    """``steps`` with an override's ``stepsPatch`` applied, in order: ``{"prepend": [...]}``, ``{"append": [...]}``,
    ``{"remove": ref}``, ``{"replace": ref, "with": [...]}``, ``{"before": ref, "insert": [...]}``, ``{"after": ref,
    "insert": [...]}``. A ref is a step's ``name`` (or a 1-based position in the steps as they are when that entry
    runs). Raises ``PatchError`` for a ref that isn't there, so a renamed base step is caught when the plan loads."""
    out = copy.deepcopy(list(steps))
    for k, op in enumerate(patch or []):
        here = "%s/%d" % (where, k)
        if "prepend" in op:
            out = copy.deepcopy(op["prepend"]) + out
        elif "append" in op:
            out = out + copy.deepcopy(op["append"])
        elif "remove" in op:
            del out[_locate(out, op["remove"], here)]
        elif "replace" in op:
            i = _locate(out, op["replace"], here)
            out[i:i + 1] = copy.deepcopy(op.get("with") or [])
        elif "before" in op:
            i = _locate(out, op["before"], here)
            out[i:i] = copy.deepcopy(op.get("insert") or [])
        elif "after" in op:
            i = _locate(out, op["after"], here) + 1
            out[i:i] = copy.deepcopy(op.get("insert") or [])
        else:
            raise PatchError("%s: a patch entry is one of %s" % (here, ", ".join(PATCH_OPS)))
    return out


def override_keys(device):
    """The ``overrides`` keys that apply to a resolved device, least specific first: its platform, its layout,
    its id."""
    keys = [device["platform"]]
    if device.get("layout"):
        keys.append(device["layout"])
    keys.append(device["id"])
    return keys


def staging_vars(plan):
    """The environment variables ``staging.account.env`` names (a demo account's, never a value in the plan)."""
    return list(((plan.get("staging") or {}).get("account") or {}).get("env") or [])


def _launch_values(plan):
    """Every ``launch`` step's args and env values in the plan (and staging's), as ``(where, key, value)``."""
    st = plan.get("staging") or {}
    for key in ("args", "env"):
        for k, v in ((st.get("launch") or {}).get(key) or {}).items():
            yield "/staging/launch/%s" % key, k, v
    for i, screen in enumerate(plan["screens"]):
        layers = [("/screens/%d" % i, screen.get("steps") or [])]
        for name, o in (screen.get("overrides") or {}).items():
            layers.append(("/screens/%d/overrides/%s" % (i, name), o.get("steps") or []))
        for where, steps in layers:
            for j, step in enumerate(steps):
                if isinstance(step, dict) and isinstance(step.get("launch"), dict):
                    for key in ("args", "env"):
                        for k, v in (step["launch"].get(key) or {}).items():
                            yield "%s/steps/%d/launch/%s" % (where, j, key), k, v


def check_staging(plan):
    """What the schema can't say about ``staging``: a demo account names its variables, ``${NAME}`` names only
    those, a seed has what its kind needs, ``confirmed`` names a screen of the plan. Returns messages."""
    problems = []
    st = plan.get("staging")
    names = set(staging_vars(plan))
    if st is not None:
        account = st.get("account") or {}
        if account.get("kind") == "demo" and not names:
            problems.append("/staging/account: a demo account is named by its environment variables (env: "
                            "[\"DEMO_USER\", \"DEMO_PASSWORD\"]), never written into the plan")
        seed = st.get("seed") or {}
        if seed.get("kind") == "command" and not seed.get("run"):
            problems.append("/staging/seed: a command seed needs run")
        if seed.get("kind") == "file" and not (seed.get("file") and seed.get("into")):
            problems.append("/staging/seed: a file seed needs file and into")
        confirmed = st.get("confirmed") or {}
        if confirmed.get("screen") and confirmed["screen"] not in [s["id"] for s in plan["screens"]]:
            problems.append("/staging/confirmed: no screen %s" % confirmed["screen"])
    for where, key, value in _launch_values(plan):
        for name in VAR.findall(str(value)):
            if name not in names:
                problems.append("%s/%s: ${%s} isn't one of staging.account.env's variables" % (where, key, name))
    return problems


def credential_warnings(plan):
    """Launch values that look like a password written into the plan (they belong in a variable)."""
    out = []
    for where, key, value in _launch_values(plan):
        if CREDENTIAL_KEY.search(key) and isinstance(value, str) and value and not VAR.search(value):
            out.append("%s/%s looks like a password written into the plan: name it in staging.account.env and "
                       "write ${NAME} (and only ever a demo account's)" % (where, key))
    return out


def app_for(plan, device):
    """The app entry a device uses: the plan's for its platform (or its family's), merged with the device's."""
    apps = plan.get("app") or {}
    platform = device["platform"]
    entry = apps.get(platform)
    if entry is None and platform in FAMILY:
        entry = apps.get(FAMILY[platform])
    merged = dict(entry or {})
    merged.update(device.get("app") or {})
    merged.pop("$comment", None)
    return merged


def resolve_device(plan, device):
    """A device as a driver gets it: its own fields, each setting from the device or else the plan (or the
    default), its ``app`` entry and ``target`` (``{}`` when absent)."""
    out = copy.deepcopy(device)
    out.pop("$comment", None)
    out["locales"] = list(device.get("locales") or plan.get("locales") or DEFAULTS["locales"])
    for key in SETTINGS:
        value = device.get(key)
        out[key] = value if value is not None else plan.get(key, DEFAULTS[key])
    out["app"] = app_for(plan, device)
    out["target"] = dict(device.get("target") or {})
    perms = (plan.get("staging") or {}).get("permissions") or {}
    platform = device["platform"]
    out["permissions"] = list(perms.get(platform) or perms.get(FAMILY.get(platform, platform)) or [])
    return out


def screens_for(plan, device, omitted=None):
    """The screens a resolved device captures, each resolved for it: its settings (the device's, then the
    screen's, then its overrides' for the device's platform, then its layout, then its id), its ``steps`` (an
    override's ``steps`` replace the ones before; its ``stepsPatch`` changes them, so a fix to the base steps still
    reaches the device) and its ``locales`` (those of the device's it's limited to). An override's ``omit`` leaves
    the screen out on that device (``omitted``, a list, gets ``(screen id, reason)``). Raises ``PatchError``."""
    out = []
    for i, screen in enumerate(plan["screens"]):
        if screen.get("devices") and device["id"] not in screen["devices"]:
            continue
        if screen.get("platforms") and device["platform"] not in screen["platforms"]:
            continue
        layers = [("", screen)]
        overrides = screen.get("overrides") or {}
        for key in override_keys(device):
            if key in overrides:
                layers.append((key, overrides[key]))
        resolved = {"id": screen["id"], "steps": copy.deepcopy(screen.get("steps") or []),
                    "staging": screen.get("staging", True)}
        for key in SETTINGS:
            resolved[key] = device.get(key)
        wanted = None
        omit = None
        for name, layer in layers:
            for key in SETTINGS:
                if layer.get(key) is not None:
                    resolved[key] = layer[key]
            for key in ("state", "inUse", "verify"):
                if layer.get(key) is not None:
                    resolved[key] = copy.deepcopy(layer[key])
            if layer is not screen and "steps" in layer:
                resolved["steps"] = copy.deepcopy(layer["steps"])
            if layer is not screen and layer.get("stepsPatch"):
                resolved["steps"] = patch_steps(resolved["steps"], layer["stepsPatch"],
                                                "/screens/%d/overrides/%s/stepsPatch" % (i, name))
            if layer is not screen and layer.get("omit") not in (None, False):
                omit = layer["omit"]
            if layer.get("locales"):
                wanted = layer["locales"]
        if omit not in (None, False):
            if omitted is not None:
                omitted.append((screen["id"], omit if isinstance(omit, str) else "omitted"))
            continue
        resolved["locales"] = [l for l in device["locales"] if wanted is None or l in wanted]
        out.append(resolved)
    return out


def out_dir(plan, plan_path):
    """The captures' folder, absolute."""
    rel = plan.get("out") or DEFAULTS["out"]
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(plan_path)), rel))


# -- staging --------------------------------------------------------------------------------------------------

def staging_doc_path(plan, plan_path):
    """Where the plan's ``staging.md`` goes (``staging.doc``, beside the plan)."""
    rel = (plan.get("staging") or {}).get("doc") or STAGING_DOC
    return rel if os.path.isabs(rel) else os.path.join(os.path.dirname(os.path.abspath(plan_path)), rel)


def _describe_step(step):
    """A step for ``staging.md``: a ``fill`` by its fields (their values are in the In use column)."""
    try:
        kind, value = base.step_of(step)
    except ValueError:
        return "?"
    if kind != "fill":
        return base.describe_step(step)
    opts = base.fill_options(value)
    try:
        fields = ", ".join(q[1] for q, _ in base.fill_fields(opts))
    except ValueError:
        return base.describe_step(step)
    extra = []
    if opts.get("in") is not None:
        q = base.element_query(opts["in"])
        extra.append("in %s" % (q[1] if q else "?"))
    if opts.get("scrollTo") is not None:
        to = opts["scrollTo"]
        q = base.element_query(to) if isinstance(to, dict) else None
        extra.append("then to %s" % (q[1] if q else to))
    return "fill %s%s" % (fields, (" (%s)" % ", ".join(extra)) if extra else "")


def _describe_steps(steps):
    return " → ".join(_describe_step(st) for st in steps or []) or "(no steps)"


def _describe_patch(op):
    if "prepend" in op:
        return "first %s" % _describe_steps(op["prepend"])
    if "append" in op:
        return "then %s" % _describe_steps(op["append"])
    if "remove" in op:
        return "without step %s" % op["remove"]
    if "replace" in op:
        return "step %s as %s" % (op["replace"], _describe_steps(op.get("with")))
    if "before" in op:
        return "%s before step %s" % (_describe_steps(op.get("insert")), op["before"])
    if "after" in op:
        return "%s after step %s" % (_describe_steps(op.get("insert")), op["after"])
    return "?"


def _verify_words(verify):
    checks = verify if isinstance(verify, list) else [verify] if verify else []
    out = []
    for c in checks:
        if isinstance(c, dict) and c.get("keyboard"):
            out.append("the keyboard %s" % c["keyboard"])
            continue
        q = base.element_query(c) if isinstance(c, dict) else None
        if q:
            out.append("%s `%s`%s" % (q[0], q[1], (" containing `%s`" % c["contains"]) if c.get("contains") else ""))
    return ", ".join(out)


def typed_values(steps):
    """What a screen's ``fill`` and ``type`` steps enter, in a few words: ``id `servings` = `12`, id `minutes` = `45```."""
    out = []
    for st in steps or []:
        if not isinstance(st, dict):
            continue
        try:
            kind, value = base.step_of(st)
        except ValueError:
            continue
        if kind == "fill":
            try:
                pairs = base.fill_fields(value)
            except ValueError:
                continue
        elif kind == "type" and isinstance(value, dict):
            query = base.step_element("type", value)
            pairs = [(query, str(value.get("text", "")))]
        else:
            continue
        for query, text in pairs:
            out.append("%s = `%s`" % ("%s `%s`" % query if query else "the focused field", text))
    return out


def in_use_missing(plan):
    """With the app-wide ``staging.inUse`` rule, the screens that don't say how they look in use (their ``inUse``),
    leaving out those ``"staging": false``."""
    if not ((plan.get("staging") or {}).get("inUse") or {}).get("rule"):
        return []
    return [sc["id"] for sc in plan["screens"] if not sc.get("inUse") and sc.get("staging") is not False]


def staging_markdown(plan, plan_name="capture-plan.json"):
    """The plan's staging as a page a person reads (``staging.md``): how the app is signed in, seeded and set up,
    what's skipped, and per screen what it shows, how it's reached and what's checked. Generated from the plan
    (``capture.py --write-staging``); the plan is what's edited."""
    st = plan.get("staging") or {}
    lines = ["# Staging for the store captures", "",
             "Generated from `%s` by `capture.py --write-staging`: edit the plan's `staging` and screens, then "
             "write this again. Agreed with the user before the first capture; reused on every later one." %
             plan_name, ""]
    confirmed = st.get("confirmed") or {}
    if confirmed:
        lines += ["**Confirmed** on `%s`%s%s." % (confirmed.get("screen"),
                                                  (" (%s)" % confirmed["device"]) if confirmed.get("device") else "",
                                                  (", %s" % confirmed["on"]) if confirmed.get("on") else ""), ""]
    else:
        lines += ["**Not confirmed yet:** capture one screen, show it to the user, then set `staging.confirmed`.",
                  ""]

    def section(title, rows):
        rows = [r for r in rows if r]
        if rows:
            lines.extend(["## " + title, ""] + rows + [""])

    account = st.get("account") or {}
    section("Signing in", [
        "- %s" % {"none": "No sign-in needed.", "guest": "Guest mode.", "bypass": "A debug sign-in bypass.",
                  "demo": "A demo account (invented, never a real person's)."}.get(account.get("kind"), "")
        if account.get("kind") else "",
        "- Its variables (set in the environment, never written here): %s" % ", ".join(
            "`%s`" % n for n in account.get("env") or []) if account.get("env") else "",
        "- How: %s" % account["how"] if account.get("how") else ""])
    seed = st.get("seed") or {}
    run = seed.get("run")
    section("Data", [
        "- Kind: %s" % seed["kind"] if seed.get("kind") else "",
        "- Command: `%s`" % (" ".join(run) if isinstance(run, list) else run) if run else "",
        "- File: `%s` into the app's data at %s" % (seed.get("file"), ", ".join(
            "`%s` (%s)" % (v, k) for k, v in sorted(seed["into"].items())) if isinstance(seed.get("into"), dict)
            else "`%s`" % seed.get("into")) if seed.get("file") else "",
        "- When: %s" % ("before every screen" if seed.get("when", "each-screen") == "each-screen"
                        else "once, before a device's first screen") if seed.get("kind") in ("command", "file")
        else "",
        "- How: %s" % seed["how"] if seed.get("how") else ""])
    launch = st.get("launch") or {}
    section("Every launch gets", ["- `%s` = `%s` (%s)" % (k, v, kind) for kind in ("args", "env")
                                  for k, v in sorted((launch.get(kind) or {}).items())])
    skips = []
    for item in st.get("skip") or []:
        if isinstance(item, dict):
            skips.append("- %s: %s" % (item.get("what"), item.get("how") or "skipped"))
        else:
            skips.append("- %s" % item)
    section("Skipped", skips)
    perms = st.get("permissions") or {}
    section("Permissions granted before launch", ["- %s: %s" % (k, ", ".join(v)) for k, v in sorted(perms.items())])
    flags = []
    for f in st.get("flags") or []:
        if isinstance(f, dict):
            flags.append("- `%s`%s%s" % (f.get("name"), (" = `%s`" % f["value"]) if "value" in f else "",
                                         (": %s" % f["how"]) if f.get("how") else ""))
        else:
            flags.append("- %s" % f)
    section("Feature flags", flags)
    clock = st.get("clock") or {}
    section("Date and time", [
        "- The status bar: %s" % plan.get("clock", DEFAULTS["clock"]),
        "- The app's now: %s" % clock["now"] if clock.get("now") else "",
        "- How: %s" % clock["how"] if clock.get("how") else ""])
    network = st.get("network") or {}
    section("Network", ["- %s" % network["kind"] if network.get("kind") else "",
                        "- How: %s" % network["how"] if network.get("how") else ""])
    in_use = st.get("inUse") or {}
    section("Looking in use", [
        "- The rule: %s%s" % (in_use["rule"], (" (%s)" % in_use["by"]) if in_use.get("by") else "")
        if in_use.get("rule") else "",
        "- Believable values: %s" % in_use["values"] if in_use.get("values") else "",
        ("- Saved: %s" % ("yes, where saving is the screen's story" if in_use.get("save") else
                          "no: forms are captured filled, before they're saved")) if in_use.get("rule") else "",
        "- Not said yet for: %s (ask the user what each looks like in use)" % ", ".join(
            "`%s`" % i for i in in_use_missing(plan)) if in_use_missing(plan) else ""])
    section("House rules", ["- %s" % n for n in st.get("notes") or []])
    folded = ["- `%s`: %s%s" % (d["id"], d.get("posture") or "as it is",
                                (", the %s layout" % d["layout"]) if d.get("layout") else "")
              for d in plan["devices"] if d.get("posture") or d.get("layout")]
    section("Postures and layouts", folded)
    lines += ["## Screens", "", "| Screen | Shows | In use | Reached by | Checked |", "|---|---|---|---|---|"]
    for screen in plan["screens"]:
        reached = _describe_steps(screen.get("steps"))
        for name, o in sorted((screen.get("overrides") or {}).items()):
            if o.get("steps") is not None:
                reached += "; on %s: %s" % (name, _describe_steps(o["steps"]))
            if o.get("stepsPatch"):
                reached += "; on %s: %s" % (name, ", ".join(_describe_patch(op) for op in o["stepsPatch"]))
            if o.get("posture"):
                reached += "; on %s: %s" % (name, o["posture"])
            if o.get("omit") not in (None, False):
                reached += "; not on %s%s" % (name, (" (%s)" % o["omit"]) if isinstance(o["omit"], str) else "")
        entered = typed_values(screen.get("steps"))
        use = "; ".join(([screen["inUse"]] if screen.get("inUse") else []) +
                        (["typed: %s" % ", ".join(entered)] if entered else []))
        lines.append("| `%s` | %s | %s | %s | %s |" % (
            screen["id"], (screen.get("state") or "").replace("|", "\\|"), use.replace("|", "\\|"),
            reached.replace("|", "\\|"), _verify_words(screen.get("verify")) or "(nothing: look at it)"))
    return "\n".join(lines).rstrip() + "\n"


def write_staging(plan_path):
    """Write the plan's ``staging.md``; return its path."""
    plan = load_plan(plan_path)
    path = staging_doc_path(plan, plan_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(staging_markdown(plan, os.path.basename(plan_path)))
    return path


PICTURES = (".png", ".jpg", ".jpeg", ".webp")


def _group_key(name):
    """Order groups as a person reads a set: App Store before Play, phones before tablets, then by name."""
    low = name.lower()
    store = 0 if "apple" in low else 1 if "google" in low else 2
    kind = 1 if any(k in low for k in ("ipad", "tablet", "seven", "ten")) else 2 if any(
        k in low for k in ("tv", "watch", "desktop", "mac", "vision")) else 0
    return store, kind, low


def current_screenshots(plan_dir, folder=None):
    """What the current store set already shows, to start the screen list from: ``[(group, rel, note)]`` for
    every picture under ``folder`` (or ``existing/<store>/screenshots/`` from ``store-listings``' pull) and every
    shot ``store-screenshots.json`` or ``design/current.json`` lists, grouped (``design/current.json``'s ``group``:
    a store, locale and slot, App Store and phones first) and in order, each shot with what it shows, the capture
    screen it maps to and its caption, where those are written down."""
    out = []
    roots = []
    if folder:
        roots.append((folder, folder if os.path.isabs(folder) else os.path.join(plan_dir, folder)))
    else:
        existing = os.path.join(plan_dir, "existing")
        if os.path.isdir(existing):
            for store in sorted(os.listdir(existing), key=_group_key):
                shots = os.path.join(existing, store, "screenshots")
                if os.path.isdir(shots):
                    roots.append(("existing/%s/screenshots" % store, shots))
    for group, root in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs.sort(key=_group_key)
            for name in sorted(files):
                if not name.lower().endswith(PICTURES):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    meta = png.info(full)
                    size = "%dx%d" % (meta.width, meta.height)
                except (png.ImageError, OSError):
                    size = "(not a picture this can read)"
                out.append((group, os.path.relpath(full, root), size))
    for name in ("store-screenshots.json", os.path.join("design", "current.json")):
        path = os.path.join(plan_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            data = jsonio.load(path)
        except (jsonio.JsonError, OSError):
            out.append((name, "(unreadable)", ""))
            continue
        shots = data.get("shots") if isinstance(data, dict) else data if isinstance(data, list) else None
        shots = [s for s in shots or [] if isinstance(s, dict)]
        groups = []
        for shot in shots:
            g = shot.get("group")
            if g not in groups:
                groups.append(g)
        if any(groups):
            groups.sort(key=lambda g: _group_key(g or ""))
        for g in groups:
            members = [s for s in shots if s.get("group") == g]
            if any(isinstance(s.get("order"), int) for s in members):
                members.sort(key=lambda s: s.get("order") if isinstance(s.get("order"), int) else 10 ** 6)
            label = "%s: %s" % (name, g) if g else name
            for n, shot in enumerate(members, 1):
                order = shot.get("order") if isinstance(shot.get("order"), int) else n
                what = shot.get("id") or shot.get("file") or "shot %d" % order
                bits = []
                if shot.get("screen"):
                    bits.append("shows: %s" % shot["screen"])
                bits.append("capture: %s" % (shot.get("capture") or "(not mapped yet)"))
                if shot.get("caption"):
                    bits.append("caption: %s" % shot["caption"])
                if shot.get("verdict"):
                    bits.append("verdict: %s" % shot["verdict"])
                out.append((label, "%d. %s" % (order, what), "; ".join(bits)))
    return out


# -- the app's source: its revision, and what changed since the last capture ---------------------------------

def app_source(plan, plan_dir):
    """The app's checkout and the paths the staged screens are drawn by: ``(repo, paths)``, ``repo`` absolute
    (``appSource.repo``, default the plan's folder), ``paths`` relative to it (``appSource.paths``, then every
    screen's ``sources``; empty: the whole checkout)."""
    src = plan.get("appSource") or {}
    repo = src.get("repo") or "."
    repo = repo if os.path.isabs(repo) else os.path.normpath(os.path.join(plan_dir, repo))
    wanted = list(src.get("paths") or []) + [p for s in plan["screens"] for p in s.get("sources") or []]
    paths = []
    for path in wanted:
        covered = any(other != path and _under(path, other) for other in wanted)
        if path not in paths and not covered:
            paths.append(path)
    return repo, paths


def git(repo, *args):
    """``git -C <repo> <args>``'s output, stripped; ``None`` when git isn't there, it isn't a checkout or the
    command failed. Never logged (it isn't the run's)."""
    try:
        res = base.run(["git", "-C", repo] + list(args), check=False, quiet=True, timeout=120)
    except base.DriverError:
        return None
    if not res.ok:
        return None
    return (res.out or "").strip()


def _git_lines(repo, *args):
    out = git(repo, *args)
    return [l for l in (out or "").splitlines() if l.strip()]


def app_builds(plan, plan_dir):
    """The version and build number of the builds the plan points at, where a picture's worth of reading tells
    (an iOS-family ``.app``'s ``Info.plist``): ``{platform: {"version", "build"}}``."""
    out = {}
    for platform, entry in sorted((plan.get("app") or {}).items()):
        if not isinstance(entry, dict) or not entry.get("app"):
            continue
        path = entry["app"] if os.path.isabs(entry["app"]) else os.path.join(plan_dir, entry["app"])
        for info in (os.path.join(path, "Info.plist"), os.path.join(path, "Contents", "Info.plist")):
            if not os.path.isfile(info):
                continue
            try:
                with open(info, "rb") as f:
                    data = plistlib.load(f)
            except Exception:  # noqa: BLE001 - not a plist this can read: say nothing
                break
            build = {}
            if data.get("CFBundleShortVersionString"):
                build["version"] = str(data["CFBundleShortVersionString"])
            if data.get("CFBundleVersion"):
                build["build"] = str(data["CFBundleVersion"])
            if build:
                out[platform] = build
            break
    return out


def app_revision(plan, plan_dir):
    """The app as this run captures it, for the report's ``app``: git's ``revision`` (the commit), ``describe``,
    ``committed`` (its date), ``dirty`` (the screens' paths had changes not committed) and ``repo`` (relative to
    the plan), with ``builds`` (``app_builds``). ``{}`` when the app isn't in a git checkout and no build says."""
    repo, paths = app_source(plan, plan_dir)
    out = {}
    sha = git(repo, "rev-parse", "HEAD")
    if sha:
        out["revision"] = sha
        out["repo"] = os.path.relpath(repo, plan_dir)
        describe = git(repo, "describe", "--always", "--tags")
        if describe:
            out["describe"] = describe
        committed = git(repo, "log", "-1", "--format=%cI")
        if committed:
            out["committed"] = committed
        status = git(repo, "status", "--porcelain", "--", *(paths or ["."]))
        out["dirty"] = bool(status)
    builds = app_builds(plan, plan_dir)
    if builds:
        out["builds"] = builds
    return out


def last_revisions(report):
    """The app revisions a report's taken shots were captured at (``appRevision``, else the report's
    ``app.revision``), each once."""
    out = []
    for e in (report or {}).get("shots") or []:
        if isinstance(e, dict) and e.get("status") == "taken" and e.get("appRevision") and \
                e["appRevision"] not in out:
            out.append(e["appRevision"])
    if not out and isinstance((report or {}).get("app"), dict) and report["app"].get("revision"):
        out.append(report["app"]["revision"])
    return out


def _under(path, source):
    """True when the changed file ``path`` is ``source`` itself, under a folder ``source``, or matches it as a
    glob."""
    source = source.rstrip("/")
    return path == source or path.startswith(source + "/") or fnmatch.fnmatch(path, source)


def _element_values(steps, verify):
    """The ids, texts and labels a screen's steps and ``verify`` look for (an xpath's quoted words too), as
    ``(value, where)`` (``step "amount" (type)'s id``): what to look for on a changed line."""
    out = []

    def add(element, where):
        if not isinstance(element, dict):
            return
        for key in ("id", "text", "label", "contains", "into"):
            v = element.get(key)
            if isinstance(v, str) and len(v.strip()) >= 3:
                out.append((v.strip(), "%s's %s" % (where, key)))
        if isinstance(element.get("xpath"), str):
            for word in re.findall(r"""['"]([^'"]{3,})['"]""", element["xpath"]):
                out.append((word.strip(), "%s's xpath" % where))

    for n, step in enumerate(steps or [], 1):
        if not isinstance(step, dict):
            continue
        try:
            kind, value = base.step_of(step)
        except ValueError:
            continue
        where = "step %s (%s)" % ('"%s"' % step["name"] if step.get("name") else n, kind)
        if kind == "fill":
            opts = base.fill_options(value)
            for entry in opts.get("fields") or []:
                field = entry.get("field") if isinstance(entry, dict) else None
                add({"id": field} if isinstance(field, str) else field, where)
            add(opts.get("in"), where)
            add(opts.get("scrollTo"), where)
            continue
        if isinstance(value, dict):
            add(value, where)
            add(value.get("to"), where)
            add(value.get("in"), where)
            add(value.get("tap"), where)
            add(value.get("done"), where)
    checks = verify if isinstance(verify, list) else [verify] if verify else []
    for c in checks:
        add(c, "verify")
    return out


def _screen_layers(screen):
    """A screen's steps and verify, and each override's, as ``[(label, steps, verify)]``."""
    layers = [("", screen.get("steps") or [], screen.get("verify"))]
    for name, o in sorted((screen.get("overrides") or {}).items()):
        steps = list(o.get("steps") or [])
        for op in o.get("stepsPatch") or []:
            for key in ("prepend", "append", "with", "insert"):
                steps.extend(op.get(key) or [])
        if steps or o.get("verify"):
            layers.append((" on %s" % name, steps, o.get("verify")))
    return layers


def changed_lines(diff_text):
    """A unified diff's changed lines: ``{path: {"-": [lines], "+": [lines]}}`` (a deleted file's under its old
    path)."""
    out = {}
    path = old = None
    header = False
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            header, path, old = True, None, None
            continue
        if header and line.startswith("--- "):
            source = line[4:].strip()
            old = None if source == "/dev/null" else (source[2:] if source.startswith("a/") else source)
            continue
        if header and line.startswith("+++ "):
            target = line[4:].strip()
            path = old if target == "/dev/null" else (target[2:] if target.startswith("b/") else target)
            header = False
            continue
        if header or path is None or not line or line[0] not in "+-":
            continue
        out.setdefault(path, {"-": [], "+": []})[line[0]].append(line[1:])
    return out


def _on_line(value, line):
    return re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(value), line) is not None


def affected_screens(plan, changed_files, lines):
    """Which screens the changes may break: ``[(screen id, [reasons])]`` for those whose ``sources`` changed or
    whose steps' or ``verify``'s ids and texts are on a changed line (removed and not added back anywhere: likely
    gone or renamed; on both: moved or changed), in the plan's order."""
    out = []
    added = [l for d in lines.values() for l in d["+"]]
    for screen in plan["screens"]:
        reasons = []
        for source in screen.get("sources") or []:
            hit = [f for f in changed_files if _under(f, source)]
            if hit:
                reasons.append("its sources changed (%s)" % ", ".join(hit[:4]) + (" and more" if len(hit) > 4 else ""))
        seen = set()
        for label, steps, verify in _screen_layers(screen):
            for value, where in _element_values(steps, verify):
                key = (value, where + label)
                if key in seen:
                    continue
                for path, d in sorted(lines.items()):
                    if any(_on_line(value, l) for l in d["-"]):
                        back = any(_on_line(value, l) for l in added)
                        reasons.append("%s%s `%s` %s in %s" % (
                            where, label, value, "is on a changed line" if back else
                            "was removed (and isn't added back anywhere)", path))
                        seen.add(key)
                        break
        if reasons:
            out.append((screen["id"], reasons))
    return out


def changes_since(plan_path, since=None):
    """What changed in the app since the last capture, as lines to print (``capture.py --changes``): the
    revision then and now, the commits and files changed in the paths the screens use (uncommitted changes
    included: the next build is made from them), the screens to re-check and why, and what to do next. ``since``
    (a commit, tag or branch) instead of the report's revision. Raises ``UsageError`` when there's no checkout or
    no revision to start from."""
    plan = load_plan(plan_path)
    plan_dir = os.path.dirname(os.path.abspath(plan_path))
    repo, paths = app_source(plan, plan_dir)
    head = git(repo, "rev-parse", "HEAD")
    if not head:
        raise UsageError("%s isn't a git checkout (or git isn't installed): set the plan's appSource.repo to the "
                         "app's checkout" % repo)
    if since:
        base_rev = git(repo, "rev-parse", "--verify", "--quiet", since + "^{commit}")
        if not base_rev:
            raise UsageError("%s isn't a commit, tag or branch in %s" % (since, repo))
        revs = [base_rev]
    else:
        report_path = os.path.join(out_dir(plan, plan_path), REPORT_NAME)
        try:
            report = jsonio.load(report_path)
        except (jsonio.JsonError, OSError):
            report = None
        revs = [r for r in last_revisions(report) if git(repo, "rev-parse", "--verify", "--quiet", r + "^{commit}")]
        if not revs:
            raise UsageError("the last capture's report (%s) doesn't say which revision of the app it was taken at "
                             "(none yet, or a report from before it was recorded): pass --changes <revision>, the "
                             "commit, tag or branch the captures were taken from" % report_path)
    # The oldest revision the kept shots were taken at: the most commits behind.
    counts = dict((r, int(git(repo, "rev-list", "--count", "%s..HEAD" % r) or 0)) for r in revs)
    base_rev = max(revs, key=lambda r: counts[r])
    short = lambda r: r[:10]  # noqa: E731
    spec = ["--"] + (paths or ["."])
    lines = []
    when = git(repo, "log", "-1", "--format=%cs", base_rev) or "?"
    dirty = bool(git(repo, "status", "--porcelain", *spec))
    lines.append("the app since the last capture: %s (%s) -> %s (HEAD%s), %d commit%s in all" % (
        short(base_rev), when, short(head), ", with changes not committed" if dirty else "", counts[base_rev],
        "" if counts[base_rev] == 1 else "s"))
    if len(revs) > 1:
        lines.append("  (the kept shots were taken at %d revisions: %s; from the oldest)" % (
            len(revs), ", ".join(short(r) for r in revs)))
    lines.append("looking at %s" % (", ".join(paths) if paths else
                                     "the whole checkout (set appSource.paths and each screen's sources to the files "
                                     "that draw the screens, to narrow it)"))
    commits = _git_lines(repo, "log", "--oneline", "--no-decorate", "%s..HEAD" % base_rev, *spec)
    lines.append("")
    lines.append("commits there (%d):" % len(commits))
    for c in commits[:40]:
        lines.append("  " + c)
    if len(commits) > 40:
        lines.append("  ... and %d more (git -C %s log --oneline %s..HEAD)" % (len(commits) - 40, repo, short(base_rev)))
    stat = _git_lines(repo, "diff", "--stat", base_rev, *spec)
    changed = _git_lines(repo, "diff", "--name-only", base_rev, *spec)
    lines.append("")
    lines.append("files changed (%d):" % len(changed))
    for l in stat[:60]:
        lines.append("  " + l.strip())
    diff = git(repo, "diff", "--unified=0", base_rev, *spec) or ""
    affected = affected_screens(plan, changed, changed_lines(diff))
    lines.append("")
    if affected:
        lines.append("screens to re-check (their steps or verify may no longer fit the app):")
        for sid, reasons in affected:
            lines.append("  %s: %s" % (sid, "; ".join(reasons)))
    else:
        lines.append("no screen's sources, ids or texts are on a changed line")
    rest = [s["id"] for s in plan["screens"] if s["id"] not in dict(affected)]
    if rest:
        lines.append("the rest (%s): nothing in the diff points at them; a change elsewhere (a shared style, a new "
                     "sheet) can still move them" % ", ".join(rest))
    lines.append("")
    lines.append("next: show this to the user; build the app clean (stale build output can fail to link: .NET, "
                 "delete the target's obj/ and bin/; Xcode, clean the build folder; Gradle, clean); capture.py "
                 "--dry-run; capture one screen (--screens <first> --devices <one>) and look at it; repair a step "
                 "that no longer fits (a stepsPatch for one device or layout), never the check")
    return lines


# -- checking a picture ---------------------------------------------------------------------------------------

_BROWSER = [None]


def _browser():
    if _BROWSER[0] is None:
        _BROWSER[0] = chrome.Chrome()
        _BROWSER[0].start()
    return _BROWSER[0]


def close_browser():
    """Stop the Chrome flattening used, if it started one."""
    if _BROWSER[0] is not None:
        _BROWSER[0].close()
        _BROWSER[0] = None


def flatten_with_chrome(src, dest, width, height, colour):
    """Draw ``src`` at 1:1 onto an opaque ``colour`` page of exactly ``width`` x ``height`` CSS px at scale 1 in
    headless Chrome and write ``dest``: 8-bit RGB, sRGB (Chrome converts a tagged profile), not interlaced, every
    opaque pixel unchanged. Raises ``chrome.ChromeNotFound`` / ``chrome.ChromeError``."""
    folder = os.path.dirname(os.path.abspath(dest))
    os.makedirs(folder, exist_ok=True)
    page = os.path.join(folder, ".flatten-%s.html" % os.getpid())
    with open(page, "w", encoding="utf-8") as f:
        f.write('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;'
                'background:%s}img{display:block;width:%dpx;height:%dpx}</style></head><body>'
                '<img src="%s"></body></html>' % (colour, width, height, chrome.to_url(os.path.abspath(src))))
    try:
        _browser().render(page, width, height, dest, scale=1)
    finally:
        os.unlink(page)


FLATTEN = flatten_with_chrome   # callable(src, dest, width, height, colour): tests replace it


def picture_fixes(meta):
    """What a picture needs before it's a capture (CONTRACT.md 10.4), as fix names; empty when it's fine."""
    fixes = []
    if meta.format != "png":
        fixes.append("converted-to-png")
    if meta.has_alpha:
        fixes.append("alpha-flattened")
    if meta.bit_depth == 16:
        fixes.append("16-bit-to-8-bit")
    if meta.format == "png" and meta.color_type in (0, 3, 4) or meta.format == "jpeg" and meta.color_type != 3:
        fixes.append("converted-to-rgb")
    if not meta.srgb:
        fixes.append("converted-to-srgb")
    if meta.interlaced:
        fixes.append("de-interlaced")
    return fixes


def verify_picture(src, dest, width, height, colour="#000000"):
    """Check the picture a driver wrote and put the capture at ``dest``.

    Returns ``(status, fixes, reason)``: ``("taken", fixes, None)`` with ``dest`` written (copied, or drawn
    again by ``FLATTEN`` when it needed fixes), or ``("failed", [], reason)`` for a picture that isn't one, isn't
    exactly ``width`` x ``height`` (never resized) or couldn't be fixed.
    """
    if not src or not os.path.isfile(src):
        return "failed", [], "the driver said it took a picture, but there's no file"
    try:
        meta = png.info(src)
    except (png.ImageError, OSError) as e:
        return "failed", [], "not a picture: %s" % e
    if (meta.width, meta.height) != (width, height):
        hint = " (the other way round: rotated?)" if (meta.height, meta.width) == (width, height) else \
            " (never resized: pick the device, display size or viewport that renders %dx%d)" % (width, height)
        return "failed", [], "came out %dx%d, not %dx%d%s" % (meta.width, meta.height, width, height, hint)
    fixes = picture_fixes(meta)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if not fixes:
        shutil.copyfile(src, dest)
        return "taken", [], None
    try:
        FLATTEN(src, dest, width, height, colour)
    except chrome.ChromeNotFound as e:
        return "failed", [], "needs %s, which takes Chrome: %s" % (", ".join(fixes), e)
    except (chrome.ChromeError, OSError) as e:
        return "failed", [], "couldn't fix it (%s): %s" % (", ".join(fixes), e)
    try:
        after = png.info(dest)
    except (png.ImageError, OSError) as e:
        return "failed", [], "fixing it (%s) made no picture: %s" % (", ".join(fixes), e)
    left = picture_fixes(after)
    if (after.width, after.height) != (width, height) or left:
        if os.path.exists(dest):
            os.unlink(dest)
        return "failed", [], "fixing it (%s) left %s" % (", ".join(fixes), ", ".join(left) or "the wrong size")
    return "taken", fixes, None


# -- running --------------------------------------------------------------------------------------------------

def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def take_lock(out):
    """Claim ``<out>`` for this run (``.capture.lock`` with this process's id); raise ``Refused`` when a live
    capture holds it. Returns the lock's path."""
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, LOCK_NAME)
    if os.path.exists(path):
        try:
            with open(path) as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise Refused("another capture (process %d) is writing to %s: wait for it, or remove %s if it's gone"
                          % (pid, out, path))
    with open(path, "w") as f:
        f.write(str(os.getpid()))
    return path


def _entry(locale, device, screen_id, driver_name):
    return {"locale": locale, "device": device["id"], "screen": screen_id, "driver": driver_name}


def _rel(locale, device_id, screen_id):
    return "/".join((locale, device_id, screen_id + ".png"))


class Run(object):
    """One capture run: the plan, the filters and options, and what it found. ``execute()`` does it."""

    def __init__(self, plan_path, devices=None, screens=None, locales=None, keep_going=False, cleanup=False,
                 dry_run=False, inspect=False):
        """Load the plan and check the filters name things it has (``UsageError`` otherwise), and that a staged
        plan has been confirmed with the user before it captures more than one screen."""
        self.plan_path = os.path.abspath(plan_path)
        self.plan = load_plan(plan_path)
        self.plan_dir = os.path.dirname(self.plan_path)
        self.out = out_dir(self.plan, plan_path)
        self.keep_going = keep_going
        self.cleanup = cleanup
        self.dry_run = dry_run
        self.inspect = inspect
        self.quiet_alpha = 0
        self.notes = []
        ids = [d["id"] for d in self.plan["devices"]]
        screen_ids = [s["id"] for s in self.plan["screens"]]
        all_locales = set(self.plan.get("locales") or DEFAULTS["locales"])
        for d in self.plan["devices"]:
            all_locales.update(d.get("locales") or [])
        for name, wanted, have in (("device", devices, ids), ("screen", screens, screen_ids),
                                   ("locale", locales, sorted(all_locales))):
            for w in wanted or []:
                if w not in have:
                    raise UsageError("the plan has no %s %s (it has %s)" % (name, w, ", ".join(have)))
        self.only_devices = devices
        self.only_screens = screens
        self.only_locales = locales
        staging = self.plan.get("staging")
        wanted = screens or screen_ids
        if staging is not None and not staging.get("confirmed") and not dry_run and len(wanted) > 1:
            raise UsageError("the staging isn't confirmed with the user yet: capture one screen first (--screens %s), "
                             "show it, and when they agree set staging.confirmed ({\"screen\": \"%s\"}); then run "
                             "the rest" % (wanted[0], wanted[0]))
        self.entries = []
        self.device_notes = []
        self.environment_problem = False
        self.stopped = None
        self.moves = []
        self.app = {}

    # Which shots this run makes, for one device.

    def jobs(self, device):
        """``(locale, screen)`` pairs for a resolved device, locale by locale (so a device switches locale least)."""
        omitted = []
        screens = [s for s in screens_for(self.plan, device, omitted)
                   if not self.only_screens or s["id"] in self.only_screens]
        for sid, why in omitted:
            if not self.only_screens or sid in self.only_screens:
                (print if self.dry_run else log)("  %s isn't captured on %s: %s" % (sid, device["id"], why))
        pairs = []
        for locale in device["locales"]:
            if self.only_locales and locale not in self.only_locales:
                continue
            for s in screens:
                if locale in s["locales"]:
                    pairs.append((locale, s))
        return pairs

    def devices(self):
        """The resolved devices this run captures."""
        return [resolve_device(self.plan, d) for d in self.plan["devices"]
                if not self.only_devices or d["id"] in self.only_devices]

    def kept(self, locale, device_id, screen_id):
        """``previous`` when an older picture of this shot stays in ``<out>``, else ``none``."""
        return "previous" if os.path.isfile(os.path.join(self.out, locale, device_id, screen_id + ".png")) else "none"

    def not_taken(self, locale, device, screen_id, driver_name, status, reason, source=None, warnings=None,
                  status_bar="none", state=None, state_check=None, panes=None):
        """Record a shot that wasn't taken, keeping any previous picture."""
        e = _entry(locale, device, screen_id, driver_name)
        reason = base.mask(reason)
        e.update({"status": status, "reason": reason, "kept": self.kept(locale, device["id"], screen_id),
                  "source": source or {}, "statusBar": status_bar, "fixes": [],
                  "warnings": [base.mask(w) for w in warnings or []]})
        if state:
            e["state"] = state
        if state_check and state_check != "none":
            e["stateCheck"] = state_check
        if panes:
            e["panes"] = [base.mask(p) for p in panes]
        self.entries.append(e)
        log("%-7s %s/%s/%s: %s%s" % (status, locale, device["id"], screen_id, reason,
                                     " (kept: previous)" if e["kept"] == "previous" else ""))
        return e

    def execute(self):
        """Run every device; return the report (``None`` under ``--dry-run``)."""
        started = now()
        tmp = None
        lock = None
        if self.dry_run:
            base.DRY_RUN = True
            base.LOG = lambda line: print(line)
        saved_secrets = list(base.SECRETS)
        try:
            self.check_staging_run()
            if not self.dry_run:
                self.app = app_revision(self.plan, self.plan_dir)
                self.check_app_moved()
                lock = take_lock(self.out)
                tmp = tempfile.mkdtemp(prefix=".capture-", dir=self.out)
            for device in self.devices():
                self.capture_device(device, tmp)
            if self.dry_run:
                return None
            for src, dest in self.moves:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.replace(src, dest)
            if self.inspect:
                self.keep_trees(tmp)
            if self.quiet_alpha:
                self.notes.append("%d picture%s came with an alpha channel whose every pixel is opaque (simulators and "
                                  "emulators write one): flattened, nothing that shows changed; each lists "
                                  "alpha-flattened in its fixes" % (self.quiet_alpha, "" if self.quiet_alpha == 1 else "s"))
            report = self.report(started)
            jsonio.dump(report, os.path.join(self.out, REPORT_NAME))
            return report
        finally:
            base.SECRETS[:] = saved_secrets
            close_browser()
            if self.dry_run:
                base.DRY_RUN = False
                base.LOG = base._stderr_log
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            if lock and os.path.exists(lock):
                os.unlink(lock)

    def check_staging_run(self):
        """Before anything runs: the staging account's variables are set (their values masked in every log and
        report), ``staging.md`` matches the plan, nothing looks like a password written into it."""
        staging = self.plan.get("staging")
        say = print if self.dry_run else log
        for w in credential_warnings(self.plan):
            say("warning: %s" % w)
        if staging is None:
            say("warning: the plan has no staging section: agree with the user how the app is signed in, seeded and "
                "set up for each screen (references/staging.md), and record it")
            return
        missing = [n for n in staging_vars(self.plan) if not os.environ.get(n)]
        if missing and not self.dry_run:
            raise UsageError("the staging account needs %s set in the environment (a demo account's, never a real "
                             "person's): set %s and run again" % (", ".join(missing),
                                                                  "it" if len(missing) == 1 else "them"))
        for n in staging_vars(self.plan):
            if os.environ.get(n):
                base.SECRETS.append(os.environ[n])
        missing_use = in_use_missing(self.plan)
        if missing_use:
            say("warning: staging.inUse says the screens look in use, but %s %s say how (inUse): ask the user what "
                "each looks like in use, and fill it (references/staging.md)" % (
                    ", ".join(missing_use), "doesn't" if len(missing_use) == 1 else "don't"))
        doc = staging_doc_path(self.plan, self.plan_path)
        want = staging_markdown(self.plan, os.path.basename(self.plan_path))
        try:
            with open(doc, encoding="utf-8") as f:
                have = f.read()
        except OSError:
            have = None
        if have != want:
            say("warning: %s is %s: capture.py --write-staging" % (os.path.basename(doc),
                                                                  "missing" if have is None else "out of date"))

    def check_app_moved(self):
        """Warn when the shots the report keeps were taken at another revision of the app: run ``--changes``
        first, and build the app clean."""
        now_rev = self.app.get("revision")
        if not now_rev:
            return
        try:
            old = jsonio.load(os.path.join(self.out, REPORT_NAME))
        except (jsonio.JsonError, OSError):
            return
        others = [r for r in last_revisions(old) if r != now_rev]
        if others:
            log("warning: the app changed since the last capture (%s, now %s): capture.py --changes lists what "
                "changed and the screens to re-check; build it clean before capturing (references/staging.md, "
                "\"Updating: when the app changed\")" % (", ".join(r[:10] for r in others), now_rev[:10]))

    def staged(self, device, screen, first):
        """A screen with the plan's staging put in: the seed before its steps (each screen, or ``once`` before a
        device's first), the staging's launch args and env under every ``launch`` step's own, ``${NAME}`` taken
        from the environment (left as it is under ``--dry-run``). ``"staging": false`` on a screen leaves it out."""
        st = self.plan.get("staging") or {}
        out = dict(screen)
        steps = copy.deepcopy(screen.get("steps") or [])
        if not st or screen.get("staging") is False:
            return out
        pre = []
        seed = st.get("seed") or {}
        if seed.get("kind") in ("command", "file") and (seed.get("when", "each-screen") == "each-screen" or first):
            if seed["kind"] == "command":
                pre.append({"script": {"run": seed["run"], "timeout": seed.get("timeout") or 300}})
            else:
                pre.append({"appFile": {"file": seed["file"], "into": seed["into"]}})
        launch = st.get("launch") or {}
        for step in steps:
            if isinstance(step, dict) and "launch" in step:
                value = dict(step["launch"] or {})
                for key in ("args", "env"):
                    merged = dict(launch.get(key) or {})
                    merged.update(value.get(key) or {})
                    if merged:
                        value[key] = dict((k, self.expand(v)) for k, v in merged.items())
                step["launch"] = value
        out["steps"] = pre + steps
        return out

    def expand(self, value):
        """``${NAME}`` in a launch value, from the environment (only names ``staging.account.env`` lists)."""
        if self.dry_run or not isinstance(value, str):
            return value
        return VAR.sub(lambda m: os.environ.get(m.group(1), ""), value)

    def keep_trees(self, tmp):
        """Move the UI trees ``--inspect`` saved into ``<out>/.inspect``."""
        src_root = os.path.join(tmp, "work")
        dest_root = os.path.join(self.out, INSPECT_DIR)
        for dirpath, _, files in os.walk(src_root):
            if os.sep + "inspect" not in dirpath + os.sep:
                continue
            for name in files:
                src = os.path.join(dirpath, name)
                rel = os.path.relpath(src, src_root).split(os.sep)
                rel = rel[rel.index("inspect") + 1:]
                dest = os.path.join(dest_root, *rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.replace(src, dest)
                log("tree    %s" % os.path.relpath(dest, self.out))

    def capture_device(self, device, tmp):
        """Prepare one device, take its shots, and always reset it."""
        name = device["driver"]
        header = "device %s (%s, %s, %dx%d%s)" % (device["id"], name, device["platform"], device["width"],
                                                   device["height"],
                                                   (", %s" % device["posture"]) if device.get("posture") else "")
        (print if self.dry_run else log)(header)
        jobs = self.jobs(device)
        if not jobs:
            log("  nothing to capture on %s" % device["id"])
            return
        if self.stopped:
            for locale, s in jobs:
                self.not_taken(locale, device, s["id"], name, "missed", self.stopped)
            return
        try:
            cls = drivers.get(name)
        except drivers.UnknownDriver as e:
            for locale, s in jobs:
                self.not_taken(locale, device, s["id"], name, "skipped", str(e))
            return
        work = os.path.join(tmp, "work", device["id"]) if tmp else os.path.join(self.out, ".capture-dry-run")
        if tmp:
            os.makedirs(work, exist_ok=True)
        driver = cls(base.Options(plan_dir=self.plan_dir, workdir=work, cleanup=self.cleanup, inspect=self.inspect))
        note = {"id": device["id"], "driver": name, "source": {}, "warnings": []}
        self.device_notes.append(note)
        if driver.PLATFORMS and device["platform"] not in driver.PLATFORMS:
            for locale, s in jobs:
                self.not_taken(locale, device, s["id"], name, "skipped", "the %s driver doesn't capture %s devices"
                               % (name, device["platform"]))
            return
        prepared = False
        try:
            try:
                (print if self.dry_run else log)("  prepare")
                driver.prepare(device, self.plan)
                prepared = True
                note["source"] = driver.source(device)
            except base.ToolMissing as e:
                self.environment_problem = True
                reason = "couldn't prepare %s: %s" % (device["id"], e)
            except base.DriverError as e:
                reason = "couldn't prepare %s: %s" % (device["id"], e)
            except Exception as e:  # a driver's bug: report it and still reset
                traceback.print_exc()
                reason = "the %s driver failed preparing %s: %s" % (name, device["id"], e)
            if not prepared:
                for locale, s in jobs:
                    self.not_taken(locale, device, s["id"], name, "missed", reason)
                if not self.keep_going:
                    self.stopped = "not attempted: the run stopped after %s couldn't be prepared (pass --keep-going " \
                                   "to go on)" % device["id"]
                return
            for n, (locale, s) in enumerate(jobs):
                if self.stopped:
                    self.not_taken(locale, device, s["id"], name, "missed", self.stopped)
                    continue
                (print if self.dry_run else log)("  screen %s (%s)" % (s["id"], locale))
                self.shoot(driver, device, self.staged(device, s, n == 0), locale, tmp)
        finally:
            (print if self.dry_run else log)("  reset")
            try:
                warnings = driver.reset(device) or []
            except Exception as e:
                warnings = ["reset failed: %s (check the device by hand)" % e]
            for w in warnings:
                log("  warning: %s" % w)
            note["warnings"].extend(warnings)
            note["warnings"].extend(getattr(driver, "warnings", []) or [])
            if prepared:
                try:
                    note["source"] = driver.source(device) or note["source"]
                except Exception:  # noqa: BLE001 - the report keeps what prepare said
                    pass

    def shoot(self, driver, device, screen, locale, tmp):
        """Take one shot and record it."""
        name = device["driver"]
        try:
            shot = driver.run_screen(device, screen, locale)
        except base.ToolMissing as e:
            self.environment_problem = True
            shot = base.Shot(status="missed", reason=str(e))
        except base.DriverError as e:
            shot = base.Shot(status="missed", reason=str(e))
        except Exception as e:  # a driver's bug: report it, go on to reset
            traceback.print_exc()
            shot = base.Shot(status="missed", reason="the %s driver failed: %s" % (name, e))
        rel = _rel(locale, device["id"], screen["id"])
        if self.dry_run:
            print("  -> %s %s" % ("would save" if shot.status == "taken" else shot.status,
                                  rel if shot.status == "taken" else (shot.reason or "")))
            return
        state_check = getattr(shot, "state_check", "none")
        if screen.get("verify") and state_check == "none" and shot.status == "taken":
            state_check = "unchecked"
            shot.warnings.append("verify not checked: the %s driver runs the screen its own way; look at the "
                                 "picture for it" % name)
        panes = getattr(shot, "panes", None) or []
        if shot.status != "taken":
            self.not_taken(locale, device, screen["id"], name, shot.status, shot.reason or "not reached",
                           shot.source, shot.warnings, shot.status_bar, screen.get("state"), state_check, panes)
            if shot.status in ("missed", "failed"):
                self.stop_after(rel)
            return
        dest = os.path.join(tmp, "out", locale, device["id"], screen["id"] + ".png")
        status, fixes, reason = verify_picture(shot.path, dest, device["width"], device["height"],
                                               screen.get("flatten") or device.get("flatten") or "#000000")
        if status != "taken":
            self.not_taken(locale, device, screen["id"], name, "failed", reason, shot.source, shot.warnings,
                           shot.status_bar, screen.get("state"), state_check, panes)
            self.stop_after(rel)
            return
        warnings = [base.mask(w) for w in shot.warnings]
        shown = list(shot.fixes) + fixes
        if "alpha-flattened" in fixes:
            if see_through(shot.path):
                warnings.append("the picture had see-through pixels, drawn onto %s: look at its corners and "
                                "background" % (screen.get("flatten") or device.get("flatten") or "#000000"))
            else:
                self.quiet_alpha += 1
                shown.remove("alpha-flattened")
        e = _entry(locale, device, screen["id"], name)
        e.update({"status": "taken", "path": rel, "width": device["width"], "height": device["height"],
                  "sha256": png.sha256(dest), "source": shot.source, "statusBar": shot.status_bar,
                  "fixes": list(shot.fixes) + fixes, "warnings": warnings})
        if self.app.get("revision"):
            e["appRevision"] = self.app["revision"]
        if screen.get("state"):
            e["state"] = screen["state"]
        if state_check != "none":
            e["stateCheck"] = state_check
        if panes:
            e["panes"] = [base.mask(p) for p in panes]
        self.entries.append(e)
        self.moves.append((dest, os.path.join(self.out, locale, device["id"], screen["id"] + ".png")))
        log("taken   %s%s" % (rel, (" (%s)" % ", ".join(shown)) if shown else ""))

    def stop_after(self, rel):
        """Without ``--keep-going``, the rest of the run isn't attempted after a missed or failed shot."""
        if not self.keep_going and not self.stopped:
            self.stopped = "not attempted: the run stopped after %s (pass --keep-going to go on)" % rel

    def report(self, started):
        """The report: this run's shots, plus the previous report's for shots this run didn't make."""
        keys = set((e["locale"], e["device"], e["screen"]) for e in self.entries)
        previous = []
        old_path = os.path.join(self.out, REPORT_NAME)
        if os.path.isfile(old_path):
            try:
                old = jsonio.load(old_path)
                previous = [e for e in (old.get("shots") or [])
                            if isinstance(e, dict) and (e.get("locale"), e.get("device"), e.get("screen")) not in keys]
            except (jsonio.JsonError, OSError, AttributeError):
                previous = []
        planned = self.planned()
        gone = [e for e in previous if (e.get("locale"), e.get("device"), e.get("screen")) not in planned]
        if gone:
            previous = [e for e in previous if e not in gone]
            self.notes.append("dropped %d entr%s the plan no longer has (a screen, device or locale removed or "
                              "omitted): %s" % (len(gone), "y" if len(gone) == 1 else "ies", ", ".join(
                                  "%s/%s/%s" % (e.get("locale"), e.get("device"), e.get("screen")) for e in gone)))
        out = {"version": 1, "startedAt": _stamp(started), "finishedAt": _stamp(now()),
               "plan": os.path.basename(self.plan_path), "devices": self.device_notes,
               "shots": previous + self.entries}
        if self.app:
            out["app"] = dict(self.app)
        if self.notes:
            out["notes"] = list(self.notes)
        return out

    def planned(self):
        """Every ``(locale, device, screen)`` the plan captures, whatever this run's filters: what the report may
        keep from earlier runs."""
        out = set()
        for d in self.plan["devices"]:
            device = resolve_device(self.plan, d)
            for screen in screens_for(self.plan, device):
                for locale in screen["locales"]:
                    out.add((locale, device["id"], screen["id"]))
        return out

    def exit_code(self):
        """0, 1 (a failure, or a miss/skip with nothing kept) or 3 (a tool was missing)."""
        if self.environment_problem:
            return EXIT_USAGE
        for e in self.entries:
            if e["status"] == "failed":
                return EXIT_ERRORS
            if e["status"] in ("missed", "skipped") and e.get("kept") != "previous":
                return EXIT_ERRORS
        return EXIT_OK


def see_through(path):
    """True when a picture has pixels that aren't opaque (``False`` for an alpha channel that's all opaque, or a
    picture this can't read)."""
    try:
        return png.has_transparency(path)
    except (png.ImageError, OSError, ValueError):
        return True


def summary(entries):
    """One line: how many taken, missed, failed, skipped."""
    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return ", ".join("%d %s" % (counts.get(k, 0), k) for k in ("taken", "missed", "failed", "skipped"))


def parser():
    p = argparse.ArgumentParser(prog="capture.py", description="Capture an app's screens at the stores' exact sizes.")
    p.add_argument("--plan", default="capture-plan.json", help="the capture plan (default capture-plan.json)")
    p.add_argument("--devices", help="only these devices (comma-separated ids)")
    p.add_argument("--screens", help="only these screens (comma-separated ids)")
    p.add_argument("--locales", help="only these locales (comma-separated)")
    p.add_argument("--keep-going", action="store_true", help="go on after a shot is missed or fails")
    p.add_argument("--cleanup", action="store_true",
                   help="delete the simulators and emulators this skill created (appstores-<device id>) when done")
    p.add_argument("--dry-run", action="store_true", help="print what each driver would run; run nothing")
    p.add_argument("--inspect", action="store_true",
                   help="also save each screen's UI tree to <out>/.inspect/<locale>/<device>/<screen>.txt")
    p.add_argument("--write-staging", action="store_true",
                   help="write staging.md (the plan's staging and screens, readable) beside the plan, and stop")
    p.add_argument("--changes", nargs="?", const="", metavar="REVISION",
                   help="what changed in the app since the last capture (the report's revision, or REVISION) in the "
                        "paths the screens use, and which screens to re-check; then stop")
    p.add_argument("--current", nargs="?", const="", metavar="FOLDER",
                   help="list the current store screenshots (existing/<store>/screenshots/, store-screenshots.json, "
                        "design/current.json, or FOLDER) to start the screen list from, and stop")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.current is not None:
        plan_dir = os.path.dirname(os.path.abspath(args.plan))
        found = current_screenshots(plan_dir, args.current or None)
        if not found:
            print("no current screenshots found (existing/<store>/screenshots/, store-screenshots.json, "
                  "design/current.json%s)" % (", " + args.current if args.current else ""))
            return EXIT_OK
        group = None
        for g, rel, note in found:
            if g != group:
                print(g)
                group = g
            print("  %s  %s" % (rel, note))
        print("map each to the app screen it shows; those screens, in this order, start the plan's screens")
        return EXIT_OK
    try:
        if args.changes is not None:
            for line in changes_since(args.plan, args.changes or None):
                print(line)
            return EXIT_OK
        if args.write_staging:
            print(write_staging(args.plan))
            return EXIT_OK
        run = Run(args.plan, _csv(args.devices), _csv(args.screens), _csv(args.locales), args.keep_going,
                  args.cleanup, args.dry_run, args.inspect)
        report = run.execute()
    except UsageError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except Refused as e:
        print("refused: %s" % e, file=sys.stderr)
        return EXIT_REFUSED
    if report is None:
        return EXIT_OK
    print("%s: %s" % (os.path.join(run.out, REPORT_NAME), summary(run.entries)))
    for n in run.notes:
        print("note: %s" % n)
    return run.exit_code()


if __name__ == "__main__":
    sys.exit(main())
