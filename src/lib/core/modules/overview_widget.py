#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the modules domain owns (see lib.core.overview.discovery).

``modules_list`` is a data-driven **table** widget: its rows are fetched over AJAX from
``/api/v1/overview/widget/modules_list?f=<filter>`` (served by ``_modules_list_rows``,
filtered server-side), and painted by the generic table renderer from the ``columns``
declared in its ``view``.  So only the needed rows are queried, and the filter is passed
to the server instead of being applied client-side.
"""


def _mod_checks(status_raw: dict, name: str) -> dict:
    mc = status_raw.get(name, {})
    if not isinstance(mc, dict):
        return {'total': 0, 'ok': 0, 'error': 0, 'warning': 0}
    ok = sum(1 for v in mc.values() if isinstance(v, dict) and v.get('status') is True)
    warn = sum(1 for v in mc.values() if isinstance(v, dict)
               and v.get('status') is False and (v.get('severity') or '') == 'warning')
    err = sum(1 for v in mc.values() if isinstance(v, dict)
              and v.get('status') is False and (v.get('severity') or '') != 'warning')
    return {'total': len(mc), 'ok': ok, 'error': err, 'warning': warn}


def _modules_list_rows(wa, f: str = '') -> list:
    """Rows for the modules_list table, filtered server-side by *f*:
    ``''`` = all, ``'on'`` = enabled only, ``'error'`` = with check errors."""
    status_raw = wa._read_check_status()
    rows = []
    for name, cfg in (wa._load_modules() or {}).items():
        if not isinstance(cfg, dict):
            continue
        items_obj = cfg.get('list')
        rows.append({
            'name':    name,
            'enabled': bool(cfg.get('enabled', False)),
            'items':   len(items_obj) if isinstance(items_obj, dict) else 0,
            'checks':  _mod_checks(status_raw, name),
        })
    if f == 'on':
        rows = [r for r in rows if r['enabled']]
    elif f == 'error':
        rows = [r for r in rows if r['checks']['error'] > 0]
    return rows


def incident_rows(wa, f: str = '', *, status_raw=None, modules_raw=None) -> list:
    """Active issues (every check currently reporting ``status: False``) for the incidents
    table: module/check/host, sorted by module then check.  Display name mirrors the public
    status page (other_data.name > item label > raw key); host from the item's host_uid."""
    if status_raw is None:
        status_raw = wa._read_check_status()
    if modules_raw is None:
        modules_raw = wa._load_modules() or {}
    host_name: dict = {}
    hstore = getattr(wa, '_hosts_store', None)
    if hstore is not None:
        try:
            for h in (hstore.list(decrypt=False) or []):
                host_name[h.get('uid')] = h.get('name', '')
        except Exception:  # pylint: disable=broad-except
            pass
    out = []
    try:
        for mn, mstatus in status_raw.items():
            if not isinstance(mstatus, dict):
                continue
            mcfg = modules_raw.get(mn)
            mcfg = mcfg if isinstance(mcfg, dict) else {}
            labels, hosts_of = {}, {}
            for coll, items in mcfg.items():
                if coll.startswith('__') or not isinstance(items, dict):
                    continue
                for k, it in items.items():
                    if not isinstance(it, dict):
                        continue
                    lbl = str(it.get('label') or '').strip()
                    if lbl:
                        labels[k] = lbl
                    if it.get('host_uid'):
                        hosts_of[k] = it['host_uid']
            for ck, info in mstatus.items():
                if not (isinstance(info, dict) and info.get('status') is False):
                    continue
                extra = info.get('other_data')
                extra = extra if isinstance(extra, dict) else {}
                head = ck.split('/', 1)[0] if '/' in ck else ck
                disp = extra.get('name') or labels.get(ck)
                if not disp and '/' in ck and labels.get(head):
                    disp = f'{labels[head]} / {ck.split("/", 1)[1]}'
                disp = disp or ck
                huid = hosts_of.get(ck) or hosts_of.get(head, '')
                out.append({'module': mn, 'check': disp,
                            'host': host_name.get(huid, '') if huid else ''})
        out.sort(key=lambda x: (str(x['module']).lower(), str(x['check']).lower()))
    except Exception:  # pylint: disable=broad-except
        pass
    return out


def modules_stat(wa) -> dict:
    """Stat content for the ``modules`` card (total + enabled/disabled breakdown),
    fetched over AJAX by the generic stat renderer."""
    mods = wa._load_modules() or {}
    total = sum(1 for c in mods.values() if isinstance(c, dict))
    enabled = sum(1 for c in mods.values() if isinstance(c, dict) and c.get('enabled'))
    disabled = total - enabled
    badges = []
    if enabled:
        badges.append({'style': 'ok', 'icon': 'bi-check-circle', 'count': enabled,
                       'key': 'overview_enabled'})
    if disabled:
        badges.append({'style': 'muted', 'count': disabled, 'key': 'overview_disabled'})
    return {'value': total, 'badges': badges}


OVERVIEW_WIDGETS = [
    {'id': 'modules', 'icon': 'bi-puzzle', 'label_key': 'overview_modules',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 20,
     'perms': {'any': ['modules_view']}, 'nav': {'tab': '#tab-modules'},
     'stat': modules_stat,
     'view': {'kind': 'stat', 'icon': 'bi-puzzle-fill', 'label_key': 'overview_modules',
              'accent': 'indigo', 'data_url': '/api/v1/overview/widget/modules'}},
    {'id': 'incidents', 'icon': 'bi-exclamation-triangle', 'label_key': 'overview_incidents',
     'cols': 4, 'h': 140, 'has_h': True, 'order': 140,
     'perms': {'any': ['modules_view']}, 'nav': {'tab': '#tab-status'},
     'rows': incident_rows,
     'view': {'kind': 'table', 'icon': 'bi-exclamation-triangle', 'title_key': 'overview_incidents',
              'accent': 'red', 'data_url': '/api/v1/overview/widget/incidents',
              'empty_key': 'overview_no_issues', 'empty_ok': True,
              'columns': [
                  {'key': 'module', 'label_key': 'col_module', 'sortable': True, 'cell': 'module_incident'},
                  {'key': 'check',  'label_key': 'col_check',  'sortable': True, 'cell': 'check_danger'},
                  {'key': 'host',   'label_key': 'col_host',   'sortable': True, 'cell': 'host_code'},
              ]}},
    {'id': 'modules_list', 'icon': 'bi-puzzle', 'label_key': 'overview_modules',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 160,
     'perms': {'any': ['modules_view']}, 'nav': {'tab': '#tab-modules'},
     # Data-driven AJAX table: rows fetched (filtered) server-side by ``rows``, painted
     # by the generic table renderer from ``columns`` (cell types); ``rows`` is stripped
     # before the descriptor is serialised to the frontend.
     'rows': _modules_list_rows,
     'view': {'kind': 'table', 'icon': 'bi-puzzle', 'title_key': 'overview_modules',
              'accent': 'indigo', 'data_url': '/api/v1/overview/widget/modules_list',
              'filter': {'store': 'modf', 'param': 'f', 'options': [
                  {'v': '',      'label_key': 'all'},
                  {'v': 'on',    'label_key': 'dw_mod_on',
                   'badge': {'color': '#16a34a', 'bg': 'rgba(34,197,94,.16)'}},
                  {'v': 'error', 'label_key': 'host_status_error',
                   'badge': {'color': '#dc3545', 'bg': 'rgba(220,53,69,.16)'}},
              ]},
              'columns': [
                  {'key': 'name',    'label_key': 'col_module',     'sortable': True, 'cell': 'module_name'},
                  {'key': 'enabled', 'label_key': 'col_enabled',    'sortable': True, 'cell': 'on_badge'},
                  {'key': 'checks',  'label_key': 'col_checks',                       'cell': 'checks'},
                  {'key': 'items',   'label_key': 'overview_items', 'sortable': True, 'cell': 'num', 'align': 'muted'},
              ]}},
]
