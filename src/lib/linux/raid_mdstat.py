#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiSesentry
#
# Copyright © 2019  Javier Pastor (aka vsc55)
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
""" RAID mdstat information collection for Linux. """

import os.path
import shlex
from enum import IntEnum

from lib.dict_files_path import DictFilesPath
from lib.exe import Exec, ExecResult

__all__ = ['RaidMdstat']


class RaidMdstat:
    """ RAID mdstat information collection for Linux. """

    class UpdateStatus(IntEnum):
        """ Status of the RAID update. """
        unknown = 0
        ok = 1
        error = 2
        recovery = 3

    def __init__(
            self,
            mdstat=None,
            host=None,
            port=22,
            user=None,
            password=None,
            key_file=None,
            timeout=None
        ):
        """ Initialize the RaidMdstat object. """
        self.paths = DictFilesPath()
        self.paths.set('mdstat', '/proc/mdstat')
        if mdstat is not None:
            self.paths.set('mdstat', mdstat)
        self._host = host
        self._port = port
        self._user = user
        self._pass = password
        self._key_file = key_file
        self._timeout = timeout

    @property
    def is_remote(self) -> bool:
        """ Return if the mdstat information is collected from a remote host. """
        return bool(self._host)

    @property
    def validate_remote(self) -> bool:
        """ Validate if the remote configuration is valid. """
        return (self.is_remote
                and bool(str(self._host).strip())
                and int(self._port) > 0
                and bool(str(self._user).strip()))

    def _exec_remote(self, cmd) -> ExecResult:
        """ Execute a command on the remote host. Returns (stdout, stderr, stdexcept). """
        result = Exec.execute(
            cmd,
            self._host,
            self._port,
            self._user,
            self._pass,
            self._key_file,
            self._timeout
        )
        return result

    def _read_lines(self):
        """ Read the mdstat information and return a list of lines. """
        path_mdstat = self.paths.find('mdstat')

        if self.is_remote:
            if not self.validate_remote:
                raise ValueError(
                    f"Remote config not valid ({self._user}:***@{self._host})"
                )

            remote_cmd = f"cat {shlex.quote(path_mdstat)}"
            result = self._exec_remote(remote_cmd)
            stdout = result.out
            stderr = result.err
            stdexcept = result.exception

            if stderr:
                raise OSError(f"REMOTE ERROR ({remote_cmd}): {stderr}")
            if stdexcept:
                raise RuntimeError(f"REMOTE EXCEPTION ({remote_cmd}): {stdexcept}")

            return stdout.splitlines()

        with open(path_mdstat, 'r', encoding='utf-8') as f:
            return f.read().splitlines()

    @property
    def is_exist(self) -> bool:
        """ Check if the mdstat file exist. """
        path_mdstat  = self.paths.find('mdstat')

        if self.is_remote:
            if not self.validate_remote:
                return False

            str_check = "exists"
            cmd = f"test -e {shlex.quote(path_mdstat)} && echo {str_check}"
            result = self._exec_remote(cmd)
            stdout = result.out
            stderr = result.err
            stdexcept = result.exception

            if stderr or stdexcept:
                return False

            return stdout.strip() == str_check

        return os.path.isfile(path_mdstat)

    def read_status(self):
        """ Read the mdstat information and return a dictionary with the status of each RAID. """
        md_list = {}
        md_actual = None

        if not self.is_exist:
            return md_list

        f_buffer = self._read_lines()

        for line in f_buffer:
            line = line.strip()

            if not line:
                md_actual = None
                continue

            if line.startswith("Personalities :") or line.startswith("unused devices:"):
                md_actual = None
                continue

            if md_actual is None and line.startswith("md") and ":" in line:
                name, info = line.split(":", 1)
                parts = info.strip().split()

                if len(parts) >= 2:
                    md_actual = name.strip()
                    md_list[md_actual] = {
                        'status': parts[0],
                        'type': parts[1],
                        'disk': parts[2:]
                    }
                continue

            if md_actual is None:
                continue

            if "recovery" in line:
                md_list[md_actual]['update'] = self.UpdateStatus.recovery
                try:
                    parts = line.split("]")[-1].strip().split()
                    md_list[md_actual]['recovery'] = {
                        'percent': float(parts[2].rstrip('%')),
                        'blocks': parts[3][1:-1].split("/"),
                        'finish': parts[4].split("=", 1)[1].strip(),
                        'speed': parts[5].split("=", 1)[1].strip()
                    }
                except (IndexError, ValueError):
                    md_list[md_actual]['recovery'] = {}
                continue

            if "blocks" in line:
                parts = line.split()
                if len(parts) >= 3:
                    md_list[md_actual]['blocks'] = parts[0]
                    disks = parts[2][1:-1].split("/")
                    if len(disks) == 2:
                        md_list[md_actual]['update'] = (
                            self.UpdateStatus.ok if disks[0] == disks[1]
                            else self.UpdateStatus.error
                        )
                continue

        return md_list
