#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared foundation for the Microsoft Graph client submodules — endpoints,
well-known ids and error formatting.  No HTTP itself."""

from __future__ import annotations

from lib.providers.entraid.declarations import (  # noqa: F401  (re-exported)
    DEFAULT_APP_NAME, GRAPH_APP_ID, OIDC_APP_NAME, SAML2_APP_NAME, SCIM_APP_NAME)

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
AUTHORITY = 'https://login.microsoftonline.com'
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


def graph_error(r) -> str:
    """Best-effort human message from a failed Graph response."""
    try:
        return ((r.json().get('error') or {}).get('message') or r.text) if r.content else r.reason
    except Exception:  # pylint: disable=broad-except
        return getattr(r, 'reason', '') or 'Graph error'
