"""JSON Web Tokens signed with ES256 (App Store Connect) or RS256 (Google service accounts) by ``openssl``.

The standard library can't sign with EC or RSA keys, so the signing is ``openssl dgst -sha256 -sign``,
run with the key in a private temporary file that's removed straight after. Keys are never logged or put
in an error message.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import tempfile


class KeyProblem(ValueError):
    """A key that couldn't be read or used (the message never includes the key)."""


def find_openssl():
    """Return the path of ``openssl`` (``$OPENSSL`` first, then ``PATH``), or raise ``RuntimeError`` saying so."""
    env = os.environ.get("OPENSSL")
    if env:
        found = shutil.which(env) or (env if os.path.isfile(env) and os.access(env, os.X_OK) else None)
        if found:
            return found
        raise RuntimeError("$OPENSSL is set to %r, which isn't a program that can run" % env)
    found = shutil.which("openssl")
    if not found:
        raise RuntimeError(
            "Signing the stores' tokens needs the openssl command, and it isn't on PATH. It comes with macOS "
            "and most Linux distributions (the openssl package); install it or set OPENSSL to its path.")
    return found


_PEM = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", re.DOTALL)


def _normalize_pem(text):
    """Rebuild a PEM block whose line breaks were damaged (escaped ``\\n``, spaces, CRLF, one long line)."""
    text = text.replace("\\r", "").replace("\\n", "\n").replace("\r", "")
    m = _PEM.search(text)
    if not m:
        return None
    label, body = m.group(1).strip(), m.group(2)
    lines = [ln.strip() for ln in body.strip().split("\n")]
    headers = [ln for ln in lines if ":" in ln]  # e.g. Proc-Type in old encrypted keys
    data = re.sub(r"[^A-Za-z0-9+/=]", "", "".join(ln for ln in lines if ":" not in ln))
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    wrapped = "\n".join(data[i: i + 64] for i in range(0, len(data), 64))
    head = ("\n".join(headers) + "\n\n") if headers else ""
    return "-----BEGIN %s-----\n%s%s\n-----END %s-----\n" % (label, head, wrapped, label)


def _from_base64(value):
    compact = re.sub(r"\s+", "", value)
    if not compact or not re.match(r"^[A-Za-z0-9+/_-]+=*$", compact):
        return None
    try:
        raw = base64.b64decode(compact + "=" * (-len(compact) % 4), altchars=b"-_" if ("-" in compact or "_" in compact) else None)
        return raw.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def load_key(value):
    """Return a private key as PEM text from a path to it, its text, or base64 of either.

    Whitespace damage from environment variables and CI secrets (escaped ``\\n``, spaces instead of line
    breaks, CRLF, stray indentation) is repaired. Raises ``KeyProblem`` (a ``ValueError``) when no PEM key
    can be found; the message never contains the value.
    """
    if not value or not str(value).strip():
        raise KeyProblem("no key given")
    value = str(value).strip()
    tried = [value]
    decoded = _from_base64(value) if "-----BEGIN" not in value else None
    if decoded:
        tried.append(decoded.strip())
    for candidate in tried:
        if "-----BEGIN" in candidate:
            pem = _normalize_pem(candidate)
            if pem:
                return pem
            raise KeyProblem("the key's PEM text is damaged beyond repair")
        path = os.path.expanduser(candidate)
        if len(candidate) < 4096 and "\n" not in candidate and os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                pem = _normalize_pem(f.read())
            if pem:
                return pem
            raise KeyProblem("%s doesn't hold a PEM key" % path)
    raise KeyProblem("the key is neither a file that exists, PEM text, nor base64 of either")


def b64url(data):
    """Base64url without padding, as JWTs use."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signing_input(header, claims):
    def enc(obj):
        return b64url(json.dumps(obj, separators=(",", ":")))
    return enc(header) + "." + enc(claims)


def _openssl_sign(pem, data):
    """Sign ``data`` (bytes) with SHA-256 and the PEM key; return openssl's signature bytes."""
    openssl = find_openssl()
    folder = tempfile.mkdtemp(prefix="appstores-key-")
    try:
        key_path = os.path.join(folder, "key.pem")
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(pem)
        proc = subprocess.run([openssl, "dgst", "-sha256", "-sign", key_path], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if proc.returncode != 0 or not proc.stdout:
        first = proc.stderr.decode("utf-8", "replace").strip().splitlines()[:1]
        raise KeyProblem("openssl couldn't sign with this key%s" % (": " + first[0] if first else ""))
    return proc.stdout


def _der_length(der, pos):
    first = der[pos]
    if first < 0x80:
        return first, pos + 1
    n = first & 0x7F
    return int.from_bytes(der[pos + 1: pos + 1 + n], "big"), pos + 1 + n


def der_to_raw(der, size=32):
    """Convert an ECDSA signature from DER (``SEQUENCE { INTEGER r, INTEGER s }``) to raw ``r‖s``, each
    left-padded to ``size`` bytes (32 for P-256), as JWS wants."""
    try:
        if der[0] != 0x30:
            raise ValueError
        _seq_len, pos = _der_length(der, 1)
        out = b""
        for _ in range(2):
            if der[pos] != 0x02:
                raise ValueError
            length, pos = _der_length(der, pos + 1)
            num = der[pos: pos + length].lstrip(b"\0")
            pos += length
            if len(num) > size:
                raise ValueError
            out += num.rjust(size, b"\0")
        return out
    except (IndexError, ValueError):
        raise KeyProblem("openssl's signature isn't an ECDSA P-256 signature: is the key an EC P-256 key?") from None


def es256(pem, header, claims):
    """Return a JWT signed with ES256 (ECDSA P-256, SHA-256), as App Store Connect's API wants.

    ``header`` is completed with ``"alg": "ES256"`` (and ``"typ": "JWT"`` if absent); ``claims`` is the
    payload. ``pem`` is the private key's PEM text (``load_key`` reads it from wherever it is).
    """
    header = dict(header or {})
    header["alg"] = "ES256"
    header.setdefault("typ", "JWT")
    signing = _signing_input(header, claims)
    der = _openssl_sign(pem, signing.encode("ascii"))
    return signing + "." + b64url(der_to_raw(der, 32))


def rs256(pem, header, claims):
    """Return a JWT signed with RS256 (RSA PKCS#1 v1.5, SHA-256), as Google's OAuth token exchange wants.

    ``header`` is completed with ``"alg": "RS256"`` (and ``"typ": "JWT"`` if absent).
    """
    header = dict(header or {})
    header["alg"] = "RS256"
    header.setdefault("typ", "JWT")
    signing = _signing_input(header, claims)
    return signing + "." + b64url(_openssl_sign(pem, signing.encode("ascii")))
