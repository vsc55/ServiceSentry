#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Symmetric encryption for sensitive config values.

Values are stored as ``enc:<fernet-token>`` in JSON files.  Everything else
is passed through unchanged, so the module is safe to use on files that were
written before encryption was introduced.
"""

import base64
import binascii
from typing import Any

__all__ = ['ENCRYPT_KEYS', 'fernet_from_secret_file', 'decrypt_all', 'encrypt_sensitive']

ENC_PREFIX = 'enc:'

# Field names whose values are encrypted when written to disk.
ENCRYPT_KEYS: frozenset[str] = frozenset({'password', 'ssh_password', 'token', 'secret'})


def fernet_from_secret_file(path: str):
    """Return a ``Fernet`` instance derived from the hex secret at *path*.

    The first 32 bytes of the decoded hex string are used as the raw key
    material, matching the existing ``.flask_secret`` format (64 hex chars
    = 32 bytes = 256 bits).

    Returns ``None`` if the file is missing, unreadable, or the
    ``cryptography`` package is not installed.
    """
    try:
        from cryptography.fernet import Fernet
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
    non-string values are left untouched.  Decryption failures are silently
    ignored (the original ``enc:...`` string is kept).
    """
    if isinstance(data, dict):
        for k in data:
            data[k] = decrypt_all(data[k], fernet)
    elif isinstance(data, list):
        for i in range(len(data)):
            data[i] = decrypt_all(data[i], fernet)
    elif isinstance(data, str) and data.startswith(ENC_PREFIX):
        try:
            return fernet.decrypt(data[len(ENC_PREFIX):].encode()).decode('utf-8')
        except Exception:
            pass
    return data


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
        except Exception:
            pass
    return data
