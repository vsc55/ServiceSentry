#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The WebAuthn ceremonies, as arithmetic over bytes somebody else composed.

Registration and authentication, verified here and nowhere else. Pure: it takes the blobs the
browser posted plus what the server already knew — the challenge it issued, the RP ID it
serves under, the origin it expects — and answers what is true about them. No Flask, no store,
no clock beyond what is passed in, which is what makes every check below a test rather than a
comment.

**What this checks, and why each one is not optional**

* **the challenge**, compared in constant time against the one THIS server issued. Without it
  an assertion captured once is an assertion replayable forever, which is the whole of what a
  second factor is supposed to prevent.
* **the origin**, exactly — string equality against what the panel expects, not "ends with".
  `https://panel.example.com.attacker.net` ends with nothing useful, and a substring test is
  how that becomes a valid login.
* **the RP ID hash** inside the authenticator data, against SHA-256 of the RP ID the server
  serves under. The browser scopes a credential to it; this is the server checking the browser
  was scoping it to the same place.
* **the user-presence flag**, because a credential that can be exercised without anybody
  touching anything is a file, not a factor.
* **the signature counter**, when the authenticator keeps one. A counter that did not move
  forward means two authenticators are answering for one credential — the one signal in the
  protocol that says "this key has been cloned".

**What this deliberately does NOT check: attestation.** The attestation statement says which
model of authenticator was used, and verifying it means shipping and maintaining a list of
vendor roots in order to answer a question this panel does not ask. A second factor here is
"something the person has", not "something from a manufacturer we approve", so the format is
read for the key it carries and the statement itself is ignored. That is the standard choice
for this use, and it is a choice rather than an omission.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct

from lib.core.mfa import cbor, cose

# Authenticator data flags (WebAuthn §6.1).
FLAG_UP = 0x01          # user present — somebody touched it
FLAG_UV = 0x04          # user verified — a PIN or a fingerprint, not just a touch
FLAG_AT = 0x40          # attested credential data is present (registration)

CHALLENGE_BYTES = 32    # what the specification asks for, and what every library sends


class CeremonyError(ValueError):
    """The ceremony does not hold.

    One exception for all of it and no detail on the wire: which check failed is something the
    server logs, not something the sender is told. "Wrong origin" and "wrong challenge" are
    two different pieces of help to give somebody probing.
    """


def b64u_encode(raw: bytes) -> str:
    """base64url without padding — how WebAuthn puts bytes in JSON."""
    return base64.urlsafe_b64encode(bytes(raw)).decode('ascii').rstrip('=')


def b64u_decode(text: str) -> bytes:
    """base64url in, bytes out; `b''` for anything that is not it.

    Never raises: every one of these arrives from the browser, and a malformed field must fail
    the ceremony rather than the request handler.
    """
    s = str(text or '')
    s += '=' * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s)
    except Exception:      # pylint: disable=broad-except
        return b''


def new_challenge() -> str:
    """A fresh challenge, base64url. From `secrets`: it is the anti-replay of the whole thing."""
    return b64u_encode(secrets.token_bytes(CHALLENGE_BYTES))


def rp_id_from(public_url: str) -> str:
    """The RP ID this panel serves under, taken from `web_admin|public_url`.

    The registrable domain and nothing else — no scheme, no port, no path. A credential is
    scoped to it by the browser and **cannot be moved**: register against `panel.example.com`
    and the key is useless the day the panel answers on another name. So it is derived from the
    address the operator declared as public rather than from the request, which behind a
    reverse proxy is whatever the proxy last said.

    Empty when there is nothing usable — the caller does not offer WebAuthn rather than
    guessing, because a guess here produces a credential that silently never works again.
    """
    text = str(public_url or '').strip()
    if not text:
        return ''
    if '://' in text:
        text = text.split('://', 1)[1]
    text = text.split('/', 1)[0].split('?', 1)[0]
    # A bracketed IPv6 literal, or a host:port. Neither a literal address nor a port belongs
    # in an RP ID: the specification wants a domain.
    if text.startswith('['):
        return ''
    host = text.split(':', 1)[0].strip().lower().rstrip('.')
    if not host or host.replace('.', '').isdigit():
        return ''          # an IP address is not a registrable domain
    return host


def origin_from(public_url: str) -> str:
    """The exact origin the browser will report, for the string comparison below."""
    text = str(public_url or '').strip().rstrip('/')
    if not text:
        return ''
    if '://' not in text:
        text = 'https://' + text
    scheme, rest = text.split('://', 1)
    return f'{scheme.lower()}://{rest.split("/", 1)[0]}'


def parse_auth_data(blob: bytes) -> dict:
    """Authenticator data → its fields, credential and public key included when present.

    Fixed 37-byte head (RP ID hash, flags, counter) and then, only if the AT flag says so, the
    attested credential: the AAGUID, the credential id, and the public key as CBOR. The key is
    followed by whatever extensions were requested, which is exactly why the CBOR decoder
    reports how far it read.
    """
    data = bytes(blob or b'')
    if len(data) < 37:
        raise CeremonyError('authenticator data too short')
    out = {
        'rp_id_hash': data[:32],
        'flags': data[32],
        'sign_count': struct.unpack('>I', data[33:37])[0],
        'credential_id': b'',
        'public_key': None,
        'public_key_raw': b'',
        'aaguid': b'',
    }
    if not out['flags'] & FLAG_AT:
        return out
    if len(data) < 55:
        raise CeremonyError('attested credential data truncated')
    out['aaguid'] = data[37:53]
    cred_len = struct.unpack('>H', data[53:55])[0]
    # A length the authenticator chose. The specification caps a credential id at 1023 bytes,
    # and a two-byte field can say sixty-five thousand.
    if cred_len > 1023 or len(data) < 55 + cred_len:
        raise CeremonyError('credential id length is not usable')
    out['credential_id'] = data[55:55 + cred_len]
    key_at = 55 + cred_len
    try:
        key, consumed = cbor.decode_from(data, key_at)
    except cbor.CborError as exc:
        raise CeremonyError('credential public key is not readable') from exc
    if not isinstance(key, dict):
        raise CeremonyError('credential public key is not a COSE key')
    out['public_key'] = key
    # The key's own bytes, as they arrived. Stored verbatim and re-parsed by this same decoder
    # when an assertion turns up, so there is ONE representation and no second place that can
    # disagree about what the key is — which is also why nothing here encodes CBOR: this
    # module reads it, and a writer would be a second opinion.
    # `consumed` is a LENGTH, not an end offset — the decoder answers how far it read from
    # where it was told to start. Slicing to it as if it were absolute silently produced a
    # truncated key that stored and then would not verify, which is the shape of bug that only
    # shows up on the second half of the feature.
    out['public_key_raw'] = data[key_at:key_at + consumed]
    return out


def _client_data(raw: bytes, want_type: str, challenge: str, origin: str) -> dict:
    """The client data, checked against what the server issued and expects.

    Three checks and each is the whole feature when it is missing: the ceremony TYPE (a
    registration response replayed at login is otherwise a login), the CHALLENGE (compared in
    constant time — an assertion captured once would otherwise be replayable forever), and the
    ORIGIN (exact equality, because `https://panel.example.com.attacker.net` passes any test
    that is not).
    """
    try:
        data = json.loads(bytes(raw or b'').decode('utf-8'))
    except Exception as exc:      # pylint: disable=broad-except
        raise CeremonyError('client data is not JSON') from exc
    if not isinstance(data, dict):
        raise CeremonyError('client data is not an object')
    if str(data.get('type') or '') != want_type:
        raise CeremonyError('wrong ceremony type')
    got = str(data.get('challenge') or '')
    if not challenge or not hmac.compare_digest(got, str(challenge)):
        raise CeremonyError('challenge does not match')
    if not origin or str(data.get('origin') or '') != origin:
        raise CeremonyError('origin does not match')
    return data


def verify_registration(*, attestation_object: bytes, client_data_json: bytes,
                        challenge: str, rp_id: str, origin: str,
                        require_uv: bool = False) -> dict:
    """A registration response → the credential to store, or raise.

    Answers `{'credential_id', 'public_key', 'alg', 'sign_count', 'aaguid', 'uv'}`. The
    algorithm is recorded HERE, at registration, and is what every later assertion is checked
    with — a key that gets to name its own algorithm when the assertion arrives is the JWT
    `alg` flaw with different words.

    The attestation STATEMENT is not verified; see this module's header. The format is read
    only far enough to find the authenticator data inside it.
    """
    _client_data(client_data_json, 'webauthn.create', challenge, origin)
    try:
        att = cbor.decode(bytes(attestation_object or b''))
    except cbor.CborError as exc:
        raise CeremonyError('attestation object is not readable') from exc
    if not isinstance(att, dict) or not isinstance(att.get('authData'), bytes):
        raise CeremonyError('attestation object has no authenticator data')

    auth = parse_auth_data(att['authData'])
    if auth['rp_id_hash'] != hashlib.sha256(str(rp_id).encode()).digest():
        raise CeremonyError('this credential was scoped to a different site')
    if not auth['flags'] & FLAG_UP:
        raise CeremonyError('nobody was present')
    if require_uv and not auth['flags'] & FLAG_UV:
        raise CeremonyError('user verification was required and did not happen')
    if not auth['credential_id'] or auth['public_key'] is None:
        raise CeremonyError('no credential was attested')

    alg = cose.algorithm_of(auth['public_key'])
    if alg not in cose.SUPPORTED:
        raise CeremonyError('unsupported key algorithm')
    # Built once here so a key this cannot use is refused at REGISTRATION rather than at the
    # first sign-in, when the person no longer has the setup screen in front of them.
    cose.public_key(auth['public_key'], alg)
    return {'credential_id': auth['credential_id'],
            'public_key': auth['public_key'],
            'public_key_raw': auth['public_key_raw'],
            'alg': alg,
            'sign_count': auth['sign_count'],
            'aaguid': auth['aaguid'],
            'uv': bool(auth['flags'] & FLAG_UV)}


def verify_assertion(*, auth_data: bytes, client_data_json: bytes, signature: bytes,
                     challenge: str, rp_id: str, origin: str,
                     public_key: dict, alg: int, last_sign_count: int = 0,
                     require_uv: bool = False) -> dict:
    """An authentication response → what it proved, or raise.

    The signature covers the authenticator data followed by the SHA-256 of the client data —
    concatenated, in that order. Checking it over anything else checks nothing: the client data
    is where the challenge and the origin live, so a signature that does not cover its hash is
    a signature over a ceremony somebody else chose.

    `sign_count` comes back so the caller can store it. A counter that does not move forward,
    when the authenticator keeps one at all, means two devices are answering for one
    credential — the only signal in this protocol that says a key has been cloned.
    """
    _client_data(client_data_json, 'webauthn.get', challenge, origin)
    auth = parse_auth_data(auth_data)
    if auth['rp_id_hash'] != hashlib.sha256(str(rp_id).encode()).digest():
        raise CeremonyError('this credential was scoped to a different site')
    if not auth['flags'] & FLAG_UP:
        raise CeremonyError('nobody was present')
    if require_uv and not auth['flags'] & FLAG_UV:
        raise CeremonyError('user verification was required and did not happen')

    signed = bytes(auth_data) + hashlib.sha256(bytes(client_data_json or b'')).digest()
    if not cose.verify(public_key, int(alg), bytes(signature or b''), signed):
        raise CeremonyError('signature does not verify')

    count, last = auth['sign_count'], int(last_sign_count or 0)
    # Zero on either side means this authenticator does not keep a counter — which is allowed,
    # and common on platform authenticators. Only a counter that EXISTS and went backwards (or
    # stood still) is evidence, and it is evidence of the one thing worth refusing for.
    cloned = bool(count and last and count <= last)
    if cloned:
        raise CeremonyError('the signature counter went backwards')
    return {'sign_count': count, 'uv': bool(auth['flags'] & FLAG_UV)}
