#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a Microsoft Teams *tab SSO* token (from ``getAuthToken`` in the Teams JS SDK).

The Teams client hands the tab a signed access token whose audience is the app's own
API (``api://<clientId>`` / ``<clientId>``).  We verify it (signature via the tenant's
JWKS, audience, issuer, expiry) and return its claims so the caller can map the AAD
identity to a ServiceSentry user and start a session.

Requires **PyJWT** (optional dependency); :func:`available` reports whether validation
can run, so the sign-in endpoint can refuse cleanly (HTTP 501) rather than trust a token
it cannot verify.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request

try:
    import jwt as _jwt                       # PyJWT
    from jwt import PyJWKClient as _PyJWKClient
    _HAS_JWT = True
except Exception:  # pylint: disable=broad-except
    _HAS_JWT = False


# Microsoft device origins that embed a Teams personal tab (Teams + the Outlook/Microsoft 365
# devices that also render Teams tabs). Declared here (Teams-specific) and registered as an
# "embed profile" so the core security layer stays provider-agnostic.
TEAMS_FRAME_ANCESTORS: tuple[str, ...] = (
    'https://teams.microsoft.com', 'https://*.teams.microsoft.com',
    'https://*.teams.microsoft.us', 'https://*.microsoft.com',
    'https://*.office.com', 'https://*.office365.com', 'https://outlook.office.com',
)


class TabSsoUnavailable(RuntimeError):
    """Raised when the Teams SSO token cannot be validated (PyJWT missing)."""


def available() -> bool:
    """Return True when PyJWT is installed, i.e. Teams tab SSO tokens can be
    validated; when False the sign-in endpoint refuses with HTTP 501."""
    return _HAS_JWT


def _jwks_uri(tenant_id: str) -> str:
    return f'https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys'


_GUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
#: Authorities that are not ONE tenant: a token from any of them proves nothing about which
#: organisation signed somebody in, so they cannot be what this installation trusts.
_MULTI_TENANT = frozenset({'common', 'organizations', 'consumers'})
_TENANT_CACHE: dict = {}
_TENANT_LOCK = threading.Lock()


def _fetch_tenant_guid(tenant: str) -> str:
    """The directory GUID behind a domain-form tenant (``contoso.onmicrosoft.com``), read from
    its OpenID discovery document — the ``issuer`` there carries it. Network; cached."""
    url = f'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration'
    with urllib.request.urlopen(url, timeout=10) as resp:     # noqa: S310 (fixed https host)
        doc = json.loads(resp.read().decode('utf-8'))
    m = re.match(r'^https://login\.microsoftonline\.com/([0-9a-fA-F-]{36})/v2\.0$',
                 str(doc.get('issuer') or ''))
    if not m:
        raise ValueError('could not resolve the tenant id')
    return m.group(1).lower()


def tenant_guid(tenant_id: str) -> str:
    """The configured tenant as its directory GUID (lower-case), or ``ValueError``.

    A token's ``tid`` claim is always the GUID; the setting may be the GUID or a domain name,
    so the domain is resolved once. A multi-tenant authority is refused outright.
    """
    t = (tenant_id or '').strip()
    if _GUID.match(t):
        return t.lower()
    if not t or t.lower() in _MULTI_TENANT:
        raise ValueError('Teams SSO needs a single tenant id, not a multi-tenant authority')
    if not re.match(r'^[A-Za-z0-9.-]+$', t):
        raise ValueError('malformed tenant id')
    key = t.lower()
    with _TENANT_LOCK:
        if key in _TENANT_CACHE:
            return _TENANT_CACHE[key]
    guid = _fetch_tenant_guid(t)
    with _TENANT_LOCK:
        _TENANT_CACHE[key] = guid
    return guid


def check_tenant(claims: dict, tenant_id: str) -> None:
    """Refuse a token that was not issued by THIS tenant (``ValueError``).

    The signature cannot say it: Microsoft signs every tenant's tokens with the same keys, so
    a valid signature, our audience and *a* Microsoft issuer is what a token from ANY
    organisation looks like the moment the app registration is multi-tenant. The ``tid`` claim
    must be ours, and the issuer must be ours exactly — v2 or v1 form.
    """
    want = tenant_guid(tenant_id)
    tid = str((claims or {}).get('tid') or '').strip().lower()
    if tid != want:
        raise ValueError('token issued by another tenant')
    iss = str((claims or {}).get('iss') or '').strip().lower()
    if iss not in (f'https://login.microsoftonline.com/{want}/v2.0',
                   f'https://sts.windows.net/{want}/'):
        raise ValueError('unexpected token issuer')


def validate_tab_token(token: str, tenant_id: str, client_id: str) -> dict:
    """Validate a Teams tab SSO access token and return its claims.

    Raises :class:`TabSsoUnavailable` (PyJWT missing), ``ValueError`` (not configured or
    invalid token), or a ``jwt`` exception on a verification failure."""
    if not _HAS_JWT:
        raise TabSsoUnavailable('PyJWT is required to validate Teams SSO tokens')
    tenant_id = (tenant_id or '').strip()
    client_id = (client_id or '').strip()
    if not (tenant_id and client_id):
        raise ValueError('Teams SSO is not configured (tenant id / client id missing)')
    token = (token or '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise ValueError('missing token')
    signing_key = _PyJWKClient(_jwks_uri(tenant_id)).get_signing_key_from_jwt(token)
    # The token audience is the app's App ID URI or the bare client id; accept either.
    claims = _jwt.decode(
        token, signing_key.key, algorithms=['RS256'],
        audience=[f'api://{client_id}', client_id],
        options={'verify_iss': False})   # issuer checked below (tenant may be domain or GUID)
    check_tenant(claims, tenant_id)
    return claims
