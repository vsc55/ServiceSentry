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
from lib.util import fmt_bytes


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
        # The tenant check used to publish `limit_bytes` — an alert threshold, not a
        # capacity — so its ring drew "used against the number you wanted to be warned at",
        # which is not a fraction of anything. It now sums every site's quota and publishes a
        # real `total_bytes`, the same pair the per-site check uses.
        'tenant':      {'used': 'used_bytes', 'total': 'total_bytes'},
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
                # What the row is made of, when the check published it (SharePoint's sites).
                # It travels outside `metrics` because that is scalars only — a list would be
                # dropped by the filter above and never reach the page.
                if isinstance(od.get('breakdown'), dict):
                    rows[-1]['breakdown'] = od['breakdown']
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
        # Nothing this run produces is written anywhere, so the caps that keep a stored check
        # result small do not apply: a per-site list that the admin asked for by hand comes
        # back whole, however many rows the item chose to store on its cycle (even none).
        config = {**(config or {}), '_live': True}
        raw, err = run_item_once('m365', config, modules_dir=modules_dir_for(__file__),
                                 default_key='page')
        if err:
            return {'ok': False, 'message': err}
        # run_module_check returns a flat list of results; rebuild the status shape the
        # section grouping expects ({key: {status, severity, message, other_data}}).
        status = {str(r.get('key')): r for r in (raw or []) if isinstance(r, dict)}
        sections = cls._page_sections(status, lang)
        return {'ok': True, 'sections': sections, 'counts': cls._totals(sections), 'live': True}

    # The Storage view's columns. Declared here because what a column MEANS is module
    # knowledge; the core is told the id, the label key and the kind, and lays it out.
    # `filter` marks a column worth a dropdown: the core fills it with the values actually
    # present, so it offers no choice that matches nothing and learns no vocabulary of ours.
    # Tenant and kind are the two axes this table is read along — "of my SharePoint, which
    # site" and "of this tenant, what".
    _STORAGE_COLS = (
        ('tenant', 'col_tenant', 'text', True),
        ('kind',   'col_kind',   'text', True),
        ('name',   'col_name',   'text', False),
        ('used',   'col_used',   'num',  False),
        ('quota',  'col_quota',  'num',  False),
        ('share',  'col_share',  'pct',  False),
        ('full',   'col_full',   'pct',  False),
    )

    @classmethod
    def storage_report(cls, config: dict) -> dict:
        """POST /api/v1/modules/watchfuls/m365/storage_report — the Storage view's data.

        One row per PLACE storage is going: every SharePoint site and every OneDrive
        account, side by side in one table, which is the question this view exists for —
        the status page answers "is it all right", this one answers "where is it going".

        Live and unstored: it runs the two storage checks now, with the caps lifted (see
        ``_live``), and keeps nothing. There is no history here because there is nothing
        to keep — a table of who holds what is a photograph, and the monitor's own checks
        are what carry the alerting and the trend.
        """
        lang = str((config or {}).get('_lang') or 'en_EN')
        tenant = str((config or {}).get('label') or (config or {}).get('_item_key') or '')
        # Only the storage checks: this view asks a storage question, and running the
        # licence/health/identity checks to answer it would spend a dozen Graph calls a
        # reader did not ask for.
        cfg = {**(config or {}), '_live': True, 'check_site': False,
               'check_health': False, 'check_licenses': False, 'check_secrets': False,
               'check_mailbox': False, 'check_secure_score': False,
               'check_risky_users': False, 'check_mfa': False,
               'check_unused_licenses': False, 'check_privileged': False,
               'check_domains': False, 'check_announcements': False}
        raw, err = run_item_once('m365', cfg, modules_dir=modules_dir_for(__file__),
                                 default_key='storage')
        if err:
            return {'ok': False, 'columns': [], 'rows': [], 'message': err}
        ui = cls._lang_section(lang, 'ui')
        columns = [{'id': cid, 'label': ui.get(key) or cid, 'kind': kind, 'filter': filt}
                   for cid, key, kind, filt in cls._STORAGE_COLS]
        rows = []
        for res in (raw or []):
            if not isinstance(res, dict):
                continue
            od = res.get('other_data') or {}
            bd = od.get('breakdown')
            if not isinstance(bd, dict):
                continue
            kind = ui.get('kind_onedrive') or 'OneDrive' \
                if str(res.get('key') or '').endswith('/onedrive') \
                else (ui.get('kind_sharepoint') or 'SharePoint')
            rows.extend(cls._storage_rows(bd, tenant, kind))
        return {
            'ok': True, 'columns': columns, 'rows': rows, 'message': f'{len(rows)}',
            # Which column names a row, which one is its magnitude and which one groups it.
            # Without this the core would be guessing which of six columns is worth drawing,
            # and a bar of the wrong column is worse than no bar — so declaring it is what
            # unlocks the bar and grouped layouts.
            'layout': {'label': 'name', 'value': 'used', 'group': 'kind'},
        }

    @staticmethod
    def _storage_rows(breakdown: dict, tenant: str, kind: str) -> list:
        """A breakdown's items as table rows.

        The breakdown already carries a formatted size and a percentage — the same numbers
        the collapsible list draws — so this is a reshape, not a second measurement: one
        source, two layouts, and no way for them to disagree.

        ``{v, s}`` where the two differ: `v` is what sorts and `s` is what is read, which is
        how "3.0 TB" sorts as its bytes without the core learning what a byte is.
        """
        out = []
        for it in (breakdown.get('items') or []):
            used = int(it.get('bytes') or 0)
            quota = int(it.get('quota_bytes') or 0)
            share = float(it.get('share') or 0)
            full = it.get('full')
            out.append({
                'tenant': tenant, 'kind': kind, 'name': str(it.get('name') or ''),
                'used':  {'v': used,  's': fmt_bytes(used)},
                # No quota is "—", never 0 bytes: under automatic site storage management
                # SharePoint assigns every site the 25 TB ceiling, which is not a limit
                # anybody set — printing it would invent one.
                'quota': {'v': quota, 's': fmt_bytes(quota) if quota else '—'},
                # Two readings, two columns: how much of the whole this row is, and how close
                # it is to its own limit. One column could only ever mean one of them, and it
                # meant a different one on each half of the table.
                # Of its OWN service, not of the two added together. A share of everything
                # is arithmetic nobody asked for: the question a row provokes is "how much of
                # my SharePoint is this site eating", and dividing it by SharePoint plus
                # OneDrive answers a question with no operational meaning — you cannot move a
                # site into OneDrive. The `kind` column and its filter are what keep the two
                # halves apart; the column header names the whole.
                'share': {'v': share, 's': f'{share}%'},
                'full':  ({'v': full, 's': f'{full}%'} if full is not None
                          else {'v': -1, 's': '—'}),
            })
        return out

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
