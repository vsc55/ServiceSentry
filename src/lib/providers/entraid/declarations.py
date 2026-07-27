#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — app-provisioning declarations (``__entraid_provision__``).

A module (or the SSO OIDC config) can declare the Entra app the shared device-code
wizard should register for its credential: which API resource(s), which
*application* roles and *delegated* scopes, and — for a user sign-in app — the
SSO-style properties (web redirect URIs, groups claim, require-assignment).

The DECLARATION side (discovery + normalisation) lives here; the actual Graph
registration is in :mod:`lib.providers.entraid.graph`.
"""

from __future__ import annotations

import json
import os

# Microsoft Graph's well-known application (resource) id — the default API a
# provisioned app targets when a profile doesn't name another ``resource``.
GRAPH_APP_ID = '00000003-0000-0000-c000-000000000000'

# Default display names for the apps ServiceSentry registers in Entra ID. SINGLE
# SOURCE OF TRUTH for both the Python side (provisioning + routes, via the client
# re-export) and the JS wizards (injected into the templates by app.py's context
# processor → core/_constants.html). Kept in this base module so every layer can
# reach them without an import cycle.
DEFAULT_APP_NAME = 'ServiceSentry Monitor'   # app-only monitoring / module apps
OIDC_APP_NAME = 'ServiceSentry - OIDC'       # OIDC SSO app
SAML2_APP_NAME = 'ServiceSentry - SAML2'     # SAML2 SSO app
SCIM_APP_NAME = 'ServiceSentry - SCIM'       # SCIM provisioning enterprise app
EMAIL_APP_NAME = 'ServiceSentry - Email'     # Email notifications via Microsoft Graph (Mail.Send)
TEAMS_APP_NAME = 'ServiceSentry - Teams'     # Teams user notifications via Graph (TeamsActivity.Send)


def _watchfuls_dir(watchfuls_dir: str | None) -> str:
    if watchfuls_dir:
        return watchfuls_dir
    # this file is lib/providers/entraid/declarations.py → climb three levels to src root.
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, 'watchfuls'))


def normalize_entraid_provision(decl: dict) -> dict:
    """Normalise an ``__entraid_provision__`` declaration into a stable shape::

        {'app_name': str,
         'app_roles': [str],            # Graph application roles (legacy convenience)
         'resources': [{'resource': appId, 'roles': [str], 'scopes': [str]}]}

    A profile may target more than Microsoft Graph and mix permission kinds:

    * top-level ``app_roles`` / ``scopes`` apply to ``resource`` (default Graph);
      ``app_roles`` are *application* permissions (consented as appRoleAssignments),
      ``scopes`` are *delegated* permissions (consented as an oauth2PermissionGrant);
    * an optional ``resources`` list adds further APIs, each ``{resource, app_roles,
      scopes}``.

    The flat ``app_roles`` (Graph application roles) is kept alongside for the
    back-compat callers/scripts that only speak Graph."""
    resources: list = []

    def _add(res, roles, scopes):
        roles = [str(r) for r in (roles or []) if str(r).strip()]
        scopes = [str(s) for s in (scopes or []) if str(s).strip()]
        if roles or scopes:
            resources.append({'resource': str(res or GRAPH_APP_ID).strip() or GRAPH_APP_ID,
                              'roles': roles, 'scopes': scopes})

    if isinstance(decl, dict):
        _add(decl.get('resource'), decl.get('app_roles'), decl.get('scopes'))
        for r in (decl.get('resources') or []):
            if isinstance(r, dict):
                _add(r.get('resource'), r.get('app_roles') or r.get('roles'), r.get('scopes'))
    graph_roles = [n for r in resources if r['resource'] == GRAPH_APP_ID for n in r['roles']]
    decl = decl if isinstance(decl, dict) else {}
    return {
        'app_name': str(decl.get('app_name') or DEFAULT_APP_NAME),
        'app_roles': graph_roles,
        'resources': resources,
        # Optional SSO-style app-registration properties (for a user sign-in app):
        #   redirect_uris — web reply URLs (a "{public_url}" token is expanded to the
        #                   server's public base by the caller); group_claims — emit
        #                   the groups claim in tokens; require_assignment — only
        #                   users/apps explicitly assigned may sign in.
        'redirect_uris': [str(u) for u in (decl.get('redirect_uris') or []) if str(u).strip()],
        'group_claims': bool(decl.get('group_claims')),
        'require_assignment': bool(decl.get('require_assignment')),
        # Optional Azure RBAC step. Azure access is NOT an Entra app permission: reading a
        # subscription needs a role assignment ON that subscription, an ARM operation on a
        # different audience. A module declares it here and the wizard chains it after the
        # app exists; the subscription id comes from the user (it is not in the schema).
        #   "azure_rbac": {"role": "reader", "field": "subscription_id"}
        'azure_rbac': _azure_rbac(decl.get('azure_rbac')),
    }


def _azure_rbac(decl) -> dict:
    """Normalise the optional ``azure_rbac`` block; ``{}`` when absent or unusable."""
    if not isinstance(decl, dict):
        return {}
    role = str(decl.get('role') or 'reader').strip().lower()
    field = str(decl.get('field') or 'subscription_id').strip()
    if not role or not field:
        return {}
    return {'role': role, 'field': field}


def entraid_provision_extras(schema: dict) -> dict:
    """The provision-action fields a credential's device-code action inherits from
    the module's ``__entraid_provision__`` — the proposed app name, permissions and
    the optional SSO-style properties.  Empty ``{}`` when the module declares none.

    Lets the credential catalog stay generic: it just merges whatever this returns
    into an action's ``provision`` object, knowing nothing about Entra permissions."""
    ep = (schema or {}).get('__entraid_provision__')
    if not isinstance(ep, dict):
        return {}
    n = normalize_entraid_provision(ep)
    out = {'app_name': n['app_name'], 'app_roles': n['app_roles'], 'resources': n['resources']}
    for k in ('redirect_uris', 'group_claims', 'require_assignment', 'azure_rbac'):
        if n.get(k):
            out[k] = n[k]
    # `azure_rbac` travels to the client for ONE reason: it names the credential field
    # (e.g. subscription_id) whose value the wizard must post, since the RBAC target is
    # the user's, not the schema's. The role itself is re-read server-side — the client
    # cannot pick which role it gets.
    return out


def module_entraid_provision(watchfuls_dir: str | None = None) -> dict:
    """Return ``{module: normalized_profile}`` — the Microsoft Entra ID app a module
    can provision for its credential via the shared device-code wizard
    (``__entraid_provision__`` in the schema); see
    :func:`normalize_entraid_provision` for the shape.  Module-agnostic — the core
    knows no module's permissions, it discovers them here."""
    base = _watchfuls_dir(watchfuls_dir)
    out: dict = {}
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        sp = os.path.join(base, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        decl = schema.get('__entraid_provision__')
        if not isinstance(decl, dict):
            continue
        norm = normalize_entraid_provision(decl)
        if norm['resources']:
            out[entry] = norm
    return out


def provision_profile(watchfuls_dir: str | None, profile) -> dict | None:
    """The normalised profile a caller names by module id, or ``None``.

    Never raises: a malformed or missing schema means "this caller declared nothing",
    which every caller already has to handle — an exception here would turn a bad schema
    in one module into a broken wizard for all of them.
    """
    try:
        return module_entraid_provision(watchfuls_dir).get(str(profile or ''))
    except Exception:  # pylint: disable=broad-except
        return None


def declared_profile(watchfuls_dir: str | None, body: dict) -> dict | None:
    """The profile a request refers to: named by ``profile``, else declared inline.

    Inline is how a non-module caller (the SSO "Register in Azure" button) reuses the same
    wizard without inventing a module — same declaration vocabulary, no schema file.
    """
    prof = provision_profile(watchfuls_dir, body.get('profile'))
    if not prof or not prof.get('resources'):
        inline = normalize_entraid_provision(body)
        if inline['resources']:
            return inline
    return prof


def declared_roles(watchfuls_dir: str | None, body: dict) -> list[str]:
    """The application permissions a check or a fix needs — every resource's roles,
    de-duplicated in declaration order. Empty means nothing was declared, which callers
    treat as "there is no question to ask"."""
    prof = declared_profile(watchfuls_dir, body)
    roles = [r for res in ((prof or {}).get('resources') or []) for r in (res.get('roles') or [])]
    return list(dict.fromkeys(roles))
