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

""" Class to execute commands locally or remotely via SSH. """

import shlex
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum

import paramiko

__author__ = "Javier Pastor"
__copyright__ = "Copyright © 2019, Javier Pastor"
__credits__ = "Javier Pastor"
__license__ = "GPL"
__version__ = "0.1.0"
__maintainer__ = 'Javier Pastor'
__email__ = "python[at]cerebelum[dot]net"
__status__ = "Development"

__all__ = ['EnumLocationExec', 'Exec', 'ExecConfig', 'ExecResult']


class EnumLocationExec(StrEnum):
    """ Enum to specify the location where the command will be executed. """
    local = "local"
    remote = "remote"


@dataclass
class ExecConfig:
    """ Class to hold the configuration for executing a command. """
    command: str = ""
    location: EnumLocationExec = EnumLocationExec.local
    host: str = ""
    port: int = 22
    user: str = "root"
    password: str | None = None
    key_file: str | None = None
    timeout: float = 30
    host_key_policy: paramiko.MissingHostKeyPolicy | None = field(
        default_factory=paramiko.AutoAddPolicy
    )


@dataclass
class ExecResult:
    """ Class to hold the result of an executed command. """
    out: str | None = None
    err: str | None = None
    code: int | None = None
    exception: Exception | None = None


class Exec:
    """ Class to execute commands locally or remotely via SSH. """

    def __init__(self, command: str = ""):
        self.config = ExecConfig(command=command)

    @property
    def location(self) -> EnumLocationExec:
        """ Return the location where the command will be executed. """
        return self.config.location

    @location.setter
    def location(self, val: EnumLocationExec):
        """ Set the location where the command will be executed. """
        self.config.location = val

    @property
    def command(self) -> str:
        """ Return the command to execute. """
        return self.config.command

    @command.setter
    def command(self, val: str):
        """ Set the command to execute. """
        self.config.command = val

    def _has_command(self) -> bool:
        """ Check if the command is not empty. """
        return bool(self.config.command and self.config.command.strip())

    @staticmethod
    def _empty_result(exception: Exception | None = None) -> ExecResult:
        """ Return an empty result. """
        return ExecResult(exception=exception)

    def _execute_local(self) -> ExecResult:
        """ Execute the command on the local machine. """
        if not self._has_command():
            return self._empty_result()

        try:
            result = subprocess.run(
                shlex.split(self.config.command),
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                check=False
            )
            return ExecResult(
                out=result.stdout,
                err=result.stderr,
                code=result.returncode,
            )
        except subprocess.TimeoutExpired as ex:
            return self._empty_result(ex)
        except OSError as ex:
            return self._empty_result(ex)

        except Exception as ex: # pylint: disable=broad-except
            return self._empty_result(ex)

    def _execute_remote(self) -> ExecResult:
        """ Execute the command on the remote host that has been configured. """
        if not self._has_command():
            return self._empty_result()

        client = None
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if self.config.host_key_policy:
                client.set_missing_host_key_policy(self.config.host_key_policy)

            connect_kwargs = {
                'hostname': self.config.host,
                'port': self.config.port,
                'username': self.config.user,
                'timeout': self.config.timeout,
            }

            if self.config.key_file:
                connect_kwargs['key_filename'] = self.config.key_file
            else:
                connect_kwargs['password'] = self.config.password

            client.connect(**connect_kwargs)

            _, stdout, stderr = client.exec_command(
                self.config.command,
                timeout=self.config.timeout
            )
            exit_code = stdout.channel.recv_exit_status()

            read_out = stdout.read().decode() if stdout else ""
            read_err = stderr.read().decode() if stderr else ""

            return ExecResult(
                out=read_out,
                err=read_err,
                code=exit_code,
            )

        except paramiko.AuthenticationException as ex:
            return self._empty_result(ex)
        except paramiko.SSHException as ex:
            return self._empty_result(ex)
        except OSError as ex:
            return self._empty_result(ex)

        except Exception as ex: # pylint: disable=broad-except
            return self._empty_result(ex)

        finally:
            if client:
                client.close()

    def start(self) -> ExecResult:
        """ Execute the command and determine if it should be run locally or on a remote host. """
        if self.config.location == EnumLocationExec.remote:
            return self._execute_remote()
        return self._execute_local()

    def set_remote(
        self,
        host: str = "",
        port: int = 22,
        user: str = "root",
        password: str | None = None,
        key_file: str | None = None,
        timeout: float | None = None
    ) -> None:
        """ Set the configuration for remote execution. """
        self.config.location = EnumLocationExec.remote
        self.config.host = host
        self.config.port = port
        self.config.user = user
        self.config.password = password
        self.config.key_file = key_file
        if timeout is not None:
            self.config.timeout = timeout

    @staticmethod
    def execute(
        command: str = "",
        host: str = "",
        port: int = 22,
        user: str = "root",
        password: str | None = None,
        key_file: str | None = None,
        timeout: float | None = None
    ) -> ExecResult:
        """ Static method to execute a command with the specified configuration. """
        runner = Exec(command=command)
        if host and host.strip():
            runner.set_remote(
                host=host,
                port=port,
                user=user,
                password=password,
                key_file=key_file,
                timeout=timeout
            )
        elif timeout is not None:
            runner.config.timeout = timeout

        return runner.start()
