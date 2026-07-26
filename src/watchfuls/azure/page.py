#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: the /azure section and the Overview widget
#
"""Turning stored results into the shapes the core renderers consume.

The module ships **no front-end code**: it declares a page in ``schema.json``
(``__page__``) and answers with data, and the core's generic renderer draws it. So the
whole contract lives here — sections, counts, rows, and which measurements are worth
grouping an inventory by.

Both halves of the page answer in the SAME shape on purpose: ``page_data`` (the monitor's
last results, instant and free) and ``page_refresh`` (a live run against Azure) go through
``_page_payload``, so the page has one renderer rather than two.
"""

from lib.modules.page_support import lang_section

# What each section's inventory is worth grouping by, offered as a selector in the page.
# The order is the order they appear. Declared here because only the module knows which of
# its measurements are categories rather than numbers — the core cannot know what a
# "group" or an "owner" means.
_GROUP_BY = {
    'resources': ('group', 'type', 'owner'),
    'vms':       ('group', 'power'),
    'quotas':    ('region',),
    'budgets':   ('grain', 'currency'),
    'secrets':   ('kind',),
}


class AzurePage:
    """Section page (schema ``__page__`` → /azure) and Overview widget."""

    @classmethod
    def _lang_section(cls, lang: str, section: str) -> dict:
        """A section of the module's lang file (fallback en_EN) — classmethod-safe, for
        the page/widget hooks, which run without a monitor."""
        return lang_section(__file__, lang, section)

    @classmethod
    def _sections(cls, status: dict, lang: str) -> list:
        """Group results into one section per check kind — the shape the core's generic
        page renderer consumes (the module ships no front-end code)."""
        labels = cls._lang_section(lang, 'labels')
        by_kind: dict = {}
        for k, v in (status or {}).items():
            if not isinstance(v, dict) or 'status' not in v:
                continue
            parts = str(k).split('/')
            kind = parts[1] if len(parts) >= 2 else ''
            if kind:
                by_kind.setdefault(kind, []).append((k, v))
        out = []
        for tog, sfx, _m in cls._SERVICES:
            rows_v = by_kind.get(sfx)
            if not rows_v:
                continue
            rows, n_ok, n_warn, n_err = [], 0, 0, 0
            for rk, v in sorted(rows_v, key=lambda kv: kv[0]):
                od = v.get('other_data') or {}
                ok = v.get('status') is True
                state = 'ok' if ok else ('warn' if v.get('severity') == 'warning' else 'error')
                n_ok += ok
                n_warn += state == 'warn'
                n_err += state == 'error'
                rows.append({
                    'key': rk, 'name': od.get('name') or rk.split('/')[-1], 'state': state,
                    'message': v.get('message') or '',
                    'metrics': {mk: mv for mk, mv in od.items()
                                if mk != 'name' and isinstance(mv, (int, float, str))},
                })
            sec = {
                'id': sfx, 'name': labels.get(tog) or sfx,
                'state': 'ok' if not (n_warn or n_err) else ('error' if n_err else 'warn'),
                'counts': {'ok': n_ok, 'warn': n_warn, 'error': n_err, 'total': len(rows)},
                'rows': rows,
            }
            # Which measurements are worth grouping an inventory by. Only offered when the
            # rows actually carry them — an empty selector is worse than none.
            gb = [k for k in _GROUP_BY.get(sfx, ())
                  if any(k in (r.get('metrics') or {}) for r in rows)]
            if gb:
                sec['group_by'] = gb
            out.append(sec)
        return out

    @classmethod
    def _page_payload(cls, status: dict, lang: str, live: bool, items: dict = None) -> dict:
        sections = cls._sections(status, lang)
        tot = {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}
        for s in sections:
            for k in tot:
                tot[k] += s['counts'][k]
        out = {'sections': sections, 'counts': tot, 'live': live}
        if items is not None:
            out['items'] = [{'key': k, 'label': (it or {}).get('label') or k}
                            for k, it in items.items()
                            if isinstance(it, dict) and it.get('enabled', True)]
        return out

    @classmethod
    def page_data(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Cached half of the /azure section: the monitor's last results, so the page
        paints instantly and costs Azure nothing."""
        return cls._page_payload(status, lang, live=False, items=items or {})

    @classmethod
    def page_refresh(cls, config: dict) -> dict:
        """Live half: run this item's enabled checks against Azure right now and answer
        in the SAME shape as ``page_data``, so the page has one renderer."""
        lang = str((config or {}).get('_lang') or 'en_EN')
        raw, err = cls._run_once(config, default_key='page')
        if err:
            return {'ok': False, 'message': err}
        status = {str(r.get('key')): r for r in (raw or []) if isinstance(r, dict)}
        payload = cls._page_payload(status, lang, live=True)
        payload['ok'] = True
        return payload

    @classmethod
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Overview-widget data: one entry per check kind, same convention as m365."""
        wlbl = cls._lang_section(lang, 'widget')
        sections = cls._sections(status, lang)
        entries = [{
            'id': s['id'], 'name': s['name'], 'ok': s['counts']['ok'] == s['counts']['total'],
            'state': s['state'], 'counts': s['counts'],
            'stats': [{'label': wlbl.get('ok', 'OK'),
                       'value': f"{s['counts']['ok']}/{s['counts']['total']}",
                       'state': s['state']}],
            'rows': [{'name': r['name'], 'state': r['state'], 'detail': ''}
                     for r in s['rows']] if s['counts']['total'] > 1 else [],
        } for s in sections]
        tot = {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}
        for s in sections:
            for k in tot:
                tot[k] += s['counts'][k]
        return {
            'entries': entries,
            'aggregate': {
                'count_label': wlbl.get('checks', 'Checks'), 'count': len(entries),
                'ok': tot['warn'] == 0 and tot['error'] == 0,
                'stats': [{'label': wlbl.get('ok', 'OK'),
                           'value': f"{tot['ok']}/{tot['total']}",
                           'state': 'ok' if tot['ok'] == tot['total'] else 'error'}],
                'counts': tot,
            },
        }
