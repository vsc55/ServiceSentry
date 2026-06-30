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
""" Store configuration in a file. """

import json
import os
import tempfile
import threading
import time

from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase

# Module-level lock serialises concurrent writes from multiple threads in the
# same process (e.g. parallel watchful checks each calling status.save()).
_write_lock = threading.Lock()

# Optional error callback — set by the web admin so file-write errors are
# forwarded to the audit log in addition to the debug terminal.
# Signature: callback(event: str, detail: str) -> None
_error_callback = None


def set_error_callback(callback) -> None:
    """Register a function to be called when a file write fails."""
    global _error_callback
    _error_callback = callback


def _atomic_replace(src: str, dst: str, retries: int = 8, base_delay: float = 0.05) -> None:
    """Rename *src* to *dst* atomically, retrying on Windows [WinError 5].

    On Windows, ``os.replace()`` raises ``PermissionError`` (WinError 5) when
    the destination file is briefly locked by another thread or process doing
    its own rename.  Retrying with exponential back-off resolves the transient
    conflict in practice without requiring cross-process file locking.
    """
    with _write_lock:
        for attempt in range(retries):
            try:
                os.replace(src, dst)
                return
            except OSError as exc:
                # WinError 5 = Access Denied — target briefly locked by a
                # concurrent rename.  Any other OSError is re-raised immediately.
                if getattr(exc, 'winerror', None) != 5 or attempt == retries - 1:
                    raise
                time.sleep(base_delay * (2 ** attempt))  # 50 ms, 100 ms, 200 ms …


__all__ = ['ConfigStore']

class ConfigStore(ObjectBase):
    """ Object to store configuration in a file. """

    def __init__(self, file):
        self.file = file

    @property
    def is_exist_file(self) -> bool:
        """ Check if the file exist. """
        return bool(self.file and os.path.isfile(self.file))

    @property
    def is_writable_file(self) -> bool:
        """ Check if the file is writable. """
        if not self.file:
            return False

        if self.is_exist_file:
            return os.access(self.file, os.W_OK)

        parent = os.path.dirname(self.file) or '.'
        return os.access(parent, os.W_OK)

    @property
    def file(self) -> str:
        """ Get the file path. """
        return self._file

    @file.setter
    def file(self, val: str):
        """ Set the file path. """
        self._file: str = val

    def read(self, def_return = None):
        """ Read the configuration from the file. """
        return_date = def_return

        if self.is_exist_file:
            try:
                with open(self.file, 'r', encoding='utf-8') as f:
                    return_date = json.load(f)

            except json.JSONDecodeError:
                self.debug.print(
                    f"Config >> Warning: File ({self.file}) is not a valid JSON file!!!",
                    DebugLevel.warning
                )

            except OSError as e:
                self.debug.exception(e)

            except Exception as e:
                self.debug.exception(e)

        else:
            self.debug.print(
                f"Config >> Warning: File ({self.file}) not exist!!!",
                DebugLevel.warning
            )

        return return_date

    def save(self, data) -> bool:
        """ Save the configuration to the file. """
        if not self.file:
            self.debug.print(
                "Config >> Warning: File path is empty",
                DebugLevel.error
            )
            return False

        if not self.is_writable_file:
            self.debug.print(
                f"Config >> Warning: File ({self.file}) is not writable!!!",
                DebugLevel.error
            )
            return False

        dir_path = os.path.dirname(self.file) or '.'
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                'w', dir=dir_path, suffix='.tmp', delete=False, encoding='utf-8'
            ) as tmp:
                json.dump(data, tmp, ensure_ascii=False, indent=4)
                tmp_path = tmp.name
            _atomic_replace(tmp_path, self.file)
            tmp_path = None

        except TypeError as e:
            self.debug.print(
                f"Config >> Warning: Data is not JSON serializable ({e})",
                DebugLevel.warning
            )
            return False

        except OSError as e:
            msg = f"Config >> Warning: Cannot write file ({self.file}) ({e})"
            self.debug.print(msg, DebugLevel.error)
            if _error_callback:
                try:
                    _error_callback('file_write_error', {'file': self.file, 'error': str(e)})
                except Exception:  # pylint: disable=broad-except
                    pass
            return False

        except Exception as e:
            self.debug.exception(e)
            if _error_callback:
                try:
                    _error_callback('file_write_error', {'file': self.file, 'error': str(e)})
                except Exception:  # pylint: disable=broad-except
                    pass
            return False

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return True
