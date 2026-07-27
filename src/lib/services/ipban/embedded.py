#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fail2ban embedded service: exposes the internal IP-ban gate to the Services tab.

The jail itself is the shared :class:`~lib.services.ipban.jail.IpBanManager`
(``host._ipban``) enforced inline on every request by the host glue in
:mod:`lib.services.ipban.manager`; this thin wrapper just gives it a service surface
(status + on/off control) and a per-container heartbeat.  There is no worker thread —
``start``/``stop``
flip the ``web_admin|ipban_enabled`` master switch (persisted to config) and re-apply
it to the live jail, so every replica converges on the shared desired state.
"""
from __future__ import annotations

import time

from lib.services.embedded import _EmbeddedBase


class EmbeddedIpban(_EmbeddedBase):
    """Service twin around the inline IP-ban gate.  Heartbeat + status only reflect
    the shared enabled flag and jail counters; the enforcement lives in the request
    hook (:mod:`lib.services.ipban.manager`)."""

    # ── boot ────────────────────────────────────────────────────────────────────
    def start_at_boot(self) -> None:
        # Nothing to start: the gate is inline and configured at app init. The host
        # boot loop already launched the heartbeat (state is never 'external'), so
        # this container advertises whether it is enforcing the jail.
        return

    # ── helpers ──────────────────────────────────────────────────────────────────
    def _enabled(self) -> bool:
        return bool(getattr(self._host, '_IPBAN_ENABLED', False))

    def _counts(self) -> tuple:
        """(banned, watchlist, whitelist) — best-effort; a half-initialised host must
        never crash the Services tab or a heartbeat cycle."""
        mgr = getattr(self._host, '_ipban', None)
        store = getattr(self._host, '_ip_whitelist_store', None)
        try:
            banned = len(mgr.list_bans(active_only=True)) if mgr is not None else 0
        except Exception:  # pylint: disable=broad-except
            banned = 0
        try:
            watch = len(mgr.list_offenders()) if mgr is not None else 0
        except Exception:  # pylint: disable=broad-except
            watch = 0
        try:
            whitelist = len(store.list()) if store is not None else 0
        except Exception:  # pylint: disable=broad-except
            whitelist = 0
        return banned, watch, whitelist

    # ── heartbeat: advertise this container's own jail counters ──────────────────
    def _hb_detail(self) -> dict:
        banned, watch, whitelist = self._counts()
        return {'banned': banned, 'watchlist': watch, 'whitelist': whitelist}

    # ── ServiceDescriptor surface (Services tab) ─────────────────────────────────
    def status(self) -> dict:
        enabled = self._enabled()
        banned, watch, whitelist = self._counts()
        return {
            'state': 'running' if enabled else 'disabled',
            'running': enabled, 'enabled': enabled,
            'embedded': True, 'controllable': True,
            'banned': banned, 'watchlist': watch, 'whitelist': whitelist,
            'detail': [
                {'label_key': 'svc_mode', 'value_key': 'svc_mode_embedded'},
                {'label_key': 'svc_ipban_banned', 'value': banned},
                {'label_key': 'svc_ipban_watchlist', 'value': watch},
                {'label_key': 'svc_ipban_whitelist', 'value': whitelist},
            ],
        }

    def control(self, action: str) -> tuple:
        """Flip the master switch. ``start``/``stop`` → enable/disable the jail. The
        new value is written to config (shared desired-state every replica reconciles),
        applied to the live manager here, and pushed to remote instances via a poke."""
        enable = (action == 'start')
        host = self._host
        # Round-trip the FULL effective config with only this field changed — the
        # ConfigManager treats its argument as the complete config (see _control_external).
        cfg = host._read_config_file(self._CONFIG_FILE) or {}
        wa_cfg = {**(cfg.get('web_admin') or {}), 'ipban_enabled': enable}
        cfg = {**cfg, 'web_admin': wa_cfg}
        host._write_config(cfg)
        host._invalidate_config_cache()
        host._IPBAN_ENABLED = enable
        try:
            host._configure_ipban()
        except Exception:  # pylint: disable=broad-except
            pass
        # Let remote replicas converge now instead of at their next watch tick.
        poke = getattr(host, '_poke_service_instances', None)
        if poke is not None and self._HB_KEY:
            poke(self._HB_KEY)
        self._audit_system('service_started' if enable else 'service_stopped',
                           {'service': 'ipban', 'web_admin|ipban_enabled': enable})
        self._notify_service_control(action)
        return True, ''

    # ── Imperative commands (reload / prune) ─────────────────────────────────────
    def _apply_command(self, action: str, args: dict | None = None) -> tuple[bool, str]:
        """Execute a one-shot command on the instance enforcing the jail.

        This service has no worker loop to nudge — the gate runs inline on every request —
        so both commands are maintenance the jail otherwise only does on its own schedule,
        made available on demand. Same queue as the other services, so the button works
        against a jail enforced in another container just as well as this one.
        """
        host = self._host
        if action == 'reload':
            # Re-read the stored config and push it into the live jail: thresholds,
            # windows, ban durations and the whitelist. The whitelist is the reason this
            # is worth a button — an address added to it does nothing until the jail is
            # reconfigured, and until now that only happened on a config save.
            try:
                host._invalidate_config_cache()
            except Exception:  # pylint: disable=broad-except
                pass
            try:
                host._configure_ipban()
            except Exception as exc:  # pylint: disable=broad-except
                return False, str(exc)
            return True, 'jail reconfigured'
        if action in ('prune', 'clear_status'):
            store = getattr(host, '_ipban_store', None)
            if store is None:
                return False, 'no store'
            # Deliberately NOT the jail's own _gc: that one is throttled to once every
            # five minutes, so pressing the button inside that window would report
            # success and sweep nothing.
            try:
                store.prune(time.time())
            except Exception as exc:  # pylint: disable=broad-except
                return False, str(exc)
            return True, 'retention sweep run'
        return False, 'unknown_action'

    def on_config_changed(self, changed) -> None:
        # A Config-tab edit to ipban_enabled already re-applies via routes/config; this
        # keeps twins in other embedded services consistent when the switch is flipped
        # elsewhere (e.g. control() on a peer replica pushing shared desired-state).
        if 'web_admin|ipban_enabled' in changed:
            wa_cfg = (self._host._read_config_file(self._CONFIG_FILE) or {}).get('web_admin', {})
            self._host._IPBAN_ENABLED = bool(wa_cfg.get('ipban_enabled', self._host._IPBAN_ENABLED))
            try:
                self._host._configure_ipban()
            except Exception:  # pylint: disable=broad-except
                pass

    @property
    def running(self) -> bool:
        return self._enabled()


def make_embedded(host) -> EmbeddedIpban:
    return EmbeddedIpban(host)
