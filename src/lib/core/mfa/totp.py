#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Time-based one-time passwords (RFC 6238), from the standard library and nothing else.

`hmac`, `hashlib`, `struct` and `base64` are the whole of it. A dependency here would be a
dependency in a panel that gets installed on segregated networks by somebody who counts what it
pulls in — for thirty lines of arithmetic that has not changed since 2011.

**Pure.** No Flask, no database, no clock of its own beyond the one passed in: every function
here is a function of its arguments, which is what makes the RFC's own published vectors a
test rather than a comment. :mod:`lib.core.mfa.service` is where state lives.

Two things that are easy to leave out and are the whole security of it:

* **the step is returned, not just a yes.** A code is valid for thirty seconds, so a code read
  over somebody's shoulder — or off a phishing page — works until it expires. The caller stores
  the step that matched and refuses it and everything before it, so a code is good exactly once.
* **the comparison is `hmac.compare_digest`.** A `==` on the code leaks, through timing, how
  many leading digits were right, and six digits guessed one at a time is not six digits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

# The defaults every authenticator app assumes. They are parameters in the URI because the
# standard allows others; in practice an app that is handed anything else tends to ignore it,
# so the panel offers no way to change them and this is where they are written down.
PERIOD = 30          # seconds per step
DIGITS = 6           # length of the code
ALGORITHM = 'SHA1'   # what the apps implement; SHA256 is in the URI spec and rarely honoured
# 160 bits, which is what RFC 4226 asks for and what `otpauth://` links carry in the wild.
SECRET_BYTES = 20
# How many steps either side of now are accepted. One step = the user's clock may be half a
# minute out, which is common enough that zero tolerance reads as "the feature is broken".
# Two would be a minute and a half of validity for one code, which is the other mistake.
WINDOW = 1


def secret_new(nbytes: int = SECRET_BYTES) -> str:
    """A fresh shared secret, base32 as the authenticator apps expect it.

    From `secrets`, never `random`: this is a credential, and the difference between the two
    modules is the whole reason one of them exists.
    """
    return base64.b32encode(secrets.token_bytes(nbytes)).decode('ascii').rstrip('=')


def secret_bytes(secret: str) -> bytes:
    """A base32 secret as bytes, or `b''` when it is not one.

    Tolerant on the way in — lowercase, spaces and the groups of four that every enrolment
    screen prints — because this also parses what somebody typed by hand off a screen. Strict
    on the way out: anything that is not base32 answers empty rather than raising, and an
    empty secret verifies nothing.
    """
    text = ''.join(str(secret or '').split()).upper()
    if not text:
        return b''
    text += '=' * (-len(text) % 8)          # base32 wants a multiple of eight
    try:
        return base64.b32decode(text, casefold=True)
    except Exception:      # pylint: disable=broad-except
        return b''


def current_step(now: float | None = None, period: int = PERIOD) -> int:
    """Which time step *now* falls in — the counter RFC 6238 feeds to HOTP."""
    return int((time.time() if now is None else float(now)) // max(1, int(period)))


def code_at(secret: str, step: int, digits: int = DIGITS) -> str:
    """The code for one step, zero-padded — HOTP (RFC 4226) over the step counter.

    Empty for a secret that is not base32: a caller comparing against `''` fails closed,
    which is the direction a wrong answer here has to fail in.
    """
    key = secret_bytes(secret)
    if not key:
        return ''
    mac = hmac.new(key, struct.pack('>Q', max(0, int(step))), hashlib.sha1).digest()
    # Dynamic truncation: the low nibble of the last byte picks where to read the four bytes
    # from, and the top bit is masked off so the result is the same on every platform's idea
    # of a signed integer.
    offset = mac[-1] & 0x0F
    trunc = struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(trunc % (10 ** digits)).zfill(digits)


def verify(secret: str, code: str, *, now: float | None = None, period: int = PERIOD,
           digits: int = DIGITS, window: int = WINDOW, after_step: int = -1):
    """The step *code* matched, or `None`.

    The step and not a boolean, because a code that has been used must not work again: the
    caller stores what came back and passes it as *after_step* next time. Thirty seconds is a
    long time to hold somebody else's code.

    Every candidate step is checked even after one matches. A loop that returns early takes
    less time when the match is in the first step than in the last, and that difference is a
    clock the caller does not control — the same reason the digits are compared with
    `compare_digest` rather than `==`.
    """
    key = secret_bytes(secret)
    got = ''.join(str(code or '').split())
    if not key or not got.isdigit() or len(got) != int(digits):
        return None
    here = current_step(now, period)
    found = None
    for step in range(here - int(window), here + int(window) + 1):
        if step <= int(after_step):
            # Already used, or older than one that was. Not a match, and not a shortcut
            # either: the loop runs to the end whatever happens.
            continue
        if hmac.compare_digest(code_at(secret, step, digits), got) and found is None:
            found = step
    return found


def provisioning_uri(secret: str, account: str, issuer: str,
                     digits: int = DIGITS, period: int = PERIOD) -> str:
    """The `otpauth://totp/…` link an authenticator app reads out of a QR code.

    The issuer appears twice on purpose — once in the label prefix and once as a parameter.
    The parameter is the one the specification defines; the prefix is what the apps that
    predate it read, and an entry that shows up as a bare username among forty others is the
    complaint that follows.

    Every part is percent-encoded, including the separating colon, because an account name is
    an email address as often as not and `@` and `:` in a path segment are how the link
    arrives at the phone truncated.
    """
    if not secret or not account:
        return ''
    label = urllib.parse.quote(f'{issuer}:{account}' if issuer else str(account), safe='')
    params = {'secret': str(secret), 'algorithm': ALGORITHM,
              'digits': str(int(digits)), 'period': str(int(period))}
    if issuer:
        params['issuer'] = str(issuer)
    return f'otpauth://totp/{label}?' + urllib.parse.urlencode(params)


def secret_groups(secret: str, size: int = 4) -> str:
    """A secret in groups of four, which is how it is read off a screen and typed into a phone.

    The only reason this exists: thirty-two unbroken base32 characters get mistyped, and the
    person doing it has already decided the QR code did not work.
    """
    text = str(secret or '')
    return ' '.join(text[i:i + size] for i in range(0, len(text), size))
