#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inbound Bot Framework messaging endpoint logic for Teams proactive messaging.

Teams (via the Bot Connector) POSTs an *Activity* to the bot's public messaging
endpoint whenever a user interacts with it.  We use that to **capture the
conversation reference** so alerts can later be pushed 1:1 (see
:mod:`lib.core.notify.msteams.bot_store`).

Security: the endpoint is public, so every request MUST carry a valid Bot Framework
JWT (issuer ``https://api.botframework.com``, audience == the bot's app id).  That
validation needs **PyJWT** (optional dependency); when it is not installed we refuse
to process the request (the route returns HTTP 501) rather than trust it blindly.
"""

from __future__ import annotations

try:
    import jwt as _jwt                      # PyJWT
    from jwt import PyJWKClient as _PyJWKClient
    _HAS_JWT = True
except Exception:  # pylint: disable=broad-except
    _HAS_JWT = False

_BF_ISSUER = 'https://api.botframework.com'
_BF_OPENID = 'https://login.botframework.com/v1/.well-known/keys'


class BotValidationUnavailable(RuntimeError):
    """Raised when the Bot Framework JWT cannot be validated (PyJWT missing)."""


def validation_available() -> bool:
    return _HAS_JWT


def validate_bearer(auth_header: str, expected_app_id: str) -> None:
    """Validate a Bot Framework bearer token.  Raises on any problem.

    Raises :class:`BotValidationUnavailable` when PyJWT is not installed (the caller
    must then refuse the request), or ``ValueError`` when the token is invalid."""
    if not _HAS_JWT:
        raise BotValidationUnavailable('PyJWT is required to validate the Teams bot endpoint')
    token = (auth_header or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise ValueError('missing bearer token')
    signing_key = _PyJWKClient(_BF_OPENID).get_signing_key_from_jwt(token)
    _jwt.decode(token, signing_key.key, algorithms=['RS256'],
                audience=expected_app_id, issuer=_BF_ISSUER)


def reference_from_activity(activity: dict) -> dict:
    """Extract a conversation reference from a Bot Framework Activity dict."""
    activity = activity or {}
    frm = activity.get('from') or {}
    conv = activity.get('conversation') or {}
    return {
        'service_url':     (activity.get('serviceUrl') or '').strip(),
        'conversation_id': str(conv.get('id') or ''),
        'user_id':         str(frm.get('aadObjectId') or frm.get('id') or ''),
        'upn':             str(frm.get('userPrincipalName') or activity.get('_upn') or ''),
        'name':            str(frm.get('name') or ''),
    }
