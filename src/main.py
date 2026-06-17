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
from lib.config.spec import cfg_default
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

        # Add src/ (parent of watchfuls/) so modules can be imported as
        # 'watchfuls.dns', 'watchfuls.ping', etc.  This avoids name collisions
        # with third-party packages that share a short name (e.g. dnspython→'dns').
        self._sys_path_insert([self._dir, self._modules_dir])
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
        _is_new = not self.cfg_general.is_data
        if self._check_config():
            self._default_conf()
            if _is_new:
                self.cfg_general.save()
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
                self.cfg_general.set_conf(['daemon', 'timer_check'], cfg_default('daemon|timer_check'))

            if not self.cfg_general.is_exist_conf(['global', 'log_level']):
                self.cfg_general.set_conf(['global', 'log_level'], cfg_default('global|log_level'))

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
            # CLI --verbose forces debug on regardless of config.
            self.debug.enabled = True
            self.debug.level = DebugLevel.null
        else:
            self.debug.set_from_config(self.cfg_general.get_conf(
                ['global', 'log_level'], cfg_default('global|log_level')
            ))

        if self._timer_check_force:
            self._timer_check = self._timer_check_force
        else:
            self._timer_check = self.cfg_general.get_conf(
                ['daemon', 'timer_check'],
                self._timer_check
            )

    @staticmethod
    def _sys_path_append(list_dir):
        """Appends directories to sys.path (kept for compatibility)."""
        for f in list_dir:
            if os.path.isdir(f) and f not in sys.path:
                sys.path.append(f)

    @staticmethod
    def _sys_path_insert(list_dir):
        """Insert directories at the front of sys.path.

        Inserting at position 0 ensures these directories are searched
        before site-packages, preventing short module names from being
        shadowed by installed packages with the same name
        (e.g. 'watchfuls/dns/' vs the 'dnspython' package which is also
        importable as 'dns').
        """
        for f in reversed(list_dir):   # reversed so first item ends up at index 0
            if os.path.isdir(f) and f not in sys.path:
                sys.path.insert(0, f)

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
            return self._config_dir
        elif sys.platform == 'win32':
            return os.path.join(
                os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'ServiSesentry'
            )
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


def start_web(args):
    """Start the web administration server.

    Reads web_admin settings from ``config.json`` and launches a Flask
    server for browser-based configuration editing.
    """
    try:
        from lib.web_admin import WebAdmin  # noqa: WPS433 – conditional import
    except ImportError:
        print("Error: Flask es necesario para el panel web.")
        print("       Instálalo con:  pip install flask")
        sys.exit(1)

    from lib.config import ConfigControl as _CC

    dir_base = os.path.dirname(os.path.abspath(__file__))
    is_dev = 'src' in dir_base

    path_config = getattr(args, 'path', None)
    if path_config:
        config_dir = path_config
    elif is_dev:
        config_dir = os.path.normpath(os.path.join(dir_base, '../data/'))
    else:
        config_dir = '/etc/ServiSesentry/'

    if is_dev:
        var_dir = config_dir
    elif sys.platform == 'win32':
        var_dir = os.path.join(
            os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'ServiSesentry'
        )
    else:
        var_dir = '/var/lib/ServiSesentry/'

    cfg = _CC(os.path.join(config_dir, 'config.json'))
    cfg.read()

    # Env vars take precedence for first-run credential setup (never written to disk)
    username = os.environ.get('WA_USERNAME') or cfg.get_conf(['web_admin', 'username'], 'admin')
    password = os.environ.get('WA_PASSWORD') or cfg.get_conf(['web_admin', 'password'], 'admin')
    # All web_admin runtime options are loaded from config.json by WebAdmin
    # itself (via _apply_saved_config / the central registry config_spec), so
    # they need not be read or forwarded here — only the first-run credentials
    # and the bind host/port (which also accept CLI overrides) are handled here.
    host = getattr(args, 'web_host', None) or cfg.get_conf(
        ['web_admin', 'host'], WebAdmin.DEFAULT_HOST
    )
    port = getattr(args, 'web_port', None) or cfg.get_conf(
        ['web_admin', 'port'], WebAdmin.DEFAULT_PORT
    )

    admin = WebAdmin(config_dir, str(username), str(password), var_dir,
                     modules_dir=os.path.join(dir_base, 'watchfuls'))

    print("ServiceSentry Web Admin")
    print(f"  URL:    http://{host}:{port}")
    print(f"  Config: {config_dir}")
    if username == 'admin' and password == 'admin':
        print("  ⚠  Credenciales por defecto (admin/admin).")
        print("     Configúralas en config.json → web_admin")
    print("  Pulsa Ctrl+C para detener")
    print()

    admin.run(host=str(host), port=int(port), debug=getattr(args, 'verbose', False))


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


def _env_str(name: str, default=None):
    """Environment fallback for a string CLI argument."""
    v = os.environ.get(name)
    return v if v not in (None, '') else default


def _env_bool(name: str, default: bool = False) -> bool:
    """Environment fallback for a boolean (store_true) CLI argument."""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default=None):
    """Environment fallback for an integer CLI argument."""
    v = os.environ.get(name)
    if v in (None, ''):
        return default
    try:
        return int(v)
    except ValueError:
        return default


def args_init() -> argparse.Namespace:
    """Initialize and parse command-line arguments.

    Every argument falls back to an ``SS_*`` environment variable (handy for
    Docker, where flags are awkward): e.g. ``SS_WEB=true``, ``SS_WEB_PORT=8080``,
    ``SS_CONFIG_DIR=/config``, ``SS_VERBOSE=1``, ``SS_NOCOLOR=1``.  Config.json
    fields keep their own env vars (``WA_*``, ``CHECK_INTERVAL``, ``TELEGRAM_*``).
    The standard ``NO_COLOR`` env var is also honoured.

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
        default=_env_bool('SS_CLEAR', False),
        action="store_true",
        dest="clear_status",
        help="clear the status file (status.json) before starting (env: SS_CLEAR)",
    )
    ap.add_argument(
        '-d', '--daemon',
        default=_env_bool('SS_DAEMON', False),
        action="store_true",
        dest="daemon_mode",
        help="run in daemon mode (continuous monitoring loop) (env: SS_DAEMON)",
    )
    ap.add_argument(
        '-t', '--timer',
        default=_env_int('SS_TIMER', None),
        type=arg_check_timer,
        metavar='SECONDS',
        dest="timer_check",
        help="check interval in seconds for daemon mode (default: config file value) (env: SS_TIMER)",
    )
    ap.add_argument(
        '-v', '--verbose',
        default=_env_bool('SS_VERBOSE', False),
        action="store_true",
        dest="verbose",
        help="enable verbose/debug output (env: SS_VERBOSE)",
    )
    ap.add_argument(
        '--nocolor', '--no-color',
        default=_env_bool('SS_NOCOLOR', False) or bool(os.environ.get('NO_COLOR')),
        action="store_true",
        dest="nocolor",
        help="disable ANSI colours in debug output (env: SS_NOCOLOR / NO_COLOR)",
    )
    ap.add_argument(
        '-p', '--path',
        default=_env_str('SS_CONFIG_DIR', None),
        type=arg_check_dir_path,
        metavar='DIR',
        dest="path",
        help="path to the configuration files directory (env: SS_CONFIG_DIR)",
    )

    # Web admin arguments
    web_group = ap.add_argument_group('web admin')
    web_group.add_argument(
        '--web',
        default=_env_bool('SS_WEB', False),
        action="store_true",
        dest="web_mode",
        help="start the web administration panel instead of monitoring (env: SS_WEB)",
    )
    web_group.add_argument(
        '--web-port',
        default=_env_int('SS_WEB_PORT', None),
        type=int,
        metavar='PORT',
        dest="web_port",
        help="port for the web admin panel (default: 8080 or config.json) (env: SS_WEB_PORT)",
    )
    web_group.add_argument(
        '--web-host',
        default=_env_str('SS_WEB_HOST', None),
        metavar='HOST',
        dest="web_host",
        help="host/IP to bind the web admin panel (default: 0.0.0.0) (env: SS_WEB_HOST)",
    )
    return ap.parse_args()

if __name__ == "__main__":
    _args = args_init()
    if getattr(_args, 'nocolor', False):
        from lib.debug import Debug as _Debug
        _Debug.set_color(False)
    if getattr(_args, 'web_mode', False):
        start_web(_args)
    else:
        main = Main(_args)
        start_code = main.start()
        sys.exit(start_code)
