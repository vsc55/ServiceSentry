#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where a second factor lives — its own tables, deliberately not the user record.

The obvious place is the users table's ``extra`` JSON column, and it is the wrong one:
:mod:`lib.core.users.store` merges that blob into the user dict it returns, and that dict is
what the users API serialises. A TOTP secret in there is a secret one ``GET /api/v1/users``
away from everybody with ``users_view``. So: its own tables, and nothing here ever hands a
secret back to a caller that did not ask for it by name.

The secret is encrypted at rest with the same value-level Fernet the credentials store uses
(:mod:`lib.security.secret_manager`, ``enc:`` prefix), keyed from ``SS_SECRET_KEY`` or the key
file. A shared database with a per-process key would make every OTHER process unable to verify
— which is the same constraint sessions already live under, and the reason that key is pinned.

Schema::

    mfa_factors(uid PK, user_uid, method, secret, confirmed, last_step, label,
                credential_id, public_key, alg, sign_count, created, updated)
    mfa_recovery(uid PK, user_uid, code_hash, used_at, created)

Two tables and not one column, because a user may end up with a TOTP app AND a security key —
``method`` is what tells them apart, and it was there from the first commit for exactly this.
The four WebAuthn columns are their own and do not reuse ``secret``: a public key is not a
secret, and putting it there would make enrolling a security key fail on an install with no
encryption key, for a value that has nothing to protect.

``last_step`` is the anti-replay counter and the reason this is a store rather than a cache: a
code lives thirty seconds, and "already used" has to hold across processes. Two web replicas
with a local counter each would accept the same code twice.
"""

from __future__ import annotations

import uuid

from lib.db import BaseConnector
from lib.db.schema import Column, Index, TableSpec
from lib.db.store_base import BaseStore
from lib.security import secret_manager

_FACTORS = TableSpec(
    name='mfa_factors',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        Column('user_uid',  'TEXT', nullable=False, default="''"),
        Column('method',    'TEXT', nullable=False, default="'totp'"),
        # Encrypted at rest. Never selected by the listing queries — only `factor()` reads it,
        # and only the verifier calls that.
        Column('secret',    'TEXT', nullable=False, default="''"),
        # An enrolment that was started and never proved. It exists so the QR can be shown
        # before the code is typed; it grants nothing until a code verifies against it.
        Column('confirmed', 'INTEGER', nullable=False, default='0'),
        # The last time step accepted, so a code cannot be replayed inside its own window.
        Column('last_step', 'INTEGER', nullable=False, default='-1'),
        Column('label',     'TEXT', nullable=False, default="''"),
        # ── WebAuthn only ────────────────────────────────────────────────────
        # The credential the browser will present, base64url. Its own column and not the
        # `secret` one: a public key is not a secret, and putting it there would make
        # enrolling a security key fail on an install with no encryption key — for a value
        # that has nothing to protect.
        Column('credential_id', 'TEXT', nullable=False, default="''"),
        # The COSE key exactly as the authenticator sent it, base64url of the CBOR. Kept in
        # the form it arrived in rather than unpacked into columns: it is re-parsed by the
        # decoder that is tested against the standard, so there is one representation and no
        # second place that can disagree about what the key is.
        Column('public_key',    'TEXT', nullable=False, default="''"),
        # Recorded at REGISTRATION and used for every assertion after it. A key that names
        # its own algorithm when the assertion arrives is the JWT `alg` flaw in other words.
        Column('alg',           'INTEGER', nullable=False, default='0'),
        # The authenticator's own counter. Zero means it keeps none, which is allowed.
        Column('sign_count',    'INTEGER', nullable=False, default='0'),
        Column('created',   'TEXT', nullable=False, default="''"),
        Column('updated',   'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_mfa_factors_user', ('user_uid',)),),
)

_RECOVERY = TableSpec(
    name='mfa_recovery',
    columns=(
        Column('uid',       'TEXT', primary_key=True),
        Column('user_uid',  'TEXT', nullable=False, default="''"),
        # HASHED, not encrypted: nothing ever needs to read a recovery code back, only to
        # check one. The same password hasher the accounts use, so the cost factor moves with
        # it instead of being a second decision nobody revisits.
        Column('code_hash', 'TEXT', nullable=False, default="''"),
        Column('used_at',   'TEXT', nullable=False, default="''"),
        Column('created',   'TEXT', nullable=False, default="''"),
    ),
    indexes=(Index('idx_mfa_recovery_user', ('user_uid',)),),
)

_F = _FACTORS.name
_R = _RECOVERY.name


class MfaStore(BaseStore):
    """Second-factor enrolments and their recovery codes (backend-agnostic)."""

    _TABLE = _F

    def __init__(self, db: BaseConnector, *, fernet=None) -> None:
        super().__init__(db)
        self._fernet = fernet
        self._bootstrap()

    def _bootstrap(self) -> None:
        self._db.reconcile_table(_FACTORS)
        self._db.reconcile_table(_RECOVERY)

    # ── Secrets ──────────────────────────────────────────────────────────────

    def _seal(self, secret: str) -> str:
        """Encrypt a secret for storage, or `''` when there is no key to do it with.

        Empty, and the enrolment fails — this is the one place in the project that refuses
        rather than falling back to plaintext. `encrypt_sensitive` logs and stores the clear
        value when it cannot encrypt, which is the right trade for a stored password nobody
        can use without also reaching the service it belongs to. A TOTP seed is not that: it
        is a generator, and somebody who reads one out of a database produces valid codes for
        that account for as long as the factor exists, with nothing to notice and nothing to
        rotate. `cryptography` is in the lock, so this is the diagnostics page's
        `diag_feat_secrets` saying no on an install that stripped it out.
        """
        if self._fernet is None:
            return ''
        out = secret_manager.encrypt_sensitive({'secret': str(secret or '')}, self._fernet,
                                               keys=frozenset({'secret'}))
        sealed = str((out or {}).get('secret') or '')
        return sealed if sealed.startswith(secret_manager.ENC_PREFIX) else ''

    def _open(self, stored: str) -> str:
        return str((secret_manager.decrypt_all({'secret': str(stored or '')},
                                               self._fernet) or {}).get('secret') or '')

    # ── Read ─────────────────────────────────────────────────────────────────

    def factor(self, user_uid: str, *, method: str = 'totp', decrypt: bool = False) -> dict | None:
        """One user's factor, secret included only when asked for.

        `decrypt` defaults to False and every caller that does not verify a code leaves it
        that way: the enrolment screen, the users list and the audit trail all need to know
        that a factor EXISTS, and none of them needs what it is.
        """
        row = self._db.fetchone(
            'SELECT uid, user_uid, method, secret, confirmed, last_step, label, created,'
            f' updated, credential_id, public_key, alg, sign_count FROM {_F}'
            ' WHERE user_uid = ? AND method = ?', (str(user_uid or ''), str(method)))
        if not row:
            return None
        return {'uid': row[0], 'user_uid': row[1], 'method': row[2],
                'secret': self._open(row[3]) if decrypt else '',
                'confirmed': bool(row[4]), 'last_step': int(row[5] if row[5] is not None else -1),
                'label': row[6] or '', 'created': row[7] or '', 'updated': row[8] or '',
                'credential_id': row[9] or '', 'public_key': row[10] or '',
                'alg': int(row[11] or 0), 'sign_count': int(row[12] or 0)}

    def enrolled_user_uids(self, *, confirmed_only: bool = True) -> set:
        """Every user with a factor — one query, because the users list draws a column from it.

        A row per user asked one at a time is the shape that turns a page of forty accounts
        into forty round trips.
        """
        sql = f'SELECT DISTINCT user_uid FROM {_F}'
        if confirmed_only:
            sql += ' WHERE confirmed = 1'
        return {r[0] for r in self._db.fetchall(sql) if r[0]}

    def recovery_left(self, user_uid: str) -> int:
        """How many unused recovery codes remain — the number `/account` shows."""
        row = self._db.fetchone(
            f"SELECT COUNT(*) FROM {_R} WHERE user_uid = ? AND used_at = ''",
            (str(user_uid or ''),))
        return int(row[0]) if row else 0

    def recovery_unused(self, user_uid: str) -> list:
        """`[(uid, code_hash)]` for the codes still available. Hashes, so the caller compares
        rather than reads: nothing in this system can turn one back into a code."""
        return [(r[0], r[1]) for r in self._db.fetchall(
            f"SELECT uid, code_hash FROM {_R} WHERE user_uid = ? AND used_at = ''",
            (str(user_uid or ''),))]

    # ── Write ────────────────────────────────────────────────────────────────

    def begin(self, user_uid: str, secret: str, *, method: str = 'totp', label: str = '') -> str:
        """Start (or restart) an enrolment. Returns the factor uid.

        Restarting replaces whatever was pending: somebody who closed the page halfway and
        came back must get a fresh secret, not the one that may be sitting in a screenshot.
        A CONFIRMED factor is replaced too — the caller is responsible for having asked for a
        password or a current code first, which is a decision that belongs at the route.
        """
        sealed = self._seal(secret)
        if not sealed:
            return ''          # no key, no enrolment — see `_seal`
        uid, now = str(uuid.uuid4()), self._now()
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_F} WHERE user_uid = ? AND method = ?',
                                 (str(user_uid or ''), str(method)))
                self._db.execute(
                    f'INSERT INTO {_F}(uid, user_uid, method, secret, confirmed, last_step,'
                    ' label, created, updated) VALUES(?,?,?,?,?,?,?,?,?)',
                    (uid, str(user_uid or ''), str(method), sealed, 0, -1,
                     str(label or ''), now, now))
            return uid
        except Exception:      # pylint: disable=broad-except
            return ''

    def confirm(self, user_uid: str, step: int, *, method: str = 'totp') -> bool:
        """Switch a pending factor on, recording the step that proved it.

        The step goes in with the confirmation and not afterwards: the code that enrolled the
        factor is a used code, and leaving it valid for the rest of its window would make the
        very first thing a new factor does be accept a replay.
        """
        try:
            with self._db.transaction():
                changed = self._db.execute(
                    f'UPDATE {_F} SET confirmed = 1, last_step = ?, updated = ?'
                    ' WHERE user_uid = ? AND method = ?',
                    (int(step), self._now(), str(user_uid or ''), str(method)))
            return changed > 0
        except Exception:      # pylint: disable=broad-except
            return False

    def note_step(self, user_uid: str, step: int, *, method: str = 'totp') -> bool:
        """Record the step a code was accepted at, so it and everything before it are spent.

        Monotonic on purpose (`last_step = max(...)`): two requests racing on the same account
        must not let the later one lower the bar back down for the earlier.
        """
        try:
            with self._db.transaction():
                changed = self._db.execute(
                    f'UPDATE {_F} SET last_step = ?, updated = ?'
                    ' WHERE user_uid = ? AND method = ? AND last_step < ?',
                    (int(step), self._now(), str(user_uid or ''), str(method), int(step)))
            return changed > 0
        except Exception:      # pylint: disable=broad-except
            return False

    def delete(self, user_uid: str, *, method: str = '') -> bool:
        """Remove a user's factor(s) and every recovery code with them.

        Together, in one transaction: a factor without its codes is an account somebody can
        still get into with a code that no longer opens anything, and codes without a factor
        are a second door left standing after the first was taken off.
        """
        who = str(user_uid or '')
        if not who:
            return False
        try:
            with self._db.transaction():
                if method:
                    gone = self._db.execute(
                        f'DELETE FROM {_F} WHERE user_uid = ? AND method = ?', (who, str(method)))
                else:
                    gone = self._db.execute(f'DELETE FROM {_F} WHERE user_uid = ?', (who,))
                if not self._db.fetchone(f'SELECT 1 FROM {_F} WHERE user_uid = ?', (who,)):
                    self._db.execute(f'DELETE FROM {_R} WHERE user_uid = ?', (who,))
            return gone > 0
        except Exception:      # pylint: disable=broad-except
            return False

    def set_recovery(self, user_uid: str, code_hashes) -> bool:
        """Replace a user's recovery codes with a fresh set.

        Replace, never append: regenerating is what somebody does when they think the old list
        leaked, and a set that grew would leave the leaked half working.
        """
        who, now = str(user_uid or ''), self._now()
        try:
            with self._db.transaction():
                self._db.execute(f'DELETE FROM {_R} WHERE user_uid = ?', (who,))
                for code_hash in code_hashes:
                    self._db.execute(
                        f'INSERT INTO {_R}(uid, user_uid, code_hash, used_at, created)'
                        ' VALUES(?,?,?,?,?)',
                        (str(uuid.uuid4()), who, str(code_hash), '', now))
            return True
        except Exception:      # pylint: disable=broad-except
            return False

    def consume_recovery(self, uid: str) -> bool:
        """Spend one recovery code. False when it was already spent — which is the check.

        The `used_at = ''` in the WHERE clause is what makes this safe under a race: two
        requests presenting the same code both find it unused, and exactly one UPDATE changes
        a row.
        """
        try:
            with self._db.transaction():
                changed = self._db.execute(
                    f"UPDATE {_R} SET used_at = ? WHERE uid = ? AND used_at = ''",
                    (self._now(), str(uid or '')))
            return changed > 0
        except Exception:      # pylint: disable=broad-except
            return False

    # ── WebAuthn ─────────────────────────────────────────────────────────────

    def save_credential(self, user_uid: str, *, credential_id: str, public_key: str,
                        alg: int, sign_count: int, label: str = '') -> bool:
        """Store a registered security key, replacing whatever was there.

        Confirmed on arrival, unlike a TOTP enrolment: the ceremony IS the proof. A registration
        response that verified was signed by the authenticator over a challenge this server
        issued, so there is nothing left for a second step to establish.
        """
        who, now = str(user_uid or ''), self._now()
        if not who or not credential_id or not public_key:
            return False
        try:
            with self._db.transaction():
                self._db.execute(f"DELETE FROM {_F} WHERE user_uid = ? AND method = 'webauthn'",
                                 (who,))
                self._db.execute(
                    f'INSERT INTO {_F}(uid, user_uid, method, secret, confirmed, last_step,'
                    ' label, created, updated, credential_id, public_key, alg, sign_count)'
                    " VALUES(?,?,'webauthn','',1,-1,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), who, str(label or ''), now, now,
                     str(credential_id), str(public_key), int(alg), int(sign_count)))
            return True
        except Exception:      # pylint: disable=broad-except
            return False

    def note_sign_count(self, user_uid: str, count: int) -> bool:
        """Move the authenticator's counter forward.

        Monotonic in the SQL (`sign_count < ?`), the same way `note_step` is: two assertions
        racing must not let the later one lower the bar for the earlier, which is precisely
        the state a cloned authenticator would try to produce.
        """
        try:
            with self._db.transaction():
                changed = self._db.execute(
                    f'UPDATE {_F} SET sign_count = ?, updated = ?'
                    " WHERE user_uid = ? AND method = 'webauthn' AND sign_count < ?",
                    (int(count), self._now(), str(user_uid or ''), int(count)))
            return changed > 0
        except Exception:      # pylint: disable=broad-except
            return False

    def methods_of(self, user_uid: str) -> list:
        """Which kinds of factor this account has, confirmed. Ordered, so the screen is."""
        rows = self._db.fetchall(
            f'SELECT method FROM {_F} WHERE user_uid = ? AND confirmed = 1 ORDER BY method',
            (str(user_uid or ''),))
        return [r[0] for r in rows if r[0]]
