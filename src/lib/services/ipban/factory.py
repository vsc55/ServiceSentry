#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Framework-free construction of the internal fail2ban jail.

``_IpBanMixin`` (``manager.py``) is Flask-coupled (request gate, HTTP capture), so it
cannot be inherited by a non-HTTP daemon. The pieces a standalone service DOES need — a
shared, DB-backed :class:`~lib.services.ipban.jail.IpBanManager`, its configuration from
the ``web_admin`` config section, and the ban-lifecycle notification — live here so both
the web admin and the standalone Syslog receiver build the jail the same way and read/write
the SAME ``ip_bans`` table on the general connector (every replica converges on desired
state).
"""

from __future__ import annotations

import time


def make_ipban(connector, notify=None):
    """Build the shared jail manager + its ban store on *connector* (the general DB).

    The store's tables self-create via ``reconcile_table`` on construction, so no
    migration step is needed; state is shared cross-process with every other replica.
    Returns ``(ip_ban_store, manager)``. ``notify(action, ip, info)`` is an optional
    ban-lifecycle hook (see :func:`ipban_notify`)."""
    from lib.services.ipban.store import IpBanStore  # noqa: PLC0415
    from lib.services.ipban.jail import IpBanManager  # noqa: PLC0415
    store = IpBanStore(connector)
    store.prune(time.time())
    manager = IpBanManager(store=store, notify=notify)
    return store, manager


def configure_ipban(manager, wa_cfg: dict, extra_whitelist=()) -> None:
    """Push the ``web_admin|ipban_*`` settings from *wa_cfg* into *manager*.

    *wa_cfg* is the ``web_admin`` config SECTION (env already overlaid by the caller, so
    ``SS_IPBAN_ENABLED`` / ``SS_IPBAN_WHITELIST`` take effect). ``cfg_get`` supplies the
    registry default for any missing field. *extra_whitelist* (UI-managed whitelist +
    trusted hops) is always merged inside ``configure`` alongside loopback."""
    from lib.config.spec import cfg_get  # noqa: PLC0415
    manager.configure(
        enabled=cfg_get(wa_cfg, 'web_admin|ipban_enabled'),
        auth_threshold=cfg_get(wa_cfg, 'web_admin|ipban_auth_threshold'),
        auth_window=cfg_get(wa_cfg, 'web_admin|ipban_auth_window_secs'),
        authz_threshold=cfg_get(wa_cfg, 'web_admin|ipban_authz_threshold'),
        authz_window=cfg_get(wa_cfg, 'web_admin|ipban_authz_window_secs'),
        durations=cfg_get(wa_cfg, 'web_admin|ipban_durations'),
        permanent_after=cfg_get(wa_cfg, 'web_admin|ipban_permanent_after'),
        whitelist=cfg_get(wa_cfg, 'web_admin|ipban_whitelist'),
        extra_whitelist=list(extra_whitelist),
    )


def ipban_notify(surface, action: str, ip: str, info: dict) -> None:
    """Audit a ban lifecycle event and route it through the notification matrix.

    Parameterised by *surface* (the WebAdmin or a standalone service) so both hosts share
    one implementation: it needs only ``_read_config_file`` / ``_CONFIG_FILE`` and a
    ``_notify`` router (used by ``dispatch``); ``_audit_system`` is used when present. Both
    the audit and the dispatch are best-effort (a notify failure never affects the ban)."""
    try:
        detail = {'ip': ip, 'reason': info.get('reason', ''),
                  'level': info.get('level'), 'by': info.get('by', 'system')}
        detail['permanent'] = info.get('until') is None
        audit = getattr(surface, '_audit_system', None)
        if callable(audit):
            audit(f'ip_{action}', detail={k: v for k, v in detail.items() if v is not None})
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        from lib.core.notify.notification_dispatcher import dispatch  # noqa: PLC0415
        from lib.core.notify.formatting import notify_lang, notify_text  # noqa: PLC0415
        unbanned = action == 'unbanned'
        kind = 'ipban_unbanned' if unbanned else 'ipban_banned'
        reason = info.get('reason', '')
        cfg = surface._read_config_file(surface._CONFIG_FILE) or {}
        lang = notify_lang(cfg)
        msg = notify_text(cfg, lang, 'notif_msg_ip_unbanned' if unbanned else 'notif_msg_ip_banned', ip)
        if reason:
            msg += f' ({reason})'
        status = notify_text(cfg, lang, 'notif_status_unbanned' if unbanned else 'notif_status_banned')
        dispatch(surface, kind=kind, module='ipban', item=ip, status=status,
                 message=msg, timestamp=time.strftime('%Y-%m-%d %H:%M:%S'))
    except Exception:  # pylint: disable=broad-except
        pass
