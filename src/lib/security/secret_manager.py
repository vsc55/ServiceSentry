#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Symmetric encryption for sensitive config values.

Values are stored as ``enc:<fernet-token>`` in JSON files.  Everything else
is passed through unchanged, so the module is safe to use on files that were
written before encryption was introduced.
"""

import base64
import binascii
import logging
from typing import Any

# Stdlib logging, like lib/db/base.py: this module is deliberately dependency-light
# (no lib.debug, no config) so anything may import it.
_log = logging.getLogger(__name__)

# Latched so the warning below is emitted ONCE per process.  decrypt_all runs on every
# read of every store; a line per failed value would bury the signal it exists to give.
_decrypt_failure_reported = False

__all__ = ['ENCRYPT_KEYS', 'fernet_from_secret_file', 'decrypt_all', 'encrypt_sensitive',
           'mask_sensitive', 'restore_sensitive']

ENC_PREFIX = 'enc:'

# Core secret field names — values encrypted when written to disk.
# These belong to *core* features (auth providers, notifications).  Secret
# fields declared by watchful MODULES are NOT listed here: the core discovers
# them dynamically from each module's schema (``"secret"``/``"sensitive"``
# flags) so modules stay 100% independent of core.  Callers pass an augmented
# key set via the ``keys=`` parameter of the functions below.
ENCRYPT_KEYS: frozenset[str] = frozenset({
    'password', 'ssh_password', 'token', 'secret',
    'bind_password',        # LDAP service-account password
    'client_secret',        # OIDC client secret
    'sp_key',               # SAML2 SP private key
    'graph_secret',         # SAML2 → Microsoft Graph client secret (group→role lookups)
    'idp_cert',             # SAML2 IdP signing certificate (masked from the UI once set)
    'smtp_password',        # Email SMTP password
    'ms365_client_secret',  # Email Microsoft 365 client secret
    'gmail_client_secret',  # Email Gmail client secret
    'gmail_refresh_token',  # Email Gmail refresh token
    'webhook_url',          # Teams channel Incoming Webhook URL (embeds a secret token)
    'bot_app_password',     # Teams Bot Framework app password/secret
    # GitHub personal token for MIB imports. A core secret since the setting became one:
    # it used to be encrypted because the SNMP module declared it `secret` in its schema,
    # and a module's declaration stops applying the moment the setting leaves the module.
    'github_token',
})


def fernet_from_secret_file(path: str):
    """Return a ``Fernet`` instance derived from the hex secret at *path*.

    ``SS_SECRET_KEY`` wins when set: it is how every process sharing a database is given
    the SAME key (a pod per role has no shared volume to keep the file in). The file stays
    the fallback, so an existing install is untouched.

    The first 32 bytes of the decoded hex string are used as the raw key material,
    matching the existing ``.flask_secret`` format (64 hex chars = 32 bytes = 256 bits).

    Returns ``None`` if the file is missing, unreadable, or the ``cryptography`` package is
    not installed — but a MALFORMED ``SS_SECRET_KEY`` raises instead of falling back: the
    fallback would encrypt with a key the operator did not choose and never say so.
    """
    # Imported here, not at module scope: lib.config.manager imports THIS module, so a
    # top-level import would close the cycle.
    from lib.config import secret_key_from_env       # noqa: PLC0415
    hex_secret = secret_key_from_env()          # raises on a set-but-malformed value
    try:
        from cryptography.fernet import Fernet
        if not hex_secret:
            with open(path, encoding='utf-8') as fh:
                hex_secret = fh.read().strip()
        raw = binascii.unhexlify(hex_secret)[:32]
        return Fernet(base64.urlsafe_b64encode(raw))
    except Exception:
        return None


def decrypt_all(data: Any, fernet) -> Any:
    """Recursively decrypt every ``enc:``-prefixed string in *data*.

    Dicts and lists are modified **in-place**; the function also returns
    *data* so it can be used in an assignment.  Non-encrypted strings and
    non-string values are left untouched.

    A value that fails to decrypt keeps its original ``enc:...`` string.  That is the
    right fallback — there is no plaintext to fall back to, and raising here would take
    down every page that reads a store — but it is **logged once per process**, because
    the usual cause is a wrong key (the secret file regenerated, a container rebuilt, a
    restore without it), and then *every* secret fails at once.  Without that line the
    operator sees each LDAP bind, SSH check and API credential fail to authenticate with
    no hint that one key file explains all of them.
    """
    global _decrypt_failure_reported  # noqa: PLW0603  (one-shot latch, see module top)
    if isinstance(data, dict):
        for k in data:
            data[k] = decrypt_all(data[k], fernet)
    elif isinstance(data, list):
        for i in range(len(data)):
            data[i] = decrypt_all(data[i], fernet)
    elif isinstance(data, str) and data.startswith(ENC_PREFIX):
        try:
            return fernet.decrypt(data[len(ENC_PREFIX):].encode()).decode('utf-8')
        except Exception:  # pylint: disable=broad-except  (any failure → keep the token)
            if not _decrypt_failure_reported:
                _decrypt_failure_reported = True
                _log.warning(
                    'Could not decrypt a stored secret — the encryption key does not match '
                    'the data. Every encrypted value will stay unusable until the original '
                    'key file is restored; expect authentication failures across LDAP, SSH '
                    'and API credentials until then. (Reported once per process.)')
    return data


def mask_sensitive(data: Any, keys: frozenset = ENCRYPT_KEYS) -> Any:
    """Return a copy of *data* with sensitive field values replaced by ``None``.

    ``None`` serialises to JSON ``null``, which the frontend treats as
    "value is set on the server but not transmitted to the client".
    Empty strings and ``None`` values are left as-is (not yet set).
    """
    if isinstance(data, dict):
        return {k: (None if (k in keys and v) else mask_sensitive(v, keys))
                for k, v in data.items()}
    if isinstance(data, list):
        return [mask_sensitive(item, keys) for item in data]
    return data


def restore_sensitive(new_data: "dict | list", old_data: "dict | list",
                      keys: frozenset = ENCRYPT_KEYS) -> None:
    """In-place: restore sensitive fields that are ``None`` or ``''`` in
    *new_data* by copying the existing value from *old_data*.

    Called before saving submitted data so that the client's omission of a
    sensitive value (represented as ``null`` / empty string) does not erase
    the stored secret.
    """
    # Lists: restore element-wise against the matching old element (by index), mirroring
    # mask_sensitive which recurses into lists too — otherwise a secret nested inside a
    # list of dicts is masked on read but never restored, silently erasing it on save.
    # NB: pairing is POSITIONAL — a caller must not reorder/insert/delete elements of a list
    # whose secrets are still masked, or a masked secret would be restored from the wrong
    # element. (No current schema stores secrets in a list; this is a safety net.)
    if isinstance(new_data, list):
        for i, nv in enumerate(new_data):
            if isinstance(nv, (dict, list)):
                ov = old_data[i] if isinstance(old_data, list) and i < len(old_data) else None
                restore_sensitive(nv, ov, keys)
        return
    if not isinstance(old_data, dict):
        return
    for k in list(new_data.keys()):
        nv = new_data[k]
        ov = old_data.get(k)
        if isinstance(nv, dict):
            restore_sensitive(nv, ov if isinstance(ov, dict) else {}, keys)
        elif isinstance(nv, list):
            restore_sensitive(nv, ov if isinstance(ov, list) else [], keys)
        elif k in keys and (nv is None or nv == '') and ov:
            new_data[k] = ov


def encrypt_sensitive(data: Any, fernet,
                      keys: frozenset = ENCRYPT_KEYS,
                      _cur_key: str | None = None) -> Any:
    """Return *data* with values at sensitive key names encrypted.

    A **new** dict / list is returned for every container; scalars are
    returned as-is or replaced with their ``enc:``-prefixed ciphertext.
    Values that already start with ``enc:`` are not re-encrypted.
    """
    if isinstance(data, dict):
        return {k: encrypt_sensitive(v, fernet, keys, k) for k, v in data.items()}
    if isinstance(data, list):
        return [encrypt_sensitive(item, fernet, keys, _cur_key) for item in data]
    if (isinstance(data, str) and _cur_key in keys
            and data and not data.startswith(ENC_PREFIX)):
        try:
            return ENC_PREFIX + fernet.encrypt(data.encode()).decode()
        except Exception as exc:  # pylint: disable=broad-except
            # NOT the same trade-off as decrypt_all. A failed DEcryption keeps the
            # ciphertext, which is harmless; a failed ENcryption keeps the PLAINTEXT, and
            # the caller is about to persist it — a password written to disk in the clear,
            # which is the one outcome this module exists to prevent.
            #
            # Every caller guards with `if self._fernet`, so this is not reachable today.
            # It is logged per occurrence (not latched like the decrypt warning) because
            # each one is a distinct secret exposed, and the field name is what tells the
            # operator which. The VALUE is never logged.
            _log.error('Could not encrypt the value of %r (%s) — it will be stored in '
                       'CLEAR TEXT. Rotate that secret once encryption works again.',
                       _cur_key, type(exc).__name__)
    return data
