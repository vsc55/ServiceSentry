#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Just enough CBOR (RFC 8949) to read what a security key sends back.

WebAuthn speaks CBOR: the attestation object is one, and the credential's public key is
another, nested inside a byte string inside the first. There is no CBOR library in this
project and adding one to parse two structures was not a trade worth making — the same
reasoning as the QR encoder next door, and the same discipline: this is checked against the
table of encodings the RFC publishes in its own appendix, not against itself.

**Decoding only.** Nothing here needs to produce CBOR — the browser sends it and the server
reads it — and an encoder would be a hundred lines that only tests would ever run.

Two rules that are security and not tidiness:

* **indefinite lengths are refused.** WebAuthn requires the canonical form (CTAP2 §6), where
  every length is stated up front. Accepting the streaming form as well would mean accepting
  two encodings of the same value — and "two ways to say the same thing" is how a signature
  gets computed over one of them and checked against the other.
* **the decoder says how much it consumed.** The authenticator data carries the public key as
  CBOR followed by whatever extensions come after it, so "parse the rest of the buffer" is not
  a question that has an answer here. A parser that silently ignores trailing bytes cannot
  tell a key from a key with something appended.
"""

from __future__ import annotations

import struct


class CborError(ValueError):
    """Malformed, truncated, or encoded in a form this refuses to accept.

    One exception for all of it: every caller does the same thing with a bad blob, which is
    reject the ceremony. Telling them WHICH way it was malformed would be telling whoever sent
    it, and they already know.
    """


# A ceiling on any single item, so a two-byte header cannot ask for a gigabyte. WebAuthn's
# structures are a few hundred bytes; this is generous by three orders of magnitude and still
# refuses the length field that says 2^64.
MAX_ITEM = 1 << 20


def _head(data: bytes, i: int) -> tuple:
    """`(major, argument, next_index)` for the item starting at *i*."""
    if i >= len(data):
        raise CborError('truncated')
    initial = data[i]
    major, minor = initial >> 5, initial & 0x1F
    i += 1
    if minor < 24:
        return major, minor, i
    if minor == 24:
        if i + 1 > len(data):
            raise CborError('truncated')
        return major, data[i], i + 1
    if minor in (25, 26, 27):
        width = {25: 2, 26: 4, 27: 8}[minor]
        if i + width > len(data):
            raise CborError('truncated')
        fmt = {2: '>H', 4: '>I', 8: '>Q'}[width]
        return major, struct.unpack(fmt, data[i:i + width])[0], i + width
    # 28–30 are reserved; 31 is the indefinite/streaming form, which the canonical encoding
    # WebAuthn requires does not use.
    raise CborError('indefinite or reserved length')


def _decode(data: bytes, i: int, depth: int) -> tuple:
    """`(value, next_index)`. *depth* bounds nesting — a few bytes of `[[[[…` is otherwise a
    recursion limit away from being a denial of service on the login path."""
    if depth > 16:
        raise CborError('too deeply nested')
    major, arg, i = _head(data, i)

    if major == 0:                                   # unsigned
        return arg, i
    if major == 1:                                   # negative: -1 - n
        return -1 - arg, i
    if major in (2, 3):                              # byte string / text string
        if arg > MAX_ITEM or i + arg > len(data):
            raise CborError('string too long or truncated')
        raw = data[i:i + arg]
        if major == 2:
            return raw, i + arg
        try:
            return raw.decode('utf-8'), i + arg
        except UnicodeDecodeError as exc:
            raise CborError('text is not utf-8') from exc
    if major == 4:                                   # array
        if arg > MAX_ITEM:
            raise CborError('array too long')
        out = []
        for _ in range(arg):
            item, i = _decode(data, i, depth + 1)
            out.append(item)
        return out, i
    if major == 5:                                   # map
        if arg > MAX_ITEM:
            raise CborError('map too long')
        out = {}
        for _ in range(arg):
            key, i = _decode(data, i, depth + 1)
            if isinstance(key, (list, dict)):
                raise CborError('map key is not hashable')
            value, i = _decode(data, i, depth + 1)
            # A repeated key is not a value judgement to make quietly: the two encodings
            # disagree about what the map says, and picking one of them is picking for
            # whoever sent it.
            if key in out:
                raise CborError('duplicate map key')
            out[key] = value
        return out, i
    if major == 6:                                   # tag — the tagged value is what matters
        value, i = _decode(data, i, depth + 1)
        return value, i
    # major == 7: the simple values and floats.
    if arg == 20:
        return False, i
    if arg == 21:
        return True, i
    if arg == 22:
        return None, i
    raise CborError('unsupported simple value')


def decode_from(data: bytes, offset: int = 0) -> tuple:
    """`(value, bytes_consumed)` — decode ONE item and say where it ended.

    The pair is the point. Authenticator data carries the credential's public key as CBOR
    followed by whatever extensions were requested, so the caller needs to know where the key
    stopped; a decoder that answers only the value cannot tell a key from a key with something
    appended to it.
    """
    value, end = _decode(bytes(data or b''), int(offset), 0)
    return value, end - int(offset)


def decode(data: bytes):
    """One item that is the WHOLE input — trailing bytes are an error.

    The attestation object is a complete document, and something after it is either a
    different encoding of the same thing or a second document nobody asked for. Both are
    reasons to stop rather than to shrug.
    """
    value, consumed = decode_from(data, 0)
    if consumed != len(bytes(data or b'')):
        raise CborError('trailing data')
    return value
