#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A WebAuthn ceremony, fabricated: a real key, a real blob, a real signature.

There is no published vector for a whole ceremony the way RFC 6238 prints codes, so the tests
build one. This is that builder, and it lives outside both test files because two of them need
it — :mod:`tests.unit.test_mfa_webauthn`, which takes a ceremony that WOULD verify and breaks
exactly one thing at a time, and :mod:`tests.integration.test_wa_mfa`, which pushes a whole one
through HTTP to prove the wiring carries it.

A copy in each would be two CBOR encoders that can disagree about what a valid ceremony looks
like, and the day they did, one of the two suites would be proving something about itself.

Not named ``test_*`` on purpose: it holds no tests and must not be collected. The
``importorskip`` is at import time, so a suite without ``cryptography`` skips the files that
import this rather than failing to collect them.
"""

import hashlib
import json
import struct

import pytest

from lib.core.mfa import cose, webauthn as wa

pytest.importorskip('cryptography')

from cryptography.hazmat.primitives import hashes                    # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec             # noqa: E402

RP_ID = 'panel.example.com'
ORIGIN = 'https://panel.example.com'


def _cbor_map(pairs: dict) -> bytes:
    """The tiny bit of CBOR encoding the tests need — the decoder is the code under test."""
    def item(v):
        if isinstance(v, int):
            if v >= 0:
                return bytes([0x00 | v]) if v < 24 else b'\x18' + bytes([v]) if v < 256 \
                    else b'\x19' + struct.pack('>H', v)
            n = -1 - v
            return bytes([0x20 | n]) if n < 24 else b'\x38' + bytes([n])
        if isinstance(v, bytes):
            return (bytes([0x40 | len(v)]) if len(v) < 24
                    else b'\x58' + bytes([len(v)])) + v
        raise TypeError(v)
    out = bytes([0xA0 | len(pairs)])
    for k, v in pairs.items():
        out += item(k) + item(v)
    return out


def _key():
    priv = ec.generate_private_key(ec.SECP256R1())
    n = priv.public_key().public_numbers()
    return priv, {1: cose.KTY_EC2, 3: cose.ES256, -1: cose.CRV_P256,
                  -2: n.x.to_bytes(32, 'big'), -3: n.y.to_bytes(32, 'big')}


def _auth_data(rp_id=RP_ID, flags=wa.FLAG_UP | wa.FLAG_AT, count=1,
               cred_id=b'cred-0001', cose_key=None, extra=b''):
    blob = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack('>I', count)
    if flags & wa.FLAG_AT:
        blob += b'\x00' * 16 + struct.pack('>H', len(cred_id)) + cred_id
        blob += _cbor_map(cose_key) if cose_key else b''
    return blob + extra


def _client_data(kind, challenge, origin=ORIGIN):
    return json.dumps({'type': kind, 'challenge': challenge, 'origin': origin,
                       'crossOrigin': False}).encode()


def _registration(challenge, **kw):
    priv, key = _key()
    auth = _auth_data(cose_key=key, **kw)
    att = b'\xa3' + b'\x63fmt' + b'\x64none' + b'\x67attStmt' + b'\xa0' \
          + b'\x68authData' + b'\x59' + struct.pack('>H', len(auth)) + auth
    return priv, key, att, _client_data('webauthn.create', challenge)


def _assertion(priv, challenge, origin=ORIGIN, rp_id=RP_ID, flags=wa.FLAG_UP, count=2):
    auth = _auth_data(rp_id=rp_id, flags=flags, count=count)
    cdj = _client_data('webauthn.get', challenge, origin)
    sig = priv.sign(auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))
    return auth, cdj, sig
