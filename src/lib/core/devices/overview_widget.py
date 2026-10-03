#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the devices domain (Servers) owns (see lib.core.overview.discovery)."""

from lib.core.overview.filters import (
    parse_severity_filter, severity_matches, severity_rank)


def _device_checks(status_raw: dict, modules_raw: dict) -> dict:
    """Enabled bound-check tally per device uid (total/ok/error/warning), from the module
    configuration cross-referenced with the status file — same shape as the per-module
    ``checks`` object so the table can reuse it."""
    out: dict = {}
    for mn, mc in modules_raw.items():
        if not isinstance(mc, dict):
            continue
        mstatus = status_raw.get(mn, {})
        if not isinstance(mstatus, dict):
            mstatus = {}
        for coll, items in mc.items():
            if coll.startswith('__') or not isinstance(items, dict):
                continue
            for ikey, it in items.items():
                if not (isinstance(it, dict) and it.get('device_uid')
                        and it.get('enabled') is not False):
                    continue
                c = out.setdefault(it['device_uid'], {'total': 0, 'ok': 0, 'error': 0, 'warning': 0})
                c['total'] += 1
                sv = mstatus.get(ikey)
                if isinstance(sv, dict):
                    if sv.get('status') is True:
                        c['ok'] += 1
                    elif sv.get('status') is False:
                        if (sv.get('severity') or '') == 'warning':
                            c['warning'] += 1
                        else:
                            c['error'] += 1
    return out


def server_list_rows(wa, f: str = '', *, status_raw=None, modules_raw=None) -> list:
    """Per-device rows for the servers_list table (name/status/checks/modules), sorted by
    name and filtered server-side by *f* (``''`` all, ``'error'``, ``'maint'``,
    ``'errmaint'``).  Also the single source the overview aggregate derives the servers
    stat + coverage from.  ``status_raw``/``modules_raw`` may be passed to avoid re-reads."""
    hstore = getattr(wa, '_devices_store', None)
    if hstore is None:
        return []
    rows = []
    try:
        from lib.core.devices.service import _device_statuses, _device_bound_modules  # noqa: PLC0415
        if status_raw is None:
            status_raw = wa._read_check_status()
        if modules_raw is None:
            modules_raw = wa._load_modules() or {}
        devices = hstore.list(decrypt=False) or []
        hstatuses = _device_statuses(wa)
        hbound = _device_bound_modules(wa)
        hchecks = _device_checks(status_raw, modules_raw)
        for h in devices:
            uid = h.get('uid')
            mods = hbound.get(uid, {})
            all_m = set(h.get('modules') or []) | set(mods)
            rows.append({
                'uid': uid, 'name': h.get('name', ''),
                'virtual': bool(h.get('virtual')),
                'maintenance': bool(h.get('maintenance')),
                'status': hstatuses.get(uid, ''),
                'checks': hchecks.get(uid, {'total': 0, 'ok': 0, 'error': 0, 'warning': 0}),
                'modules_total': len(all_m),
                'modules_active': sum(1 for m in all_m if mods.get(m)),
            })
        rows.sort(key=lambda s: str(s.get('name') or '').lower())
    except Exception:  # pylint: disable=broad-except
        return rows

    level, op, maint = parse_severity_filter(f)
    if level == '' and not maint:
        return rows                                   # all
    return [r for r in rows if _server_matches(r, level, op, maint)]


def _server_matches(r: dict, level: str, op: str, maint: bool) -> bool:
    """Whether a server row passes the compound filter. Maintenance is its own bucket (as in
    servers_summary/servers_stat) — a maintenance device, whose skipped checks read 'warning'
    (pending), is excluded from the severity/type match and only re-added by the maint flag."""
    if maint and r['maintenance']:
        return True                                   # maintenance union
    if r['maintenance'] or level == '':
        return False                                  # maint devices / maint-only handled above
    if level == 'virtual':
        return bool(r.get('virtual'))
    if level == 'physical':
        return not r.get('virtual')
    rank = severity_rank(
        (r['checks'].get('error', 0) > 0) or r['status'] == 'error',
        (r['checks'].get('warning', 0) > 0) or r['status'] == 'warning')
    return severity_matches(rank, level, op)          # warning / error


def servers_summary(rows: list) -> dict:
    """Total + status breakdown + physical/virtual split (for the servers stat),
    derived from server_list_rows — a device in maintenance counts as maintenance,
    else by its status."""
    status = {'ok': 0, 'error': 0, 'warning': 0, 'maintenance': 0}
    virtual = 0
    for r in rows:
        if r.get('virtual'):
            virtual += 1
        if r.get('maintenance'):
            status['maintenance'] += 1
        else:
            st = r.get('status', '')
            if st in status:
                status[st] += 1
    return {'total': len(rows), 'virtual': virtual,
            'physical': len(rows) - virtual, 'status': status}


def servers_stat(wa) -> dict:
    """Stat content for the ``servers`` card: device status breakdown badges (only non-zero)
    + a virtual-devices badge + accent turning red when any device errors."""
    summ = servers_summary(server_list_rows(wa))
    ss = summ.get('status', {}) or {}
    badges = []
    for n, cls, ic, key in (
            (ss.get('ok', 0),      'text-bg-success', 'bi-check-circle',    'device_status_ok'),
            (ss.get('error', 0),   'text-bg-danger',  'bi-x-circle',        'device_status_error'),
            (ss.get('warning', 0), 'text-bg-warning', 'bi-hourglass-split', 'device_status_warning')):
        if n:
            badges.append({'cls': cls, 'icon': ic, 'count': n, 'key': key})
    if ss.get('maintenance', 0):
        badges.append({'bg': '#fd7e14', 'color': '#fff', 'icon': 'bi-cone-striped',
                       'count': ss['maintenance'], 'key': 'device_status_maintenance'})
    # Physical/virtual split: mark how many of the devices are virtual (VIP/cluster).
    if summ.get('virtual', 0):
        badges.append({'cls': 'text-bg-info', 'icon': 'bi-diagram-3',
                       'count': summ['virtual'], 'key': 'device_virtual'})
    # `state` tints the whole card; `accent` is only the 3px bar. Maintenance is
    # deliberately NOT a state: a device somebody took down on purpose is the one case where
    # the panel already knows there is nothing to react to.
    state = 'error' if ss.get('error', 0) else ('warn' if ss.get('warning', 0) else '')
    return {'value': sum(ss.values()), 'state': state,
            'accent': 'red' if ss.get('error', 0) > 0 else 'blue', 'badges': badges}


def coverage_stat(wa) -> dict:
    """Stat content for the ``coverage`` card: monitored/total devices + accent by
    percentage (≥90 green, ≥50 orange, else red)."""
    rows = server_list_rows(wa)
    total = len(rows)
    monitored = sum(1 for r in rows if (r.get('checks') or {}).get('total', 0) > 0)
    pct = round(100 * monitored / total) if total else 0
    accent = 'green' if pct >= 90 else ('orange' if pct >= 50 else 'red')
    return {'value': f'{pct}%', 'accent': accent,
            'badges': [{'plain': True, 'key': 'overview_of_devices',
                        'args': [monitored, total]}]}
