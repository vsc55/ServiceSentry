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
from lib.core.mfa import qr, totp

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

    No secret, ever — not even the encrypted one. Three facts: is there a factor, has it been
    proved, and how many ways back in are left.
    """
    factor = store.factor(user_uid)
    return {
        'enrolled': bool(factor and factor.get('confirmed')),
        'pending': bool(factor and not factor.get('confirmed')),
        'method': (factor or {}).get('method', ''),
        'since': (factor or {}).get('updated', ''),
        'recovery_left': store.recovery_left(user_uid) if factor else 0,
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
