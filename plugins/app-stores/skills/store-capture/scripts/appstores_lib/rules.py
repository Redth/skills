"""The stores' rules data (``rules/<store>.json``) and the evaluators for word rules.

A rule says what a store requires (a limit, forbidden words, a picture count…), where that's written
(``source``), when it was last checked and whether it's ``verified``. A rule that isn't verified is
reported as a warning whatever its declared severity, and its message says so.

``limit``, ``words``, ``pattern`` and ``count`` rules are evaluated here (``evaluate``); ``size``,
``format``, ``required`` and ``video`` rules need the files and the config, and are the caller's to check
(``finding`` builds their findings the same way).
"""

from __future__ import annotations

import collections
import os
import re

from . import jsonio
from . import text

SEVERITIES = ("error", "warning")
STATUSES = ("verified", "observed", "unverified")
COUNTS = ("characters", "graphemes", "bytes")

Finding = collections.namedtuple("Finding", ["rule_id", "severity", "where", "message", "source", "status"])
Finding.__doc__ = """One thing a check found: the rule's id, the severity it's reported at (``error`` or
``warning``), where (``en-US apple.subtitle``, a file path…), the message, the rule's source URL and its
status."""


class RulesError(ValueError):
    """A rules file that's missing or malformed."""


class Rule:
    """One rule from a rules file. ``data`` is its JSON object; the common fields are attributes."""

    def __init__(self, data):
        """Wrap a rule's JSON object."""
        self.data = dict(data)

    def __repr__(self):
        return "Rule(%r)" % self.id

    def get(self, key, default=None):
        """A field of the rule's JSON, or ``default``."""
        return self.data.get(key, default)

    @property
    def id(self):
        """The rule's stable id, ``<store>.<area>.<what>``."""
        return self.data.get("id")

    @property
    def kind(self):
        """``limit``, ``count``, ``size``, ``format``, ``words``, ``required``, ``video`` or ``pattern``."""
        return self.data.get("kind")

    @property
    def status(self):
        """``verified``, ``observed`` or ``unverified`` (missing counts as unverified)."""
        return self.data.get("status") or "unverified"

    @property
    def verified(self):
        """True if the rule's status is ``verified``."""
        return self.status == "verified"

    @property
    def declared_severity(self):
        """The severity the rules file gives (``error`` when it gives none)."""
        return self.data.get("severity") or "error"

    @property
    def severity(self):
        """The severity it's reported at: the declared one if verified, else ``warning``."""
        return self.declared_severity if self.verified else "warning"

    @property
    def source(self):
        """Where the rule is written (a URL), or ``None``."""
        return self.data.get("source")

    @property
    def checked(self):
        """The date the rule was last checked against its source, or ``None``."""
        return self.data.get("checked")

    @property
    def note(self):
        """The rule's note, or ``None``."""
        return self.data.get("note")

    @property
    def fields(self):
        """The config fields the rule applies to (``applies.field``/``fields`` and a ``words`` rule's ``fields``)."""
        applies = self.data.get("applies") or {}
        out = []
        if applies.get("field"):
            out.append(applies["field"])
        out += list(applies.get("fields") or [])
        out += list(self.data.get("fields") or [])
        return list(dict.fromkeys(out))

    @property
    def slots(self):
        """The store slots the rule applies to (``applies.slot``/``slots``)."""
        applies = self.data.get("applies") or {}
        out = []
        if applies.get("slot"):
            out.append(applies["slot"])
        out += list(applies.get("slots") or [])
        return list(dict.fromkeys(out))


class RuleSet:
    """A store's rules: iterate it for every rule, or ask by field, slot or id. ``slots`` is the store's
    slot table (without ``$comment``-style keys). After ``relaxed()``, ``relaxed_rules`` holds ``(rule, reason)`` pairs left out and
    ``unknown_relaxed`` the ids a relax list named that this store doesn't have."""

    def __init__(self, store, rules, slots=None, checked=None, path=None):
        """Build a rule set from ``Rule`` objects (``load`` is the usual way)."""
        self.store = store
        self.rules = list(rules)
        self.slots = slots or {}
        self.checked = checked
        self.path = path
        self.relaxed_rules = []
        self.unknown_relaxed = []
        self._by_id = dict((r.id, r) for r in self.rules)

    def __iter__(self):
        return iter(self.rules)

    def __len__(self):
        return len(self.rules)

    def get(self, rule_id):
        """The rule with this id, or ``None``."""
        return self._by_id.get(rule_id)

    def for_field(self, field):
        """The rules that apply to a config field (``apple.subtitle``, ``google.title``, ``description``…)."""
        return [r for r in self.rules if field in r.fields]

    def for_slot(self, slot):
        """The rules that apply to a store slot (``APP_IPHONE_67``, ``phone``, ``featureGraphic``…)."""
        return [r for r in self.rules if slot in r.slots]

    def by_kind(self, kind):
        """The rules of one kind."""
        return [r for r in self.rules if r.kind == kind]


def _bad(path, message):
    return RulesError("%s: %s" % (path, message))


def load(store, rules_dir):
    """Load ``<rules_dir>/<store>.json`` and return its ``RuleSet``.

    Checks the shape a caller relies on: a ``rules`` list of objects, each with an ``id`` starting with
    ``<store>.`` (unique), a ``kind``, a known ``severity`` and ``status`` when given, and a known ``count``
    for ``limit`` rules. Keys of ``slots`` starting with ``$`` (``$comment``) are left out. Raises
    ``RulesError`` naming the file otherwise.
    """
    path = os.path.join(rules_dir, "%s.json" % store)
    if not os.path.isfile(path):
        raise RulesError("no rules for %r: %s doesn't exist" % (store, path))
    try:
        data = jsonio.load(path)
    except jsonio.JsonError as e:
        raise RulesError(str(e)) from None
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise _bad(path, "expected an object with a \"rules\" list")
    if data.get("store", store) != store:
        raise _bad(path, "says it's for %r, not %r" % (data.get("store"), store))
    rules = []
    seen = set()
    for i, item in enumerate(data["rules"]):
        if not isinstance(item, dict):
            raise _bad(path, "rule %d isn't an object" % i)
        rid = item.get("id")
        if not isinstance(rid, str) or not rid.startswith(store + "."):
            raise _bad(path, "rule %d's id %r doesn't start with %r" % (i, rid, store + "."))
        if rid in seen:
            raise _bad(path, "the id %s is used twice" % rid)
        seen.add(rid)
        if not item.get("kind"):
            raise _bad(path, "%s has no kind" % rid)
        if "severity" in item and item["severity"] not in SEVERITIES:
            raise _bad(path, "%s's severity %r isn't error or warning" % (rid, item["severity"]))
        if "status" in item and item["status"] not in STATUSES:
            raise _bad(path, "%s's status %r isn't one of %s" % (rid, item["status"], ", ".join(STATUSES)))
        if item["kind"] == "limit" and item.get("count", "characters") not in COUNTS:
            raise _bad(path, "%s counts %r, not characters, graphemes or bytes" % (rid, item.get("count")))
        rules.append(Rule(item))
    slots = data.get("slots") or {}
    if not isinstance(slots, dict):
        raise _bad(path, "\"slots\" isn't an object")
    slots = dict((k, v) for k, v in slots.items() if not k.startswith("$"))
    return RuleSet(store, rules, slots, data.get("checked"), path)


def relaxed(ruleset, relax_list):
    """Return a copy of ``ruleset`` without the rules a config relaxes.

    ``relax_list`` is the config's ``rules.relax``: objects with an ``id`` and a ``reason`` (plain id
    strings are accepted too). Ids for other stores are ignored, so one list serves every store. The
    returned set's ``relaxed_rules`` lists ``(rule, reason)`` for the report, and ``unknown_relaxed`` the
    ids of this store that match no rule (a typo, or a rule since renamed).
    """
    reasons = collections.OrderedDict()
    for entry in relax_list or []:
        if isinstance(entry, str):
            rid, reason = entry, ""
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            rid, reason = entry["id"], entry.get("reason") or ""
        else:
            raise ValueError("a relax entry needs an id: %r" % (entry,))
        if rid.startswith(ruleset.store + "."):
            reasons[rid] = reason
    kept = [r for r in ruleset.rules if r.id not in reasons]
    out = RuleSet(ruleset.store, kept, ruleset.slots, ruleset.checked, ruleset.path)
    out.relaxed_rules = list(ruleset.relaxed_rules) + [
        (ruleset.get(rid), reason) for rid, reason in reasons.items() if ruleset.get(rid) is not None]
    out.unknown_relaxed = list(ruleset.unknown_relaxed) + [rid for rid in reasons if ruleset.get(rid) is None]
    return out


def finding(rule, where, message):
    """Build the ``Finding`` for ``rule`` at ``where``: its reported severity, and for a rule that isn't
    verified a note in the message saying so."""
    if not rule.verified:
        message = "%s (unverified rule: %s%s)" % (
            message, rule.status, ", checked " + rule.checked if rule.checked else "")
    return Finding(rule.id, rule.severity, where, message, rule.source, rule.status)


def _as_text(value, joiner):
    if isinstance(value, (list, tuple)):
        return joiner.join(str(v) for v in value)
    return value


def check_limit(rule, value, where):
    """Evaluate a ``limit`` rule on a text value (``None`` is skipped; a list is joined with commas, as
    Apple's keywords are sent). Returns a list of findings."""
    value = _as_text(value, ",")
    if value is None:
        return []
    how = rule.get("count", "characters")
    n = text.count(value, how)
    unit = {"characters": "characters", "graphemes": "characters", "bytes": "bytes"}[how]
    out = []
    if rule.get("max") is not None and n > rule.get("max"):
        out.append(finding(rule, where, "is %d %s; the limit is %d" % (n, unit, rule.get("max"))))
    if rule.get("min") is not None and n < rule.get("min"):
        out.append(finding(rule, where, "is %d %s; it needs at least %d" % (n, unit, rule.get("min"))))
    return out


def check_words(rule, value, where, extra_words=None):
    """Evaluate a ``words`` rule (plus a config's ``extraForbiddenWords``) on a text value or a list of
    them; whole words, case-insensitive. Returns a list of findings (one naming every word found)."""
    value = _as_text(value, ", ")
    if not value:
        return []
    words = list(rule.get("words") or []) + list(extra_words or [])
    found = text.find_words(value, words)
    if not found:
        return []
    listed = ", ".join('"%s"' % w for w in found)
    return [finding(rule, where, "contains %s" % listed)]


def _flags(rule):
    flags = 0
    for letter in rule.get("flags") or "":
        flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}.get(letter, 0)
    return flags


def check_pattern(rule, value, where):
    """Evaluate a ``pattern`` rule: ``regex`` must match the value (searched anywhere), or with
    ``"forbid": true`` must not. Optional ``flags`` letters: ``i``, ``m``, ``s``. ``None`` is skipped."""
    value = _as_text(value, ", ")
    if value is None:
        return []
    regex = rule.get("regex")
    m = re.search(regex, value, _flags(rule))
    if rule.get("forbid"):
        if m:
            return [finding(rule, where, "contains %r, which isn't allowed" % m.group(0))]
        return []
    if not m:
        return [finding(rule, where, "doesn't match what's required (%s)" % regex)]
    return []


def check_count(rule, n, where, noun="pictures"):
    """Evaluate a ``count`` rule's ``min``/``max`` on a number of pictures (or items: ``noun``)."""
    out = []
    if rule.get("max") is not None and n > rule.get("max"):
        out.append(finding(rule, where, "has %d %s; at most %d are allowed" % (n, noun, rule.get("max"))))
    if rule.get("min") is not None and n < rule.get("min"):
        out.append(finding(rule, where, "has %d %s; at least %d are needed" % (n, noun, rule.get("min"))))
    return out


EVALUATED_KINDS = ("limit", "words", "pattern", "count")


def evaluate(rule, value, where, extra_words=None):
    """Evaluate a ``limit``, ``words``, ``pattern`` or ``count`` rule on a value and return its findings.

    For ``count`` the value is a number or a list (its length), counted as pictures for a rule on slots and
    items otherwise (a rule's ``noun`` overrides). Raises ``ValueError`` for other kinds,
    which need files or the config (see the module's docstring).
    """
    kind = rule.kind
    if kind == "limit":
        return check_limit(rule, value, where)
    if kind == "words":
        return check_words(rule, value, where, extra_words)
    if kind == "pattern":
        return check_pattern(rule, value, where)
    if kind == "count":
        n = len(value) if isinstance(value, (list, tuple)) else int(value or 0)
        noun = rule.get("noun") or ("pictures" if rule.slots else "items")
        return check_count(rule, n, where, noun)
    raise ValueError("%s is a %s rule, which evaluate() doesn't check" % (rule.id, kind))
