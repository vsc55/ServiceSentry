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
import glob
import importlib
import os
import pprint
import socket
import time

from lib.config import ConfigControl
from lib.debug import DebugLevel
from lib.modules import ReturnModuleCheck
from lib.object_base import ObjectBase
from lib.telegram import Telegram

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

    def __init__(self, dir_base: str, dir_config: str, dir_modules: str, dir_var: str):
        self.dir_base = dir_base
        self.dir_config = dir_config
        self.dir_modules = dir_modules
        self.dir_var = dir_var

        self._read_config()
        self._read_status()
        self._init_telegram()
        self.debug.print("> Monitor >> Monitor Init OK")

    @staticmethod
    def _check_dir(path_dir):
        if path_dir:
            os.makedirs(path_dir, exist_ok=True)

    def _read_config(self):
        """ Read the configuration files. """
        if self.dir_config:
            self.config = ConfigControl(os.path.join(self.dir_config, 'config.json'))
            self.config.read()

            self.config_monitor = ConfigControl(os.path.join(self.dir_config, 'monitor.json'))
            self.config_monitor.read()

            self.config_modules = ConfigControl(os.path.join(self.dir_config, 'modules.json'))
            self.config_modules.read()
        else:
            self.config = ConfigControl(None, {})
            self.config_monitor = ConfigControl(None, {})
            self.config_modules = ConfigControl(None, {})

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
        # TODO: Pendiente crear funcion clear en el objeto config
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
            self.tg.send_message_end(hostname)

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
            module_import = importlib.import_module(module_name)
            module = module_import.Watchful(self)
            result_data = module.check()

            if isinstance(result_data, ReturnModuleCheck):
                return True, module_name, result_data

            msg_debug = '\n\n' + '*' * 60 + '\n'
            msg_debug += f"WARNING: check_module({module_name}) - Format not implement: {type(result_data)}\n"
            msg_debug += f'Data Return: {pprint.pformat(result_data)}\n'
            msg_debug += '*' * 60 + '\n'
            msg_debug += '*' * 60 + '\n\n'
            self.debug.print(msg_debug, DebugLevel.warning)

        except Exception as e:
            self.debug.exception(e)

        return False, module_name, None

    def _get_enabled_modules(self) -> list[str]:
        """Return enabled module names."""
        if not self.dir_modules:
            return []

        modules = []
        for module_path in glob.glob(os.path.join(self.dir_modules, '*.py')):
            module_name = os.path.splitext(os.path.basename(module_path))[0]

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

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            future_to_module = {
                executor.submit(self.check_module, module): module
                for module in list_modules
            }

            for future in concurrent.futures.as_completed(future_to_module):
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
                except Exception as exc:
                    self.debug.exception(exc)

        self.debug.debug_obj(__name__, self.status.data, "Debug Status Save")

        if changed:
            self.status.save()

        self.send_message_end()
        self.debug.print(f"> Monitor > check >> Check End: {time.strftime('%c')}", DebugLevel.info)
