#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the hosts domain (Servers) owns (see lib.core.overview.discovery)."""


def _host_checks(status_raw: dict, modules_raw: dict) -> dict:
    """Enabled bound-check tally per host uid (total/ok/error/warning), from the module
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
                if not (isinstance(it, dict) and it.get('host_uid')
                        and it.get('enabled') is not False):
                    continue
                c = out.setdefault(it['host_uid'], {'total': 0, 'ok': 0, 'error': 0, 'warning': 0})
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
    """Per-host rows for the servers_list table (name/status/checks/modules), sorted by
    name and filtered server-side by *f* (``''`` all, ``'error'``, ``'maint'``,
    ``'errmaint'``).  Also the single source the overview aggregate derives the servers
    stat + coverage from.  ``status_raw``/``modules_raw`` may be passed to avoid re-reads."""
    hstore = getattr(wa, '_hosts_store', None)
    if hstore is None:
        return []
    rows = []
    try:
        from lib.core.hosts.routes._helpers import _host_statuses, _host_bound_modules  # noqa: PLC0415
        if status_raw is None:
            status_raw = wa._read_check_status()
        if modules_raw is None:
            modules_raw = wa._load_modules() or {}
        hosts = hstore.list(decrypt=False) or []
        hstatuses = _host_statuses(wa)
        hbound = _host_bound_modules(wa)
        hchecks = _host_checks(status_raw, modules_raw)
        for h in hosts:
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

    def _err(r):
        return (r['checks'].get('error', 0) > 0) or r['status'] == 'error'
    if f == 'error':
        rows = [r for r in rows if _err(r)]
    elif f == 'maint':
        rows = [r for r in rows if r['maintenance']]
    elif f == 'errmaint':
        rows = [r for r in rows if _err(r) or r['maintenance']]
    elif f == 'virtual':
        rows = [r for r in rows if r.get('virtual')]
    elif f == 'physical':
        rows = [r for r in rows if not r.get('virtual')]
    return rows


def servers_summary(rows: list) -> dict:
    """Total + status breakdown + physical/virtual split (for the servers stat),
    derived from server_list_rows — a host in maintenance counts as maintenance,
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
    """Stat content for the ``servers`` card: host status breakdown badges (only non-zero)
    + a virtual-hosts badge + accent turning red when any host errors."""
    summ = servers_summary(server_list_rows(wa))
    ss = summ.get('status', {}) or {}
    badges = []
    for n, cls, ic, key in (
            (ss.get('ok', 0),      'text-bg-success', 'bi-check-circle',    'host_status_ok'),
            (ss.get('error', 0),   'text-bg-danger',  'bi-x-circle',        'host_status_error'),
            (ss.get('warning', 0), 'text-bg-warning', 'bi-hourglass-split', 'host_status_warning')):
        if n:
            badges.append({'cls': cls, 'icon': ic, 'count': n, 'key': key})
    if ss.get('maintenance', 0):
        badges.append({'bg': '#fd7e14', 'color': '#fff', 'icon': 'bi-cone-striped',
                       'count': ss['maintenance'], 'key': 'host_status_maintenance'})
    # Physical/virtual split: mark how many of the hosts are virtual (VIP/cluster).
    if summ.get('virtual', 0):
        badges.append({'cls': 'text-bg-info', 'icon': 'bi-diagram-3',
                       'count': summ['virtual'], 'key': 'host_virtual'})
    return {'value': sum(ss.values()),
            'accent': 'red' if ss.get('error', 0) > 0 else 'blue', 'badges': badges}


def coverage_stat(wa) -> dict:
    """Stat content for the ``coverage`` card: monitored/total hosts + accent by
    percentage (≥90 green, ≥50 orange, else red)."""
    rows = server_list_rows(wa)
    total = len(rows)
    monitored = sum(1 for r in rows if (r.get('checks') or {}).get('total', 0) > 0)
    pct = round(100 * monitored / total) if total else 0
    accent = 'green' if pct >= 90 else ('orange' if pct >= 50 else 'red')
    return {'value': f'{pct}%', 'accent': accent,
            'badges': [{'plain': True, 'key': 'overview_of_hosts',
                        'args': [monitored, total]}]}


OVERVIEW_WIDGETS = [
    {'id': 'servers', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 30,
     'perms': {'any': ['servers_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'stat': servers_stat,
     'view': {'kind': 'stat', 'icon': 'bi-hdd-network-fill', 'label_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers'}},
    {'id': 'coverage', 'icon': 'bi-pie-chart', 'label_key': 'overview_coverage',
     'cols': 2, 'h': 'auto', 'has_h': False, 'order': 100,
     'perms': {'any': ['servers_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'stat': coverage_stat,
     'view': {'kind': 'stat', 'icon': 'bi-pie-chart-fill', 'label_key': 'overview_coverage',
              'accent': 'green', 'data_url': '/api/v1/overview/widget/coverage'}},
    {'id': 'servers_list', 'icon': 'bi-hdd-network', 'label_key': 'overview_servers',
     'cols': 4, 'h': 340, 'has_h': True, 'order': 170,
     'perms': {'any': ['servers_view'], 'prefix': ['server.']}, 'nav': {'tab': '#tab-servers'},
     'rows': server_list_rows,
     'view': {'kind': 'table', 'icon': 'bi-hdd-network', 'title_key': 'overview_servers',
              'accent': 'blue', 'data_url': '/api/v1/overview/widget/servers_list',
              'empty_key': 'host_monitor_none',
              'filter': {'store': 'srvf', 'param': 'f', 'options': [
                  {'v': '',      'label_key': 'all'},
                  {'v': 'error', 'label_key': 'host_status_error',
                   'badge': {'color': '#dc3545', 'bg': 'rgba(220,53,69,.16)'}},
                  {'v': 'maint', 'label_key': 'host_status_maintenance',
                   'badge': {'color': '#fd7e14', 'bg': 'rgba(253,126,20,.18)'}},
                  {'v': 'errmaint', 'label_key': 'host_status_error',
                   'badge': {'color': '#dc3545', 'bg': 'rgba(220,53,69,.16)'}},
                  {'v': 'virtual', 'label_key': 'host_virtual',
                   'badge': {'color': '#0dcaf0', 'bg': 'rgba(13,202,240,.16)'}},
                  {'v': 'physical', 'label_key': 'host_physical'},
              ]},
              'columns': [
                  {'key': 'name',    'label_key': 'col_server',        'sortable': True, 'cell': 'host_name'},
                  {'key': 'status',  'label_key': 'col_host_status',   'sortable': True, 'cell': 'host_status'},
                  {'key': 'checks',  'label_key': 'col_checks',        'sortable': True, 'cell': 'host_checks'},
                  {'key': 'modules', 'label_key': 'col_host_modules',  'sortable': True, 'cell': 'host_modules'},
              ]}},
]
