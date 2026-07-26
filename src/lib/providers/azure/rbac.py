#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Azure RBAC — subscriptions and role assignments, for the provisioning wizard.

Azure access is **not** an Entra app permission.  Reading a subscription's Service Health
needs an Azure **RBAC role assignment** on that subscription, which is an ARM operation
against a different audience (``management.azure.com``) — so it cannot ride along with the
Graph consent the wizard grants, and gets its own step.

This is the **web** side of ARM: it runs in the Flask process during the device-code
wizard and uses ``requests`` like the rest of the provisioning path.  The monitor side
reads ARM through :class:`~lib.providers.azure.arm.ArmApi` instead.
"""

from __future__ import annotations

import uuid as _uuid

import requests as _req

from lib.providers.azure.arm import (
    API_ROLE_ASSIGNMENTS, API_SUBSCRIPTIONS, ARM_BASE, ARM_SCOPE)
from lib.providers.entraid.client import AUTHORITY

# Well-known built-in role definition ids (stable across every tenant).
ARM_ROLES = {
    'reader': 'acdd72a7-3385-48ef-bd42-f606fba81ae7',
}

# Identifier of the role-assignment row in a check-permissions report.  The UI pre-draws
# that row from the same declaration and matches the answer on THIS, never on the display
# label — a label is translated and reworded, an id is not.
ROW_ID = 'azure_rbac'


def check_subscription_access(tenant: str, client_id: str, secret: str,
                              subscription_id: str) -> dict:
    """Can this app-only credential actually READ the subscription?

    Returns ``{'ok': bool, 'detail': str}``.

    This exists because inspecting the token's ``roles`` claim — which is how every
    other permission check in the product works — **cannot answer the question for
    Azure**.  That claim lists Entra *application permissions*; access to a subscription
    comes from an ARM **RBAC role assignment**, which appears nowhere in it.  A check
    built the usual way would report "all permissions granted" while every single ARM
    call 403s, which is worse than having no check at all.

    So this does the only thing that is conclusive: acquires a token for the ARM
    audience and performs a real read.  Never raises — a failure IS the answer.
    """
    sub = str(subscription_id or '').strip()
    if not (tenant and client_id and secret and sub):
        return {'ok': False, 'detail': 'tenant, client, secret and subscription are required'}
    try:
        tok = _req.post(f'{AUTHORITY}/{tenant}/oauth2/v2.0/token', timeout=20,
                        data={'grant_type': 'client_credentials', 'client_id': client_id,
                              'client_secret': secret, 'scope': ARM_SCOPE}).json()
    except Exception as exc:  # pylint: disable=broad-except
        return {'ok': False, 'detail': str(exc)[:200]}
    access = tok.get('access_token')
    if not access:
        # An ARM-audience token can be refused on its own (a disabled app, a bad secret),
        # and the AADSTS text is the whole diagnosis.
        return {'ok': False,
                'detail': str(tok.get('error_description') or tok.get('error') or 'no token')[:200]}
    try:
        r = _req.get(f'{ARM_BASE}/subscriptions/{sub}?api-version={API_SUBSCRIPTIONS}',
                     headers={'Authorization': f'Bearer {access}'}, timeout=20)
    except Exception as exc:  # pylint: disable=broad-except
        return {'ok': False, 'detail': str(exc)[:200]}
    if r.ok:
        return {'ok': True, 'detail': ''}
    detail = ''
    try:
        detail = ((r.json() or {}).get('error') or {}).get('message') or ''
    except Exception:  # pylint: disable=broad-except
        detail = (r.text or '')[:200]
    if r.status_code in (401, 403):
        # The characteristic failure: the app exists and authenticates, but holds no role
        # on the subscription. Say what fixes it rather than echoing ARM's phrasing.
        detail = detail or 'no role assignment on this subscription'
    return {'ok': False, 'detail': (detail or f'HTTP {r.status_code}')[:200]}


def permission_row(declaration: dict, values: dict, label: str = '') -> dict:
    """The extra check-permissions row an ``azure_rbac`` declaration contributes.

    Everything Azure-specific about that row lives here: which credential field names the
    target (``field``), which role is expected (``role``), and the stable ``id`` the UI
    matches its pre-drawn row against.  The generic Entra check-permissions route only
    asks the declaration's owner for a row and folds it in — it must not learn that
    "subscription_id" or "reader" mean anything, the same reason the RBAC assignment code
    lives in this package instead of in the Entra provisioning module.

    *values* is the resolved credential (stored fields overlaid with whatever the editor
    sent).  Returns a row shaped like :func:`~lib.providers.entraid.permissions.
    permission_report`'s, ready for ``merge_row``.
    """
    field = str((declaration or {}).get('field') or 'subscription_id')
    role = str((declaration or {}).get('role') or 'reader')
    out = check_subscription_access(
        str((values or {}).get('tenant_id') or ''),
        str((values or {}).get('client_id') or ''),
        str((values or {}).get('client_secret') or ''),
        str((values or {}).get(field) or ''))
    return {'id': ROW_ID, 'priv': label or f'Azure RBAC: {role}',
            'ok': out['ok'], 'detail': out['detail']}


def list_subscriptions(arm_token: str) -> list:
    """The subscriptions the signed-in admin can see, newest API, as
    ``[{'id', 'name', 'state'}]`` sorted by name.

    Used to let the wizard OFFER a target instead of asking the admin to paste a GUID.
    ARM only returns subscriptions the caller has access to, which is exactly the set
    where they might also be able to create a role assignment — so an empty list is a
    meaningful answer (this account manages none), not an error.

    Returns ``[]`` on any failure: the picker is a convenience, and the caller always
    keeps the "type the id by hand" path.
    """
    try:
        r = _req.get(f'{ARM_BASE}/subscriptions?api-version={API_SUBSCRIPTIONS}',
                     headers={'Authorization': f'Bearer {arm_token}'}, timeout=20)
        if not r.ok:
            return []
        rows = (r.json() or {}).get('value') or []
    except Exception:  # pylint: disable=broad-except
        return []
    out = []
    for s in rows:
        if not isinstance(s, dict):
            continue
        sid = str(s.get('subscriptionId') or '').strip()
        if not sid:
            continue
        # Disabled/expired subscriptions cannot take a role assignment usefully; keep
        # them listed but let the caller show the state rather than silently hiding one.
        out.append({'id': sid,
                    'name': str(s.get('displayName') or sid),
                    'state': str(s.get('state') or '')})
    return sorted(out, key=lambda s: s['name'].lower())


def assign_subscription_role(arm_token: str, subscription_id: str, principal_id: str,
                             role: str = 'reader') -> dict:
    """Assign a built-in Azure role to a service principal ON a subscription.

    *arm_token* must be issued for ``management.azure.com`` and belong to someone who
    may create role assignments there (**Owner** or **User Access Administrator**);
    being an Entra admin is NOT enough, which is the usual cause of a 403 here.

    Returns ``{'ok': bool, 'already': bool, 'role': str, 'message': str}`` — an
    existing identical assignment (409 ``RoleAssignmentExists``) counts as success, so
    re-running the wizard is safe.
    """
    role_id = ARM_ROLES.get(str(role or 'reader').lower())
    if not role_id:
        return {'ok': False, 'already': False, 'role': role, 'message': f'unknown role: {role}'}
    if not (subscription_id and principal_id):
        return {'ok': False, 'already': False, 'role': role,
                'message': 'subscription id and principal id are required'}
    sub = str(subscription_id).strip()
    # The assignment NAME must be a GUID and is what makes the call idempotent-ish;
    # a fresh one plus the 409 handling below covers the re-run case.
    name = str(_uuid.uuid4())
    url = (f'{ARM_BASE}/subscriptions/{sub}/providers/Microsoft.Authorization/'
           f'roleAssignments/{name}?api-version={API_ROLE_ASSIGNMENTS}')
    body = {'properties': {
        'roleDefinitionId': (f'/subscriptions/{sub}/providers/Microsoft.Authorization/'
                             f'roleDefinitions/{role_id}'),
        'principalId': principal_id,
        # Without this ARM may reject a brand-new SP it has not replicated yet.
        'principalType': 'ServicePrincipal',
    }}
    try:
        r = _req.put(url, headers={'Authorization': f'Bearer {arm_token}',
                                   'Content-Type': 'application/json'},
                     json=body, timeout=20)
    except Exception as exc:  # pylint: disable=broad-except
        return {'ok': False, 'already': False, 'role': role, 'message': str(exc)}
    if r.ok:
        return {'ok': True, 'already': False, 'role': role, 'message': ''}
    detail = ''
    try:
        detail = ((r.json() or {}).get('error') or {}).get('message') or ''
    except Exception:  # pylint: disable=broad-except
        detail = (r.text or '')[:200]
    if r.status_code == 409 or 'RoleAssignmentExists' in (detail or ''):
        return {'ok': True, 'already': True, 'role': role, 'message': ''}
    return {'ok': False, 'already': False, 'role': role,
            'message': detail or f'HTTP {r.status_code}'}
