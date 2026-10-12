#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""When a test may use a secret the form did not send.

A connection test (LDAP, SMTP) takes the form as it stands, unsaved changes included, and a
masked password arrives as "not sent" — so the stored one is used. That is right while the
test goes where the secret already goes. When the form points it somewhere else, the stored
secret would be handed to whatever answers there: a user allowed to press "test" but not to
read the section got the LDAP bind password in clear by pointing the test at their own
listener. So the stored secret travels only to the stored destination.
"""

from __future__ import annotations


def _same(sent, stored) -> bool:
    return str(sent if sent is not None else '').strip().lower() == \
        str(stored if stored is not None else '').strip().lower()


def stored_secret_for(data: dict, stored: dict, secret_key: str, target_keys) -> str:
    """The secret the test should use: the one sent, else the stored one only if every key
    of *target_keys* the form sent equals the stored value; otherwise ``''``."""
    data = data if isinstance(data, dict) else {}
    stored = stored if isinstance(stored, dict) else {}
    sent = data.get(secret_key)
    if sent is not None:
        return str(sent)
    for k in target_keys:
        if k in data and data[k] not in (None, '') and not _same(data[k], stored.get(k)):
            return ''
    return str(stored.get(secret_key) or '')
