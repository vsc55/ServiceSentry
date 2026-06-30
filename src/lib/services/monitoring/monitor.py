#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Lorenzo Carbonell (aka atareao)
# <lorenzo.carbonell.cerezo at gmail dot com>
#
# Copyright © 2019  Javier Pastor (aka VSC55)
# <jpastor at cerebelum dot net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
""" Monitor class to check the status of the system. """

import concurrent.futures
import datetime
import glob
import importlib
import json
import os
import pprint
import socket
import sys
import tempfile
import time

from lib.config import ConfigControl, load_config
from lib.config.spec import cfg_default, normalize_url
from lib.debug import DebugLevel
from lib.modules import ReturnModuleCheck
from lib.core.object_base import ObjectBase
from lib.core.telegram import Telegram
from lib.security import secret_manager

__all__ = ['Monitor']

__author__ = "Javier Pastor"
__copyright__ = "Copyright © 2019, Javier Pastor"
__credits__ = "Javier Pastor"
__license__ = "GPL"
__version__ = "0.1.0"
__maintainer__ = 'Javier Pastor'
__email__ = "python[at]cerebelum[dot]net"
__status__ = "Development"


class Monitor(ObjectBase):
    """ Monitor class to check the status of the system. """

    _DEFAULT_THREADS = 5     # Number of threads to use for parallel processing as default value.
    _DEFAULT_ENABLED = True

    _AUDIT_MAX_ENTRIES = 500

    # Set by ModuleBase.fail_streak when a consecutive-failure counter changes:
    # status.json must then be saved even if no item status flipped this cycle
    # (otherwise the counters would be lost in systemd one-shot mode).
    _status_counts_dirty = False

    def __init__(self, dir_base: str, dir_config: str, dir_modules: str, dir_var: str,
                 *, config=None):
        self.dir_base = dir_base
        self.dir_config = dir_config
        self.dir_modules = dir_modules
        self.dir_var = dir_var
        # An already-loaded config (the daemon's Main loads+seeds config.json once
        # and hands it over) so we don't read the file a second time.  When None
        # (e.g. the web admin spawns monitors on demand) we load it ourselves.
        self._injected_config = config

        self._read_config()
        self._db = self._init_db()
        # Fold the editable DB config layer under the read-only config.json now
        # that the shared connector exists (config.json/env stay read-only on top).
        self._apply_db_config()
        # Telegram MUST be initialised after _apply_db_config: the token/chat_id
        # are editable config that live in the DB, not config.json — initialising
        # before the DB layer is folded in would read them empty.
        self._init_telegram()
        # Module configuration lives in the DB; needs the connector + fernet, so
        # it is wired here rather than in _read_config.
        self.config_modules = self._init_modules()
        self._history = self._init_history()
        self._check_state_store = self._init_check_state()
        # The working state lives in the DB (check_state) — no status.json.
        self._read_status()
        self._hosts_store = self._init_hosts_store()
        self._credentials_store = self._init_credentials_store()
        self._audit_store = self._init_audit_store()
        self._reconcile_module_tables()
        self.debug.print("> Monitor >> Monitor Init OK")

    def _init_db(self):
        """Create the shared DB connector from the ``database`` config section.

        Shared by the HistoryStore and exposed to watchful modules via the
        ``db`` property so they can use their own module-declared tables.
        """
        if not self.dir_var:
            return None
        try:
            from lib.db import get_connector  # noqa: PLC0415
            from lib.config.manager import bootstrap_database_cfg  # noqa: PLC0415
            # Overlay SS_DB_* env on the config.json database section (same
            # bootstrap path the web admin and syslog service use).
            db_cfg = bootstrap_database_cfg({'database': self.config.get_conf(['database']) or {}})
            return get_connector(db_cfg or None,
                                 default_sqlite_path=os.path.join(self.dir_var, 'data.db'))
        except Exception:  # pylint: disable=broad-except
            return None

    def _apply_db_config(self):
        """Overlay the editable DB config under the read-only ``config.json``.

        The connector was built from the (file/env) ``database`` section; here we
        fold in the rest of the configuration that now lives in the DB so every
        ``self.config.get_conf(...)`` sees the effective values.  ``config.json``
        keeps overriding the DB (read-only), exactly like the web admin.  Secrets
        in the DB are ciphertext → decrypted by field name.  The monitor only
        *reads*; the one-time file→DB migration is owned by the web admin.
        """
        if getattr(self, '_db', None) is None or not self.dir_config:
            return
        try:
            from lib.stores.config  import ConfigStore     # noqa: PLC0415
            from lib.config         import config_path      # noqa: PLC0415
            from lib.config.manager import ConfigManager   # noqa: PLC0415
            # Same single ConfigManager the web admin uses — the one place that
            # merges the editable DB layer under config.json.  The monitor only
            # reads; the file→DB migration is owned by the web admin.
            mgr = ConfigManager(ConfigStore(self._db), config_path(self.dir_config),
                                fernet=getattr(self, '_fernet', None))
            self.config.data = mgr.read()
        except Exception:  # pylint: disable=broad-except
            return
        # Recompute the public URL from the now-effective config.
        _raw_url = normalize_url(self.config.get_conf(['web_admin', 'public_url'], ''))
        if _raw_url:
            _force_https = self.config.get_conf(
                ['web_admin', 'force_https'], cfg_default('web_admin|force_https'))
            self._public_url = ('https://' if _force_https else 'http://') + _raw_url
        else:
            self._public_url = ''

    @property
    def db(self):
        """The shared DB connector (or None when no var dir / init failed)."""
        return getattr(self, '_db', None)

    def _init_hosts_store(self):
        """Create the host registry store so modules can resolve host_uid → connection."""
        if self._db is None:
            return None
        try:
            from lib.stores.hosts import HostsStore  # noqa: PLC0415
            from lib.security import secret_manager          # noqa: PLC0415
            from lib.modules import ModuleBase       # noqa: PLC0415
            secret_keys = secret_manager.ENCRYPT_KEYS | ModuleBase.discover_secret_fields(self.dir_modules)
            return HostsStore(self._db, fernet=getattr(self, '_fernet', None),
                              secret_keys=secret_keys)
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_credentials_store(self):
        """Create the reusable-credentials store so checks can resolve cred_uid."""
        if self._db is None:
            return None
        try:
            from lib.stores.credentials import CredentialsStore   # noqa: PLC0415
            from lib.security import secret_manager                        # noqa: PLC0415
            from lib.modules import ModuleBase                    # noqa: PLC0415
            from lib.modules.credential_schemas import credential_secret_fields  # noqa: PLC0415
            secret_keys = (secret_manager.ENCRYPT_KEYS
                           | ModuleBase.discover_secret_fields(self.dir_modules)
                           | credential_secret_fields(self.dir_modules))
            return CredentialsStore(self._db, fernet=getattr(self, '_fernet', None),
                                    secret_keys=secret_keys)
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_history(self):
        """Create a HistoryStore on the shared connector."""
        if self._db is None:
            return None
        try:
            from lib.stores.history import HistoryStore  # noqa: PLC0415
            return HistoryStore(self._db)
        except Exception:  # pylint: disable=broad-except
            return None

    def _init_check_state(self):
        """Create the persistent current-state store on the shared connector."""
        if self._db is None:
            return None
        try:
            from lib.stores.check_state import CheckStateStore  # noqa: PLC0415
            return CheckStateStore(self._db)
        except Exception:  # pylint: disable=broad-except
            return None

    def purge_maintenance_states(self):
        """Drop the live status of checks bound to a host in maintenance.

        A host in maintenance has its checks skipped (``resolve_host`` disables
        them), so their last status would otherwise linger stale.  We remove
        those entries from the working state (persisted to ``check_state`` on
        the next save) — the history is kept, so the host modal can still show
        the last recorded value as *historic*.  When the host leaves
        maintenance, the next check has no baseline and re-announces its current
        state.  Called once per cycle.
        """
        hstore = getattr(self, '_hosts_store', None)
        if hstore is None:
            return
        try:
            maint = {h.get('uid') for h in (hstore.list(decrypt=False) or [])
                     if isinstance(h, dict) and h.get('maintenance')}
        except Exception:  # pylint: disable=broad-except
            return
        if not maint:
            return
        # {module: {item_key}} for items bound to a maintenance host.
        maint_items: dict = {}
        cfg = self.config_modules.data or {}
        for mod_name, mod_cfg in cfg.items():
            if not isinstance(mod_cfg, dict):
                continue
            for coll, items in mod_cfg.items():
                if coll.startswith('__') or not isinstance(items, dict):
                    continue
                for ikey, item in items.items():
                    if isinstance(item, dict) and item.get('host_uid') in maint:
                        maint_items.setdefault(mod_name, set()).add(ikey)
        if not maint_items:
            return
        dirty = False
        for mod_name, item_keys in maint_items.items():
            mod_status = self.status.data.get(mod_name)
            if not isinstance(mod_status, dict):
                continue
            for skey in list(mod_status.keys()):
                # Match exact item keys and derived "<base>_suffix" result keys.
                base = skey if skey in item_keys else skey.rsplit('_', 1)[0]
                if base in item_keys:
                    del mod_status[skey]
                    dirty = True
        if dirty:
            self.status.save()

    def _reconcile_module_tables(self):
        """Let watchful modules create their own tables on the shared connector."""
        if self._db is None:
            return
        try:
            from lib.db import reconcile_module_tables  # noqa: PLC0415
            reconcile_module_tables(self._db)
        except Exception:  # pylint: disable=broad-except
            pass

    def _init_audit_store(self):
        """Audit store on the shared connector — same ``audit`` table the web
        admin uses, so daemon/systemd events land in one audit trail instead of
        a separate audit.json file."""
        if self._db is None:
            return None
        try:
            from lib.stores.audit import AuditStore  # noqa: PLC0415
            return AuditStore(self._db)
        except Exception:  # pylint: disable=broad-except
            return None

    def _get_item_uid(self, module_name: str, key: str) -> str | None:
        """Return the stable item UID for a result *key* within *module_name*.

        Result keys may be *derived* from the item key — e.g. ram_swap emits
        ``"<item>_ram"`` / ``"<item>_swap"`` for a single item — so when the
        exact key isn't a configured item we fall back to its base key (the
        part before the last ``_``). The exact key is always tried first, so an
        item whose own key contains an underscore is matched correctly.
        """
        module_cfg = self.config_modules.get_conf([module_name])
        if not isinstance(module_cfg, dict):
            return None
        candidates = [key]
        base = key.rsplit('_', 1)[0]
        if base and base != key:
            candidates.append(base)
        for cand in candidates:
            for section_val in module_cfg.values():
                if isinstance(section_val, dict):
                    item = section_val.get(cand)
                    if isinstance(item, dict):
                        uid = item.get('uid')
                        if uid:
                            return str(uid)
        return None

    # ── Audit helpers ─────────────────────────────────────────────────────────

    def _audit_system(self, event: str, detail: str | dict = '') -> None:
        """Append a system-generated audit entry without Flask context.

        Safe to call from background threads and the systemd monitoring process.
        Writes to the shared audit table in the database (the same trail the
        web admin uses) when available; falls back to audit.json otherwise so
        events are never silently dropped.
        """
        store = getattr(self, '_audit_store', None)
        if store is not None:
            try:
                store.insert(
                    ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    event=event, user='system', ip='internal', detail=detail,
                    max_entries=self._AUDIT_MAX_ENTRIES,
                )
                return
            except Exception as exc:  # pylint: disable=broad-except
                self.debug.print(
                    f'> Monitor >> _audit_system DB insert failed, '
                    f'falling back to file: {exc}',
                    DebugLevel.warning,
                )

        if not self.dir_config:
            return
        audit_path = os.path.join(self.dir_config, 'audit.json')
        tmp_path = None
        try:
            # Read existing log
            try:
                with open(audit_path, encoding='utf-8') as f:
                    log: list = json.load(f)
                if not isinstance(log, list):
                    log = []
            except (OSError, json.JSONDecodeError):
                log = []

            log.append({
                'ts':     datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'event':  event,
                'user':   'system',
                'ip':     'internal',
                'detail': detail,
            })
            log = log[-self._AUDIT_MAX_ENTRIES:]

            # Atomic write
            with tempfile.NamedTemporaryFile(
                'w', dir=self.dir_config, suffix='.tmp',
                delete=False, encoding='utf-8',
            ) as tmp:
                json.dump(log, tmp, indent=2, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, audit_path)
        except Exception as exc:  # pylint: disable=broad-except
            self.debug.print(
                f'> Monitor >> _audit_system failed: {exc}',
                DebugLevel.warning,
            )
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _check_dir(path_dir):
        if path_dir:
            os.makedirs(path_dir, exist_ok=True)

    def _read_config(self):
        """ Read the configuration files. """
        if self.dir_config:
            _secret_file = os.path.join(self.dir_config, '.flask_secret')
            _fernet = secret_manager.fernet_from_secret_file(_secret_file)
            self._fernet = _fernet   # kept for the host registry (decrypts profiles)

            # Reuse the config the caller already loaded (centralised single read);
            # only fall back to loading it ourselves when none was injected. Either
            # way the monitor owns runtime decryption of the secrets.  seed=False:
            # the entry point already seeded missing defaults.
            if self._injected_config is not None:
                self.config = self._injected_config
            else:
                self.config = load_config(self.dir_config)
            if _fernet:
                secret_manager.decrypt_all(self.config.data, _fernet)

            # config_modules (DB-backed) is set up by _init_modules() in __init__,
            # once the shared DB connector exists.

            _raw_url = normalize_url(self.config.get_conf(['web_admin', 'public_url'], ''))
            if _raw_url:
                _force_https = self.config.get_conf(['web_admin', 'force_https'], cfg_default('web_admin|force_https'))
                _scheme = 'https://' if _force_https else 'http://'
                self._public_url = _scheme + _raw_url
            else:
                self._public_url = ''
        else:
            self.config = ConfigControl(None, {})
            self._public_url = ''

    def _init_modules(self):
        """Module configuration store (DB-backed).

        Mirrors :meth:`_read_status`: a ``DbBackedModules`` facade over
        ``ModulesStore`` so every ``config_modules.get_conf(...)`` caller is
        unchanged.  Falls back to an in-memory ConfigControl when no DB is
        available.
        """
        if getattr(self, '_db', None) is None:
            return ConfigControl(None, {})
        from lib.stores.modules import ModulesStore, DbBackedModules  # noqa: PLC0415
        store = ModulesStore(self._db)
        facade = DbBackedModules(store, fernet=getattr(self, '_fernet', None))
        facade.read()
        return facade

    def _read_status(self):
        """Load the working state from the ``check_state`` DB table.

        The state lives entirely in the database now (no ``status.json``); when
        no DB store is available (e.g. no var dir) an in-memory store is used.
        """
        store = getattr(self, '_check_state_store', None)
        if store is not None:
            from lib.stores.check_state import DbBackedStatus  # noqa: PLC0415
            self.status = DbBackedStatus(store, self._get_item_uid)
            self.status.read()
        else:
            self.status = ConfigControl(None, {})

    def clear_status(self):
        """Clear all current check state (the ``check_state`` table)."""
        self.debug.print("> Monitor >> Clear Status", DebugLevel.info)
        self.status.data = {}
        self.status.save()

    def _init_telegram(self):
        """ Initialize (or refresh) the Telegram object from the config.

        The token/chat_id are editable config that live in the DB, so this MUST
        run after :meth:`_apply_db_config` (the effective config is folded in).
        When a Telegram instance already exists (live refresh from the daemon),
        the credentials are updated in place — the background sender thread reads
        them at send time — so changing them in the UI takes effect without a
        restart and without churning the sender thread.
        """
        if not self.config:
            self.tg = None
            return
        token   = self.config.get_conf(['telegram', 'token'], '')
        chat_id = self.config.get_conf(['telegram', 'chat_id'], '')
        group   = self.config.get_conf(['telegram', 'group_messages'],
                                       cfg_default('telegram|group_messages'))
        if getattr(self, 'tg', None) is not None:
            self.tg.token = token
            self.tg.chat_id = chat_id
            self.tg.group_messages = group
        else:
            self.tg = Telegram(token, chat_id)
            self.tg.group_messages = group
        self.debug.print(
            f"> Monitor >> Telegram {'configured' if token else 'not configured'}"
            f" (group_messages={self.tg.group_messages})", DebugLevel.info)

    def refresh_runtime_config(self):
        """Re-read the effective (DB+file) config and re-apply the bits that may
        change live: the Telegram credentials and the public URL.  Called by the
        persistent daemon each cycle so UI config edits take effect without a
        restart (the Telegram sender thread is updated in place, not recreated)."""
        self._apply_db_config()
        self._init_telegram()
        # Re-read the module config from the DB each cycle.  The persistent daemon
        # monitor holds its OWN ModulesStore whose version() counter is bumped only
        # by its own writes — it never sees the web admin's edits (a separate store
        # instance) — so a conditional reload would never fire.  Read unconditionally
        # so checks added/edited in the UI (e.g. a new Proxmox cluster) are picked
        # up without restarting the daemon.  State (streaks) lives elsewhere.
        cm = getattr(self, 'config_modules', None)
        if cm is not None and getattr(cm, '_store', None) is not None:
            try:
                cm.read()
            except Exception:  # pylint: disable=broad-except
                pass

    @property
    def dir_base(self):
        """ Get the base directory. """
        return self._dir_base

    @dir_base.setter
    def dir_base(self, val):
        """ Set the base directory. """
        self._dir_base = val

    @property
    def dir_config(self):
        """ Get the configuration directory. """
        return self._dir_config

    @dir_config.setter
    def dir_config(self, val):
        """ Set the configuration directory. """
        self._dir_config = val

    @property
    def dir_modules(self):
        """ Get the modules directory. """
        return self._dir_modules

    @dir_modules.setter
    def dir_modules(self, val):
        """ Set the modules directory. """
        self._dir_modules = val

    @property
    def dir_var(self):
        """ Get the variable directory. """
        return self._dir_var

    @dir_var.setter
    def dir_var(self, val):
        """ Set the variable directory. """
        self._dir_var = val

    def send_message(self, message, status=None) -> None:
        """ Send a message to Telegram if the Telegram object is initialized. """
        if message and self.tg:
            hostname = socket.gethostname()
            # Hay que enviar "\[" ya que solo "[" se lo come Telegram en modo "Markdown".
            message = f"💻 \\[{hostname}]: {message}"
            if status is True:
                message = f"✅ {message}"
            elif status is False:
                message = f"❎ {message}"
            self.tg.send_message(message)

    def send_message_end(self) -> None:
        """ Send a summary message to Telegram at the end of the check. """
        if self.tg is not None:
            hostname = socket.gethostname()
            self.tg.send_message_end(hostname, public_url=self._public_url)

    def check_status(self, status, module, module_sub_key='') -> bool:
        """ Check if the status has changed for a given module and sub-key. """
        find_key = [module]
        if module_sub_key:
            find_key.append(module_sub_key)
        find_key.append('status')

        current_status = self.status.get_conf(find_key, None)
        return current_status != status

    def _process_module_result(self, module_name: str, result_data: ReturnModuleCheck) -> bool:
        """Apply module result to status and notifications."""
        changed = False

        for key, value in result_data.items():
            self.debug.print(
                f"> Monitor > check_module >> Module: {module_name} - Key: {key} - Val: {value}"
            )

            tmp_status = result_data.get_status(key)
            tmp_message = result_data.get_message(key)
            tmp_send = result_data.get_send(key)
            tmp_other_data = result_data.get_other_data(key)
            tmp_severity = result_data.get_severity(key)

            # Working state lives in self.status (DB-backed); other_data, the
            # message and the severity are refreshed every cycle so the UI/latest-data
            # stay current.
            self.status.set_conf([module_name, key, 'other_data'], tmp_other_data)
            self.status.set_conf([module_name, key, 'message'], tmp_message)
            self.status.set_conf([module_name, key, 'severity'], tmp_severity)

            if self.check_status(tmp_status, module_name, key):
                self.status.set_conf([module_name, key, 'status'], tmp_status)
                changed = True

                # The persisted check_state row is the durable baseline: a
                # restart with an unchanged state stays quiet, while the very
                # first record of a check still notifies its current state.
                if tmp_send:
                    self.send_message(tmp_message, tmp_status)

                self.debug.print(
                    f"> Monitor > check_module >> Module: {module_name}/{key} - New Status: {tmp_status}"
                )

        return changed

    def _import_watchful(self, module_name: str):
        """Import a watchful module by name (returns the imported module).

        Ensures ``watchfuls/`` is on ``sys.path`` so local packages take
        precedence over same-named third-party ones (e.g. our ``dns`` watchful vs
        dnspython), and evicts a stale same-named cache entry left by such a
        third-party import.  Pre-warming all modules with this before the
        concurrent check phase makes later imports cache hits, so a module that
        temporarily mutates ``sys.path`` during its check (dns loading dnspython)
        can't make concurrent bare-name imports of other modules fail.
        """
        if self.dir_modules and self.dir_modules not in sys.path:
            sys.path.insert(0, self.dir_modules)
        cached = sys.modules.get(module_name)
        if cached is not None and not hasattr(cached, 'Watchful'):
            del sys.modules[module_name]
            for _k in [k for k in sys.modules if k.startswith(module_name + '.')]:
                del sys.modules[_k]
        return importlib.import_module(module_name)

    def check_module(self, module_name: str) -> tuple[bool, str, ReturnModuleCheck | None]:
        """
        Execute module check and return raw result.

        Returns:
            tuple[bool, str, ReturnModuleCheck | None]
            (success, module_name, result_data)
        """
        try:
            self.debug.print(f"> Monitor > check_module >> Module: {module_name}", DebugLevel.info)
            module_import = self._import_watchful(module_name)
            module = module_import.Watchful(self)
            result_data = module.check()

            if isinstance(result_data, ReturnModuleCheck):
                return True, module_name, result_data

            msg_debug = '\n\n' + '*' * 60 + '\n'
            msg_debug += f"WARNING: check_module({module_name}) - Format not implement: {type(result_data)}\n" # pylint: disable=line-too-long
            msg_debug += f'Data Return: {pprint.pformat(result_data)}\n'
            msg_debug += '*' * 60 + '\n'
            msg_debug += '*' * 60 + '\n\n'
            self.debug.print(msg_debug, DebugLevel.warning)

        except Exception as e: # pylint: disable=broad-except
            self.debug.exception(e)
            self._audit_system('module_check_error', {
                'module': module_name,
                'error':  f'{type(e).__name__}: {e}',
            })

        return False, module_name, None

    def _get_enabled_modules(self) -> list[str]:
        """Return enabled module names."""
        if not self.dir_modules:
            return []

        modules = []

        # Package-based modules (folder with __init__.py)
        for module_path in glob.glob(os.path.join(self.dir_modules, '*', '__init__.py')):
            module_name = os.path.basename(os.path.dirname(module_path))

            if module_name.startswith('__'):
                continue

            if self.config_modules.get_conf([module_name, "enabled"], self._DEFAULT_ENABLED):
                modules.append(module_name)

        return modules

    def check(self) -> None:
        """Run all enabled checks."""
        self.debug.print(f"> Monitor > check >> Check Init: {time.strftime('%c')}", DebugLevel.info)

        self.status.read()
        self.purge_maintenance_states()
        list_modules = self._get_enabled_modules()

        # Warm module imports sequentially before the concurrent phase below: a
        # module whose check mutates the global sys.path (dns loads dnspython,
        # whose package shadows our 'dns' watchful) must not race with bare-name
        # imports of the other modules.  After warming, every check_module import
        # is a cache hit, immune to that transient sys.path window.
        for _m in list_modules:
            try:
                self._import_watchful(_m)
            except Exception as _e:  # pylint: disable=broad-except
                self.debug.print(
                    f"> Monitor > check >> preload {_m} failed: {_e}", DebugLevel.warning)

        changed = False
        # How many modules to check in parallel — the global Modules default
        # (Configuration > Modules).
        max_threads = self.config.get_conf(['modules', 'threads'], self._DEFAULT_THREADS)
        try:
            max_threads = int(max_threads) or self._DEFAULT_THREADS
        except (TypeError, ValueError):
            max_threads = self._DEFAULT_THREADS

        self.debug.print(
            f"> Monitor > check >> Monitor Max Threads: {max_threads}",
            DebugLevel.info
        )

        # Per-module hard timeout (seconds).  Prevents a single hanging module
        # from blocking the entire monitoring cycle.  Each module enforces its
        # own internal timeouts; this is a last-resort safety net.
        _MODULE_TIMEOUT = 120

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)
        try:
            future_to_module = {
                executor.submit(self.check_module, module): module
                for module in list_modules
            }

            done, not_done = concurrent.futures.wait(
                future_to_module.keys(),
                timeout=_MODULE_TIMEOUT,
            )

            for future in done:
                module_name = future_to_module[future]
                try:
                    success, result_module_name, result_data = future.result()
                    if success and result_data is not None:
                        if self._process_module_result(result_module_name, result_data):
                            changed = True
                    else:
                        self.debug.print(
                            f"> Monitor > check >> Module failed: {module_name}",
                            DebugLevel.warning
                        )
                        # Already audited inside check_module's except block
                except Exception as exc:  # pylint: disable=broad-except
                    self.debug.exception(exc)
                    self._audit_system('module_check_error', {
                        'module': module_name,
                        'error':  f'{type(exc).__name__}: {exc}',
                    })

            for future in not_done:
                module_name = future_to_module[future]
                self.debug.print(
                    f"> Monitor > check >> Module timed out after {_MODULE_TIMEOUT}s: {module_name}",
                    DebugLevel.warning
                )
                self._audit_system('module_check_timeout', {
                    'module':  module_name,
                    'timeout': _MODULE_TIMEOUT,
                })
                future.cancel()
        finally:
            # wait=False: do not block for hanging threads; they will finish
            # on their own module-level timeouts (socket/subprocess timeouts).
            executor.shutdown(wait=False, cancel_futures=True)

        self.debug.debug_obj(__name__, self.status.data, "Debug Status Save")

        if changed or self._status_counts_dirty:
            self.status.save()
            self._status_counts_dirty = False

        self.send_message_end()
        self.debug.print(f"> Monitor > check >> Check End: {time.strftime('%c')}", DebugLevel.info)
