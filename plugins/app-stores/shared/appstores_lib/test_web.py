"""Tests for appstores_lib.web (stdlib unittest). A fake transport answers; nothing reaches a network."""

import email.utils
import http.client
import os
import socket
import sys
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import web as ahttp  # noqa: E402

URL = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/com.example.samplerecipes/edits"


class FakeTransport:
    """Answers each request with the next scripted reply (a Response, or an exception to raise)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body, timeout))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def reply(status, body=b"", headers=None):
    return ahttp.Response(status, headers or {}, body)


class HttpTestCase(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self._transport, self._sleep = ahttp.TRANSPORT, ahttp.SLEEP
        ahttp.SLEEP = self.sleeps.append

        def no_network(*args):
            raise AssertionError("a test reached the real transport")

        ahttp.TRANSPORT = no_network

    def tearDown(self):
        ahttp.TRANSPORT, ahttp.SLEEP = self._transport, self._sleep

    def use(self, *replies):
        fake = FakeTransport(*replies)
        ahttp.TRANSPORT = fake
        return fake


class RequestTests(HttpTestCase):
    def test_one_request_without_retry(self):
        fake = self.use(reply(503))
        self.assertEqual(ahttp.request("GET", URL).status, 503)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_retries_wait_15_30_45_and_the_last_answer_comes_back_as_it_came(self):
        fake = self.use(reply(500), reply(502), reply(503), reply(504, b"still down"))
        res = ahttp.request("GET", URL, retry=True)
        self.assertEqual((res.status, res.body), (504, b"still down"))
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(self.sleeps, [15, 30, 45])

    def test_a_retry_that_succeeds(self):
        self.use(reply(429), reply(408), reply(200, b"{}"))
        self.assertEqual(ahttp.request("GET", URL, retry=True).status, 200)
        self.assertEqual(self.sleeps, [15, 30])

    def test_client_errors_are_not_retried(self):
        fake = self.use(reply(404), reply(200))
        self.assertEqual(ahttp.request("GET", URL, retry=True).status, 404)
        self.assertEqual(len(fake.calls), 1)

    def test_retry_after_seconds_is_honoured_and_capped(self):
        self.use(reply(429, headers={"Retry-After": "7"}), reply(503, headers={"retry-after": "1000"}), reply(200))
        ahttp.request("GET", URL, retry=True)
        self.assertEqual(self.sleeps, [7, 120])

    def test_retry_after_as_a_date(self):
        when = email.utils.formatdate(time.time() + 60, usegmt=True)
        self.use(reply(503, headers={"Retry-After": when}), reply(200))
        ahttp.request("GET", URL, retry=True)
        self.assertTrue(55 <= self.sleeps[0] <= 61, self.sleeps)

    def test_timeouts_and_dropped_connections_are_retried(self):
        fake = self.use(socket.timeout("timed out"), ConnectionResetError("reset"),
                        http.client.RemoteDisconnected("gone"), reply(200))
        self.assertEqual(ahttp.request("PUT", URL, body=b"x", retry=True).status, 200)
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(self.sleeps, [15, 30, 45])

    def test_the_last_error_is_raised_when_every_try_fails(self):
        self.use(*[socket.timeout("timed out")] * 4)
        with self.assertRaises(socket.timeout):
            ahttp.request("GET", URL, retry=True)
        self.assertEqual(len(self.sleeps), 3)

    def test_without_retry_an_error_is_raised_at_once(self):
        self.use(ConnectionResetError("reset"))
        with self.assertRaises(ConnectionResetError):
            ahttp.request("GET", URL)

    def test_bodies(self):
        fake = self.use(reply(200), reply(200), reply(200))
        ahttp.request("POST", URL, body={"title": "Sample Recipes"})
        ahttp.request("POST", URL, body="café", headers={"Content-Type": "text/plain"})
        ahttp.request("POST", URL, body={"a": 1}, headers={"content-type": "application/merge-patch+json"})
        (_, _, h1, b1, _), (_, _, h2, b2, _), (_, _, h3, _, _) = fake.calls
        self.assertEqual(b1, b'{"title": "Sample Recipes"}')
        self.assertEqual(h1["Content-Type"], "application/json")
        self.assertEqual(b2, "café".encode("utf-8"))
        self.assertEqual(h3, {"content-type": "application/merge-patch+json"})
        with self.assertRaises(TypeError):
            ahttp.request("POST", URL, body=3)

    def test_method_url_headers_and_timeout_reach_the_transport(self):
        fake = self.use(reply(204))
        ahttp.request("DELETE", URL, headers={"Authorization": "Bearer test-token"}, timeout=5)
        self.assertEqual(fake.calls[0], ("DELETE", URL, {"Authorization": "Bearer test-token"}, None, 5))


class ResponseTests(unittest.TestCase):
    def test_headers_by_any_case(self):
        r = ahttp.Response(200, {"Content-Type": "application/json", "X-Rate": "1"}, b'{"a": 1}')
        self.assertEqual(r.header("content-type"), "application/json")
        self.assertEqual(r.header("X-RATE"), "1")
        self.assertEqual(r.headers["x-rate"], "1")
        self.assertEqual(r.json(), {"a": 1})
        self.assertEqual(r.text(), '{"a": 1}')
        self.assertIsNone(ahttp.Response(204).json())


class RequestJsonTests(HttpTestCase):
    def test_parses_json_and_asks_for_it(self):
        fake = self.use(reply(200, b'{"id": "edit-1"}'))
        self.assertEqual(ahttp.request_json("POST", URL), {"id": "edit-1"})
        self.assertEqual(fake.calls[0][2]["Accept"], "application/json")

    def test_an_empty_body_is_none(self):
        self.use(reply(204))
        self.assertIsNone(ahttp.request_json("DELETE", URL))

    def test_errors_raise_http_error(self):
        self.use(reply(403, b'{"error": {"message": "The caller does not have permission"}}'))
        with self.assertRaises(ahttp.HttpError) as cm:
            ahttp.request_json("GET", URL)
        e = cm.exception
        self.assertEqual((e.status, e.method, e.url), (403, "GET", URL))
        self.assertIn("does not have permission", e.body_text)
        self.assertEqual(e.json()["error"]["message"], "The caller does not have permission")
        self.assertIn("403", str(e))

    def test_errors_after_retries(self):
        self.use(reply(500), reply(500), reply(500), reply(500, b"oops"))
        with self.assertRaises(ahttp.HttpError) as cm:
            ahttp.request_json("GET", URL, retry=True)
        self.assertEqual(cm.exception.body_text, "oops")
        self.assertIsNone(cm.exception.json())

    def test_a_reply_that_is_not_json(self):
        self.use(reply(200, b"<html>"))
        with self.assertRaises(ahttp.HttpError):
            ahttp.request_json("GET", URL)



class RedirectTests(unittest.TestCase):
    """The real transport's redirect handler: GETs follow redirects, writes don't, and a guard can refuse one."""

    def setUp(self):
        self.handler = ahttp._NoRedirectForWrites()
        self.addCleanup(setattr, ahttp, "REDIRECT_ALLOWED", ahttp.REDIRECT_ALLOWED)

    def follow(self, method, newurl):
        import urllib.request
        req = urllib.request.Request("https://cdn.example.com/a.png", method=method)
        return self.handler.redirect_request(req, None, 302, "Found", {}, newurl)

    def test_a_get_follows_a_redirect(self):
        ahttp.REDIRECT_ALLOWED = None
        new = self.follow("GET", "https://cdn.example.com/b.png")
        self.assertEqual(new.full_url, "https://cdn.example.com/b.png")

    def test_a_write_never_follows_one(self):
        self.assertIsNone(self.follow("POST", "https://cdn.example.com/b.png"))

    def test_the_guard_refuses_a_redirect_to_another_host(self):
        ahttp.REDIRECT_ALLOWED = lambda url: url.startswith("https://cdn.example.com/")
        self.assertIsNotNone(self.follow("GET", "https://cdn.example.com/b.png"))
        self.assertIsNone(self.follow("GET", "https://elsewhere.example.net/b.png"))


if __name__ == "__main__":
    unittest.main()
