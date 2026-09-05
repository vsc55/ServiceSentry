#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Building the stores the panel reads from, once, at startup.

Each domain owns its own store; what lives here is the CONSTRUCTION of them - which backend,
which connector, what to do when the database is not reachable yet, and the order they have to
come up in. That is a boot concern, not a domain one, and it was taking a hundred lines out of
the middle of a class whose job is to serve requests.
"""

import os

class _StoresMixin:
    """Store construction for :class:`WebAdmin`."""

    def _init_entity_store(self) -> None:
        """Create the shared DB connector and the entity stores on top of it.

        A single :class:`lib.db.BaseConnector` (SQLite by default; PostgreSQL/
        MySQL via the ``database`` config section) is shared by the users,
        groups, sessions and roles stores so they never open the database
        directly nor fight over separate connections.
        """
        from lib.db             import (get_connector, reconcile_core_tables,  # noqa: PLC0415
                                reconcile_module_tables)
        from lib.core.users.store  import UsersStore   # noqa: PLC0415
        from lib.core.groups.store import GroupsStore  # noqa: PLC0415
        from lib.core.sessions.store import SessionsStore   # noqa: PLC0415
        from lib.core.roles.store  import RolesStore   # noqa: PLC0415
        from lib.config.manager import bootstrap_database_cfg  # noqa: PLC0415
        db_path = os.path.join(self._var_dir or self._config_dir, 'data.db')
        db_cfg  = bootstrap_database_cfg(self._read_config_file(self._CONFIG_FILE))
        self._db_connector   = get_connector(db_cfg or None, default_sqlite_path=db_path)
        self._users_store    = UsersStore(self._db_connector)
        self._groups_store   = GroupsStore(self._db_connector)
        self._sessions_store = SessionsStore(self._db_connector)
        self._roles_store    = RolesStore(self._db_connector)
        # Internal fail2ban — the jail + its persistent store live on the shared
        # connector so every in-process service (web + syslog) enforces one ban list.
        # Internal fail2ban: shared, store-backed jail manager (persistent + consistent
        # across processes). Wiring lives in _IpBanMixin.
        self._init_ipban()
        # Host registry — connection profiles defined once, reused by modules.
        from lib.core.hosts.store import HostsStore  # noqa: PLC0415
        self._hosts_store = HostsStore(
            self._db_connector,
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        # Whose everything is, and who the companies are. Before the inventory on purpose:
        # the inventory reads this one, and a store that builds its own copy of a table another
        # store owns is two stores writing the same rows.
        from lib.core.orgs.store import OrgsStore  # noqa: PLC0415
        self._orgs_store = OrgsStore(self._db_connector)
        # Where the equipment IS and whose it is — the other axis of the same fleet. Its own
        # store rather than columns on `hosts`, because most of what fills a rack answers to
        # nothing: a patch panel, a blanking plate, a switched-off server still bolted in.
        from lib.core.dcim.store import DcimStore  # noqa: PLC0415
        from lib.core.dcim.catalog import CatalogStore  # noqa: PLC0415
        from lib.core.dcim.schemas import SchemaStore  # noqa: PLC0415
        self._dcim_store = DcimStore(self._db_connector)
        self._dcim_catalog = CatalogStore(self._db_connector)
        # Qué campos tiene un modelo, dicho por quien publica la biblioteca — y clonable, para
        # las cosas de una sala que no están en ningún repositorio.
        self._dcim_schemas = SchemaStore(self._db_connector)
        # Y lo que de verdad se compra, que no está en el catálogo de ningún fabricante: un R740
        # con doce DIMM, ocho SSD y una controladora. De aquí salen los equipos del inventario
        # con sus piezas ya puestas, y lo único que queda por teclear es el número de serie.
        from lib.core.dcim.builds import BuildStore  # noqa: PLC0415
        self._dcim_builds = BuildStore(self._db_connector)
        # Qué se pregunta de un componente de cada clase. Viene en un JSON con el panel y se
        # puede sustituir por uno más nuevo guardado aquí — que es lo que permite añadir el
        # formato de una tarjeta sin publicar una versión.
        from lib.core.dcim.profiles import ProfileStore  # noqa: PLC0415
        self._dcim_profiles = ProfileStore(self._db_connector)
        # Por dónde se enchufa cada cosa. El mismo almacén y la misma tabla: `dc_profile` lleva
        # un `name` desde el primer día precisamente para el segundo documento que quisiera
        # poder actualizarse sin publicar una versión, y este es ese. Lo único suyo es cómo se
        # limpia lo que entra, porque un catálogo de conectores no tiene clases ni atributos.
        from lib.core.dcim import connectors as dcim_connectors  # noqa: PLC0415
        self._dcim_conns = ProfileStore(self._db_connector, norm=dcim_connectors.normalise,
                                        scope=dcim_connectors.SCOPE)
        # Lo que no es una foto: el manual, la hoja de características, el zip del firmware. Hoy
        # eso vive en la carpeta de alguien, y el día que hace falta es un martes a las once.
        from lib.core.dcim.files import FileStore  # noqa: PLC0415
        self._dcim_files = FileStore(self._db_connector)
        # Con qué sale un equipo — Debian, RouterOS, ESXi—, escrito UNA vez. En una caja de
        # texto por plantilla acaban siendo cuatro formas de escribir lo mismo, y entonces
        # «cuántas máquinas hay que actualizar» no tiene respuesta. Y no es solo de un
        # dispositivo físico: una máquina virtual corre lo mismo y pregunta lo mismo.
        from lib.core.dcim.platforms import PlatformStore  # noqa: PLC0415
        self._dcim_platforms = PlatformStore(self._db_connector)
        # What the panel does in the background, after it has done it. The package is handed
        # the connector rather than going looking for one: a job finishes inside a worker
        # thread that has no web admin, no request and no handle of its own, and threading one
        # through four unrelated pieces of machinery to write a note is worse than this.
        from lib.core.jobs import record as jobs_record  # noqa: PLC0415
        jobs_record.bind(self._db_connector, {
            'keep':  getattr(self, '_JOBS_HISTORY_KEEP', None),
            'days':  getattr(self, '_JOBS_HISTORY_DAYS', None),
            'lines': getattr(self, '_JOBS_HISTORY_LINES', None),
        }, owner=self._hb_instance_id() if hasattr(self, '_hb_instance_id') else '')
        # Second factors and their recovery codes. Its own tables rather than a column on
        # `users`: that record is merged into what the users API serialises, and a TOTP seed
        # there would be one `GET /api/v1/users` away from everybody with `users_view`.
        from lib.core.mfa.store import MfaStore  # noqa: PLC0415
        self._mfa_store = MfaStore(self._db_connector, fernet=self._get_fernet())
        # API tokens: how an account is scripted without handing over its password — and
        # the only way to reach the API at all once that account carries a second factor.
        from lib.core.apitokens.store import ApiTokenStore  # noqa: PLC0415
        self._api_token_store = ApiTokenStore(self._db_connector)
        # Reusable named credentials (SSH identities referenced by hosts/checks).
        from lib.core.credentials.store import CredentialsStore  # noqa: PLC0415
        self._credentials_store = CredentialsStore(
            self._db_connector,
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        # Notification routing lives in the core-owned, web_admin-independent
        # NotificationRouter: it *owns* the channel stores (webhooks + Teams channels +
        # the Teams bot conversation-reference store) and does the fan-out.  The web admin
        # builds one from an explicit NotifyContext and reaches its stores via ``_notify``
        # (CRUD routes, config bundle) — no per-host channel wiring.
        from lib.core.notify.context import NotifyContext  # noqa: PLC0415
        from lib.core.notify.router import NotificationRouter  # noqa: PLC0415
        self._notify = NotificationRouter(NotifyContext(
            db=self._db_connector,
            read_config=lambda: self._read_config_file(self._CONFIG_FILE),
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
            dbg=self._dbg,
            audit=getattr(self, '_audit', None) or (lambda *a, **k: None),
            public_url=getattr(self, 'public_base_url', None),
            panel_user_emails=self._panel_user_emails,
            config_file=self._CONFIG_FILE,
        ))
        # Event→notification subsystem stores (rules, sent-log, worker state).
        from lib.services.events.store import (  # noqa: PLC0415
            EventRulesStore, EventStateStore, NotificationLogStore)
        self._event_rules_store = EventRulesStore(self._db_connector)
        self._notification_log_store = NotificationLogStore(self._db_connector)
        # Persisted cooldown + per-source cursor for the decoupled event worker.
        self._event_state_store = EventStateStore(self._db_connector)
        # Observed-state registry for background services (the heartbeat): every
        # instance — embedded here or in another pod — upserts its liveness row;
        # the Services tab reads them. Shared connector, so a --monitor worker and
        # this process see the same rows.
        from lib.services.manager.instances import ServiceInstancesStore  # noqa: PLC0415
        self._service_instances_store = ServiceInstancesStore(self._db_connector)
        # Imperative one-shot command queue (run-now/reload/clear): the UI enqueues,
        # the hosting instance (embedded here or a remote pod) claims + runs it.
        from lib.services.manager.commands import ServiceCommandsStore  # noqa: PLC0415
        self._service_commands_store = ServiceCommandsStore(self._db_connector)
        # Leader lease for single-owner services (monitor/events): only the holder
        # does the work, extra replicas are hot standby with TTL failover.
        from lib.services.manager.leader import ServiceLeaderStore  # noqa: PLC0415
        self._service_leader_store = ServiceLeaderStore(self._db_connector)
        # Watchful module/item configuration (DB-backed, shared with the monitor
        # through the same database).
        from lib.core.modules.store import ModulesStore    # noqa: PLC0415
        from lib.core.modules.facade import DbBackedModules  # noqa: PLC0415
        self._modules_store = ModulesStore(self._db_connector)
        self._modules_facade = DbBackedModules(
            self._modules_store,
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        self._modules_facade.read()
        # Scheduled backup tasks: a row each, because a task is a RECORD an operator
        # creates, renames and deletes one at a time — not a scalar setting. See
        # lib/core/backup/tasks_store.py.
        from lib.core.backup.tasks_store import BackupTasksStore   # noqa: PLC0415
        self._backup_tasks_store = BackupTasksStore(self._db_connector)
        # Retention profiles: a named policy several tasks share, so editing it changes all of
        # them at once instead of five numbers retyped per task. See
        # lib/core/backup/profiles_store.py.
        from lib.core.backup.profiles_store import BackupProfilesStore   # noqa: PLC0415
        self._backup_profiles_store = BackupProfilesStore(self._db_connector)
        # Editable configuration: a row per ``section|field`` in the DB, owned by
        # the single ConfigManager (the one place that reads/writes config).
        from lib.core.config.store import ConfigStore     # noqa: PLC0415
        from lib.config.manager import ConfigManager  # noqa: PLC0415
        self._config_store = ConfigStore(self._db_connector)
        self._config_mgr = ConfigManager(
            self._config_store,
            os.path.join(self._config_dir, self._CONFIG_FILE),
            fernet=self._get_fernet(),
            secret_keys=getattr(self, '_secret_keys', None),
        )
        # Create the declared tables on the shared connector — a watchful module's, and a
        # core package's. Both are built on demand, so without this the table lands inside
        # whatever request first needed it.
        try:
            reconcile_module_tables(self._db_connector)
            reconcile_core_tables(self._db_connector)
        except Exception:  # pylint: disable=broad-except
            pass

    def _init_history(self):
        """Create a HistoryStore on the shared connector (or its own if absent)."""
        if not self._var_dir:
            return None
        try:
            from lib.core.history.store import HistoryStore, create as _create_history  # noqa: PLC0415
            connector = getattr(self, '_db_connector', None)
            if connector is not None:
                return HistoryStore(connector)
            db_cfg = (self._read_config_file(self._CONFIG_FILE) or {}).get('database')
            return _create_history(
                db_cfg or None,
                sqlite_path=os.path.join(self._var_dir, 'data.db'),
            )
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_check_state(self):
        """Create the CheckStateStore (the DB-backed replacement for status.json)."""
        if not self._var_dir:
            return None
        try:
            from lib.services.monitoring.check_state import CheckStateStore, create as _create_cs  # noqa: PLC0415
            connector = getattr(self, '_db_connector', None)
            if connector is not None:
                return CheckStateStore(connector)
            db_cfg = (self._read_config_file(self._CONFIG_FILE) or {}).get('database')
            return _create_cs(
                db_cfg or None,
                sqlite_path=os.path.join(self._var_dir, 'data.db'),
            )
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_syslog_stores(self) -> None:
        """Create the shared syslog DB connector + stores.

        They are host infrastructure shared by the embedded listener, the decoupled
        event worker and the Syslog tab; the listener *server* lifecycle lives in
        the embedded syslog service object (``lib.services.syslog.embedded``)."""
        self._syslog_store = None
        self._syslog_drops_store = None
        self._syslog_db_connector = None
        connector = getattr(self, '_db_connector', None)
        if connector is None:
            return
        try:
            from lib.db import build_syslog_connector  # noqa: PLC0415
            from lib.services.syslog.store import SyslogStore, SyslogDropsStore  # noqa: PLC0415
            from lib.config.manager import overlay_section_env  # noqa: PLC0415
            var = self._var_dir or self._config_dir or ''
            sdb = overlay_section_env('syslog_db', self._config_section('syslog_db'))
            self._syslog_db_connector = build_syslog_connector(
                sdb, main_connector=connector,
                default_sqlite_path=os.path.join(var, 'syslog.db'))
            self._syslog_store = SyslogStore(self._syslog_db_connector)
            self._syslog_drops_store = SyslogDropsStore(self._syslog_db_connector)
        except Exception:  # pylint: disable=broad-except
            pass
