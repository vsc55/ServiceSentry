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


import os
import sys
import time
import argparse

from lib import Monitor
from lib import ObjectBase
from lib.debug import DebugLevel
from lib.config import ConfigControl


class Main(ObjectBase):
    """
    Main class for the ServiceSentry application.

    Attributes:
        monitor (Monitor): Instance of the Monitor class.
        cfg_general (ConfigControl): General configuration control.
        cfg_monitor (ConfigControl): Monitor configuration control.
        cfg_modules (ConfigControl): Modules configuration control.
        __cfg_file_config (str): Path to the general configuration file.
        __cfg_file_monitor (str): Path to the monitor configuration file.
        __cfg_file_modules (str): Path to the modules configuration file.

    Methods:
        __init__(args_get): Initializes the Main class with given arguments.
        __init_config(): Initializes the configuration.
        __check_config(): Checks if the configuration is valid.
        __default_conf(): Sets default configuration values.
        __read_config(): Reads the configuration values.
        __sys_path_append(list_dir): Appends directories to the system path.
        __init_monitor(): Initializes the monitor.
        _is_mode_dev(): Checks if the application is in development mode.
        _dir(): Returns the path where the program is running.
        _modules_dir(): Returns the path to the modules directory.
        _lib_dir(): Returns the path to the libraries directory.
        _config_dir(): Returns the path to the configuration files directory.
        _var_dir(): Returns the path to the /var/lib directory.
        _config_file(): Returns the path to the configuration file.
        __args_set(args_get): Sets the arguments.
        __args_cmd(args_get): Executes commands based on arguments.
        _daemon_mode(): Gets the daemon mode status.
        _daemon_mode(val): Sets the daemon mode status.
        _timer_check(): Gets the timer check value.
        _timer_check(val): Sets the timer check value.
        start(): Starts the main process.
    """

    monitor = None
    cfg_general = None
    cfg_monitor = None
    cfg_modules = None
    __cfg_file_config = 'config.json'
    __cfg_file_monitor = 'monitor.json'
    __cfg_file_modules = 'modules.json'

    def __init__(self, args_get):
        """
        Initializes the main class with the provided arguments.

        Args:
            args_get (list): List of arguments passed to the program.

        Attributes:
            _daemon_mode (bool): Indicates if the program is running in daemon mode.
            _timer_check (int): Timer check interval.
        """
        self.__path_config = None
        self.__verbose = False
        self.__timer_check_force = None
        self._daemon_mode = False
        self._timer_check = 0
        self.__sys_path_append([self._modules_dir])
        self.__args_set(args_get)
        self.__init_config()
        self.__init_monitor()
        self.__args_cmd(args_get)

    def __init_config(self):
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
        if self.__check_config():
            self.__default_conf()
            self.__read_config()
        else:
            raise ValueError("Error load config.")

    def __check_config(self):
        """
        Checks if the general configuration is set.

        Returns:
            bool: True if the general configuration is set, False otherwise.
        """
        return bool(self.cfg_general)

    def __default_conf(self):
        """
        Ensures that the default configuration settings are present.

        This method checks if certain configuration settings exist in the 
        configuration file. If they do not exist, it sets them to default values.

        Returns:
            bool: True if the configuration check is enabled and the default 
                  settings are ensured, False otherwise.
        """
        if self.__check_config():
            if not self.cfg_general.is_exist_conf(['daemon', 'timer_check']):
                self.cfg_general.set_conf(['daemon', 'timer_check'], 300)

            if not self.cfg_general.is_exist_conf(['global', 'debug']):
                self.cfg_general.set_conf(['global', 'debug'], False)

            return True
        return False

    def __read_config(self):
        """
        Reads and applies the configuration settings.

        This method sets the debug level and enables or disables debugging based on the verbose flag.
        It also updates the timer check interval based on the configuration settings.

        Attributes:
            __verbose (bool): Determines if verbose mode is enabled.
            __timer_check_force (int): Overrides the timer check interval if set.
            debug (object): Debugging configuration object.
            cfg_general (object): Configuration object for general settings.
            _timer_check (int): Timer check interval.

        Debug Levels:
            DebugLevel.null: No debugging information.
            DebugLevel.info: Informational debugging level.
        """

        if self.__verbose:
            self.debug.enabled = True
            self.debug.level = DebugLevel.null
        else:
            self.debug.level = DebugLevel.info
            # TODO: Actualizar configuracin para que use level
            self.debug.enabled = True
            # self.debug.enabled = self.cfg_general.get_conf(['global', 'debug'], self.debug.enabled)

        if self.__timer_check_force:
            self._timer_check = self.__timer_check_force
        else:
            self._timer_check = self.cfg_general.get_conf(['daemon', 'timer_check'], self._timer_check)

    @staticmethod
    def __sys_path_append(list_dir):
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

    def __init_monitor(self):
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
        if self.__path_config:
            return self.__path_config
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
        return os.path.join(self._config_dir, self.__cfg_file_config)

    def __args_set(self, args_get):
        """
        Sets the configuration parameters based on the provided arguments.

        Args:
            args_get (dict): A dictionary containing configuration parameters.

        The dictionary can have the following keys:
            - 'path': Sets the configuration path.
            - 'verbose': Sets the verbosity level.
            - 'timer_check': Sets the timer check force.
            - 'daemon_mode': Sets the daemon mode.
        """
        if args_get:
            for key, value in args_get.items():
                if key == 'path':
                    self.__path_config = value

                elif key == 'verbose':
                    self.__verbose = value

                elif key == 'timer_check':
                    self.__timer_check_force = value

                elif key == 'daemon_mode':
                    self.__daemon_mode = value

    def __args_cmd(self, args_get):
        """
        Processes command-line arguments and performs actions based on them.

        Args:
            args_get (dict): A dictionary of command-line arguments and their values.

        Actions:
            - If 'clear_status' key is present and its value is True, it calls the clear_status method on the monitor object.
        """
        if args_get:
            for key, value in args_get.items():
                if key == 'clear_status':
                    if value:
                        if self.monitor:
                            self.monitor.clear_status()

    @property
    def _daemon_mode(self):
        """
        Returns the current daemon mode status.

        Returns:
            bool: True if the service is running in daemon mode, False otherwise.
        """
        return self.__daemon_mode

    @_daemon_mode.setter
    def _daemon_mode(self, val):
        """
        Sets the daemon mode for the service.

        Args:
            val (bool): If True, the service will run in daemon mode.
        """
        self.__daemon_mode = val

    @property
    def _timer_check(self):
        """
        Checks the status of the timer.

        Returns:
            int: The current timer value if it exists, otherwise 0.
        """
        if self.__timer_check:
            return self.__timer_check
        return 0

    @_timer_check.setter
    def _timer_check(self, val):
        """
        Validates and sets the timer check value.

        This method ensures that the input value is converted to an integer and is non-negative.
        If the input value is None, a non-numeric string, or any other type that cannot be 
        converted to an integer, it defaults to 0.

        Args:
            val (Any): The value to be validated and set. It can be of type int, float, str, or None.

        Sets:
            self.__timer_check (int): The validated and converted timer check value.
        """
        if not val:
            val = 0
        elif isinstance(val, str):
            if not val.isnumeric():
                val = 0
            else:
                val = int(val)
        elif isinstance(val, float):
            val = int(val)
        elif not isinstance(val, int):
            val = 0

        if int(val) < 0:
            val = 0

        self.__timer_check = int(val)

    def start(self):
        """
        Starts the service in either single process mode or daemon mode.

        In single process mode, it runs the monitor check once.
        In daemon mode, it continuously runs the monitor check at intervals specified by `_timer_check`.

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
        else:
            self.debug.print("* Main >> Run Mode Daemon")
            while True:
                self.monitor.check()
                if self._timer_check == 0:
                    break
                self.debug.print(f"* Main >> Waiting {self._timer_check} seconds...")
                try:
                    time.sleep(self._timer_check)
                except KeyboardInterrupt:
                    self.debug.print("* Main >> Process cancel  by the user!!", DebugLevel.info)
                    try:
                        sys.exit(0)
                    except SystemExit:
                        os._exit(0)
                except Exception as e:
                    self.debug.exception(e)


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


def arg_check_timer(timer_check):
    """
    Validates that the provided timer_check argument is a positive integer.

    Args:
        timer_check (str): The timer value to be checked.

    Returns:
        str: The validated timer value if it is a positive integer.

    Raises:
        argparse.ArgumentTypeError: If the timer_check is not a positive integer.
    """
    if timer_check.isnumeric() and int(timer_check) > 0:
        return timer_check
    else:
        raise argparse.ArgumentTypeError(f"{timer_check} is not a valid timer")


if __name__ == "__main__":
    # Allow_abbrev modo estricto en la detección de argumento, de lo contrario --pat lo reconocería como --path
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument(
        '-c', '--clear',
        default=False,
        action="store_true",
        dest="clear_status",
        help="clear status.json"
    )
    ap.add_argument(
        '-d', '--daemon',
        default=False,
        action="store_true",
        dest="daemon_mode",
        help="start mode daemon"
    )
    ap.add_argument(
        '-t', '--timer',
        default=None,
        type=arg_check_timer,
        dest="timer_check",
        help="timer interval of the check in daemon mode"
    )
    ap.add_argument(
        '-v', '--verbose',
        default=False,
        action="store_true",
        dest="verbose",
        help="verbose mode true"
    )
    ap.add_argument(
        '-p', '--path',
        default=None,
        type=arg_check_dir_path,
        dest="path",
        help="path config files"
    )
    args = vars(ap.parse_args())

    main = Main(args)
    main.start()
