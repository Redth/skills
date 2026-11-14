"""Tests for appstores_lib.jwt (stdlib unittest).

Signing tests make throwaway keys with openssl in a temp folder and verify each token's signature with
``openssl dgst -verify``; they're skipped where openssl isn't installed.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import jwt  # noqa: E402

OPENSSL = shutil.which("openssl")
CLAIMS = {"iss": "00000000-0000-0000-0000-000000000000", "iat": 1700000000, "exp": 1700001200,
          "aud": "appstoreconnect-v1"}


def unb64url(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def der_int(raw):
    raw = raw.lstrip(b"\0") or b"\0"
    if raw[0] & 0x80:
        raw = b"\0" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def raw_to_der(sig):
    """The test's own raw r||s -> DER, independent of the module's DER -> raw."""
    half = len(sig) // 2
    body = der_int(sig[:half]) + der_int(sig[half:])
    return b"\x30" + bytes([len(body)]) + body


def run(*args, **kw):
    return subprocess.run([OPENSSL] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **kw)


@unittest.skipIf(OPENSSL is None, "openssl isn't installed")
class SigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = cls.dir = cls._tmp.name
        cls.ec_key = os.path.join(d, "ec.pem")
        cls.ec_pub = os.path.join(d, "ec.pub.pem")
        run("ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", cls.ec_key)
        run("ec", "-in", cls.ec_key, "-pubout", "-out", cls.ec_pub)
        cls.ec_pkcs8 = os.path.join(d, "ec.p8")
        run("pkcs8", "-topk8", "-nocrypt", "-in", cls.ec_key, "-out", cls.ec_pkcs8)
        cls.rsa_key = os.path.join(d, "rsa.pem")
        cls.rsa_pub = os.path.join(d, "rsa.pub.pem")
        run("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", cls.rsa_key)
        run("pkey", "-in", cls.rsa_key, "-pubout", "-out", cls.rsa_pub)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def verify(self, pub, signing_input, signature):
        sig_path = os.path.join(self.dir, "sig.bin")
        data_path = os.path.join(self.dir, "data.txt")
        with open(sig_path, "wb") as f:
            f.write(signature)
        with open(data_path, "wb") as f:
            f.write(signing_input.encode("ascii"))
        proc = subprocess.run([OPENSSL, "dgst", "-sha256", "-verify", pub, "-signature", sig_path, data_path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc.returncode == 0 and b"Verified OK" in proc.stdout

    def check_es256(self, key_path):
        pem = jwt.load_key(key_path)
        token = jwt.es256(pem, {"kid": "TESTKEY123"}, CLAIMS)
        head, body, sig = token.split(".")
        self.assertEqual(json.loads(unb64url(head)), {"kid": "TESTKEY123", "alg": "ES256", "typ": "JWT"})
        self.assertEqual(json.loads(unb64url(body)), CLAIMS)
        raw = unb64url(sig)
        self.assertEqual(len(raw), 64, "ES256 signatures are raw r||s, 32 bytes each")
        self.assertTrue(self.verify(self.ec_pub, head + "." + body, raw_to_der(raw)))
        self.assertFalse(self.verify(self.ec_pub, head + "." + body + "x", raw_to_der(raw)))

    def test_es256_round_trip(self):
        for _ in range(4):  # different signatures, some with short r or s
            self.check_es256(self.ec_key)

    def test_es256_with_a_pkcs8_key_like_apples_p8(self):
        self.check_es256(self.ec_pkcs8)

    def test_rs256_round_trip(self):
        pem = jwt.load_key(self.rsa_key)
        token = jwt.rs256(pem, {"kid": "abc"}, {"iss": "sa@example.com", "scope": "x"})
        head, body, sig = token.split(".")
        self.assertEqual(json.loads(unb64url(head))["alg"], "RS256")
        raw = unb64url(sig)
        self.assertEqual(len(raw), 256)
        self.assertTrue(self.verify(self.rsa_pub, head + "." + body, raw))

    def test_es256_with_an_rsa_key_explains(self):
        with self.assertRaises(jwt.KeyProblem) as cm:
            jwt.es256(jwt.load_key(self.rsa_key), {}, CLAIMS)
        self.assertIn("EC P-256", str(cm.exception))

    def test_a_key_openssl_cannot_read(self):
        bogus = "-----BEGIN PRIVATE KEY-----\n" + base64.b64encode(b"not a key at all").decode() + "\n-----END PRIVATE KEY-----\n"
        with self.assertRaises(jwt.KeyProblem):
            jwt.es256(bogus, {}, CLAIMS)

    def test_no_key_file_is_left_behind(self):
        before = set(os.listdir(tempfile.gettempdir()))
        jwt.es256(jwt.load_key(self.ec_key), {}, CLAIMS)
        after = set(os.listdir(tempfile.gettempdir()))
        self.assertEqual([n for n in after - before if n.startswith("appstores-key-")], [])

    def test_load_key_from_text_base64_and_damaged_whitespace(self):
        with open(self.ec_pkcs8) as f:
            text = f.read()
        expected = jwt.load_key(self.ec_pkcs8)
        self.assertEqual(jwt.load_key(text), expected)
        self.assertEqual(jwt.load_key(base64.b64encode(text.encode()).decode()), expected)
        self.assertEqual(jwt.load_key(base64.b64encode(self.ec_pkcs8.encode()).decode()), expected)
        self.assertEqual(jwt.load_key(text.replace("\n", "\\n")), expected)
        self.assertEqual(jwt.load_key(text.replace("\n", " ")), expected)
        self.assertEqual(jwt.load_key(text.replace("\n", "\r\n")), expected)
        self.assertEqual(jwt.load_key("   " + text.replace("\n", "\n    ") + "  "), expected)
        # the repaired key still signs
        self.check_es256(self.ec_pkcs8)


class KeyTests(unittest.TestCase):
    def test_nothing_usable(self):
        for value in ("", "   ", "not a key", "/nonexistent/key.p8", base64.b64encode(b"hello").decode()):
            with self.assertRaises(jwt.KeyProblem) as cm:
                jwt.load_key(value)
            self.assertNotIn("hello", str(cm.exception))

    def test_a_file_without_a_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "empty.p8")
            with open(path, "w") as f:
                f.write("nothing here")
            with self.assertRaises(jwt.KeyProblem):
                jwt.load_key(path)

    def test_der_to_raw_pads_and_strips(self):
        r = b"\x00" + b"\x80" + b"\x11" * 31          # a leading zero for a high bit: 33 bytes
        s = b"\x22" * 30                               # short: padded to 32
        der = b"\x30" + bytes([4 + len(r) + len(s)]) + b"\x02" + bytes([len(r)]) + r + b"\x02" + bytes([len(s)]) + s
        raw = jwt.der_to_raw(der)
        self.assertEqual(raw, b"\x80" + b"\x11" * 31 + b"\x00\x00" + b"\x22" * 30)
        with self.assertRaises(jwt.KeyProblem):
            jwt.der_to_raw(b"\x01\x02\x03")

    def test_b64url(self):
        self.assertEqual(jwt.b64url(b"\xfb\xff"), "-_8")
        self.assertEqual(jwt.b64url("{}"), "e30")

    def test_find_openssl_explains(self):
        with mock.patch.dict(os.environ, {"OPENSSL": "/nonexistent/openssl-for-a-test"}):
            with self.assertRaises(RuntimeError):
                jwt.find_openssl()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENSSL", None)
            with mock.patch.object(jwt.shutil, "which", return_value=None):
                with self.assertRaises(RuntimeError) as cm:
                    jwt.find_openssl()
        self.assertIn("openssl", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
