#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-section buttons this provider contributes (see lib.config.config_actions).

Everything Entra-specific — the registration wizards, the secret rotation, the deep link
into the portal — is owned by THIS package: the descriptors below are plain data, and the
JavaScript they name is shipped in ``lib/providers/entraid/web/*_ui.html``.  ``web_admin``
renders the buttons generically and knows nothing about Entra ID.
"""

CONFIG_ACTIONS = [
    # ── OIDC ──────────────────────────────────────────────────────────────────
    {'section': 'oidc', 'id': 'register', 'order': 10,
     'label_key': 'entra_wizard_btn', 'icon': 'bi-microsoft', 'variant': 'primary',
     'fn': 'showEntraWizard', 'group_label_key': 'entra_id'},
    {'section': 'oidc', 'id': 'open_app', 'order': 20,
     'label_key': 'entra_open_app', 'icon': 'bi-box-arrow-up-right', 'variant': 'secondary',
     'fn': 'openEntraAppFromConfig', 'group_label_key': 'entra_id',
     'show_when': {'field': 'client_id', 'not_empty': True}},
    {'section': 'oidc', 'id': 'rotate_secret', 'order': 30,
     'label_key': 'entra_oidc_secret_rotate', 'tooltip_key': 'entra_oidc_secret_rotate_tt',
     'icon': 'bi-arrow-repeat', 'variant': 'warning',
     'fn': 'showEntraOidcRotateSecret', 'group_label_key': 'entra_id',
     'show_when': {'field': 'client_id', 'not_empty': True}},

    # ── SAML2 ─────────────────────────────────────────────────────────────────
    {'section': 'saml2', 'id': 'register', 'order': 10,
     'label_key': 'entra_saml2_wizard_btn', 'icon': 'bi-microsoft', 'variant': 'primary',
     'fn': 'showEntraSaml2Wizard', 'group_label_key': 'entra_id'},
    {'section': 'saml2', 'id': 'open_app', 'order': 15,
     'label_key': 'entra_open_app', 'icon': 'bi-box-arrow-up-right', 'variant': 'secondary',
     'fn': 'openEntraSaml2AppFromConfig', 'group_label_key': 'entra_id',
     'show_when': {'field': 'sp_app_id', 'not_empty': True}},
    {'section': 'saml2', 'id': 'add_secret', 'order': 20,
     'label_key': 'entra_saml2_add_secret_btn', 'icon': 'bi-key', 'variant': 'secondary',
     'fn': '_entraSaml2AddSecret', 'group_label_key': 'entra_id',
     'show_when': {'field': 'sp_app_id', 'not_empty': True}},
]


# ── Directory group source for the group→role mapping widget ─────────────────
# Both Entra-backed sections use the same Graph endpoint; the picker id differs so the
# two sections can be open at once. The JS ships in web/_groups_ui.html.
_ENTRA_GROUPS = {
    'label_key': 'entra_fetch_groups', 'icon': 'bi-microsoft',
    'fetch_fn': '_entraFetchGroups', 'pick_fn': '_entraPickGroup',
    'lookup_url': '/api/v1/auth/entraid/group_lookup', 'lookup_key': 'group_id',
    'hint_key': 'entra_groups_pick_hint',
}

GROUP_SOURCES = [
    {**_ENTRA_GROUPS, 'section': 'oidc',  'picker_id': 'oidcGroupPicker'},
    {**_ENTRA_GROUPS, 'section': 'saml2', 'picker_id': 'saml2GroupPicker'},
]
