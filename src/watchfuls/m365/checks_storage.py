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

from ._parse import _csv_max


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

    def _check_tenant(self, it: dict, key: str, label: str, token: str, timeout: int) -> None:
        try:
            text = self._graph_text(
                token, "/reports/getSharePointSiteUsageStorage(period='D7')", timeout)
            used = _csv_max(text, 'Storage Used (Byte)')
        except Exception as exc:  # pylint: disable=broad-except
            self._emit(f'{key}/tenant', False, self._msg('m3_tenant_fail', label, exc),
                       {'name': f'{label} · SharePoint (tenant)'})
            return
        tmax = to_bytes(it.get('tenant_max'), it.get('tenant_unit') or 'TB')
        extra = {'name': f'{label} · SharePoint (tenant)', 'used_bytes': used, 'limit_bytes': tmax}
        base = self._msg('m3_tenant_base', label, fmt_bytes(used))
        if tmax > 0 and used > tmax:
            self._emit(f'{key}/tenant', False,
                       self._msg('m3_tenant_over', base, fmt_bytes(tmax)),
                       extra, severity='warning')
        else:
            suffix = self._msg('m3_tenant_limit_suffix', fmt_bytes(tmax)) if tmax else ''
            self._emit(f'{key}/tenant', True, base + suffix + ' ✅', extra)

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
