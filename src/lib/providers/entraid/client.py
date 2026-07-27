#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared foundation for the Microsoft Graph client submodules — endpoints,
well-known ids and error formatting.  No HTTP itself."""

from __future__ import annotations

import json as _json

from lib.providers.entraid.declarations import (  # noqa: F401  (re-exported)
    DEFAULT_APP_NAME, GRAPH_APP_ID, OIDC_APP_NAME, SAML2_APP_NAME, SCIM_APP_NAME)

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
AUTHORITY = 'https://login.microsoftonline.com'
# App-only (client-credentials) audience for Graph.  Azure Resource Manager is a
# DIFFERENT audience (see lib.providers.azure.arm): a Graph token is rejected by ARM
# and vice versa, which is the single most common way these integrations fail.
GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
# Azure PowerShell — a well-known public client valid for the Device Code Flow.
DCF_CLIENT_ID = '1950a258-227b-4e31-a9cf-717495945fc2'
# Microsoft Graph Command Line Tools — the modern device-code public client
# (used by Connect-MgGraph). Preauthorized for a broad set of Graph delegated
# scopes that Azure PowerShell is NOT (e.g. Synchronization.ReadWrite.All, needed
# for SCIM provisioning). Azure PowerShell → AADSTS65002 on those scopes.
GRAPH_CLI_CLIENT_ID = '14d82eec-204b-4c2f-b7e8-296a70dab67e'
# Delegated sign-in scope the device-code app-registration flow needs.
PROVISION_SCOPE = ('https://graph.microsoft.com/Application.ReadWrite.All '
                   'https://graph.microsoft.com/AppRoleAssignment.ReadWrite.All')
# SCIM provisioning also needs to create/configure the synchronization job + secrets.
SCIM_PROVISION_SCOPE = ('https://graph.microsoft.com/Application.ReadWrite.All '
                        'https://graph.microsoft.com/Synchronization.ReadWrite.All')
# The generic ("customappsso") non-gallery application template — instantiating it
# creates an app + service principal that supports a SCIM synchronization job.
CUSTOM_APP_TEMPLATE = '8adf8e6e-67b2-4cf2-a259-e3dc5476c621'
GROUP_READ_ALL = '5b567255-7703-4780-807c-7be8301ae99b'   # Graph app role id
#: The application permissions every SSO app (OIDC and SAML2) is registered with, by NAME.
#: The id above is what a grant is written with; the name is what a token's ``roles`` claim
#: carries, which is what a permission check can actually read. Both spellings of the same
#: permission live here so the register button and the check button cannot drift apart.
SSO_APP_ROLES = ('Group.Read.All',)


class EntraApiError(Exception):
    """A Microsoft API failure carrying the HTTP status code (0 = connection error).

    One exception for every Microsoft surface reached with an Entra token — Graph and
    Azure Resource Manager alike.  The ``code`` is what callers branch on (403 means a
    missing permission, 404 a wrong path), and ``msg`` is the message the service gave,
    already extracted by :func:`api_error`.
    """

    def __init__(self, code: int, msg: str = ''):
        self.code = code
        self.msg = msg
        super().__init__(f'HTTP {code}: {msg}' if code else (msg or 'connection error'))


def api_error(body: str) -> str:
    """Best-effort human message out of a raw Microsoft error body.

    Covers the three shapes these APIs answer with, because a caller cannot know in
    advance which one it will get:

    * Graph — ``{"error": {"message": "...", "code": "..."}}``
    * Azure Resource Manager — the same envelope, but the useful text is sometimes only
      in ``code`` (``AuthorizationFailed``), so fall back to it rather than to nothing.
    * The login/token endpoint — ``{"error": "invalid_client", "error_description":
      "AADSTS7000215: ..."}``, where ``error`` is a bare code string and the real reason
      is in ``error_description``.

    Handling all three is what turns a useless "HTTP 400: Bad Request" into the actual
    AADSTS reason.  Takes the raw body (not a ``requests`` response) so the urllib-based
    monitor side can use it too — see :func:`graph_error` for the response-object form.

    A body that is not JSON gives ``''`` rather than a snippet of itself: callers fall
    back to the HTTP reason, which beats pasting a proxy's HTML error page into an alert.
    """
    try:
        data = _json.loads(body or '{}') or {}
    except (ValueError, TypeError):
        return ''
    if not isinstance(data, dict):
        return ''
    err = data.get('error')
    if isinstance(err, dict):
        return str(err.get('message') or err.get('code') or '')[:200]
    return str(data.get('error_description') or err or '')[:200]


def graph_error(r) -> str:
    """Best-effort human message from a failed Graph response (``requests`` object).

    The web side works with response objects; :func:`api_error` is the same idea for a
    raw body, which is what the urllib-based monitor side has.
    """
    try:
        return ((r.json().get('error') or {}).get('message') or r.text) if r.content else r.reason
    except Exception:  # pylint: disable=broad-except
        return getattr(r, 'reason', '') or 'Graph error'
