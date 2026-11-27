"""Findings: what a check reports, printed for people or as JSON, and the exit code they make.

A finding has an ``id`` (a short kebab-case name for the rule), a ``severity`` (``error``, ``warning`` or
``info``), a ``where`` (a file, a JSON pointer or a field path) and a ``message`` (one sentence saying what's
wrong and what to do). Only errors fail: ``exit_code`` is 1 when there's at least one, else 0.
"""

from __future__ import annotations

import json
import sys

SEVERITIES = ("error", "warning", "info")
_MARK = {"error": "ERROR", "warning": "WARN ", "info": "INFO "}


class Finding(object):
    """One thing a check found."""

    __slots__ = ("id", "severity", "where", "message")

    def __init__(self, id, severity, where, message):
        if severity not in SEVERITIES:
            raise ValueError("severity must be one of %s, not %r" % (", ".join(SEVERITIES), severity))
        self.id = id
        self.severity = severity
        self.where = where
        self.message = message

    def as_dict(self):
        return {"id": self.id, "severity": self.severity, "where": self.where, "message": self.message}

    def __eq__(self, other):
        return isinstance(other, Finding) and self.as_dict() == other.as_dict()

    def __repr__(self):
        return "Finding(%r, %r, %r, %r)" % (self.id, self.severity, self.where, self.message)


def errors(findings):
    """The findings that fail."""
    return [f for f in findings if f.severity == "error"]


def exit_code(findings):
    """1 when any finding is an error, else 0."""
    return 1 if errors(findings) else 0


def as_json(findings, **extra):
    """The JSON object scripts print with ``--json``: ``ok``, ``findings`` and anything in ``extra``."""
    out = {"ok": not errors(findings), "findings": [f.as_dict() for f in findings]}
    out.update(extra)
    return out


def print_findings(findings, json_output=False, stream=None, summary=None, **extra):
    """Print findings, most severe first, one a line; or the JSON object when ``json_output``.

    ``summary`` is a line printed after the findings (people only), such as "12 pairs checked".
    """
    stream = stream or sys.stdout
    if json_output:
        stream.write(json.dumps(as_json(findings, **extra), indent=2, ensure_ascii=False) + "\n")
        return
    order = {s: i for i, s in enumerate(SEVERITIES)}
    for f in sorted(findings, key=lambda f: order[f.severity]):
        stream.write("%s %s [%s] %s\n" % (_MARK[f.severity], f.where, f.id, f.message))
    counts = [(s, sum(1 for f in findings if f.severity == s)) for s in SEVERITIES]
    tally = ", ".join("%d %s%s" % (n, s, "" if n == 1 else "s") for s, n in counts if n)
    if summary:
        stream.write(summary + "\n")
    stream.write(("No findings." if not findings else tally + ".") + "\n")
