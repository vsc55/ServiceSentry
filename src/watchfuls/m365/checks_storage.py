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
        site_usage_pct = int(it.get('site_usage_pct') or 0) \
            or self.module_default('site_usage_pct', self._MODULE_DEFAULTS.get('site_usage_pct', 0))
        # Free-space threshold: an explicit per-item value keeps its own unit;
        # a blank one inherits the module default in the module's unit.
        if it.get('site_free_min'):
            site_free_min = to_bytes(it.get('site_free_min'), it.get('site_free_unit') or 'GB')
        else:
            site_free_min = to_bytes(
                self.module_default('site_free_min', self._MODULE_DEFAULTS.get('site_free_min', 0)),
                self.get_conf('site_free_unit', self._MODULE_DEFAULTS.get('site_free_unit', 'GB')))
        over_pct = site_usage_pct > 0 and used_pct >= site_usage_pct
        low_free = site_free_min > 0 and remaining < site_free_min
        extra = {'name': f'{label} · SharePoint ({disp})', 'used': used_pct,
                 'used_bytes': used, 'total_bytes': total, 'free_bytes': remaining, 'site': disp}
        # Only advertise a Status-bar threshold when the % alert is actually set —
        # otherwise the bar shows no marker and stays neutral (no misleading "/ 90%"
        # nor early red). See __status_render__ (default_threshold 100).
        if site_usage_pct > 0:
            extra['alert'] = site_usage_pct
        summary = self._msg('m3_summary', disp, used_pct,
                            fmt_bytes(used), fmt_bytes(total), fmt_bytes(remaining))
        if not (over_pct or low_free):
            self._emit(f'{key}/site', True, self._msg('m3_site_ok', label, summary), extra)
        else:
            why = []
            if over_pct:
                why.append(f'≥ {site_usage_pct}%')
            if low_free:
                why.append(self._msg('m3_why_free', fmt_bytes(site_free_min)))
            self._emit(f'{key}/site', False,
                       self._msg('m3_site_alert', label, summary, ', '.join(why)),
                       extra, severity='warning')

    # SharePoint Online's hard ceiling for ONE site collection. Under automatic site storage
    # management — the default — Microsoft assigns every site exactly this, because it is not
    # reserving anything: the real limit is the pooled tenant quota. So a site sitting at this
    # number has NO quota of its own, and reading it as one is how a sum of ceilings ends up
    # posing as a capacity.
    #
    # Kept as a fallback, not as the answer: `_storage_is_automatic` asks the tenant outright
    # (`/admin/sharepoint/settings`). Inferring a setting from a number that happens to equal
    # its consequence works until the day Microsoft raises the ceiling.
    _SITE_QUOTA_CEILING = 25 * 1024 ** 4

    def _sp_settings(self, token: str, timeout: int) -> tuple:
        """``(automatic, ceiling)`` from the tenant's own SharePoint settings.

        Two facts this check used to guess at, asked outright:

        * ``isSitesStorageLimitAutomatic`` decides whether the per-site quotas mean anything.
          Under automatic management they are all the ceiling and their sum is not a capacity;
          under manual management a 25 TB quota is a real 25 TB quota. Nothing else can tell
          the two apart, and inferring one from a number that happens to equal its consequence
          works right up until Microsoft changes the number.
        * ``siteCreationDefaultStorageLimitInMB`` IS that ceiling, in the tenant's own words —
          so the hardcoded 25 TB drops to being the fallback it should always have been.

        `(None, 0)` when the tenant will not say: no ``SharePointTenantSettings.Read.All``, or
        any other failure. The caller then falls back to what it could always do.

        What is NOT here is the one number this check actually wants. Verified against a live
        tenant: 28 settings, three about storage, none of them the pooled tenant quota. That
        figure exists only behind the SharePoint admin API — see `tenant_capacity`.
        """
        try:
            data = self._graph_json(token, '/admin/sharepoint/settings', timeout) or {}
        except Exception:  # pylint: disable=broad-except
            return None, 0
        auto = data.get('isSitesStorageLimitAutomatic')
        ceiling = int(data.get('siteCreationDefaultStorageLimitInMB') or 0) * 1024 ** 2
        return (bool(auto) if isinstance(auto, bool) else None), ceiling

    # Fallbacks for the breakdown bounds, used only when the schema is unreadable — the real
    # values are `sites_top` / `accounts_top` / `breakdown_page` in __module__, the first two
    # overridable per item.
    _SITES_TOP = 25
    _SITES_PAGE = 25

    # The two vocabularies a breakdown can speak. Same list, same maths, different nouns: one
    # is naming sites and the other is naming PEOPLE, and a message that calls a person "site
    # 4" is not a translation away from right. Kept side by side so the pair can be read at
    # once rather than reconstructed from a prefix.
    _SP_KEYS = {'label': 'm3_sp_breakdown', 'row_n': 'm3_sp_site_n', 'dup': 'm3_sp_site_dup',
                'of_quota': 'm3_sp_site_of_quota', 'anon': 'm3_sp_anon',
                'measured': 'm3_sp_from_api'}
    _OD_KEYS = {'label': 'm3_od_breakdown', 'row_n': 'm3_od_acct_n', 'dup': 'm3_od_acct_dup',
                'of_quota': 'm3_sp_site_of_quota', 'anon': 'm3_od_anon',
                'measured': 'm3_od_from_api'}

    def _rows_kept(self, it: dict, field: str) -> int:
        """How many breakdown rows this item STORES in a check result.

        Three states, and they are three different intentions: blank inherits the module's
        value (the ordinary case), a number caps the list, and **0 stores none** — the
        breakdown is diagnostic context, not a measurement, so a tenant nobody drills into
        need not write its site list to the database on every cycle for ever. It is still one
        click away: the page's live refresh queries Graph and builds the list in full.

        `inherit_blank` is what makes the three distinguishable — clearing the field stores
        null, and an explicit 0 stays a real value rather than collapsing into "unset".

        Per breakdown, not per module, because they are not the same decision: the OneDrive
        list names PEOPLE and how much each one keeps, which is a different thing to write to
        a database every five minutes than a list of site URLs.
        """
        raw = it.get(field)
        if raw in (None, ''):
            return max(self.module_default(field, self._SITES_TOP), 0)
        try:
            return max(int(raw), 0)
        except (TypeError, ValueError):
            return self._SITES_TOP

    def _breakdown_page(self) -> int:
        """How many rows the page draws at once. Module-wide: it is presentation, and the
        same eyes read both lists."""
        return max(self.module_default('breakdown_page', self._SITES_PAGE), 1)

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
        # Asked once, before reading a single row: the tenant's answer decides how to read
        # every quota in the report, and its own ceiling beats our constant.
        automatic, ceiling = self._sp_settings(token, timeout)
        ceiling = ceiling or self._SITE_QUOTA_CEILING
        at_ceiling = False

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
            # is an identifier, so neither is shown — `_usage_breakdown` numbers instead.
            sid = _cell(r, i_id)
            if not sid.replace('-', '').strip('0'):
                sid = ''
            quota = _csv_int(r, i_alloc)
            at_ceiling = at_ceiling or quota >= ceiling
            sites.append({
                'name': _cell(r, i_url),
                'sid': sid,
                'anon': not _cell(r, i_url),
                'used': _csv_int(r, i_used),
                # A site at the per-site ceiling has no quota of its own (see the constant):
                # carrying 25 TB as if it were one puts "of 25.0 TB" on every row and implies
                # a limit nobody set.
                'quota': 0 if quota >= ceiling else quota,
                'deleted': _cell(r, i_del).lower() == 'true',
            })
        # …and the same reasoning at the tenant level, where it matters far more: a sum of
        # ceilings is not a capacity. 65 sites × 25 TB is 1.6 PB, against which any real usage
        # is a comfortable 0 % — a check that can never fire, which is the worst kind. With
        # automatic storage management the honest answer is that Graph published no total, and
        # the admin's typed `tenant_capacity` is the only capacity there is.
        #
        # The tenant's own answer when it gave one; the ceiling is only the symptom, and a
        # site at 25 TB under MANUAL management is a real quota worth summing.
        unlimited = at_ceiling if automatic is None else automatic
        allocated = 0 if unlimited else _csv_sum(text, 'Storage Allocated (Byte)')
        return (_csv_sum(text, 'Storage Used (Byte)'),
                allocated,
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
        measured = self._measure_drives(listed, '/sites', self._site_label, token, timeout)
        return (measured, True) if measured else (sites, False)

    def _measure_drives(self, listed: list, base: str, label, token: str, timeout: int) -> list:
        """Per-object usage read from the OBJECTS themselves, in the report's row shape.

        The drive quota is a live read, so it neither lags a day nor obeys the reports'
        concealment.  What is not enumerated is not measured — sites in the recycle bin,
        accounts of deleted users — which is why this is a fallback and never the source of a
        TOTAL: that stays the report's sum, with those included.

        One method for sites and mailbox accounts because ``/sites/{id}/drive`` and
        ``/users/{id}/drive`` are the same question asked of two collections; only the path
        and what to call a row differ.
        """
        if not listed or len(listed) > self._SITES_PROBE_MAX:
            return []
        names = {}
        for s in listed:
            oid = str(s.get('id') or '').strip()
            if oid:
                names[f'{base}/{oid}/drive?$select=quota'] = label(s)
        rows = []
        for path, body in self._graph_batch(token, list(names), timeout).items():
            quota = (body or {}).get('quota') or {}
            if quota.get('used') is None:
                continue                      # an object with no drive says nothing
            rows.append({'name': names.get(path, ''), 'sid': '', 'anon': False,
                         'used': int(quota.get('used') or 0),
                         'quota': int(quota.get('total') or 0), 'deleted': False})
        return rows

    def _usage_breakdown(self, rows: list, total: int, keys: dict, probed: bool = False,
                         limit: int = None, page: int = 0, own_quota: bool = False) -> dict:
        """The list the page can unfold: who is occupying the total, biggest first.

        The percentage answers a different question for each of the two lists, because the
        storage behind them is shared in one case and not in the other:

        * **SharePoint** sites draw from one POOLED tenant quota, so the share that matters is
          of the whole ("of everything, how much is this one") and the site's own quota is
          beside it as text. The bars then compose with the ring above.
        * **OneDrive** accounts each have their OWN quota — 1 TB, 5 TB — and no pool anyone
          can exhaust between them. A share of the tenant total would say nothing about
          whether that person is about to run out, which is the only per-account question
          worth asking. So with `own_quota` the bar is used-against-that-person's-quota.

        **A list is ordered by what it draws.** Otherwise the order is invisible: with mixed
        quotas, 50 GB of 1 TB (5 %) sorts below 200 GB of 5 TB (4 %) and the column reads as
        unsorted — several rows at 0 % and then, out of nowhere, one at 5 %. So the pooled
        list orders by bytes, which is what its bar shows, and the per-quota one orders by how
        full each row is, which is what ITS bar shows. Bytes break the ties, so where the
        quotas are equal — the ordinary tenant — the two orders are the same list.

        The pooled share is of the total OR of what is actually occupied, whichever is larger.
        A tenant can be over its capacity (a typed `tenant_capacity` that is out of date, or a real
        overage), and then a share of capacity exceeds 100 % for the big sites: the bar clamps
        them and a 3.4 TB site is drawn exactly like a 1.0 TB one.  Falling back to the
        occupied total keeps the bars proportional to each other and still summing to the
        whole — the ring above is where "667 % of capacity" belongs, not here.

        `limit` is how many rows are worth STORING and `page` how many are worth DRAWING at
        once; the two are different questions and only the first costs anything per cycle.
        `limit=None` keeps every row, which is what a live read wants: it is not stored.

        `keys` is the vocabulary (_SP_KEYS / _OD_KEYS): the maths is the same for sites and
        for mailbox accounts, the nouns are not.
        """
        base = max(total, sum(s['used'] for s in rows))

        def _rank(s):
            share = (s['used'] / s['quota']) if (own_quota and s['quota']) else 0.0
            return (share, s['used'])

        ordered = sorted(rows, key=_rank, reverse=True)
        top = ordered[:limit] if limit else ordered
        items = []
        seen: dict = {}
        for i, s in enumerate(top, 1):
            text = fmt_bytes(s['used'])
            if s['quota']:
                text = self._msg(keys['of_quota'], text, fmt_bytes(s['quota']))
            # Numbered when the tenant conceals every identifier: rows that all read "—" are
            # indistinguishable, and "site 3" at least lets one be pointed at.
            name = s['name'] or self._msg(keys['row_n'], i)
            # …and numbered too when the identifier that survived is SHARED. A concealed
            # report can hand back the same hash for several rows, and a list where five
            # lines read identically is worse than one that admits it cannot name them: it
            # looks like the same site listed five times.
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                name = self._msg(keys['dup'], name, seen[name])
            denom = s['quota'] if own_quota else base
            items.append({
                'name': name + (' 🗑' if s['deleted'] else ''),
                'text': text,
                'pct': round(s['used'] / denom * 100, 1) if denom else 0.0,
                # BOTH readings, always, because they answer different questions and the bar
                # can only draw one: `share` is how much of the whole this row is, `full` is
                # how close it is to its own limit — and `full` is None, not 0, where there is
                # no limit to be close to. A zero there would read as "empty".
                'share': round(s['used'] / base * 100, 1) if base else 0.0,
                'full': round(s['used'] / s['quota'] * 100, 1) if s['quota'] else None,
                # The raw figures travel beside the formatted one. The core ignores them —
                # it reads `pct` and prints `text` — but a second layout of the SAME rows
                # (the Storage table) needs numbers to sort by, and parsing "3.0 TB" back
                # into bytes would be inventing a measurement that is right here.
                'bytes': s['used'], 'quota_bytes': s['quota'],
            })
        out = {'label': self._msg(keys['label']), 'items': items,
               'more': max(len(rows) - len(top), 0)}
        if page:
            out['page'] = page
        # Say once where these rows come from, instead of leaving the reader to reconcile
        # them with the total on their own. Either the sites were measured directly (real
        # names, but no deleted ones and a live figure rather than the report's), or nothing
        # could name them — and then the reason is a tenant setting worth naming.
        if probed:
            out['note'] = self._msg(keys['measured'])
        elif rows and all(s['anon'] for s in rows):
            out['note'] = self._msg(keys['anon'])
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

        # The capacity, and there are only two honest answers: what the admin typed, and the
        # sum of real per-site quotas when the tenant manages storage manually. Graph
        # publishes no pooled tenant quota — the SharePoint admin centre reads it from its OWN
        # admin API, a different audience with different credentials.
        #
        # A licence formula lived here for one build: 1 TB + 10 GB per licence, Microsoft's
        # own published numbers. A real tenant killed it — its admin centre reads 300 GB,
        # under the formula's 1 TB FLOOR. An estimate that can be three times the truth is not
        # a capacity, and it errs in the direction that hides a tenant filling up. Reporting
        # no total is worse to look at and better to trust.
        manual = to_bytes(it.get('tenant_capacity'), it.get('tenant_capacity_unit') or 'TB')
        total = manual or allocated
        used_pct = round(used / total * 100, 1) if total else 0.0
        free = max(total - used, 0) if total else 0

        warn_pct = self._threshold(it, 'tenant_pct')
        warn_at = to_bytes(it.get('tenant_warn_at'), it.get('tenant_warn_unit') or 'GB')
        # The third way of asking the same question, and the one an admin actually plans
        # with: not "how full is it" but "how much room is left". A percentage means
        # different amounts as the tenant grows, and 250 GB used means nothing without
        # knowing the capacity — "warn me under 50 GB free" survives both.
        site_free_min = to_bytes(it.get('tenant_free_min'), it.get('tenant_free_unit') or 'GB')
        full = total > 0 and used >= total
        over_pct = total > 0 and warn_pct > 0 and used_pct >= warn_pct
        over_abs = warn_at > 0 and used >= warn_at
        # Only where there IS a capacity: without a total there is no "left", and a
        # threshold that silently never fires is worse than one that was never offered.
        low_free = total > 0 and site_free_min > 0 and free < site_free_min

        extra = {'name': name, 'used_bytes': used, 'sites': sites, 'deleted': deleted,
                 # Where the capacity came from, on the row itself: "667 % full" means one
                 # thing against a number Microsoft implies and another against one somebody
                 # typed in March.
                 'source': 'manual' if manual else ('sites' if allocated else 'none')}
        if total:
            extra.update({'used': used_pct, 'total_bytes': total, 'free_bytes': free})
        # Who is occupying it. The total answers "how much"; this is the question that always
        # follows, and without it the only way to ask is to add a per-site check per site.
        # A live read from the page is not stored anywhere, so the cap that exists to keep
        # check results small has nothing to protect: it answers with every site it found.
        live = bool(it.get('_live'))
        kept = self._rows_kept(it, 'sites_top')
        if rows and (live or kept):
            # Names first, when the report concealed them — and only if it did.
            probed = False
            try:
                rows, probed = self._identify_sites(rows, token, timeout)
            except Exception:  # pylint: disable=broad-except
                pass          # a naming failure must never cost the measurement
            extra['breakdown'] = self._usage_breakdown(
                rows, total, self._SP_KEYS, probed, None if live else kept,
                self._breakdown_page())
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
        if low_free:
            why.append(self._msg('m3_why_free', fmt_bytes(site_free_min)))
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
        threshold = self._threshold(it, 'mailbox_over_max')
        extra = {'name': f'{label} · Mailboxes over quota', 'prohibited': prohibited, 'warned': warned}
        if prohibited > threshold:
            self._emit(f'{key}/mailbox', False, self._msg('m3_mbx_over', label, prohibited, warned),
                       extra, severity='warning')
        else:
            self._emit(f'{key}/mailbox', True, self._msg('m3_mbx_ok', label, warned), extra)

    @staticmethod
    def _account_label(u: dict) -> str:
        """What to call a person's OneDrive. The sign-in name identifies them and is what an
        admin will search the tenant for; the display name is what a human recognises."""
        return str(u.get('userPrincipalName') or u.get('displayName') or '').strip()

    def _enumerate_accounts(self, token: str, timeout: int) -> list:
        """Every account the app can see. Lives here rather than beside ``_enumerate_sites``
        (in actions.py) because no field picker asks for it — only this fallback does."""
        return self._paged(
            token, '/users?$select=id,displayName,userPrincipalName&$top=100', timeout)

    def _onedrive_totals(self, token: str, timeout: int):
        """``(used, accounts, deleted, rows)`` for OneDrive across the whole tenant.

        The **account detail** report is one row per PERSON and carries what each one keeps,
        which the storage report cannot answer: it publishes a tenant total and nothing about
        who makes it up. Same report shape as SharePoint's site detail, so the same reader.
        """
        text = self._graph_text(
            token, "/reports/getOneDriveUsageAccountDetail(period='D7')", timeout)
        rows, i_used = _csv_col(text, 'Storage Used (Byte)')
        _, i_alloc = _csv_col(text, 'Storage Allocated (Byte)')
        _, i_upn = _csv_col(text, 'Owner Principal Name')
        _, i_name = _csv_col(text, 'Owner Display Name')
        _, i_del = _csv_col(text, 'Is Deleted')
        out = []

        def _cell(r, idx):
            return r[idx].strip() if 0 <= idx < len(r) else ''

        for r in rows[1:]:
            if not any((c or '').strip() for c in r):
                continue
            # Concealment replaces the principal name with a hash and blanks nothing else
            # usable, so an unnamed row is genuinely unnamed — see `_identify_accounts`.
            upn = _cell(r, i_upn)
            anon = '@' not in upn
            out.append({
                'name': '' if anon else upn,
                'display': _cell(r, i_name), 'sid': '', 'anon': anon,
                'used': _csv_int(r, i_used), 'quota': _csv_int(r, i_alloc),
                'deleted': _cell(r, i_del).lower() == 'true',
            })
        return (_csv_sum(text, 'Storage Used (Byte)'), len(out),
                sum(1 for a in out if a['deleted']), out)

    def _identify_accounts(self, rows: list, token: str, timeout: int) -> tuple[list, bool]:
        """Names for the accounts the report would not name.

        There is no join to try here: unlike a site, an account has no identifier in the
        report that survives concealment and appears in the directory too — the principal
        name IS the identifier, and it is what gets hashed. So the one way across is to ask
        the accounts themselves (``/users/{id}/drive``), batched, exactly as for sites.
        """
        if not [a for a in rows if a['anon']]:
            return rows, False
        measured = self._measure_drives(self._enumerate_accounts(token, timeout),
                                        '/users', self._account_label, token, timeout)
        return (measured, True) if measured else (rows, False)

    def _check_onedrive(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        """Tenant-wide OneDrive storage USED, and who is using it.

        Warns when the total exceeds ``onedrive_max`` (0 = informational only). There is no
        percentage and no "full": OneDrive quotas are PER PERSON, so the sum of them is not a
        pool anyone can exhaust — "OneDrive is 3 % full" would be a sentence about nothing.
        The question worth answering tenant-wide is who is using the space, and that is the
        breakdown.
        """
        try:
            used, accounts, deleted, rows = self._onedrive_totals(token, timeout)
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/onedrive', False, self._msg('m3_od_fail', label, exc),
                       {'name': f'{label} · OneDrive (tenant)'})
            return
        omax = to_bytes(it.get('onedrive_max'), it.get('onedrive_unit') or 'TB')
        extra = {'name': f'{label} · OneDrive (tenant)', 'used_bytes': used,
                 'limit_bytes': omax, 'accounts': accounts, 'deleted': deleted}
        live = bool(it.get('_live'))
        kept = self._rows_kept(it, 'accounts_top')
        if rows and (live or kept):
            probed = False
            try:
                rows, probed = self._identify_accounts(rows, token, timeout)
            except Exception:  # pylint: disable=broad-except
                pass          # a naming failure must never cost the measurement
            # Each bar is that person against THEIR OWN quota: the accounts share no pool, so
            # a share of the tenant total would not say whether anyone is about to run out.
            extra['breakdown'] = self._usage_breakdown(
                rows, omax, self._OD_KEYS, probed, None if live else kept,
                self._breakdown_page(), own_quota=True)
        base = self._msg('m3_od_base', label, accounts, fmt_bytes(used))
        if omax > 0 and used > omax:
            self._emit(f'{key}/onedrive', False, self._msg('m3_od_over', base, fmt_bytes(omax)),
                       extra, severity='warning')
        else:
            suffix = self._msg('m3_od_limit_suffix', fmt_bytes(omax)) if omax else ''
            self._emit(f'{key}/onedrive', True, base + suffix + ' ✅', extra)
