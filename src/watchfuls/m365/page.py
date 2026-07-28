#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: the /m365 section and the Overview widget
#
"""Turning stored results into the shapes the front-end consumes.

Unlike the azure module, m365 ships its own renderer (``web/_ui.html``); this file is the
data half it reads.  The result-key convention is ``<uid>/<suffix>[/…]`` (see the check
methods), so the KIND is the path segment after the first ``/`` — that one rule is what
lets a single grouping serve nine different checks.

Both halves of the page answer in the same shape on purpose: ``page_data`` (the monitor's
last results, instant and free) and ``page_refresh`` (a live run against Graph) share
``_page_sections``, so the page swaps one for the other without a second renderer.
"""

from lib.modules.page_support import lang_section, modules_dir_for, run_item_once


class M365Page:
    """Section page (schema ``__page__`` → /m365) and Overview widget."""

    # Sections whose numbers add up to a fraction the page can draw as a ring. The core
    # renders it; only this module knows WHICH of the measurements a check publishes are the
    # used-vs-total pair (``used`` is a percentage, ``used_bytes`` an absolute — summing the
    # first across sites would be meaningless).
    # Read from what each check actually publishes (checks_storage / checks_identity), not
    # from what the names suggest: check_site reports `total_bytes` while the tenant and
    # OneDrive ones report `limit_bytes`, so one spelling for all three would have silently
    # drawn nothing on two of them.
    #
    # The sections NOT here are the interesting part. Mailboxes over quota publishes
    # `prohibited` / `warned` — two independent counts, not a part and a whole. Licenses
    # publishes only how many SKUs exist; free-vs-enabled is computed per SKU and never
    # reaches the row, so there is nothing here to divide. Secrets publishes days remaining,
    # which has no maximum. A ring over any of those would be a picture of a fraction that
    # does not exist.
    _CHARTS = {
        'site':        {'used': 'used_bytes', 'total': 'total_bytes'},
        'tenant':      {'used': 'used_bytes', 'total': 'limit_bytes'},
        'onedrive':    {'used': 'used_bytes', 'total': 'limit_bytes'},
        'securescore': {'used': 'score',      'total': 'max'},
        'licenses':    {'used': 'assigned',   'total': 'total'},
        'mfa':         {'used': 'registered', 'total': 'total'},
        'unused':      {'used': 'idle',       'total': 'licensed'},
    }

    @classmethod
    def _lang_section(cls, lang: str, section: str) -> dict:
        """A section of the module's lang/ file (fallback en_EN) — classmethod-safe
        (reads the file directly, for the widget hook which has no monitor)."""
        return lang_section(__file__, lang, section)

    @classmethod
    def _page_sections(cls, status: dict, lang: str) -> list:
        """Group the check results into one section per KIND, with the numbers each
        check already publishes in ``other_data`` — no extra Graph call.

        Shared by the cached hook (``page_data``) and the live refresh, so both render
        identically; only where ``status`` came from differs."""
        labels = cls._lang_section(lang, 'labels')
        by_kind: dict = {}
        for k, v in (status or {}).items():
            if not isinstance(v, dict) or 'status' not in v:
                continue                                   # bookkeeping-only key
            parts = str(k).split('/')
            kind = parts[1] if len(parts) >= 2 else ''
            if kind:
                by_kind.setdefault(kind, []).append((k, v))
        out = []
        for tog, sfx, _m in cls._SERVICES:                 # stable, declared order
            rows_v = by_kind.get(sfx)
            if not rows_v:
                continue
            rows, n_ok, n_warn, n_err = [], 0, 0, 0
            for key, v in sorted(rows_v, key=lambda kv: kv[0]):
                od = v.get('other_data') or {}
                ok = v.get('status') is True
                state = 'ok' if ok else ('warn' if v.get('severity') == 'warning' else 'error')
                n_ok += ok
                n_warn += state == 'warn'
                n_err += state == 'error'
                rows.append({
                    'key': key,
                    'name': od.get('service') or od.get('name') or key.split('/')[-1],
                    'state': state,
                    'message': v.get('message') or '',
                    # Everything the check measured (used %, free bytes, days_left, score…)
                    # travels as-is: the page renders whatever the module put there.
                    'metrics': {mk: mv for mk, mv in od.items()
                                if mk not in ('name', 'service') and isinstance(mv, (int, float, str))},
                })
            sec = {
                'id': sfx, 'name': labels.get(tog) or sfx,
                'state': 'ok' if not (n_warn or n_err) else ('error' if n_err else 'warn'),
                'counts': {'ok': n_ok, 'warn': n_warn, 'error': n_err, 'total': len(rows)},
                'rows': rows,
            }
            # Which two measurements are a fraction worth drawing as a ring. Only offered
            # when the rows actually carry both — a ring computed from a missing total is a
            # confident-looking zero, which is worse than no ring at all.
            chart = cls._CHARTS.get(sfx)
            if chart and all(any(k in (r.get('metrics') or {}) for r in rows)
                             for k in (chart['used'], chart['total'])):
                sec['chart'] = dict(chart)
            out.append(sec)
        return out

    @staticmethod
    def _totals(sections: list) -> dict:
        """The counts of every section added up — the page's header line."""
        tot = {'ok': 0, 'warn': 0, 'error': 0, 'total': 0}
        for s in sections:
            for k in tot:
                tot[k] += s['counts'][k]
        return tot

    @classmethod
    def page_data(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Data for the module's own section (``__page__`` → ``/m365``).

        The CACHED half of the page: it reads the monitor's last results, so opening the
        section is instant and costs no Graph call. Refreshing live is the ``page_refresh``
        action below. Classmethod-safe (no monitor), like ``overview_widget``."""
        sections = cls._page_sections(status, lang)
        return {
            'sections': sections,
            'counts': cls._totals(sections),
            'live': False,
            # The configured tenants, so the page can offer a per-item refresh.
            'items': [{'key': k, 'label': (it or {}).get('label') or k}
                      for k, it in (items or {}).items()
                      if isinstance(it, dict) and it.get('enabled', True)],
            'labels': cls._lang_section(lang, 'labels'),
            'ui': cls._lang_section(lang, 'ui'),
        }

    @classmethod
    def page_refresh(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/m365/page_refresh — the LIVE half.

        Runs the item's enabled checks against Graph right now and returns the same shape
        as ``page_data``, so the page swaps one for the other without a second renderer.
        Read-only: it queries Microsoft, it changes nothing here."""
        lang = str((config or {}).get('_lang') or 'en_EN')
        raw, err = run_item_once('m365', config, modules_dir=modules_dir_for(__file__),
                                 default_key='page')
        if err:
            return {'ok': False, 'message': err}
        # run_module_check returns a flat list of results; rebuild the status shape the
        # section grouping expects ({key: {status, severity, message, other_data}}).
        status = {str(r.get('key')): r for r in (raw or []) if isinstance(r, dict)}
        sections = cls._page_sections(status, lang)
        return {'ok': True, 'sections': sections, 'counts': cls._totals(sections), 'live': True}

    @classmethod
    def _widget_ratio(cls, sfx: str, rows_v: list) -> dict | None:
        """The used/total pair for a check kind, summed across its results.

        The Overview card for a kind is an aggregate by nature — it already says "N of M
        OK" — so summing the fraction asks the same kind of question: how full is what this
        kind measures, across everything monitored. That is NOT true on the module page,
        where the ring is drawn per row precisely because summing the sites hides which one
        is filling up; the two views are answering different questions on purpose.

        Returns None unless EVERY result carries both measurements. A ratio computed from a
        missing total is a confident-looking zero, and a card is the worst place for one.
        """
        spec = cls._CHARTS.get(sfx)
        if not spec:
            return None
        used = total = 0.0
        for v in rows_v:
            od = v.get('other_data') or {}
            try:
                u, t = float(od[spec['used']]), float(od[spec['total']])
            except (KeyError, TypeError, ValueError):
                return None
            used += u
            total += t
        if not total > 0:
            return None
        return {'used': used, 'total': total,
                'pct': round(min(100.0, max(0.0, used * 100.0 / total)), 1)}

    @classmethod
    def overview_widget(cls, items: dict, status: dict, lang: str = 'en_EN') -> dict:
        """Overview-widget data: ONE entry per check KIND (Service health, Licenses,
        OneDrive, …) aggregated across every m365 item, so the widget's scope selector
        offers "all" plus each kind (e.g. just Service health). A kind with several
        results (service health = one per service) lists them as rows."""
        labels = cls._lang_section(lang, 'labels')
        wlbl = cls._lang_section(lang, 'widget')
        by_kind: dict = {}
        for k, v in (status or {}).items():
            if not isinstance(v, dict) or 'status' not in v:
                continue                                   # skip bookkeeping-only keys
            parts = str(k).split('/')
            kind = parts[1] if len(parts) >= 2 else ''
            if kind:
                by_kind.setdefault(kind, []).append(v)
        entries = []
        tot_ok = tot_warn = tot_err = tot = 0
        agg_ok = True
        for _tog, sfx, _m in cls._SERVICES:              # stable, declared order
            rows_v = by_kind.get(sfx)
            if not rows_v:
                continue
            n_total = len(rows_v)
            n_ok = sum(1 for v in rows_v if v.get('status') is True)
            n_warn = sum(1 for v in rows_v
                         if v.get('status') is False and (v.get('severity') or '') == 'warning')
            n_err = n_total - n_ok - n_warn
            hard = n_err > 0
            tot += n_total
            tot_ok += n_ok
            tot_warn += n_warn
            tot_err += n_err
            ok = n_ok == n_total
            if not ok:
                agg_ok = False
            # Several results for one kind (per-service health) → list each as a row.
            rows = []
            if n_total > 1:
                for v in rows_v:
                    od = v.get('other_data') or {}
                    st = ('ok' if v.get('status') is True
                          else ('warn' if (v.get('severity') or '') == 'warning' else 'error'))
                    one = cls._widget_ratio(sfx, [v])
                    rows.append({'name': od.get('service') or od.get('name') or '',
                                 'state': st, 'detail': '',
                                 **({'chart': one} if one else {})})
            ratio = cls._widget_ratio(sfx, rows_v)
            entries.append({
                'id': sfx,
                'name': labels.get(_tog) or sfx,
                'ok': ok,
                'state': 'ok' if ok else ('error' if hard else 'warn'),   # for the card colour
                'stats': [{'label': wlbl.get('ok', 'OK'), 'value': f'{n_ok}/{n_total}',
                           'state': 'ok' if ok else ('error' if hard else 'warn')}],
                'counts': {'ok': n_ok, 'warn': n_warn, 'error': n_err, 'total': n_total},
                'rows': rows,
                **({'chart': ratio} if ratio else {}),
            })
        return {
            'entries': entries,
            'aggregate': {
                'count_label': wlbl.get('checks', 'Checks'),
                'count': len(entries),
                'ok': agg_ok,
                'stats': [{'label': wlbl.get('ok', 'OK'), 'value': f'{tot_ok}/{tot}',
                           'state': 'ok' if (tot and tot_ok == tot) else 'error'}],
                'counts': {'ok': tot_ok, 'warn': tot_warn, 'error': tot_err, 'total': tot},
            },
        }
