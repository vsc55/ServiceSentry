#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What enrolling and verifying a second factor actually does — with no Flask in sight.

The store keeps rows and :mod:`lib.core.mfa.totp` does arithmetic; this is the layer that
decides. It takes a store and returns dicts, so the whole of the interesting behaviour —
"a code works once", "a recovery code is spent when it is used", "a pending enrolment grants
nothing" — is testable without an app, a request or a browser.

Two rules run through all of it:

* **an enrolment grants nothing until it is proved.** Starting one writes a row so the QR can
  be drawn from the same secret that will be verified, and that row is `confirmed = 0`. Every
  gate asks for a confirmed factor. A half-finished enrolment is a user with no second factor,
  which is what somebody who closed the tab expects to be.
* **nothing here says why it failed.** A wrong code and a spent recovery code both answer
  `None`, and the caller has one message. Which of the two it was is in the audit log, where
  the person who owns the account can read it and an attacker cannot.
"""

from __future__ import annotations

import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from lib import APP_NAME
from lib.core.mfa import cbor, qr, totp, webauthn

# How many recovery codes an enrolment gets. Ten is enough to lose a few and still have a way
# in, and few enough that the list stays something a person actually stores somewhere.
RECOVERY_COUNT = 10
# Two groups of five from an alphabet with no `0/O` or `1/I/l`: these get written down and read
# back, and the characters that get confused are the ones that turn a working code into a
# support thread.
_RECOVERY_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
_RECOVERY_GROUP = 5


def recovery_new() -> list:
    """A fresh set of recovery codes, in the clear. The ONLY time they exist as text.

    The caller shows them once and stores their hashes. There is no way back from the stored
    form and that is deliberate: a panel that can print somebody's recovery codes a second time
    is a panel where reading the database is enough to get in.
    """
    def one() -> str:
        raw = ''.join(secrets.choice(_RECOVERY_ALPHABET)
                      for _ in range(_RECOVERY_GROUP * 2))
        return f'{raw[:_RECOVERY_GROUP]}-{raw[_RECOVERY_GROUP:]}'
    return [one() for _ in range(RECOVERY_COUNT)]


def _normalise(code: str) -> str:
    """A recovery code as it was generated, whatever the person's keyboard did to it."""
    return ''.join(str(code or '').split()).replace('-', '').upper()


def recovery_hashes(codes) -> list:
    """The stored form. Hashed with the account hasher, so the cost factor is not a second
    decision that nobody revisits when the first one moves."""
    return [generate_password_hash(_normalise(c)) for c in codes]


def status(store, user_uid: str) -> dict:
    """What the account page and the users list need to know, and nothing more.

    No secret, ever — not even the encrypted one. Is there a factor, has it been proved, WHICH
    kinds there are, and how many ways back in are left.

    `enrolled` counts ANY confirmed method and not just the TOTP row, which is the difference
    between a gate that asks a key-only account for its key and one that waves it through: the
    login step reads this, and an account whose only factor is a security key would otherwise
    look like an account with no factor at all.
    """
    factor = store.factor(user_uid)
    methods = store.methods_of(user_uid)
    return {
        'enrolled': bool(methods),
        'pending': bool(factor and not factor.get('confirmed')),
        'method': (factor or {}).get('method', '') if factor and factor.get('confirmed')
                  else (methods[0] if methods else ''),
        'methods': methods,
        'since': (factor or {}).get('updated', ''),
        'recovery_left': store.recovery_left(user_uid) if methods else 0,
    }


def enroll_begin(store, user_uid: str, account: str, issuer: str = APP_NAME) -> dict:
    """Start an enrolment: a new secret, the link, the square and the string.

    Both ways in, always. The QR is what anybody actually uses, and the base32 secret beside it
    is the half somebody can read back and check — and the only one left when the camera will
    not focus, the phone has no camera, or this file drew the square wrong.

    Restarting replaces whatever was pending. Somebody who closed the page halfway must get a
    fresh secret rather than the one that may be sitting in a screenshot.

    Answers `{'ok': False, 'error': 'no_key'}` when secrets cannot be encrypted at rest: a TOTP
    seed is a generator, and one stored in the clear produces valid codes for that account for
    as long as the factor exists, with nothing to notice and nothing to rotate.
    """
    secret = totp.secret_new()
    if not store.begin(user_uid, secret):
        return {'ok': False, 'error': 'no_key'}
    uri = totp.provisioning_uri(secret, account, issuer)
    return {'ok': True,
            'secret': secret,
            'secret_groups': totp.secret_groups(secret),
            'uri': uri,
            # Empty when the link does not fit a version 10 symbol — the page shows the string
            # on its own rather than failing.
            'svg': qr.svg(uri),
            'digits': totp.DIGITS, 'period': totp.PERIOD, 'algorithm': totp.ALGORITHM}


def enroll_confirm(store, user_uid: str, code: str, *, now: float | None = None) -> dict:
    """Prove a pending enrolment with a code from the app, and switch it on.

    The step that proved it is stored with the confirmation, so the code that enrolled the
    factor is already spent — otherwise the very first thing a new factor does is accept a
    replay of the code that created it.

    The recovery codes are generated HERE and returned once. Not at `enroll_begin`: an
    enrolment that was abandoned would have left a set of working codes behind it, which is a
    way into an account whose owner believes they never finished setting one up.
    """
    factor = store.factor(user_uid, decrypt=True)
    if not factor:
        return {'ok': False, 'error': 'not_started'}
    if factor.get('confirmed'):
        return {'ok': False, 'error': 'already_enrolled'}
    step = totp.verify(factor['secret'], code, now=now, after_step=factor['last_step'])
    if step is None:
        return {'ok': False, 'error': 'bad_code'}
    if not store.confirm(user_uid, step):
        return {'ok': False, 'error': 'write_failed'}
    codes = recovery_new()
    store.set_recovery(user_uid, recovery_hashes(codes))
    return {'ok': True, 'recovery': codes}


def recovery_regenerate(store, user_uid: str) -> dict:
    """A fresh set, replacing the old one whole.

    Replace and never append: regenerating is what somebody does when they think the old list
    leaked, and a set that grew would leave the leaked half working.
    """
    factor = store.factor(user_uid)
    if not factor or not factor.get('confirmed'):
        return {'ok': False, 'error': 'not_enrolled'}
    codes = recovery_new()
    if not store.set_recovery(user_uid, recovery_hashes(codes)):
        return {'ok': False, 'error': 'write_failed'}
    return {'ok': True, 'recovery': codes}


def verify(store, user_uid: str, code: str, *, now: float | None = None) -> str:
    """`'totp'`, `'recovery'` or `''` — what the code was, if it was anything.

    Which one it was is the caller's business for two reasons: a recovery code being used is
    worth an audit line and a notification (it is either the owner in trouble or somebody
    inside), and it is what tells the account page its list is one shorter.

    A code is tried as a TOTP first and as a recovery code only if that fails, so a six-digit
    string never costs a recovery code. Both paths spend what they used.
    """
    factor = store.factor(user_uid, decrypt=True)
    if not factor or not factor.get('confirmed'):
        return ''
    step = totp.verify(factor['secret'], code, now=now, after_step=factor['last_step'])
    if step is not None:
        # Recorded before the caller is told yes: the window this code sits in is still open,
        # and a second request presenting it must lose.
        store.note_step(user_uid, step)
        return 'totp'
    got = _normalise(code)
    if not got:
        return ''
    for uid, code_hash in store.recovery_unused(user_uid):
        if check_password_hash(code_hash, got):
            # `consume_recovery` only changes a row that was still unused, so two requests
            # racing with the same code produce exactly one success.
            return 'recovery' if store.consume_recovery(uid) else ''
    return ''


# ── Security keys ────────────────────────────────────────────────────────────
# The ceremonies themselves live in `webauthn.py` and know nothing about this installation.
# What is here is the part that touches the store: what to keep from a registration, and how
# to check an assertion against what was kept.
#
# Every function below answers a dict and NEVER raises a `CeremonyError` outward. Which check
# failed is something the server logs; the sender is told "no". "Wrong origin" and "wrong
# challenge" are two different pieces of help to give somebody probing.

def webauthn_register(store, user_uid: str, *, attestation_object: bytes,
                      client_data_json: bytes, challenge: str, rp_id: str, origin: str,
                      label: str = '', require_uv: bool = False) -> dict:
    """Verify a registration and store the credential. `{'ok': True}` or `{'ok': False, …}`.

    Stored **confirmed**, unlike a TOTP enrolment: the ceremony IS the proof. The response was
    signed by the authenticator over a challenge this server issued, so there is nothing left
    for a second step to establish — asking for one more touch would be theatre.

    The public key is kept as it arrived (base64url of its CBOR) and the algorithm is recorded
    HERE. A key that gets to name its own algorithm when the assertion turns up is the JWT
    `alg` flaw with different words.
    """
    if not user_uid:
        return {'ok': False, 'error': 'unknown_user'}
    try:
        cred = webauthn.verify_registration(
            attestation_object=attestation_object, client_data_json=client_data_json,
            challenge=challenge, rp_id=rp_id, origin=origin, require_uv=require_uv)
    except webauthn.CeremonyError as exc:
        return {'ok': False, 'error': 'ceremony', 'detail': str(exc)}
    saved = store.save_credential(
        user_uid,
        credential_id=webauthn.b64u_encode(cred['credential_id']),
        public_key=webauthn.b64u_encode(cred['public_key_raw']),
        alg=cred['alg'], sign_count=cred['sign_count'], label=label)
    if not saved:
        return {'ok': False, 'error': 'write_failed'}
    return {'ok': True, 'method': 'webauthn',
            'credential_id': webauthn.b64u_encode(cred['credential_id'])}


def webauthn_credential(store, user_uid: str) -> dict:
    """What the browser needs to be told to use: `{'credential_id', 'alg', 'sign_count'}`.

    Empty when there is none. The `allowCredentials` list is built from this, and it is the
    reason a key can be offered before anybody has touched anything: the panel knows which
    credential to ask for.
    """
    factor = store.factor(user_uid, method='webauthn')
    if not factor or not factor.get('confirmed') or not factor.get('credential_id'):
        return {}
    return {'credential_id': factor['credential_id'], 'alg': int(factor.get('alg') or 0),
            'sign_count': int(factor.get('sign_count') or 0)}


def webauthn_verify(store, user_uid: str, *, auth_data: bytes, client_data_json: bytes,
                    signature: bytes, credential_id: str, challenge: str, rp_id: str,
                    origin: str, require_uv: bool = False) -> dict:
    """Check an assertion against the stored credential. `{'ok': True}` or `{'ok': False, …}`.

    The credential id the browser answers with is compared to the stored one **before** the
    signature is checked: an assertion from some other key of the same person's is a valid
    assertion, and it is not this account's second factor.

    The stored key is re-parsed by the same decoder that read it at registration, so there is
    one representation of what the key is rather than two that can disagree.
    """
    factor = store.factor(user_uid, method='webauthn')
    if not factor or not factor.get('confirmed') or not factor.get('credential_id'):
        return {'ok': False, 'error': 'not_enrolled'}
    if str(credential_id or '') != factor['credential_id']:
        return {'ok': False, 'error': 'wrong_credential'}
    try:
        key = cbor.decode(webauthn.b64u_decode(factor['public_key']))
    except cbor.CborError:
        # The stored key cannot be read: not the sender's doing, and not something to answer
        # with a bad-signature message that would send somebody to buy a new key.
        return {'ok': False, 'error': 'stored_key_unreadable'}
    if not isinstance(key, dict):
        return {'ok': False, 'error': 'stored_key_unreadable'}
    try:
        out = webauthn.verify_assertion(
            auth_data=auth_data, client_data_json=client_data_json, signature=signature,
            challenge=challenge, rp_id=rp_id, origin=origin, public_key=key,
            alg=int(factor.get('alg') or 0), last_sign_count=int(factor.get('sign_count') or 0),
            require_uv=require_uv)
    except webauthn.CeremonyError as exc:
        return {'ok': False, 'error': 'ceremony', 'detail': str(exc)}
    # Only after the signature held: a counter moved by a response that did not verify would
    # let somebody raise the bar for the real key without owning it.
    if out.get('sign_count'):
        store.note_sign_count(user_uid, int(out['sign_count']))
    return {'ok': True, 'method': 'webauthn', 'uv': bool(out.get('uv'))}
