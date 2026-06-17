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
""" Debug class for debugging purposes. """

import pprint
import sys
import traceback

from lib.debug.debug_level import DebugLevel

__all__ = ['Debug']

# ANSI colour per level (applied only when stdout is a TTY).
_ANSI = {
    DebugLevel.debug:     '\033[90m',    # grey  — recedes (verbose noise)
    DebugLevel.info:      '\033[36m',    # cyan
    DebugLevel.warning:   '\033[33m',    # yellow
    DebugLevel.error:     '\033[31m',    # red
    DebugLevel.emergency: '\033[1;31m',  # bold red
}
_ANSI_RESET = '\033[0m'


def _enable_windows_ansi() -> None:
    """Best-effort: enable ANSI escape processing on legacy Windows consoles."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes  # noqa: PLC0415
        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11; ENABLE_PROCESSED_OUTPUT(1) |
        # ENABLE_WRAP_AT_EOL_OUTPUT(2) | ENABLE_VIRTUAL_TERMINAL_PROCESSING(4) = 7
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:  # pylint: disable=broad-except
        pass


_enable_windows_ansi()


class Debug:
    """Leveled debug printer.

    ``print(msg, msg_level)`` shows the message only when debug is enabled and
    ``msg_level >= level`` (i.e. ``level`` is the *minimum* level shown).  The
    configured ``level`` comes from ``global|log_level`` (see
    :meth:`set_from_config`).

    Level convention used across the codebase:
      * ``debug``   — verbose per-item / per-command tracing (values, commands).
      * ``info``    — normal operational milestones (cycle start/end, module run).
      * ``warning`` — recoverable issues (item skipped, host unreachable, timeout).
      * ``error``   — failures (check raised, command failed).
      * ``emergency`` — critical, must always surface.
    """

    # Global colour switch.  Colours are emitted only when this is True AND the
    # output is a TTY.  Disabled via the ``--nocolor`` CLI flag.
    _color = True

    @classmethod
    def set_color(cls, enabled: bool) -> None:
        """Enable/disable ANSI colour output globally (e.g. ``--nocolor``)."""
        cls._color = bool(enabled)

    def __init__(self, enable: bool = True, level: DebugLevel = DebugLevel.info):
        self.enabled = enable
        self.level = level

    @property
    def enabled(self) -> bool:
        """ Return if the debug is enabled. """
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """ Set the debug enabled or disabled. """
        self._enabled = value

    @property
    def level(self) -> DebugLevel:
        """ Return the debug level. """
        return self._level

    @level.setter
    def level(self, value: DebugLevel = DebugLevel.null):
        """ Set the debug level. """
        self._level = value

    # Names offered as the configurable log level ('off' disables output).
    CONFIG_LEVELS = ('off', 'debug', 'info', 'warning', 'error')

    def set_from_config(self, level_name) -> None:
        """Configure ``enabled`` + ``level`` from a config string.

        ``'off'`` (or empty/unknown-as-off) disables debug output; any other
        :class:`DebugLevel` name (``'debug'``, ``'info'``, ``'warning'``,
        ``'error'``) enables it and sets that as the minimum level shown.
        """
        name = str(level_name or 'off').strip().lower()
        if name in ('off', 'null', '', 'false', 'none'):
            self.enabled = False
            return
        self.enabled = True
        self.level = DebugLevel[name] if name in DebugLevel.__members__ else DebugLevel.info

    def print(
            self,
            message,
            msg_level: DebugLevel = DebugLevel.debug,
            force: bool = False
        ):
        """
        Print the message if debug is enabled and the message level is
        greater than or equal to the configured debug level, or if force is True.
        """
        if not force and (not self.enabled or self.level > msg_level):
            return

        prefix = f"[{msg_level.name.upper():<7}]"
        color = _ANSI.get(msg_level, '') if (Debug._color and sys.stdout.isatty()) else ''
        if isinstance(message, str):
            line = f"{prefix} {message}"
            print(f"{color}{line}{_ANSI_RESET}" if color else line)
        else:
            print(f"{color}{prefix}{_ANSI_RESET}" if color else prefix)
            pprint.pprint(message)

    @staticmethod
    def exception(ex=None):
        """ Print the exception with traceback. """
        msg_print = f"[{DebugLevel.error.name.upper():<7}] Exception in user code:\n"
        msg_print += f"{'-'*60}\n"
        if ex:
            msg_print += f'Exception: {ex}\n'
            msg_print += f"{'-'*60}\n"
        msg_print += f'{traceback.format_exc()}\n'
        msg_print += f"{'-'*60}\n"
        if Debug._color and sys.stdout.isatty():
            print(f"{_ANSI[DebugLevel.error]}{msg_print}{_ANSI_RESET}")
        else:
            print(msg_print)

    def debug_obj(self, name_module, obj_debug, obj_info="Data Object"):
        """ Print the debug information of an object. """
        str_obj = pprint.pformat(obj_debug)
        msg_debug = f"{'*' * 60}\n"
        msg_debug += f"Debug [{name_module}] - {obj_info}:\n"
        msg_debug += f"Type: {type(obj_debug)}\n"
        msg_debug += f"{str_obj}\n"
        msg_debug += f"{'*' * 60}\n"
        self.print(msg_debug, DebugLevel.debug)


if __name__ == '__main__':

    x = Debug()
    try:
        x.print("Msg Test 1 - Enabled = False and Level Debug - No Show")
        x.print("Msg Test 2 - Level Error - Yes Show", DebugLevel.error)
        x.print("Msg Test 3 - Force = True and Level Debug - Yes Show", DebugLevel.debug, True)
        x.level = DebugLevel.debug
        x.print("Msg Test 4 - Level = debug - Yes Show")
        val = 10 * (1/0)

    except Exception as e:
        x.exception(e)
