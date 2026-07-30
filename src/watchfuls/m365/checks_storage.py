#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Microsoft 365 watchful: storage
#
"""Where the tenant's data lives, and how close it is to full.

* ``check_site`` — a SharePoint site's drive quota.  Blank ``site`` = the tenant root.
* ``check_tenant_usage`` — tenant-wide SharePoint storage USED.  Graph exposes no pooled
  total, so this alerts on an absolute amount rather than a percentage.
* ``check_onedrive`` — the same, for OneDrive.
* ``check_mailbox`` — Exchange mailboxes over quota.

The last three come from the **reports API**, which answers in CSV rather than JSON and
lags by a day or so; the site check is a live drive read.
"""

from lib.util import fmt_bytes, to_bytes

from ._parse import _csv_col, _csv_int, _csv_max, _csv_sum


class StorageChecks:
    """SharePoint, OneDrive and Exchange capacity."""

    @classmethod
    def _resolve_site(cls, token: str, site: str, timeout: int) -> tuple[str, str]:
        """Resolve a SharePoint site to (id, display).  Blank → the tenant root."""
        site = str(site or '').strip()
        if not site:
            s = cls._graph_json(token, '/sites/root', timeout)
            return str(s.get('id') or ''), str(s.get('displayName') or s.get('name') or 'root')
        url = site.replace('https://', '').replace('http://', '').strip('/')
        host, _, rel = url.partition('/')
        path = f'/sites/{host}:/{rel}' if rel else f'/sites/{host}'
        s = cls._graph_json(token, path, timeout)
        return str(s.get('id') or ''), str(s.get('displayName') or s.get('name') or site)

    def _check_site(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        try:
            site_id, disp = self._resolve_site(token, it.get('site'), timeout)
            drive = self._graph_json(token, f'/sites/{site_id}/drive?$select=quota,name', timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/site', False, self._msg('m3_site_fail', label, exc),
                       {'name': f'{label} · SharePoint'})
            return
        q = (drive or {}).get('quota') or {}
        total = int(q.get('total') or 0)
        used = int(q.get('used') or 0)
        remaining = int(q['remaining']) if q.get('remaining') is not None else max(total - used, 0)
        used_pct = round(used / total * 100, 1) if total else 0.0

        # Thresholds inherit the module-level defaults when the item leaves them
        # blank (0) — same item → module → global chain as alert/timeout.
        usage_pct = int(it.get('usage_pct') or 0) \
            or self.module_default('usage_pct', self._MODULE_DEFAULTS.get('usage_pct', 0))
        # Free-space threshold: an explicit per-item value keeps its own unit;
        # a blank one inherits the module default in the module's unit.
        if it.get('free_min'):
            free_min = to_bytes(it.get('free_min'), it.get('free_unit') or 'GB')
        else:
            free_min = to_bytes(
                self.module_default('free_min', self._MODULE_DEFAULTS.get('free_min', 0)),
                self.get_conf('free_unit', self._MODULE_DEFAULTS.get('free_unit', 'GB')))
        over_pct = usage_pct > 0 and used_pct >= usage_pct
        low_free = free_min > 0 and remaining < free_min
        extra = {'name': f'{label} · SharePoint ({disp})', 'used': used_pct,
                 'used_bytes': used, 'total_bytes': total, 'free_bytes': remaining, 'site': disp}
        # Only advertise a Status-bar threshold when the % alert is actually set —
        # otherwise the bar shows no marker and stays neutral (no misleading "/ 90%"
        # nor early red). See __status_render__ (default_threshold 100).
        if usage_pct > 0:
            extra['alert'] = usage_pct
        summary = self._msg('m3_summary', disp, used_pct,
                            fmt_bytes(used), fmt_bytes(total), fmt_bytes(remaining))
        if not (over_pct or low_free):
            self._emit(f'{key}/site', True, self._msg('m3_site_ok', label, summary), extra)
        else:
            why = []
            if over_pct:
                why.append(f'≥ {usage_pct}%')
            if low_free:
                why.append(self._msg('m3_why_free', fmt_bytes(free_min)))
            self._emit(f'{key}/site', False,
                       self._msg('m3_site_alert', label, summary, ', '.join(why)),
                       extra, severity='warning')

    # Fallbacks for the two per-site bounds, used only when the schema is unreadable — the
    # real values are `sites_top`/`sites_page` in __module__, overridable per item.
    _SITES_TOP = 25
    _SITES_PAGE = 25

    def _sites_kept(self, it: dict) -> int:
        """How many per-site rows this item STORES in a check result.

        Three states, and they are three different intentions: blank inherits the module's
        value (the ordinary case), a number caps the list, and **0 stores none** — the
        breakdown is diagnostic context, not a measurement, so a tenant nobody drills into
        need not write its site list to the database on every cycle for ever. It is still one
        click away: the page's live refresh queries Graph and builds the list in full.

        `inherit_blank` is what makes the three distinguishable — clearing the field stores
        null, and an explicit 0 stays a real value rather than collapsing into "unset".
        """
        raw = it.get('sites_top')
        if raw in (None, ''):
            return max(self.module_default('sites_top', self._SITES_TOP), 0)
        try:
            return max(int(raw), 0)
        except (TypeError, ValueError):
            return self._SITES_TOP

    def _tenant_totals(self, token: str, timeout: int):
        """``(used, allocated, sites, deleted, rows)`` for SharePoint across the whole tenant.

        The **detail** report is one row per SITE and carries both what each one uses and the
        quota it was given, so summing it answers "how full is SharePoint" — a question the
        storage report cannot, because it only publishes bytes used. Keeping the rows also
        answers the question that always follows: which sites.

        A site in the recycle bin still occupies the tenant's storage until it is purged, so
        its bytes stay in the sum; how many there are is reported separately, because "12 TB
        used, 4 of those sites deleted" is a different conversation from "12 TB used".
        """
        text = self._graph_text(
            token, "/reports/getSharePointSiteUsageDetail(period='D7')", timeout)
        rows, i_used = _csv_col(text, 'Storage Used (Byte)')
        _, i_alloc = _csv_col(text, 'Storage Allocated (Byte)')
        _, i_url = _csv_col(text, 'Site URL')
        _, i_id = _csv_col(text, 'Site Id')
        _, i_del = _csv_col(text, 'Is Deleted')
        sites = []

        def _cell(r, idx):
            return r[idx].strip() if 0 <= idx < len(r) else ''

        for r in rows[1:]:
            if not any((c or '').strip() for c in r):
                continue
            # The tenant can hide identifiable data in reports ("Display concealed user, group
            # and site names", Microsoft 365 admin centre → Settings → Reports). With it on,
            # Graph returns the bytes and blanks the URL — which is how this list ended up as a
            # column of dashes. What is left is kept as the label and as a join key, but a
            # HASH is not a name: the owner's is shared by every site that person owns, and a
            # concealed site id comes back as the zero GUID, identical on every row. Neither
            # is an identifier, so neither is shown — `_site_breakdown` numbers instead.
            sid = _cell(r, i_id)
            if not sid.replace('-', '').strip('0'):
                sid = ''
            sites.append({
                'name': _cell(r, i_url),
                'sid': sid,
                'anon': not _cell(r, i_url),
                'used': _csv_int(r, i_used),
                'quota': _csv_int(r, i_alloc),
                'deleted': _cell(r, i_del).lower() == 'true',
            })
        return (_csv_sum(text, 'Storage Used (Byte)'),
                _csv_sum(text, 'Storage Allocated (Byte)'),
                len(sites),
                sum(1 for s in sites if s['deleted']),
                sites)

    # How many sites are worth measuring one by one when the report cannot name them. Sent
    # 20 per $batch, so this is 10 round-trips at the ceiling; beyond it the anonymous list
    # is the honest answer rather than a check that spends a minute naming things.
    _SITES_PROBE_MAX = 200

    @staticmethod
    def _site_label(s: dict) -> str:
        """What to call a site in a list that is entirely one tenant's.

        The host is the same on every row — repeating ``contoso.sharepoint.com`` eighteen
        times pushes the part that differs off to the right and makes the column harder to
        scan, not more precise.  ``/sites/`` goes with it: it is the DEFAULT managed path, so
        it says nothing; ``/teams/`` and ``/personal/`` are kept, because those do.

        The root site has no path at all and is the one row where the host IS the name.
        """
        web = str(s.get('webUrl') or '').strip()
        url = web.replace('https://', '').replace('http://', '').rstrip('/')
        host, _, rel = url.partition('/')
        if not rel:
            return str(s.get('displayName') or s.get('name') or host)
        return rel[len('sites/'):] if rel.lower().startswith('sites/') else rel

    def _identify_sites(self, sites: list, token: str, timeout: int) -> tuple[list, bool]:
        """Get names onto the per-site rows the usage report would not name.

        Only one of the two APIs is affected by the tenant's "Display concealed user, group
        and site names": that setting belongs to REPORTS, while ``/sites`` — the same
        enumeration the site field's discover button uses — keeps publishing names and URLs.
        So there are two ways across, tried in that order:

        1. **Join.** The report's ``Site Id`` is the site-collection GUID and the Sites API id
           is ``host,<site-collection GUID>,<web GUID>``.  One extra call for the whole list.
        2. **Measure.** A tenant can conceal the id too, and then it arrives as the zero GUID
           — identical on every row, nothing to join on.  In that case the sites themselves
           are asked how full they are (``/sites/{id}/drive``), batched 20 per request: the
           names are real and so are the figures, which is a better list than a numbered one.

        Returns the rows to break down and whether they came from path 2 (the caller says so,
        because those rows are a different measurement from the report's).  Nothing here runs
        for a tenant that publishes its URLs.
        """
        if not [s for s in sites if s['anon']]:
            return sites, False
        listed = self._enumerate_sites(token, timeout)
        by_guid = {}
        for s in listed:
            parts = str(s.get('id') or '').split(',')
            guid = (parts[1] if len(parts) >= 2 else '').replace('-', '').strip().lower()
            if guid:
                by_guid[guid] = self._site_label(s)
        named = 0
        for s in sites:
            if not (s['anon'] and s['sid']):
                continue
            name = by_guid.get(s['sid'].replace('-', '').strip().lower())
            if name:
                s['name'], s['anon'] = name, False
                named += 1
        if named:
            return sites, False
        measured = self._measure_sites(listed, token, timeout)
        return (measured, True) if measured else (sites, False)

    def _measure_sites(self, listed: list, token: str, timeout: int) -> list:
        """Per-site usage read from the SITES themselves, in the report's row shape.

        The drive quota is a live read of each site collection, so it neither lags a day nor
        obeys the reports' concealment.  Sites in the recycle bin are not enumerated, which
        is why this is a fallback and never the source of the tenant TOTAL: that stays the
        report's sum, deleted sites included.
        """
        if not listed or len(listed) > self._SITES_PROBE_MAX:
            return []
        names = {}
        for s in listed:
            sid = str(s.get('id') or '').strip()
            if sid:
                names[f'/sites/{sid}/drive?$select=quota'] = self._site_label(s)
        rows = []
        for path, body in self._graph_batch(token, list(names), timeout).items():
            quota = (body or {}).get('quota') or {}
            if quota.get('used') is None:
                continue                      # a site with no document library says nothing
            rows.append({'name': names.get(path, ''), 'sid': '', 'anon': False,
                         'used': int(quota.get('used') or 0),
                         'quota': int(quota.get('total') or 0), 'deleted': False})
        return rows

    def _site_breakdown(self, sites: list, total: int, probed: bool = False,
                        limit: int = None, page: int = 0) -> dict:
        """The per-site list the page can unfold: who is occupying the total, biggest first.

        The percentage is each site's share of the TENANT total, not of its own quota — that
        is the question this list is opened with ("of the whole, how much is this one"), and
        the site's own quota is beside it as text for the cases where it matters.

        …of the total OR of what is actually occupied, whichever is larger.  A tenant can be
        over its capacity (a typed `tenant_max` that is out of date, or a real overage), and
        then a share of capacity exceeds 100 % for the big sites: the bar clamps them and a
        3.4 TB site is drawn exactly like a 1.0 TB one.  Falling back to the occupied total
        keeps the bars proportional to each other and still summing to the whole — the ring
        above is where "667 % of capacity" belongs, not here.

        `limit` is how many rows are worth STORING and `page` how many are worth DRAWING at
        once; the two are different questions and only the first costs anything per cycle.
        `limit=None` keeps every row, which is what a live read wants: it is not stored.
        """
        base = max(total, sum(s['used'] for s in sites))
        ordered = sorted(sites, key=lambda s: s['used'], reverse=True)
        top = ordered[:limit] if limit else ordered
        items = []
        seen: dict = {}
        for i, s in enumerate(top, 1):
            text = fmt_bytes(s['used'])
            if s['quota']:
                text = self._msg('m3_sp_site_of_quota', text, fmt_bytes(s['quota']))
            # Numbered when the tenant conceals every identifier: rows that all read "—" are
            # indistinguishable, and "site 3" at least lets one be pointed at.
            name = s['name'] or self._msg('m3_sp_site_n', i)
            # …and numbered too when the identifier that survived is SHARED. A concealed
            # report can hand back the same hash for several rows, and a list where five
            # lines read identically is worse than one that admits it cannot name them: it
            # looks like the same site listed five times.
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                name = self._msg('m3_sp_site_dup', name, seen[name])
            items.append({
                'name': name + (' 🗑' if s['deleted'] else ''),
                'text': text,
                'pct': round(s['used'] / base * 100, 1) if base else 0.0,
            })
        out = {'label': self._msg('m3_sp_breakdown'), 'items': items,
               'more': max(len(sites) - len(top), 0)}
        if page:
            out['page'] = page
        # Say once where these rows come from, instead of leaving the reader to reconcile
        # them with the total on their own. Either the sites were measured directly (real
        # names, but no deleted ones and a live figure rather than the report's), or nothing
        # could name them — and then the reason is a tenant setting worth naming.
        if probed:
            out['note'] = self._msg('m3_sp_from_api')
        elif sites and all(s['anon'] for s in sites):
            out['note'] = self._msg('m3_sp_anon')
        return out

    def _check_tenant(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """SharePoint across every site: how much of the total is occupied.

        Warns at a percentage and/or at an absolute amount used, and **fails** at 100 % —
        full is not a warning, it is the point where writes start being refused.
        """
        name = f'{label} · SharePoint (tenant)'
        try:
            used, allocated, sites, deleted, rows = self._tenant_totals(token, timeout)
        except Exception as exc:  # pylint: disable=broad-except
            # The detail report needs the same permission as the storage one and answers a
            # superset, so a failure here is a real failure — not worth a silent fallback that
            # would quietly go back to reporting bytes with no total.
            self._emit(f'{key}/tenant', False, self._msg('m3_tenant_fail', label, exc),
                       {'name': name})
            return

        # The capacity Graph will not tell us. The pooled tenant quota is 1 TB + 10 GB per
        # licensed user and no endpoint publishes it, so the admin may type it; blank falls
        # back to the sum of the per-site quotas, which is what the sites are allowed to use.
        manual = to_bytes(it.get('tenant_max'), it.get('tenant_unit') or 'TB')
        total = manual or allocated
        used_pct = round(used / total * 100, 1) if total else 0.0
        free = max(total - used, 0) if total else 0

        warn_pct = int(it.get('tenant_pct') or 0)
        warn_at = to_bytes(it.get('tenant_warn_at'), it.get('tenant_warn_unit') or 'GB')
        full = total > 0 and used >= total
        over_pct = total > 0 and warn_pct > 0 and used_pct >= warn_pct
        over_abs = warn_at > 0 and used >= warn_at

        extra = {'name': name, 'used_bytes': used, 'sites': sites, 'deleted': deleted,
                 'source': 'manual' if manual else ('sites' if allocated else 'none')}
        if total:
            extra.update({'used': used_pct, 'total_bytes': total, 'free_bytes': free})
        # Who is occupying it. The total answers "how much"; this is the question that always
        # follows, and without it the only way to ask is to add a per-site check per site.
        # A live read from the page is not stored anywhere, so the cap that exists to keep
        # check results small has nothing to protect: it answers with every site it found.
        live = bool(it.get('_live'))
        kept = self._sites_kept(it)
        if rows and (live or kept):
            # Names first, when the report concealed them — and only if it did.
            probed = False
            try:
                rows, probed = self._identify_sites(rows, token, timeout)
            except Exception:  # pylint: disable=broad-except
                pass          # a naming failure must never cost the measurement
            extra['breakdown'] = self._site_breakdown(
                rows, total, probed, None if live else kept,
                max(self.module_default('sites_page', self._SITES_PAGE), 1))
        # Only advertise a Status-bar threshold when the % alert is actually set, so the bar
        # stays neutral instead of showing a marker nobody asked for (see __status_render__).
        if warn_pct > 0:
            extra['alert'] = warn_pct

        if not total:
            # Nothing to divide by: report the amount and say so, rather than invent a 0 %.
            self._emit(f'{key}/tenant', True,
                       self._msg('m3_sp_no_total', label, fmt_bytes(used), sites), extra)
            return
        summary = self._msg('m3_sp_summary', sites, fmt_bytes(used), fmt_bytes(total),
                            used_pct, fmt_bytes(free))
        if full:
            self._emit(f'{key}/tenant', False, self._msg('m3_sp_full', label, summary), extra)
            return
        why = []
        if over_pct:
            why.append(self._msg('m3_why_pct', warn_pct))
        if over_abs:
            why.append(self._msg('m3_why_used', fmt_bytes(warn_at)))
        if why:
            self._emit(f'{key}/tenant', False,
                       self._msg('m3_sp_warn', label, summary, ', '.join(why)),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/tenant', True, self._msg('m3_sp_ok', label, summary), extra)

    def _check_mailbox(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Exchange mailboxes over quota (reports API): warn when the number of
        send/receive-prohibited mailboxes exceeds ``mailbox_over_max``."""
        try:
            text = self._graph_text(
                token, "/reports/getMailboxUsageQuotaStatusMailboxCounts(period='D7')", timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/mailbox', False, self._msg('m3_mbx_fail', label, exc),
                       {'name': f'{label} · Mailboxes over quota'})
            return
        prohibited = _csv_max(text, 'Send Prohibited') + _csv_max(text, 'Send/Receive Prohibited')
        warned = _csv_max(text, 'Warning Issued')
        threshold = int(it.get('mailbox_over_max') or 0)
        extra = {'name': f'{label} · Mailboxes over quota', 'prohibited': prohibited, 'warned': warned}
        if prohibited > threshold:
            self._emit(f'{key}/mailbox', False, self._msg('m3_mbx_over', label, prohibited, warned),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/mailbox', True, self._msg('m3_mbx_ok', label, warned), extra)

    def _check_onedrive(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Tenant-wide OneDrive storage USED (reports API): warn when it exceeds
        ``onedrive_max`` (0 = informational only)."""
        try:
            text = self._graph_text(token, "/reports/getOneDriveUsageStorage(period='D7')", timeout)
            used = _csv_max(text, 'Storage Used (Byte)')
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/onedrive', False, self._msg('m3_od_fail', label, exc),
                       {'name': f'{label} · OneDrive (tenant)'})
            return
        omax = to_bytes(it.get('onedrive_max'), it.get('onedrive_unit') or 'TB')
        extra = {'name': f'{label} · OneDrive (tenant)', 'used_bytes': used, 'limit_bytes': omax}
        base = self._msg('m3_od_base', label, fmt_bytes(used))
        if omax > 0 and used > omax:
            self._emit(f'{key}/onedrive', False, self._msg('m3_od_over', base, fmt_bytes(omax)),
                       extra, severity='warning')
        else:
            suffix = self._msg('m3_od_limit_suffix', fmt_bytes(omax)) if omax else ''
            self._emit(f'{key}/onedrive', True, base + suffix + ' ✅', extra)
