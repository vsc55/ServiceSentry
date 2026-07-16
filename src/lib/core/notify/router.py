#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The notification router — core-owned, web_admin-independent.

:class:`NotificationRouter` *owns* the channel stores (webhooks, Teams channels + the
Teams bot conversation-reference store) and *is* the routing: given an event kind it
fans out to every enabled channel (Telegram, Email, Webhook, Microsoft Teams) per the
``notifications`` matrix (``{channel}_on_{kind}``) or an explicit channel override.

A host builds one router from a :class:`lib.core.notify.context.NotifyContext` and every
subsystem (the web admin, the monitor/events/syslog workers) sends its notifications
*through that router* instead of wiring channels itself — the router is the single place
channels are registered and dispatched, and it has no idea Flask or the web admin exist.

The channels take a small generic "surface" object (``_config_section`` / ``_dbg`` /
``store`` / …); the router *is* that surface, so :func:`run_dispatch` and the channels
call back into the router — never into a host.  A channel that needs persistence owns its
store and builds it via ``router.store(key, factory)``, keeping the router channel-agnostic.
:func:`run_dispatch` is kept as a
module-level function so the thin :mod:`lib.core.notify.notification_dispatcher` shim can
route a legacy host surface through the exact same logic during the migration.
"""

from __future__ import annotations

from lib.core.notify import registry
from lib.debug import DebugLevel


def run_dispatch(surface, kind: str, module: str = '', item: str = '',
                 status: str = '', message: str = '', timestamp: str = '',
                 channels=None, webhook_ids=None) -> dict[str, tuple[bool, str]]:
    """Fan a notification out to every enabled channel for *kind*.

    *surface* is any object exposing the generic router contract (``_read_config_file`` /
    ``_CONFIG_FILE`` / ``_dbg`` / ``_config_section`` / ``store`` / ``_panel_user_emails``)
    — in practice a :class:`NotificationRouter`; channel-specific data is loaded by each
    channel through ``surface.store(...)``.  Channels are discovered from the registry (each
    self-registers); by default they are chosen by the ``notifications`` routing matrix,
    pass *channels* to target an explicit set (event rules pick their own), and
    *webhook_ids* to restrict the webhook channel to specific destinations.

    Returns ``{channel: (ok, message)}`` for each channel attempted.
    """
    results: dict[str, tuple[bool, str]] = {}
    try:
        cfg = surface._read_config_file(surface._CONFIG_FILE) or {}
    except Exception as exc:  # pylint: disable=broad-except
        surface._dbg(f"> Notify >> config read failed: {exc}", DebugLevel.error)
        return results

    notif = cfg.get('notifications') or {}
    event = dict(kind=kind, module=module, item=item,
                 status=status, message=message, timestamp=timestamp)
    reg = registry.channels()   # registration order == dispatch order
    if channels is not None:
        wanted = set(channels)
        active = [n for n in reg if n in wanted]
    else:
        active = [n for n in reg if notif.get(f'{n}_on_{kind}', False)]
    surface._dbg(f"> Notify >> {kind} {module}/{item}: channels={active or 'none'}",
                 DebugLevel.info)

    for name in active:
        ch = reg[name]
        try:
            # webhook_ids is webhook-specific; other channels swallow it via **_extra.
            ok, msg = ch.send(surface, cfg, webhook_ids=webhook_ids, **event)
            results[name] = (ok, msg)
            surface._dbg(f"> Notify > {name} >> ok={ok}: {msg}",
                         DebugLevel.debug if ok else DebugLevel.warning)
        except Exception as exc:  # pylint: disable=broad-except
            results[name] = (False, str(exc))
            surface._dbg(f"> Notify > {name} >> {type(exc).__name__}: {exc}", DebugLevel.error)

    return results


class NotificationRouter:
    """Owns the notification channel stores + the routing, built from a NotifyContext.

    This is the object every host delegates to (:meth:`dispatch`), and it is also the
    "surface" the channel senders call back into.  It stays **channel-agnostic**: it names
    no concrete store type — a channel that needs persistence asks :meth:`store` with its
    own factory (``ctx -> store``), so channel-specific code lives in the channel package,
    not here.  Channels depend on the router; the router never on the web admin.
    """

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._CONFIG_FILE = getattr(ctx, 'config_file', 'config.json')
        self._stores: dict = {}   # channel-owned stores, built lazily via store()

    def store(self, key: str, factory):
        """Return a channel-owned store, building it once (per router) from the context.

        The router caches by *key* but is agnostic about the store type — the channel
        passes ``factory(ctx)`` that constructs whatever it needs from the context's
        connector/cipher.  This is how a channel owns its persistence without the router
        importing or naming any concrete store (webhooks, Teams, …)."""
        if key not in self._stores:
            self._stores[key] = factory(self._ctx)
        return self._stores[key]

    # ── generic context surface (called back by run_dispatch + the channels) ────
    def _read_config_file(self, _filename=None) -> dict:
        try:
            return self._ctx.read_config() or {}
        except Exception:  # pylint: disable=broad-except
            return {}

    def _config_section(self, name: str) -> dict:
        return (self._read_config_file() or {}).get(name) or {}

    def _dbg(self, message, level: DebugLevel = DebugLevel.debug) -> None:
        try:
            self._ctx.dbg(message, level)
        except Exception:  # pylint: disable=broad-except
            pass

    def _audit(self, event: str, detail=None) -> None:
        try:
            self._ctx.audit(event, detail or {})
        except Exception:  # pylint: disable=broad-except
            pass

    def _panel_user_emails(self) -> list:
        fn = getattr(self._ctx, 'panel_user_emails', None)
        if not callable(fn):
            return []
        try:
            return list(fn() or [])
        except Exception:  # pylint: disable=broad-except
            return []

    def public_base_url(self) -> str:
        fn = getattr(self._ctx, 'public_url', None)
        if not callable(fn):
            return ''
        try:
            return fn() or ''
        except Exception:  # pylint: disable=broad-except
            return ''

    # ── routing ────────────────────────────────────────────────────────────────
    def dispatch(self, kind: str, module: str = '', item: str = '',
                 status: str = '', message: str = '', timestamp: str = '',
                 channels=None, webhook_ids=None) -> dict[str, tuple[bool, str]]:
        """Send a notification to every enabled channel for *kind* (see :func:`run_dispatch`)."""
        return run_dispatch(self, kind, module=module, item=item, status=status,
                            message=message, timestamp=timestamp,
                            channels=channels, webhook_ids=webhook_ids)
