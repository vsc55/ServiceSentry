#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSentry - Proxmox VE watchful: what Overview shows.
#
"""The module's Overview widget: its own numbers, described by itself.

A widget hook belongs with the page it feeds, not next to the checks - it reads the stored
results and says how to display them, which is a presentation decision the check loop should
never have to carry.
"""

import json
import os


class ProxmoxPage:
    """Overview-widget data. Mixed into ``Watchful``."""

    @classmethod
    def _widget_labels(cls, lang: str) -> dict:
        """The ``widget`` label section from the module's lang/ (fallback en_EN)."""
        ldir = os.path.join(os.path.dirname(__file__), 'lang')
        for fn in (f'{lang}.json', 'en_EN.json'):
            p = os.path.join(ldir, fn)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding='utf-8') as fh:
                    w = (json.load(fh) or {}).get('widget')
                if isinstance(w, dict):
                    return w
            except (OSError, ValueError):
                pass
        return {}

    @classmethod
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Overview-widget data hook (generic shape consumed by the core renderer):
        one ``entry`` per cluster check (name + status + stats + node rows) plus an
        ``aggregate``.  All domain strings come from this module's lang."""
        lbl = cls._widget_labels(lang)
        l_nodes = lbl.get('nodes', 'Nodes')
        l_quorum = lbl.get('quorum', 'Quorum')
        l_ceph = lbl.get('ceph', 'Ceph')
        l_clusters = lbl.get('clusters', 'Clusters')
        entries = []
        agg_nodes_total = agg_nodes_ok = 0
        agg_ok = True
        for uid, it in (items or {}).items():
            if not isinstance(it, dict):
                continue
            pref = f'{uid}/'
            own = {k: v for k, v in (status or {}).items()
                   if isinstance(v, dict) and k.startswith(pref)}
            cl = own.get(f'{uid}/cluster') or {}
            clod = cl.get('other_data') or {}
            ce = own.get(f'{uid}/ceph')
            rows, n_ok, n_total = [], 0, 0
            for nk in sorted(k for k in own if k.startswith(f'{uid}/node/')):
                nv = own[nk]
                nod = nv.get('other_data') or {}
                n_total += 1
                is_ok = nv.get('status') is True
                if is_ok:
                    n_ok += 1
                nm = nk.split('/node/', 1)[1]
                host = nod.get('host_name', '')
                rows.append({
                    'name':  f'{nm} ({host})' if host else nm,
                    'state': 'warn' if nod.get('maintenance') else ('ok' if is_ok else 'error'),
                    'detail': '',
                })
            err = any(v.get('status') is False for v in own.values())
            stats = [{
                'label': l_nodes, 'value': f'{n_ok}/{n_total}',
                'state': 'ok' if (n_total and n_ok == n_total) else ('error' if n_total else 'none'),
            }]
            if cl:
                q = clod.get('quorate')
                stats.append({'label': l_quorum,
                              'value': ('OK' if q else 'KO') if q is not None else '—',
                              'state': 'ok' if q else ('error' if q is not None else 'none')})
            if isinstance(ce, dict):
                health = (ce.get('other_data') or {}).get('health') or ''
                stats.append({'label': l_ceph,
                              'value': health or ('OK' if ce.get('status') else 'KO'),
                              'state': 'ok' if ce.get('status') else 'error'})
            entries.append({
                'id':    uid,
                'name':  str(it.get('label') or '').strip() or uid,
                'ok':    not err,
                'stats': stats,
                'rows':  rows,
            })
            agg_nodes_total += n_total
            agg_nodes_ok += n_ok
            if err:
                agg_ok = False
        return {
            'entries': entries,
            'aggregate': {
                'count_label': l_clusters,
                'count': len(entries),
                'ok': agg_ok,
                'stats': [{
                    'label': l_nodes, 'value': f'{agg_nodes_ok}/{agg_nodes_total}',
                    'state': 'ok' if (agg_nodes_total and agg_nodes_ok == agg_nodes_total) else 'error',
                }],
            },
        }
