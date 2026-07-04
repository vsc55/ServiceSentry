#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared foundation for the Microsoft Graph client submodules — endpoints,
well-known ids and error formatting.  No HTTP itself."""

from __future__ import annotations

from lib.providers.entraid.declarations import (  # noqa: F401  (re-exported)
    DEFAULT_APP_NAME, GRAPH_APP_ID, OIDC_APP_NAME, SAML2_APP_NAME)

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
AUTHORITY = 'https://login.microsoftonline.com'
# Azure PowerShell — a well-known public client valid for the Device Code Flow.
DCF_CLIENT_ID = '1950a258-227b-4e31-a9cf-717495945fc2'
# Delegated sign-in scope the device-code app-registration flow needs.
PROVISION_SCOPE = ('https://graph.microsoft.com/Application.ReadWrite.All '
                   'https://graph.microsoft.com/AppRoleAssignment.ReadWrite.All')
GROUP_READ_ALL = '5b567255-7703-4780-807c-7be8301ae99b'   # Graph app role id


def graph_error(r) -> str:
    """Best-effort human message from a failed Graph response."""
    try:
        return ((r.json().get('error') or {}).get('message') or r.text) if r.content else r.reason
    except Exception:  # pylint: disable=broad-except
        return getattr(r, 'reason', '') or 'Graph error'
