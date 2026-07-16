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

try:
    import jwt as _jwt                       # PyJWT
    from jwt import PyJWKClient as _PyJWKClient
    _HAS_JWT = True
except Exception:  # pylint: disable=broad-except
    _HAS_JWT = False


# Microsoft host origins that embed a Teams personal tab (Teams + the Outlook/Microsoft 365
# hosts that also render Teams tabs). Declared here (Teams-specific) and registered as an
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
        options={'verify_iss': False})   # issuer checked manually (tenant may be domain or GUID)
    iss = str(claims.get('iss') or '')
    if not (iss.startswith('https://login.microsoftonline.com/')
            or iss.startswith('https://sts.windows.net/')):
        raise ValueError('unexpected token issuer')
    return claims
