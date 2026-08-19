#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview widgets the fail2ban service owns (see :mod:`lib.core.overview.discovery`).

Self-describing: discovered by :func:`lib.core.overview.discovery.discover_overview_widgets`
and merged into the dashboard's widget definitions — so the service declares its widgets
here instead of the Overview frontend hardcoding them.  The data comes from
``widget_data`` below; the render still resolves by ``id`` in the overview dispatcher.
"""


def _fail2ban_stat(enabled, banned, watchlist, whitelist) -> dict:
    """Standard stat content for the fail2ban widget: value + accent + declarative
    badges (style names + i18n keys/args — never HTML), painted by the generic
    ``_dwRenderStat``.  This is where the per-widget presentation *logic* lives now."""
    badges = [
        {'style': 'ok', 'icon': 'bi-check-circle', 'key': 'overview_ipban_on'} if enabled
        else {'style': 'muted', 'icon': 'bi-slash-circle', 'key': 'overview_ipban_off'},
    ]
    if not banned:
        badges.append({'style': 'ok', 'icon': 'bi-check-circle', 'key': 'overview_ipban_no_bans'})
    if watchlist:
        badges.append({'style': 'warn', 'icon': 'bi-eye',
                       'key': 'overview_ipban_watchlist', 'args': [watchlist]})
    if whitelist:
        badges.append({'style': 'teal', 'icon': 'bi-shield-check',
                       'key': 'overview_ipban_whitelist', 'args': [whitelist]})
    # Amber used to mean "the jail is on", which is the card saying "attention" for working
    # exactly as intended — and on a dashboard where colour now carries state, that reads as
    # a problem that is not there. Grey when it is off (nothing is running), green when it is
    # on with nobody banned, amber when addresses are currently locked out.
    #
    # Deliberately no `state`, so the card is not TINTED for it: a ban is the jail doing its
    # job, and an installation facing the internet would sit permanently amber — which is how
    # a signal stops being read at all.
    accent = 'grey' if not enabled else ('amber' if banned else 'green')
    return {'value': banned, 'accent': accent, 'badges': badges}


def fail2ban_stat(wa) -> dict:
    """Standard stat content for the ``fail2ban`` card: enabled state + banned count +
    watchlist/whitelist badges.  Fetched over AJAX by the generic stat renderer."""
    try:
        mgr = getattr(wa, '_ipban', None)
        if mgr is None:
            return _fail2ban_stat(False, 0, 0, 0)
        active = mgr.list_bans(active_only=True)
        wl = getattr(wa, '_ip_whitelist_store', None)
        return _fail2ban_stat(
            bool(getattr(mgr, '_enabled', False)), len(active),
            len(mgr.list_offenders()), len(wl.list()) if wl is not None else 0)
    except Exception:  # pylint: disable=broad-except
        return _fail2ban_stat(False, 0, 0, 0)


def ipban_list_rows(wa, f: str = '') -> list:
    """Active banned-IP rows (ip/reason/level/expiry) for the ipban_list table."""
    mgr = getattr(wa, '_ipban', None)
    if mgr is None:
        return []
    try:
        return [
            {'ip': b.get('ip', ''), 'reason': b.get('reason', ''),
             'level': b.get('level', 1), 'permanent': bool(b.get('permanent')),
             'retry_after': b.get('retry_after')}
            for b in mgr.list_bans(active_only=True)[:15]]
    except Exception:  # pylint: disable=broad-except
        return []
