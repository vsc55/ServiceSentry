#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — what an auth *section* is, as far as Entra is concerned.

Two questions the routes kept answering inline, neither of which is about HTTP:

* **which app is this section's app** — OIDC and SAML2 are two registrations with two
  secrets, and mixing them silently checks or reads the directory with an identity nobody
  configured for that section;
* **which URLs this server publishes** — the SAML SP endpoints and the SCIM base, derived
  from the public URL unless the admin pinned them.

Both are section knowledge, so a caller that needs it doesn't have to be a route.
"""

from __future__ import annotations


def section_credentials(cfg_for, data: dict) -> tuple[str, str, str]:
    """``(client_id, client_secret, provider_url)`` for the auth section named in *data*.

    *cfg_for* is called with the section id and returns its stored config.

    SAML2 uses **its own** app: the wizard registers a second registration and keeps its
    Graph secret in ``graph_secret``.  Borrowing OIDC's would read the directory as an app
    nobody pointed at SAML2 — the answer would look fine and mean nothing.

    A request body may override, but **only with a full id+secret pair**.  That is the
    state right after the wizard, when the secret is on screen and not yet stored.  A lone
    client_id must never win: it would be paired with the stored secret of a different app,
    and the failure would look like a permissions problem.
    """
    sec = (data.get('sec') or 'oidc').strip()
    cfg = cfg_for(sec if sec in ('oidc', 'saml2') else 'oidc')
    if sec == 'saml2':
        cid, csec, purl = (cfg.get('sp_app_id', ''), cfg.get('graph_secret', ''),
                           cfg.get('idp_sso_url', ''))
    else:
        cid, csec, purl = (cfg.get('client_id', ''), cfg.get('client_secret', ''),
                           cfg.get('provider_url', ''))
    if data.get('client_id') and data.get('client_secret'):
        cid  = str(data.get('client_id')).strip()
        csec = str(data.get('client_secret')).strip()
    if data.get('provider_url'):
        purl = str(data.get('provider_url')).strip()
    return (cid or '').strip(), (csec or '').strip(), (purl or '').strip()


def public_base(wa) -> str:
    """The server's public base URL (scheme + host, no trailing slash) — what expands a
    ``{public_url}`` token in a profile's redirect URIs.  Single source:
    :meth:`WebAdmin.public_base_url` (config override → proxy-aware auto-detect)."""
    return wa.public_base_url()


def saml_acs_uri(wa) -> str:
    """Where Entra posts the SAML assertion. Pinned value wins — a deployment behind a
    proxy may publish an address this server cannot derive."""
    acs = wa._config_section('saml2').get('sp_acs_url', '').strip()
    return acs or f'{public_base(wa)}/auth/saml2/acs'


def saml_entity_id(wa) -> str:
    """This SP's entity id, as registered on the Entra side."""
    eid = wa._config_section('saml2').get('sp_entity_id', '').strip()
    return eid or public_base(wa)


def scim_base_url(wa) -> str:
    """The SCIM endpoint Entra will push users and groups to."""
    return f'{public_base(wa).rstrip("/")}/scim/v2'
