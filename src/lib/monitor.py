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

from lib.config import ConfigControl
from lib.debug import DebugLevel
from lib.modules import ReturnModuleCheck
from lib.object_base import ObjectBase
from lib.telegram import Telegram
from lib import secret_manager

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

    def __init__(self, dir_base: str, dir_config: str, dir_modules: str, dir_var: str):
        self.dir_base = dir_base
        self.dir_config = dir_config
        self.dir_modules = dir_modules
        self.dir_var = dir_var

        self._read_config()
        self._read_status()
        self._init_telegram()
        self._db = self._init_db()
        self._history = self._init_history()
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
            db_cfg = self.cfg_general.get_conf(['database']) or {}
            return get_connector(db_cfg or None,
                                 default_sqlite_path=os.path.join(self.dir_var, 'data.db'))
        except Exception:  # pylint: disable=broad-except
            return None

    @property
    def db(self):
        """The shared DB connector (or None when no var dir / init failed)."""
        return getattr(self, '_db', None)

    def _init_history(self):
        """Create a HistoryStore on the shared connector."""
        if self._db is None:
            return None
        try:
            from lib.history_store import HistoryStore  # noqa: PLC0415
            return HistoryStore(self._db)
        except Exception:  # pylint: disable=broad-except
            return None

    def _reconcile_module_tables(self):
        """Let watchful modules create their own tables on the shared connector."""
        if self._db is None:
            return
        try:
            from lib.db import reconcile_module_tables  # noqa: PLC0415
            reconcile_module_tables(self._db)
        except Exception:  # pylint: disable=broad-except
            pass

    def _get_item_uid(self, module_name: str, key: str) -> str | None:
        """Return the stable UID for *key* within *module_name*, or None."""
        module_cfg = self.config_modules.get_conf([module_name])
        if not isinstance(module_cfg, dict):
            return None
        for section_val in module_cfg.values():
            if isinstance(section_val, dict):
                item = section_val.get(key)
                if isinstance(item, dict):
                    uid = item.get('uid')
                    if uid:
                        return str(uid)
        return None

    # ── Audit helpers ─────────────────────────────────────────────────────────

    def _audit_system(self, event: str, detail: str | dict = '') -> None:
        """Append a system-generated entry to audit.json without Flask context.

        Safe to call from background threads and the systemd monitoring process.
        Writes directly to the audit file; concurrent access is serialised by
        the same atomic-replace logic used everywhere else.
        """
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

            self.config = ConfigControl(os.path.join(self.dir_config, 'config.json'))
            self.config.read()
            if _fernet:
                secret_manager.decrypt_all(self.config.data, _fernet)

            self.config_monitor = ConfigControl(os.path.join(self.dir_config, 'monitor.json'))
            self.config_monitor.read()

            self.config_modules = ConfigControl(os.path.join(self.dir_config, 'modules.json'))
            self.config_modules.read()
            if _fernet:
                secret_manager.decrypt_all(self.config_modules.data, _fernet)
            if not self.config_modules.is_data:
                self.config_modules.data = {}
                self.config_modules.save()

            _raw_url = self.config.get_conf(['web_admin', 'public_url'], '').strip().rstrip('/')
            if _raw_url:
                _force_https = self.config.get_conf(['web_admin', 'force_https'], False)
                _scheme = 'https://' if _force_https else 'http://'
                self._public_url = _scheme + _raw_url
            else:
                self._public_url = ''
        else:
            self.config = ConfigControl(None, {})
            self.config_monitor = ConfigControl(None, {})
            self.config_modules = ConfigControl(None, {})
            self._public_url = ''

    def _read_status(self):
        """ Read the status file. If the file does not exist, it will be created. """
        if self.dir_var:
            self._check_dir(self.dir_var)
            self.status = ConfigControl(os.path.join(self.dir_var, 'status.json'), {})
            if not self.status.is_exist_file:
                self.status.save()
        else:
            self.status = ConfigControl(None, {})

    def clear_status(self):
        """ Clear the status file. """
        # TODO: Pendiente crear funcion clear en el objeto config # pylint: disable=fixme
        self.debug.print("> Monitor >> Clear Status", DebugLevel.info)
        self.status.data = {}
        self.status.save()

    def _init_telegram(self):
        """ Initialize the Telegram object if the configuration is available. """
        if self.config:
            self.tg = Telegram(
                self.config.get_conf(['telegram', 'token'], ''),
                self.config.get_conf(['telegram', 'chat_id'], '')
            )
            self.tg.group_messages = self.config.get_conf(['telegram', 'group_messages'], False)
        else:
            self.tg = None

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

    def get_conf(self, find_key=None, default_val=None):
        """ Get a configuration value from the monitor configuration. """
        if self.config_monitor:
            return self.config_monitor.get_conf(find_key, default_val)
        return default_val

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

            self.status.set_conf([module_name, key, 'other_data'], tmp_other_data)

            if self.check_status(tmp_status, module_name, key):
                self.status.set_conf([module_name, key, 'status'], tmp_status)
                changed = True

                if tmp_send:
                    self.send_message(tmp_message, tmp_status)

                self.debug.print(
                    f"> Monitor > check_module >> Module: {module_name}/{key} - New Status: {tmp_status}"
                )

        return changed

    def check_module(self, module_name: str) -> tuple[bool, str, ReturnModuleCheck | None]:
        """
        Execute module check and return raw result.

        Returns:
            tuple[bool, str, ReturnModuleCheck | None]
            (success, module_name, result_data)
        """
        try:
            self.debug.print(f"> Monitor > check_module >> Module: {module_name}", DebugLevel.info)
            # Ensure watchfuls/ is at the front of sys.path so local packages
            # (e.g. watchfuls/dns/) take precedence over same-named third-party
            # packages (e.g. dnspython, also importable as 'dns').
            if self.dir_modules and self.dir_modules not in sys.path:
                sys.path.insert(0, self.dir_modules)

            # Python caches imports in sys.modules.  If a third-party package
            # with the same short name was imported first (e.g. dnspython→'dns'),
            # importlib.import_module() would return the wrong cached module.
            # Detect that case and evict the stale entry so a clean re-import
            # picks up the correct watchful from sys.path.
            cached = sys.modules.get(module_name)
            if cached is not None and not hasattr(cached, 'Watchful'):
                del sys.modules[module_name]
                for _k in [k for k in sys.modules if k.startswith(module_name + '.')]:
                    del sys.modules[_k]

            module_import = importlib.import_module(module_name)
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
        list_modules = self._get_enabled_modules()

        changed = False
        max_threads = self.get_conf('threads', self._DEFAULT_THREADS)

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

        if changed:
            self.status.save()

        self.send_message_end()
        self.debug.print(f"> Monitor > check >> Check End: {time.strftime('%c')}", DebugLevel.info)
