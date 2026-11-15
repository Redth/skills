"""HTTP requests with ``urllib.request`` only, retries for the failures worth retrying, and a test hook.

Every request goes through ``TRANSPORT`` (``callable(method, url, headers, body, timeout) -> Response``).
Tests replace it with a fake, and ``SLEEP`` with ``lambda s: None``, so no test reaches a network or waits.
"""

from __future__ import annotations

import email.utils
import http.client
import json
import socket
import time
import urllib.error
import urllib.request

RETRY_STATUSES = frozenset([408, 429, 500, 501, 502, 503, 504, 505, 506, 507, 508, 509, 510, 511])
TRIES = 4
WAITS = (15, 30, 45)
MAX_RETRY_AFTER = 120


class Response:
    """A reply: ``status`` (int), ``headers`` (a dict with lower-case names) and ``body`` (bytes)."""

    def __init__(self, status, headers=None, body=b""):
        """Hold a reply; header names are lower-cased."""
        self.status = int(status)
        self.headers = dict((str(k).lower(), v) for k, v in (headers or {}).items())
        self.body = body or b""

    def __repr__(self):
        return "Response(%d, %d bytes)" % (self.status, len(self.body))

    def header(self, name, default=None):
        """A header's value by any case of its name."""
        return self.headers.get(name.lower(), default)

    def text(self):
        """The body as text (UTF-8, damaged bytes replaced)."""
        return self.body.decode("utf-8", "replace")

    def json(self):
        """The body parsed as JSON (``None`` for an empty body); raises ``ValueError`` if it isn't JSON."""
        if not self.body.strip():
            return None
        return json.loads(self.body.decode("utf-8"))


class HttpError(Exception):
    """A reply with a 4xx or 5xx status, from ``request_json``."""

    def __init__(self, status, method, url, body_text):
        """Describe a failed request: its status, method, URL and the reply's body as text."""
        self.status = status
        self.method = method
        self.url = url
        self.body_text = body_text
        short = body_text if len(body_text) <= 1000 else body_text[:1000] + "…"
        super().__init__("%s %s answered %d: %s" % (method, url, status, short.strip()))

    def json(self):
        """The reply's body parsed as JSON, or ``None`` if it isn't JSON."""
        try:
            return json.loads(self.body_text)
        except ValueError:
            return None


# A caller's guard on redirects: ``callable(url) -> bool``. A GET's redirect is followed only to a URL it accepts
# (``None``: any); a refused redirect comes back as the reply (its 3xx status), never followed.
REDIRECT_ALLOWED = None


class _NoRedirectForWrites(urllib.request.HTTPRedirectHandler):
    """Follow redirects for GET and HEAD only, and only where ``REDIRECT_ALLOWED`` accepts the new URL; another
    method's redirect, or a refused one, comes back as the reply."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_method() not in ("GET", "HEAD"):
            return None
        if REDIRECT_ALLOWED is not None and not REDIRECT_ALLOWED(newurl):
            return None
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_NoRedirectForWrites())


def urllib_transport(method, url, headers, body, timeout):
    """The real transport: one request with ``urllib.request``. A 4xx/5xx comes back as a ``Response``;
    timeouts and dropped connections raise (``OSError`` or ``http.client.HTTPException``)."""
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as res:
            return Response(res.status, dict(res.headers.items()), res.read())
    except urllib.error.HTTPError as e:
        try:
            data = e.read()
        except (OSError, http.client.HTTPException):
            data = b""
        return Response(e.code, dict(e.headers.items()) if e.headers else {}, data)


TRANSPORT = urllib_transport
SLEEP = time.sleep

_RETRYABLE_ERRORS = (socket.timeout, TimeoutError, ConnectionError, urllib.error.URLError,
                     http.client.HTTPException, OSError)


def retry_after(response, default):
    """Seconds to wait before trying again: the ``Retry-After`` header (seconds or a date) if it has one,
    capped at ``MAX_RETRY_AFTER``, else ``default``."""
    value = response.header("retry-after") if response is not None else None
    if not value:
        return default
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return default
        if when is None:
            return default
        seconds = when.timestamp() - time.time()
    return max(0.0, min(float(MAX_RETRY_AFTER), seconds))


def _encode(body, headers):
    if body is None or isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if isinstance(body, (dict, list)):
        if not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = "application/json"
        return json.dumps(body).encode("utf-8")
    raise TypeError("body must be bytes, text, a dict or a list, not %s" % type(body).__name__)


def request(method, url, headers=None, body=None, timeout=60, retry=False):
    """Make one request and return its ``Response`` (a 4xx or 5xx is returned, not raised).

    ``body`` may be bytes, text (sent as UTF-8) or a dict/list (sent as JSON, with a JSON content type
    unless ``headers`` gives one). With ``retry``, a 5xx, 408 or 429 reply, a timeout or a dropped
    connection is tried again after 15, 30 and 45 seconds (or the reply's ``Retry-After``, at most 120 s),
    4 tries in all; the last reply is returned as it came, and the last error raised if every try failed.
    """
    headers = dict(headers or {})
    data = _encode(body, headers)
    tries = TRIES if retry else 1
    for attempt in range(tries):
        last = attempt == tries - 1
        try:
            res = TRANSPORT(method, url, headers, data, timeout)
        except _RETRYABLE_ERRORS:
            if last:
                raise
            SLEEP(WAITS[min(attempt, len(WAITS) - 1)])
            continue
        if last or res.status not in RETRY_STATUSES:
            return res
        SLEEP(retry_after(res, WAITS[min(attempt, len(WAITS) - 1)]))
    raise AssertionError("unreachable")


def request_json(method, url, headers=None, body=None, timeout=60, retry=False):
    """Like ``request``, but return the reply's JSON (``None`` for an empty body) and raise ``HttpError``
    for a 4xx or 5xx reply. Asks for JSON with ``Accept: application/json`` unless ``headers`` says otherwise."""
    headers = dict(headers or {})
    if not any(k.lower() == "accept" for k in headers):
        headers["Accept"] = "application/json"
    res = request(method, url, headers, body, timeout, retry)
    if res.status >= 400:
        raise HttpError(res.status, method, url, res.text())
    try:
        return res.json()
    except ValueError:
        raise HttpError(res.status, method, url, "the reply isn't JSON: " + res.text()[:200]) from None
