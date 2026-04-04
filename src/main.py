#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
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

"""Module Main."""


import argparse
import os
import sys
import time

from lib import Monitor, ObjectBase
from lib.config import ConfigControl
from lib.debug import DebugLevel


class Main(ObjectBase):
    """ Main class for the ServiceSentry application. """

    monitor = None
    cfg_general = None
    cfg_monitor = None
    cfg_modules = None
    _cfg_file_config = 'config.json'
    _cfg_file_monitor = 'monitor.json'
    _cfg_file_modules = 'modules.json'

    def __init__(self, args: argparse.Namespace):
        """ Initializes the Main class with the provided command-line arguments. """

        self._path_config = getattr(args, 'path', None)
        self._verbose = getattr(args, 'verbose', False)
        self._timer_check_force = getattr(args, 'timer_check', None)
        self._daemon_mode = getattr(args, 'daemon_mode', False)
        self._timer_check = 0

        self._sys_path_append([self._modules_dir])
        self._init_config()
        self._init_monitor()

        if getattr(args, 'clear_status', False) and self.monitor:
            self.monitor.clear_status()

    def _init_config(self):
        """
        Initializes the configuration for the service.

        This method reads the configuration file and checks its validity.
        If the configuration is invalid, it sets the default configuration
        and reads it again. If the configuration cannot be loaded, it raises
        a ValueError.

        Raises:
            ValueError: If the configuration cannot be loaded.
        """
        self.cfg_general = ConfigControl(self._config_file)
        self.cfg_general.read()
        if self._check_config():
            self._default_conf()
            self._read_config()
        else:
            raise ValueError("Error load config.")

    def _check_config(self):
        """
        Checks if the general configuration is set.

        Returns:
            bool: True if the general configuration is set, False otherwise.
        """
        return bool(self.cfg_general)

    def _default_conf(self):
        """
        Ensures that the default configuration settings are present.

        This method checks if certain configuration settings exist in the 
        configuration file. If they do not exist, it sets them to default values.

        Returns:
            bool: True if the configuration check is enabled and the default 
                  settings are ensured, False otherwise.
        """
        if self._check_config():
            if not self.cfg_general.is_exist_conf(['daemon', 'timer_check']):
                self.cfg_general.set_conf(['daemon', 'timer_check'], 300)

            if not self.cfg_general.is_exist_conf(['global', 'debug']):
                self.cfg_general.set_conf(['global', 'debug'], False)

            return True
        return False

    def _read_config(self):
        """
        Reads and applies the configuration settings.

        This method sets the debug level and enables or disables debugging based
        on the verbose flag.
        It also updates the timer check interval based on the configuration settings.

        Attributes:
            _verbose (bool): Determines if verbose mode is enabled.
            _timer_check_force (int): Overrides the timer check interval if set.
            debug (object): Debugging configuration object.
            cfg_general (object): Configuration object for general settings.
            _timer_check (int): Timer check interval.

        Debug Levels:
            DebugLevel.null: No debugging information.
            DebugLevel.info: Informational debugging level.
        """

        if self._verbose:
            self.debug.enabled = True
            self.debug.level = DebugLevel.null
        else:
            self.debug.level = DebugLevel.info
            # TODO: Actualizar configuracin para que use level
            self.debug.enabled = True
            # self.debug.enabled = self.cfg_general.get_conf(['global', 'debug'], self.debug.enabled)

        if self._timer_check_force:
            self._timer_check = self._timer_check_force
        else:
            self._timer_check = self.cfg_general.get_conf(
                ['daemon', 'timer_check'],
                self._timer_check
            )

    @staticmethod
    def _sys_path_append(list_dir):
        """
        Appends directories to the system path if they are not already present.

        Args:
            list_dir (list): A list of directory paths to be added to the system path.

        Returns:
            None
        """
        for f in list_dir:
            if os.path.isdir(f):
                if f not in sys.path:
                    sys.path.append(f)

    def _init_monitor(self):
        """
        Initializes the monitor instance with the specified directories.

        This method sets up the monitor by creating an instance of the Monitor class
        with the provided directory paths for the main directory, configuration directory,
        modules directory, and variable directory.
        """
        self.monitor = Monitor(self._dir, self._config_dir, self._modules_dir, self._var_dir)

    @property
    def _is_mode_dev(self):
        return 'src' in self._dir

    @property
    def _dir(self):
        """Path run program.

        Returns:
        str: Returning value

        """
        return os.path.dirname(os.path.abspath(__file__))

    @property
    def _modules_dir(self):
        """Path modules.

        Returns:
        str: Returning value

        """
        return os.path.join(self._dir, 'watchfuls')

    @property
    def _lib_dir(self):
        """Path lib's.

        Returns:
        str: Returning value

        """
        return os.path.join(self._dir, 'lib')

    @property
    def _config_dir(self):
        """Path config files.

        Returns:
        str: Returning value

        """
        if self._path_config:
            return self._path_config
        elif self._is_mode_dev:
            return os.path.normpath(os.path.join(self._dir, '../data/'))
        else:
            return '/etc/ServiSesentry/'

    @property
    def _var_dir(self):
        """Path /var/lib...

        Returns:
        str: Returning value

        """
        if self._is_mode_dev:
            return '/var/lib/ServiSesentry/dev/'
        else:
            return '/var/lib/ServiSesentry/'

    @property
    def _config_file(self):
        """
        Constructs the full path to the configuration file.

        Returns:
            str: The full path to the configuration file, constructed by joining
                 the configuration directory and the configuration file name.
        """
        return os.path.join(self._config_dir, self._cfg_file_config)

    @property
    def _timer_check(self) -> int:
        """ Timer check interval in seconds. """
        return self._timer_check_value

    @_timer_check.setter
    def _timer_check(self, val):
        """
        Validates and sets the timer check value.

        Ensures the value is converted to a non-negative integer.

        Args:
            val: The value to set. Accepts int, float, str, or None.
        """
        if not val:
            val = 0
        elif isinstance(val, str):
            val = int(val) if val.isnumeric() else 0
        elif isinstance(val, float):
            val = int(val)
        elif not isinstance(val, int):
            val = 0

        self._timer_check_value = max(0, int(val))

    def start(self) -> int:
        """
        Starts the service in either single process mode or daemon mode.

        In single process mode, it runs the monitor check once.
        In daemon mode, it continuously runs the monitor check at intervals 
        specified by `_timer_check`.

        Raises:
            KeyboardInterrupt: If the process is interrupted by the user.
            Exception: If any other exception occurs during the sleep interval.

        Notes:
            - In daemon mode, if `_timer_check` is set to 0, the loop will break immediately.
            - The method handles `KeyboardInterrupt` to allow graceful shutdown by the user.
        """
        if not self._daemon_mode:
            self.debug.print("* Main >> Run Mode Single Process")
            self.monitor.check()
            return 0

        self.debug.print("* Main >> Run Mode Daemon")
        while True:
            self.monitor.check()
            if self._timer_check == 0:
                break

            self.debug.print(f"* Main >> Waiting {self._timer_check} seconds...")
            try:
                time.sleep(self._timer_check)
            except KeyboardInterrupt:
                self.debug.print("* Main >> Process cancelled by the user!!", DebugLevel.info)
                try:
                    sys.exit(0)
                except SystemExit:
                    os._exit(0)

            except Exception as e:
                self.debug.exception(e)
                return 1

        return 2


def arg_check_dir_path(path):
    """
    Check if the provided path is a valid directory path.

    Args:
        path (str): The directory path to check.

    Returns:
        str: The valid directory path if it exists, otherwise an empty string.

    Raises:
        argparse.ArgumentTypeError: If the provided path is not a valid directory.
    """
    if not path:
        return ''
    elif os.path.isdir(path):
        return path
    else:
        raise argparse.ArgumentTypeError(f"{path} is not a valid path")


def arg_check_timer(timer_check: str) -> int:
    """
    Validates that the provided timer_check argument is a positive integer.

    Args:
        timer_check: The timer value string to validate.

    Returns:
        The validated timer value as integer.

    Raises:
        argparse.ArgumentTypeError: If the timer_check is not a positive integer.
    """
    if timer_check.isnumeric() and int(timer_check) > 0:
        return int(timer_check)
    raise argparse.ArgumentTypeError(f"{timer_check} is not a valid timer")


def args_init() -> argparse.Namespace:
    """
    Initializes and parses command-line arguments.

    Returns:
        argparse.Namespace: The parsed command-line arguments.
    """
    ap = argparse.ArgumentParser(
        prog='ServiceSentry',
        description='ServiceSentry - Service monitoring and alerting tool.',
        epilog='Example: %(prog)s -d -t 60 -v',
        allow_abbrev=False,
    )

    ap.add_argument(
        '-c', '--clear',
        default=False,
        action="store_true",
        dest="clear_status",
        help="clear the status file (status.json) before starting",
    )
    ap.add_argument(
        '-d', '--daemon',
        default=False,
        action="store_true",
        dest="daemon_mode",
        help="run in daemon mode (continuous monitoring loop)",
    )
    ap.add_argument(
        '-t', '--timer',
        default=None,
        type=arg_check_timer,
        metavar='SECONDS',
        dest="timer_check",
        help="check interval in seconds for daemon mode (default: config file value)",
    )
    ap.add_argument(
        '-v', '--verbose',
        default=False,
        action="store_true",
        dest="verbose",
        help="enable verbose/debug output",
    )
    ap.add_argument(
        '-p', '--path',
        default=None,
        type=arg_check_dir_path,
        metavar='DIR',
        dest="path",
        help="path to the configuration files directory",
    )
    return ap.parse_args()

if __name__ == "__main__":
    main = Main(args_init())
    start_code = main.start()
    sys.exit(start_code)
