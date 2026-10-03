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
            # Absent means on: the monitor runs a module with no `enabled` key
            # (lib/modules/discovery/schemas.py), so the card must count it as running.
            'enabled': bool(cfg.get('enabled', True)),
            'items':   len(items_obj) if isinstance(items_obj, dict) else 0,
            'checks':  _mod_checks(status_raw, name),
        })
    from lib.core.overview.filters import (  # noqa: PLC0415
        parse_severity_filter, severity_rank, severity_matches)
    level, op, _maint = parse_severity_filter(f)   # modules have no maintenance
    if level == 'on':
        rows = [r for r in rows if r['enabled']]
    elif level in ('warning', 'error'):
        rows = [r for r in rows if severity_matches(
            severity_rank(r['checks']['error'] > 0, r['checks']['warning'] > 0), level, op)]
    return rows


def incident_rows(wa, f: str = '', *, status_raw=None, modules_raw=None) -> list:
    """Active issues (every check currently reporting ``status: False``) for the incidents
    table: module/check/device, sorted by module then check.  Display name mirrors the public
    status page (other_data.name > item label > raw key); device from the item's device_uid."""
    if status_raw is None:
        status_raw = wa._read_check_status()
    if modules_raw is None:
        modules_raw = wa._load_modules() or {}
    device_name: dict = {}
    hstore = getattr(wa, '_devices_store', None)
    if hstore is not None:
        try:
            for h in (hstore.list(decrypt=False) or []):
                device_name[h.get('uid')] = h.get('name', '')
        except Exception:  # pylint: disable=broad-except
            pass
    out = []
    try:
        for mn, mstatus in status_raw.items():
            if not isinstance(mstatus, dict):
                continue
            mcfg = modules_raw.get(mn)
            mcfg = mcfg if isinstance(mcfg, dict) else {}
            labels, devices_of = {}, {}
            for coll, items in mcfg.items():
                if coll.startswith('__') or not isinstance(items, dict):
                    continue
                for k, it in items.items():
                    if not isinstance(it, dict):
                        continue
                    lbl = str(it.get('label') or '').strip()
                    if lbl:
                        labels[k] = lbl
                    if it.get('device_uid'):
                        devices_of[k] = it['device_uid']
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
                huid = devices_of.get(ck) or devices_of.get(head, '')
                out.append({'module': mn, 'check': disp,
                            'device': device_name.get(huid, '') if huid else ''})
        out.sort(key=lambda x: (str(x['module']).lower(), str(x['check']).lower()))
    except Exception:  # pylint: disable=broad-except
        pass
    return out


def modules_stat(wa) -> dict:
    """Stat content for the ``modules`` card (total + enabled/disabled breakdown),
    fetched over AJAX by the generic stat renderer."""
    mods = wa._load_modules() or {}
    total = sum(1 for c in mods.values() if isinstance(c, dict))
    enabled = sum(1 for c in mods.values() if isinstance(c, dict) and c.get('enabled', True))
    disabled = total - enabled
    badges = []
    if enabled:
        badges.append({'style': 'ok', 'icon': 'bi-check-circle', 'count': enabled,
                       'key': 'overview_enabled'})
    if disabled:
        badges.append({'style': 'muted', 'count': disabled, 'key': 'overview_disabled'})
    return {'value': total, 'badges': badges}
