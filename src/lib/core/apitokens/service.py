#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minting and checking an API token — no Flask, so it can be reasoned about on its own.

The shape is ``sst_<id>_<secret>``:

* ``sst_`` is a fixed marker. It is there so a token found in a log, a shell history or a
  commit is recognisable as one — the reason GitHub and Stripe do the same — and so a
  secret-scanning rule can be written for it.
* ``id`` is 12 hex characters, stored in clear, and turns verification into one indexed
  lookup instead of hashing the candidate against every row.
* ``secret`` is 48 hex characters — 192 bits from ``secrets.token_hex``.

Comparison is constant-time. The window is small (the id already narrowed it to one row), but
the cost of `hmac.compare_digest` is nothing and the cost of remembering to use it later is a
timing oracle nobody looks for.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

PREFIX = 'sst_'
ID_BYTES = 6           # 12 hex characters
SECRET_BYTES = 24      # 48 hex characters — 192 bits
MAX_NAME_LEN = 64
# The sentinel that means "whatever the owner can do, now and later". Stored instead of a
# materialised list on purpose: a list frozen at creation would keep granting a permission the
# account has since lost, which is the opposite of what an intersection is for.
ALL = '*'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_secret(secret: str) -> str:
    """SHA-256 of the secret half, hex.

    Not a password KDF, and the reason is the input: 192 random bits. A slow hash buys
    resistance to guessing a human-chosen secret and buys nothing here — while running on
    every API request, where slow is a denial of service anybody can trigger with garbage.
    """
    return hashlib.sha256(str(secret or '').encode('utf-8')).hexdigest()


def mint() -> tuple:
    """A new token: `(raw, token_id, token_hash)`.

    `raw` is the only time the token exists in full. Nothing stores it, and the screen shows
    it once — a token that can be read back later is a token whose database row is as good as
    the token.
    """
    token_id = secrets.token_hex(ID_BYTES)
    secret = secrets.token_hex(SECRET_BYTES)
    return f'{PREFIX}{token_id}_{secret}', token_id, hash_secret(secret)


def parse(raw: str) -> tuple:
    """`(token_id, secret)` from a presented token, or `('', '')`.

    Deliberately strict about shape before it touches the database: a value that is not a
    token of ours should cost one string check, not a query.
    """
    val = str(raw or '').strip()
    if not val.startswith(PREFIX):
        return '', ''
    rest = val[len(PREFIX):]
    token_id, _, secret = rest.partition('_')
    if not token_id or not secret:
        return '', ''
    if len(token_id) != ID_BYTES * 2 or len(secret) != SECRET_BYTES * 2:
        return '', ''
    return token_id, secret


def matches(secret: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), str(token_hash or ''))


def is_expired(expires_at: str, *, now: str = '') -> bool:
    """Whether an expiry has passed. An unreadable date counts as expired.

    Failing closed on a value nobody can parse is the only safe direction: the alternative is
    a token that lives forever because its expiry was written wrong.
    """
    raw = str(expires_at or '')
    if not raw:
        return False                       # no expiry is not an expired one
    try:
        exp = datetime.fromisoformat(raw)
    except ValueError:
        return True
    ref = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return exp <= ref


def encode_permissions(perms) -> str:
    """Store `'*'` as itself and anything else as a JSON list of flags."""
    if perms == ALL or perms == [ALL]:
        return ALL
    return json.dumps(sorted({str(p) for p in (perms or []) if str(p)}))


def decode_permissions(stored: str):
    """`'*'` or a list of flags. Anything unreadable is no permissions at all."""
    raw = str(stored or '')
    if raw == ALL:
        return ALL
    try:
        val = json.loads(raw or '[]')
    except (ValueError, TypeError):
        return []
    return [str(p) for p in val if str(p)] if isinstance(val, list) else []


def effective(stored_permissions: str, owner_permissions, *,
              unbounded: bool = False) -> frozenset:
    """What the token may actually do: its own set INTERSECTED with the owner's.

    The intersection is the whole security model. Without it a token is a standing grant that
    survives its owner being demoted — the account loses `config_edit` and the token it minted
    last year keeps writing configuration. With it, a token can never outgrow the account it
    belongs to, and taking a role away takes it away everywhere at once.

    `'*'` therefore does not mean "everything"; it means "everything the owner has", which is
    the same statement written so that it keeps being true.

    **`unbounded` is for an owner that has no permission set to intersect with** — the
    built-in `system` identity, which holds none precisely because it never passes a
    permission check. Intersecting with an empty set would make such a token able to do
    nothing at all, so its stored set applies as written. That moves the ceiling from the
    owner to the administrator who minted it (a caller may not grant what they do not hold),
    and makes revoking the only way to narrow it afterwards. `'*'` is refused there rather
    than resolved: with no owner to resolve it against it would mean "everything", forever,
    which is the one thing this whole design is built to avoid — so it fails closed.
    """
    if unbounded:
        wanted = decode_permissions(stored_permissions)
        return frozenset() if wanted == ALL else frozenset(wanted)
    owner = frozenset(owner_permissions or ())
    wanted = decode_permissions(stored_permissions)
    if wanted == ALL:
        return owner
    return frozenset(wanted) & owner


def public(row: dict, *, permissions=None) -> dict:
    """One token as the API reports it — never the hash, never the token."""
    return {
        'uid': row.get('uid', ''),
        'name': row.get('name', ''),
        'token_id': row.get('token_id', ''),
        'permissions': permissions if permissions is not None
        else decode_permissions(row.get('permissions', '[]')),
        'expires_at': row.get('expires_at', ''),
        'expired': is_expired(row.get('expires_at', '')),
        'last_used': row.get('last_used', ''),
        'revoked': bool(row.get('revoked')),
        'created': row.get('created', ''),
        'created_by': row.get('created_by', ''),
    }


def validate_name(name: str) -> str:
    """The name, trimmed — or raise-worthy emptiness reported as `''`.

    A token with no name is the one nobody dares revoke six months later, because the list
    cannot say what would break.
    """
    return str(name or '').strip()[:MAX_NAME_LEN]
