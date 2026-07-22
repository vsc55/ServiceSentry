#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the LDAP provider contributes (see lib/discovery.py).

The JavaScript named here ships in ``lib/providers/ldap/web/_groups_ui.html``; web_admin
renders the button/picker generically and knows nothing about LDAP.
"""

# ── Directory group source for the group→role mapping widget ─────────────────
GROUP_SOURCES = [
    {'section': 'ldap',
     'label_key': 'grm_fetch_groups', 'icon': 'bi-cloud-download',
     'fetch_fn': '_ldapFetchGroups', 'pick_fn': '_ldapPickGroup',
     'lookup_url': '/api/v1/auth/ldap/group_lookup', 'lookup_key': 'dn',
     'picker_id': 'ldapGroupPicker', 'hint_key': 'grm_pick_hint'},
]
