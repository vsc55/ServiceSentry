#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widget the credentials domain owns (see lib.core.overview.discovery)."""


def credentials_stat(wa) -> dict:
    """Stat content for the ``credentials`` card: count + by-type badges + disabled count.
    Only non-sensitive metadata (never the secret values)."""
    total = enabled = 0
    by_type: dict = {}
    try:
        store = getattr(wa, '_credentials_store', None)
        if store is not None:
            for c in (store.list(decrypt=False) or []):
                if not isinstance(c, dict):
                    continue
                total += 1
                if c.get('enabled') is not False:
                    enabled += 1
                ct = str(c.get('ctype') or '').strip() or 'ssh'
                by_type[ct] = by_type.get(ct, 0) + 1
    except Exception:  # pylint: disable=broad-except
        pass
    badges = [{'fn': 'credtype', 'type': ct, 'count': n} for ct, n in by_type.items()]
    disabled = total - enabled
    if disabled > 0:
        badges.append({'cls': 'text-bg-light text-muted',
                       'key': 'overview_credentials_disabled', 'args': [disabled]})
    return {'value': total, 'badges': badges}


OVERVIEW_WIDGETS = [
    {'id': 'credentials', 'icon': 'bi-key', 'label_key': 'overview_credentials',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 90,
     'perms': {'any': ['credentials_view', 'servers_view', 'modules_view']},
     'nav': {'tab': '#tab-access', 'sub': '#subtab-credentials'},
     'stat': credentials_stat,
     'view': {'kind': 'stat', 'icon': 'bi-key-fill', 'label_key': 'overview_credentials',
              'accent': 'teal', 'data_url': '/api/v1/overview/widget/credentials'}},
]
