#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone syslog receiver — run the listener as its own process/container.

The web admin hosts the receiver in-process (see
:class:`lib.web_admin.mixins.syslog._SyslogMixin`), but the same subsystem can run
on its own host or Docker container, sharing the database with the rest of
ServiceSentry.  The listener lifecycle itself (config merge, (re)build/apply,
drop recording, retention) is the shared
:class:`lib.services.syslog.manager._SyslogMixin`; this class only wires the
collaborators it needs and adds the standalone bits (a cross-process config watch
and a blocking run loop):

* a DB connector (from the ``database`` config section) and a
  :class:`lib.services.syslog.store.SyslogStore` on top of it — the same table the web
  admin reads, so received messages show up in its Syslog tab;
* a :class:`lib.config.manager.ConfigManager` so the ``syslog`` and
  ``notifications`` config is read from the very same place as everywhere else;
* a :class:`lib.core.notify.webhook.store.WebhooksStore` and a minimal context surface
  (``_read_config_file`` / ``_config_section`` / ``_load_webhooks`` / ``_dbg``)
  so alert routing through :mod:`lib.core.notify.notification_dispatcher` works
  without a running web server.

It deliberately does NOT start Flask, the monitor, or any HTTP endpoint: just
receive → store → alert → prune.
"""

from __future__ import annotations

import os
import signal
import threading

from lib.config import CONFIG_FILENAME, config_path
from lib.config.manager import ConfigManager, bootstrap_database_cfg, read_config_raw
from lib.db import get_connector
from lib.debug import Debug, DebugLevel
from lib.core.config.store import ConfigStore
from lib.services.events.store import EventRulesStore, NotificationLogStore
from lib.services.manager.instances import ServiceInstancesStore
from lib.services.manager.commands import ServiceCommandsStore
from lib.services.syslog.store import SyslogStore, SyslogDropsStore
from lib.core.notify.webhook.store import WebhooksStore
from lib.services.heartbeat import _HeartbeatMixin, db_summary
from lib.services.control_server import start_control_server
from lib.services.syslog.manager import _SyslogMixin
from lib.services.events.manager import _EventsMixin
from lib.security import secret_manager

_CONFIG_WATCH_EVERY = 15        # poll the shared DB for syslog config changes (s)


class SyslogService(_HeartbeatMixin, _EventsMixin, _SyslogMixin):
    """Own the syslog listener as a self-contained, DB-sharing daemon.

    The listener lifecycle comes from :class:`_SyslogMixin`; syslog→notification
    routing reuses the Event-rules manager (:class:`_EventsMixin`, the same rules
    edited in the web UI, stored in the shared DB), so standalone and embedded
    receivers behave identically and write to the same notification log."""

    _CONFIG_FILE = CONFIG_FILENAME
    _HB_KEY = 'syslog'

    # ── heartbeat hooks (observed state for the Services tab) ──────────────────
    def _hb_running(self) -> bool:
        return self._syslog_server is not None

    def _hb_detail(self) -> dict:
        try:
            cfg = self._syslog_cfg() or {}
        except Exception:  # pylint: disable=broad-except
            return {}
        return {k: cfg.get(k) for k in ('udp_port', 'tcp_port', 'tls_port')
                if cfg.get(k)}

    def _hb_db_info(self) -> dict:
        info = {'main': self._hb_db_main}
        if self._hb_db_syslog:
            info['syslog'] = self._hb_db_syslog
        return info

    def __init__(self, config_dir: str, var_dir: str | None = None,
                 host_override: str | None = None, port_override: int | None = None,
                 log_level: str | None = None):
        self._config_dir = config_dir
        self._var_dir = var_dir or config_dir
        # CLI/env overrides (--syslog-host / --syslog-port): when set they win over
        # the stored config (consumed by _SyslogMixin._syslog_cfg).  A single port
        # overrides both UDP and TCP (the usual syslog pair); TLS keeps its port.
        self._host_override = host_override or None
        self._port_override = port_override
        self._log_level_override = log_level or None
        self._secret_key_path = os.path.join(config_dir, '.flask_secret')
        self._fernet = secret_manager.fernet_from_secret_file(self._secret_key_path)
        self._secret_keys = secret_manager.ENCRYPT_KEYS

        # Connector from the bootstrap ``database`` section (same logic the web
        # admin uses, incl. SS_DB_* env), defaulting to the shared SQLite file.
        db_cfg = bootstrap_database_cfg(read_config_raw(config_path(config_dir), self._fernet))
        db_path = os.path.join(self._var_dir, 'data.db')
        self._db_connector = get_connector(db_cfg or None, default_sqlite_path=db_path)

        self._config_store = ConfigStore(self._db_connector)
        self._config_mgr = ConfigManager(
            self._config_store, config_path(config_dir),
            fernet=self._fernet, secret_keys=self._secret_keys)
        # Syslog storage may live in its own DB (high-volume isolation); falls
        # back to the system connector when ``syslog_db`` is not enabled.  Env
        # (SS_SYSLOG_DB_*) is overlaid so it can be configured purely via Docker.
        from lib.db import build_syslog_connector  # noqa: PLC0415
        from lib.config.manager import overlay_section_env  # noqa: PLC0415
        _sdb = overlay_section_env('syslog_db', self._config_section('syslog_db'))
        self._syslog_db_connector = build_syslog_connector(
            _sdb, main_connector=self._db_connector,
            default_sqlite_path=os.path.join(self._var_dir, 'syslog.db'))
        self._syslog_store = SyslogStore(self._syslog_db_connector)
        self._syslog_drops_store = SyslogDropsStore(self._syslog_db_connector)
        self._hb_db_main = db_summary(db_cfg, os.path.basename(db_path))
        self._hb_db_syslog = (db_summary(_sdb, 'syslog.db')
                              if (_sdb or {}).get('enabled') else None)
        self._webhooks_store = WebhooksStore(
            self._db_connector, fernet=self._fernet, secret_keys=self._secret_keys)
        # Event-rules manager (shared DB): syslog→notification routing + send log.
        self._event_rules_store = EventRulesStore(self._db_connector)
        self._notification_log_store = NotificationLogStore(self._db_connector)
        # Liveness registry (shared DB) so the web admin sees this listener.
        self._service_instances_store = ServiceInstancesStore(self._db_connector)
        # Imperative command queue (reload/prune) the heartbeat loop drains.
        self._service_commands_store = ServiceCommandsStore(self._db_connector)
        self._init_events()

        self._debug = Debug()
        self._debug.set_from_config(
            self._log_level_override
            or self._config_section('global').get('log_level') or 'info')
        # Listener state read/written by _SyslogMixin.
        self._syslog_server = None
        self._syslog_lock = threading.Lock()
        self._stop = threading.Event()

        backend = ((db_cfg or {}).get('driver') or (db_cfg or {}).get('engine')
                   or (db_cfg or {}).get('type') or 'sqlite')
        self._dbg(f'> Syslog >> service init: config={config_dir} var={self._var_dir} '
                  f'db={backend}', DebugLevel.info)

    # ── context surface used by the notification dispatcher ───────────────────
    def _read_config_file(self, _filename: str | None = None) -> dict:
        """Effective configuration (DB ← config.json), via the ConfigManager."""
        return self._config_mgr.read() or {}

    def _config_section(self, name: str) -> dict:
        return (self._read_config_file(self._CONFIG_FILE) or {}).get(name) or {}

    def _load_webhooks(self, *, decrypt: bool = True) -> list:
        try:
            return self._webhooks_store.list(decrypt=decrypt)
        except Exception:  # pylint: disable=broad-except
            return []

    def _dbg(self, message, level: DebugLevel = DebugLevel.info) -> None:
        self._debug.print(message, level)

    # ── standalone lifecycle (the shared bits live in _SyslogMixin) ────────────
    def _retention_loop(self) -> None:
        while not self._stop.wait(self.RETENTION_EVERY):
            self._syslog_prune_once()

    def _config_signature(self) -> str:
        """Stable string of the syslog config, to detect changes between polls."""
        cfg = self._syslog_cfg()
        return '|'.join(f'{k}={cfg.get(k)!r}' for k in sorted(cfg))

    def _reconcile_once(self) -> None:
        """Re-read config; reload the listener when the syslog config changed.
        Called by the periodic watch loop and on demand by the control-server poke."""
        self._config_mgr.invalidate()                # drop the cache, read fresh DB
        self._events_reload()                        # pick up event-rule edits too
        new = self._config_signature()
        if new != getattr(self, '_syslog_sig', None):
            self._syslog_sig = new
            self._dbg('> Syslog >> config changed; reloading listener',
                      DebugLevel.info)
            self._syslog_apply_config()

    def _watch_loop(self) -> None:
        """Re-apply the listener when the syslog config changes in the shared DB.

        The config is edited from the web UI (a different process), so the
        standalone container polls for changes and reloads — enabling/disabling
        or changing ports/allowlist takes effect without a container restart."""
        self._syslog_sig = self._config_signature()
        while not self._stop.wait(_CONFIG_WATCH_EVERY):
            self._reconcile_once()

    def stop(self, *_args) -> None:
        if not self._stop.is_set():
            self._dbg('> Syslog >> stop requested', DebugLevel.info)
        self._stop.set()
        with self._syslog_lock:
            if self._syslog_server is not None:
                try:
                    self._syslog_server.stop()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._syslog_server = None
                self._dbg('> Syslog >> listener stopped', DebugLevel.info)

    def run(self) -> int:
        """Run the receiver and block until stopped (SIGINT/SIGTERM).

        Stays alive even when syslog is currently disabled: the config lives in
        the shared DB and is edited from the web UI, so a background watcher
        reloads the listener when it is enabled (or its ports change) — no
        container restart needed.
        """
        self._syslog_apply_config()                  # bind now if already enabled
        threading.Thread(target=self._retention_loop,
                         name='syslog-retention', daemon=True).start()
        threading.Thread(target=self._watch_loop,
                         name='syslog-config-watch', daemon=True).start()
        self._dbg(f'> Syslog >> retention sweep every {self.RETENTION_EVERY}s; '
                  f'config watch every {_CONFIG_WATCH_EVERY}s', DebugLevel.info)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self.stop)
            except (ValueError, OSError):
                pass                                 # not in main thread / unsupported
        if self._syslog_server is None:
            self._dbg('> Syslog >> waiting for the syslog section to be enabled '
                      '(Ctrl+C to stop)', DebugLevel.warning)
        else:
            self._dbg('> Syslog >> standalone receiver running (Ctrl+C to stop)',
                      DebugLevel.info)
        self._control_server = start_control_server(self)
        self.start_heartbeat()
        self._stop.wait()
        self.stop_heartbeat()
        self._dbg('> Syslog >> receiver stopped; exiting', DebugLevel.info)
        return 0


def run_standalone(args, config_dir: str, var_dir: str, modules_dir=None) -> int:
    """Build + run the syslog receiver as a standalone process (``main.py --syslog``)."""
    return SyslogService(
        config_dir, var_dir,
        host_override=getattr(args, 'syslog_host', None),
        port_override=getattr(args, 'syslog_port', None),
        log_level=getattr(args, 'log_level', None)).run()
