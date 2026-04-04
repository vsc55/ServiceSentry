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

import os.path
from enum import Enum
from lib.exe import Exec
from lib import DictFilesPath

__all__ = ['RaidMdstat']


class RaidMdstat:

    class UpdateStatus(Enum):
        unknown = 0
        ok = 1
        error = 2
        recovery = 3

    def __init__(self, mdstat=None, host=None, port=22, user=None, password=None, timeout=None):
        self.paths = DictFilesPath()
        self.paths.set('mdstat', '/proc/mdstat')
        if mdstat is not None:
            self.paths.set('mdstat', mdstat)
        self.__host = host
        self.__port = port
        self.__user = user
        self.__pass = password
        self.__timeout = timeout

    @property
    def is_remote(self) -> bool:
        return bool(self.__host)

    @property
    def validate_remote(self) -> bool:
        return (self.is_remote
                and bool(str(self.__host).strip())
                and int(self.__port) > 0
                and bool(str(self.__user).strip()))

    def _exec_remote(self, cmd):
        """ Ejecuta un comando en el host remoto. Retorna (stdout, stderr, stdexcept). """
        stdout, stderr, _, stdexcept = Exec.execute(
            cmd, self.__host, self.__port, self.__user, self.__pass, self.__timeout)
        return stdout, stderr, stdexcept

    @property
    def is_exist(self) -> bool:
        path_md_stat = self.paths.find('mdstat')
        if self.is_remote:
            if not self.validate_remote:
                print(f"** RAID_Mdstat ** >> WARNING!! >> REMOTE >> CONFIG NOT VALID ({self.__user}:{self.__pass}@{self.__host}) NOT VALID!")
                return False

            str_check = "exists"
            stdout, stderr, stdexcept = self._exec_remote(f"test -e {path_md_stat} && echo {str_check}")

            if stderr:
                print(f"** RAID_Mdstat ** >> ERROR!! >> REMOTE >> Failed to check existence of {path_md_stat}: {stderr}!")
                return False
            if stdexcept:
                print(f"** RAID_Mdstat ** >> EXCEPTION!! >> REMOTE >> Failed to check existence of {path_md_stat}: {stdexcept}!")
                raise Exception(stdexcept)

            return stdout.strip() == str_check
        else:
            return os.path.isfile(path_md_stat)

    def read_status(self):
        md_list = {}
        md_actual = None

        if not self.is_exist:
            return md_list

        f_buffer = None
        if self.is_remote:
            remote_cmd = f"cat {self.paths.find('mdstat')}"
            stdout, stderr, stdexcept = self._exec_remote(remote_cmd)

            if stderr:
                raise Exception(f"** RAID_Mdstat ** >> ERROR!! >> REMOTE >> ({remote_cmd}): {stderr}!")
            if stdexcept:
                raise Exception(f"** RAID_Mdstat ** >> EXCEPTION!! >> REMOTE >> ({remote_cmd}): {stdexcept}!")

            f_buffer = stdout.splitlines()
        else:
            with open(self.paths.find('mdstat'), 'r') as f:
                f_buffer = f.read().splitlines()

        if f_buffer:
            for l_buffer in f_buffer:
                l_buffer = str(l_buffer).strip()

                if "Personalities :" in l_buffer:
                    md_actual = None
                elif "unused devices:" in l_buffer:
                    md_actual = None
                elif l_buffer:
                    if md_actual is None and len(l_buffer) > 2 and l_buffer[:2] == "md":
                        md_actual = l_buffer.split(":")[0].strip()
                        tmp_split = l_buffer.split(":")[1].strip().split(" ")
                        md_list[md_actual] = {
                            'status': tmp_split.pop(0),
                            'type': tmp_split.pop(0),
                            'disk': tmp_split
                        }
                    elif "recovery" in l_buffer:
                        md_list[md_actual]['update'] = self.UpdateStatus.recovery
                        tmp_split = l_buffer.split("]")[1].strip().split(" ")
                        md_list[md_actual]['recovery'] = {
                            'percent': float(tmp_split[2][:-1]),
                            'blocks': tmp_split[3][1:-1].split("/"),
                            'finish': tmp_split[4].split("=")[1].strip(),
                            'speed': tmp_split[5].split("=")[1].strip()
                        }
                    elif "blocks" in l_buffer:
                        tmp_split = l_buffer.split(" ")
                        md_list[md_actual]['blocks'] = tmp_split[0]
                        tmp_disks = tmp_split[2][1:-1].split("/")
                        md_list[md_actual]['update'] = (
                            self.UpdateStatus.ok if tmp_disks[0] == tmp_disks[1] else self.UpdateStatus.error
                        )
                    else:
                        print(f"** RAID_Mdstat ** >> WARNING!! >> {md_actual} >> NOT CONTROL TEXT: {l_buffer}")
                else:
                    md_actual = None

        return md_list
