"""Plain JSON in and out: errors that name the file and line, and atomic writes."""

from __future__ import annotations

import json
import os
import tempfile


class JsonError(ValueError):
    """A file that isn't valid JSON. ``path``, ``line`` and ``column`` say where (1-based)."""

    def __init__(self, path, line, column, message):
        self.path = path
        self.line = line
        self.column = column
        self.reason = message
        where = str(path)
        if line is not None:
            where += ":%d:%d" % (line, column or 0)
        super().__init__("%s: %s" % (where, message))


def loads(text, path="<string>"):
    """Parse JSON text; on a syntax error raise ``JsonError`` naming ``path`` and the line."""
    if text.startswith("﻿"):
        text = text[1:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise JsonError(path, e.lineno, e.colno, e.msg) from None


def load(path):
    """Read a UTF-8 JSON file (a byte-order mark is tolerated) and return its value.

    Raises ``JsonError`` (a ``ValueError``) naming the file, line and column when it isn't valid JSON or
    UTF-8; a missing file raises the usual ``OSError``.
    """
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        line = data[: e.start].count(b"\n") + 1
        raise JsonError(path, line, None, "not UTF-8 text") from None
    return loads(text, path)


def dumps(obj):
    """Return ``obj`` as this package writes JSON: keys in their order, 2-space indent, trailing newline."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def canonical(obj):
    """Return one canonical compact JSON string for ``obj`` (sorted keys, no spaces), for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _mode_for(path):
    """The permission bits a replaced file keeps, or a new file's (0666 less the umask)."""
    try:
        return os.stat(path).st_mode & 0o7777
    except OSError:
        mask = os.umask(0)
        os.umask(mask)
        return 0o666 & ~mask


def dump(obj, path):
    """Write ``obj`` to ``path`` as JSON (see ``dumps``), atomically.

    The text goes to a temporary file in the same folder, which then replaces ``path`` with ``os.replace``,
    so a reader never sees half a file. Missing parent folders are created.
    """
    text = dumps(obj)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, _mode_for(path))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
