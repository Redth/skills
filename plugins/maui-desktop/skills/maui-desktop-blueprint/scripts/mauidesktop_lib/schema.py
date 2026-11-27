"""A JSON Schema validator for the subset of draft 2020-12 the maui-desktop files use (copied from app-stores' appstores_lib).

Supported: ``type`` (a name or a list), ``properties``, ``required``, ``additionalProperties`` (a boolean or
a schema), ``patternProperties``, ``items`` (and ``prefixItems``), ``minItems``, ``maxItems``,
``uniqueItems``, ``enum``, ``const``, ``minimum``, ``maximum``, ``exclusiveMinimum``, ``exclusiveMaximum``,
``minLength``, ``maxLength`` (in code points), ``pattern``, ``format`` (``uri``, ``email``, ``date``, checked
loosely; others ignored), ``$ref`` (JSON pointers into the same document: ``#/$defs/…``), ``anyOf``,
``oneOf``, ``allOf`` and ``not``. Annotations (``$schema``, ``$id``, ``$comment``, ``title``,
``description``, ``default``, ``examples``, ``deprecated``…) are ignored. ``unsupported(schema)`` lists any
other keyword a schema uses, so a schema's own test can make sure it asks only for what's checked.
"""

from __future__ import annotations

import datetime
import json
import re

SUPPORTED = frozenset([
    "type", "properties", "required", "additionalProperties", "patternProperties", "items", "prefixItems",
    "minItems", "maxItems", "uniqueItems", "enum", "const", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "pattern", "format", "$ref", "$defs", "definitions",
    "anyOf", "oneOf", "allOf", "not", "additionalItems",
])
ANNOTATIONS = frozenset([
    "$schema", "$id", "$comment", "$anchor", "title", "description", "default", "examples", "deprecated",
    "readOnly", "writeOnly",
])
# Keywords whose value is a map of names to schemas (their keys aren't keywords).
_SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "definitions")
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_ONE = ("additionalProperties", "items", "additionalItems", "not")


def _escape(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def pointer(parts):
    """Return the JSON pointer (RFC 6901) for a path of keys and indexes; the root is ``""``."""
    return "".join("/" + _escape(p) for p in parts)


def _where(parts):
    return pointer(parts) or "(root)"


def _type_of(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_type(value, name):
    t = _type_of(value)
    if name == "number":
        return t in ("integer", "number")
    if name == "integer":
        return t == "integer" or (t == "number" and float(value).is_integer())
    return t == name


def _canon(value):
    """A hashable stand-in for JSON equality: 1 == 1.0, but true != 1."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return (_type_of(value), value)
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, list):
        return ("array", tuple(_canon(v) for v in value))
    if isinstance(value, dict):
        return ("object", tuple(sorted((k, _canon(v)) for k, v in value.items())))
    return ("other", repr(value))


def _short(value, limit=60):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s]+$")
_WEB = re.compile(r"^(https?)://[^\s/?#@]+(?:[/?#][^\s]*)?$", re.IGNORECASE)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


def _format_ok(fmt, value):
    if fmt == "uri":
        if value.lower().startswith(("http:", "https:")):
            return bool(_WEB.match(value))
        return bool(_URI.match(value))
    if fmt == "email":
        return bool(_EMAIL.match(value))
    if fmt == "date":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return False
        try:
            datetime.date(int(value[:4]), int(value[5:7]), int(value[8:10]))
        except ValueError:
            return False
        return True
    return True


def _resolve(root, ref):
    if not ref.startswith("#"):
        raise ValueError("only references within the schema (#/…) are supported, not %r" % ref)
    node = root
    frag = ref[1:]
    if frag in ("", "/"):
        return root
    for token in frag.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            raise ValueError("the schema has nothing at %s" % ref)
    return node


class _Validator:
    def __init__(self, root):
        self.root = root

    def check(self, value, schema, path, errors):
        if schema is True or schema == {}:
            return
        if schema is False:
            errors.append("%s: no value is allowed here" % _where(path))
            return
        if not isinstance(schema, dict):
            raise ValueError("a schema must be an object or a boolean, not %s" % _short(schema))

        if "$ref" in schema:
            self.check(value, _resolve(self.root, schema["$ref"]), path, errors)

        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, t) for t in types):
                errors.append("%s: expected %s, got %s" % (_where(path), " or ".join(types), _type_of(value)))
                return

        if "const" in schema and _canon(value) != _canon(schema["const"]):
            errors.append("%s: must be %s" % (_where(path), _short(schema["const"])))
        if "enum" in schema and _canon(value) not in [_canon(v) for v in schema["enum"]]:
            allowed = ", ".join(_short(v, 30) for v in schema["enum"][:12])
            more = "…" if len(schema["enum"]) > 12 else ""
            errors.append("%s: %s isn't one of %s%s" % (_where(path), _short(value), allowed, more))

        if isinstance(value, str):
            self._string(value, schema, path, errors)
        elif _is_type(value, "number") and not isinstance(value, bool):
            self._number(value, schema, path, errors)
        elif isinstance(value, list):
            self._array(value, schema, path, errors)
        elif isinstance(value, dict):
            self._object(value, schema, path, errors)

        if "allOf" in schema:
            for sub in schema["allOf"]:
                self.check(value, sub, path, errors)
        if "anyOf" in schema:
            self._any_of(value, schema["anyOf"], path, errors)
        if "oneOf" in schema:
            self._one_of(value, schema["oneOf"], path, errors)
        if "not" in schema:
            if not self._errors(value, schema["not"], path):
                errors.append("%s: must not match the schema under \"not\"" % _where(path))

    def _errors(self, value, schema, path):
        errs = []
        self.check(value, schema, path, errs)
        return errs

    def _branch_errors(self, value, options, path):
        return [self._errors(value, sub, path) for sub in options]

    def _best(self, results, path):
        """The errors of the one option the value was plainly aiming at (its type matched), if just one."""
        prefix = _where(path) + ": expected "
        aimed = [errs for errs in results if not any(e.startswith(prefix) for e in errs)]
        return aimed[0] if len(aimed) == 1 else None

    def _any_of(self, value, options, path, errors):
        results = self._branch_errors(value, options, path)
        if any(not r for r in results):
            return
        best = self._best(results, path)
        if best:
            errors.extend(best)
        else:
            errors.append("%s: %s doesn't match any of the %d allowed shapes" % (
                _where(path), _short(value), len(options)))

    def _one_of(self, value, options, path, errors):
        results = self._branch_errors(value, options, path)
        passing = [i for i, r in enumerate(results) if not r]
        if len(passing) == 1:
            return
        if len(passing) > 1:
            errors.append("%s: matches %d of the oneOf shapes (%s), but must match exactly one" % (
                _where(path), len(passing), ", ".join(str(i) for i in passing)))
            return
        best = self._best(results, path)
        if best:
            errors.extend(best)
        else:
            errors.append("%s: %s doesn't match any of the %d allowed shapes" % (
                _where(path), _short(value), len(options)))

    def _string(self, value, schema, path, errors):
        n = len(value)
        if "minLength" in schema and n < schema["minLength"]:
            errors.append("%s: is %d characters, shorter than %d" % (_where(path), n, schema["minLength"]))
        if "maxLength" in schema and n > schema["maxLength"]:
            errors.append("%s: is %d characters, longer than %d" % (_where(path), n, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append("%s: %s doesn't match the pattern %s" % (_where(path), _short(value), schema["pattern"]))
        if "format" in schema and not _format_ok(schema["format"], value):
            errors.append("%s: %s isn't a valid %s" % (_where(path), _short(value), schema["format"]))

    def _number(self, value, schema, path, errors):
        w = _where(path)
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s: %s is less than the minimum %s" % (w, value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append("%s: %s is more than the maximum %s" % (w, value, schema["maximum"]))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append("%s: %s must be more than %s" % (w, value, schema["exclusiveMinimum"]))
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append("%s: %s must be less than %s" % (w, value, schema["exclusiveMaximum"]))

    def _array(self, value, schema, path, errors):
        w = _where(path)
        n = len(value)
        if "minItems" in schema and n < schema["minItems"]:
            errors.append("%s: has %d items, fewer than %d" % (w, n, schema["minItems"]))
        if "maxItems" in schema and n > schema["maxItems"]:
            errors.append("%s: has %d items, more than %d" % (w, n, schema["maxItems"]))
        if schema.get("uniqueItems"):
            seen = {}
            for i, item in enumerate(value):
                key = _canon(item)
                if key in seen:
                    errors.append("%s: item %d repeats item %d (%s)" % (w, i, seen[key], _short(item, 40)))
                else:
                    seen[key] = i
        prefix = schema.get("prefixItems") or []
        has_items = "items" in schema
        items = schema.get("items")
        if isinstance(items, list):  # the older tuple form, with additionalItems for the rest
            prefix = items
            has_items = "additionalItems" in schema
            items = schema.get("additionalItems")
        for i, sub in enumerate(prefix[:n]):
            self.check(value[i], sub, path + [i], errors)
        if has_items:
            for i in range(len(prefix), n):
                self.check(value[i], items, path + [i], errors)

    def _object(self, value, schema, path, errors):
        for name in schema.get("required", []):
            if name not in value:
                errors.append("%s: \"%s\" is required" % (_where(path), name))
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            matched = False
            if key in props:
                matched = True
                self.check(item, props[key], path + [key], errors)
            for pat, sub in patterns.items():
                if re.search(pat, key):
                    matched = True
                    self.check(item, sub, path + [key], errors)
            if not matched:
                if additional is False:
                    errors.append("%s: \"%s\" isn't a known property" % (_where(path), key))
                elif additional is not True:
                    self.check(item, additional, path + [key], errors)


def validate(instance, schema):
    """Validate ``instance`` against ``schema``; return a list of messages, empty when it's valid.

    Each message starts with the JSON pointer of the value it's about (``/locales/en-US/apple/subtitle``,
    or ``(root)``). Raises ``ValueError`` for a ``$ref`` that doesn't resolve within the schema.
    """
    errors = []
    _Validator(schema).check(instance, schema, [], errors)
    return errors


def unsupported(schema):
    """Return ``"<pointer>: <keyword>"`` for every keyword in ``schema`` this validator wouldn't check."""
    found = []

    def walk(node, parts):
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            here = parts + [key]
            if key in _SCHEMA_MAPS and isinstance(val, dict):
                for name, sub in val.items():
                    walk(sub, here + [name])
            elif key in _SCHEMA_LISTS and isinstance(val, list):
                for i, sub in enumerate(val):
                    walk(sub, here + [i])
            elif key in _SCHEMA_ONE:
                if isinstance(val, list):
                    for i, sub in enumerate(val):
                        walk(sub, here + [i])
                else:
                    walk(val, here)
            elif key not in SUPPORTED and key not in ANNOTATIONS:
                found.append("%s: %s" % (_where(parts), key))

    walk(schema, [])
    return found
