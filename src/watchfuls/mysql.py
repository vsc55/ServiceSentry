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

import concurrent.futures
import os.path
from enum import IntEnum

import pymysql
import pymysql.cursors

from lib.debug import DebugLevel
from lib.modules import ModuleBase


class ConfigOptions(IntEnum):
    enabled = 1
    # alert = 2
    # label = 3
    host = 100
    port = 101
    user = 102
    password = 103
    db = 104
    socket = 105


class Watchful(ModuleBase):

    _default_enabled = True
    _default_port = 3306

    def __init__(self, monitor):
        super().__init__(monitor, __name__)

    def check(self):
        list_db = self._check_get_list_db()
        self._check_run(list_db)
        super().check()
        return self.dict_return

    def _check_get_list_db(self):
        return_list = []
        for (key, value) in self.get_conf('list', {}).items():
            if isinstance(value, bool):
                is_enabled = value
            elif isinstance(value, dict):
                is_enabled = self._get_conf(ConfigOptions.enabled, key)
            else:
                is_enabled = self._default_enabled

            self._debug(f"{key} - Enabled: {is_enabled}", DebugLevel.info)

            if is_enabled:
                return_list.append(key)

        return return_list

    def _check_run(self, list_db):
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_db = {executor.submit(self._db_check, db): db for db in list_db}
            for future in concurrent.futures.as_completed(future_to_db):
                db = future_to_db[future]
                try:
                    future.result()
                except Exception as exc:
                    message = f'MySQL: {db} - *Error: {exc}* {u"\U0001F4A5"}'
                    self.dict_return.set(db, False, message)

    def _db_check(self, db):
        tmp_socket = self._get_conf(ConfigOptions.socket, db)
        tmp_host = self._get_conf(ConfigOptions.host, db)
        tmp_port = self._get_conf(ConfigOptions.port, db)
        tmp_user = self._get_conf(ConfigOptions.user, db)
        tmp_pass = self._get_conf(ConfigOptions.password, db)
        tmp_db = self._get_conf(ConfigOptions.db, db)

        status, message = self._db_return(db, tmp_socket, tmp_host, tmp_port, tmp_user, tmp_pass, tmp_db)

        s_message = 'MySQL: '
        if status == "OK":
            s_message += f'*{db}* {u"\U00002705"}'
            status = True
        else:
            s_message += f'{db} - *Error:* '
            match status:
                case "1045":
                    # OperationalError(1045, "Access denied for user 'user'@'server' (using password: NO)")
                    # OperationalError(1045, "Access denied for user 'user'@'server' (using password: YES)")
                    s_message += f"*Access denied* {'\U0001F510'}"
                case "2003":
                    # OperationalError(2003, "Can't connect to MySQL server on 'host1' (timed out)")
                    # OperationalError(2003, "Can't connect to MySQL server on 'host1' ([Errno 113] No route to host)")
                    # OperationalError(2003, "Can't connect to MySQL server on 'host1' ([Errno 111] Connection refused)"
                    s_message += "*Can't connect to MySQL server*"
                    if '(timed out)' in message:
                        s_message += ' *(timed out)*'
                    elif '[Errno 111]' in message:
                        s_message += ' *(connection refused)*'
                    elif '[Errno 113]' in message:
                        s_message += ' *(no route to host)*'
                    else:
                        s_message += ' *(?????)*'
                    s_message += '\U000026A0'
                case _:
                    s_message += f'*{message}* {"\U000026A0"}'
            status = False

        other_data = {'message': message}
        self.dict_return.set(db, status, s_message, False, other_data)

        if self.check_status_custom(status, db, message):
            self.send_message(s_message, status)

    def _db_return(self, db_name, socket, host, port, user, password, db):
        return_status = 0
        return_msg = ""
        connect_socket = bool(str(socket).strip())
        try:
            if connect_socket:
                if not os.path.exists(socket):
                    return "SOCKET_NOT_EXIST", "Socket file is not exist!"

                connection = pymysql.connect(unix_socket=socket,
                                             db=db,
                                             charset='utf8mb4',
                                             cursorclass=pymysql.cursors.DictCursor)
            else:
                connection = pymysql.connect(host=host,
                                             port=port,
                                             user=user,
                                             password=password,
                                             db=db,
                                             charset='utf8mb4',
                                             connect_timeout=10,
                                             cursorclass=pymysql.cursors.DictCursor)

        except Exception as e:
            connection = None
            self._debug(f"{db_name} >> Exception: {repr(e)}", DebugLevel.error)
            return_msg = repr(e)

            err_array = str(e).split(",")
            err_code = err_array[0][1:]
            match err_code:
                case "2003" if connect_socket:
                    return "SOCKET_ERROR", "Socket file is not work!"
                case "1045" | "2003":
                    return_status = err_code
                case _:
                    return_status = "-9999"

        if connection is not None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW GLOBAL STATUS")
                    # for row in cursor:
                    #     print("ROW:", row)

                    # result = cursor.fetchone()
                    # print("RESULT SQL:", result)
                    return_status = "OK"

            except Exception as e:
                self._debug(f"{db_name} >> Exception: {repr(e)}", DebugLevel.error)
                return_msg = repr(e)
                return_status = "-9999"

            finally:
                connection.close()

        return return_status, return_msg

    def _get_conf(self, opt_find: IntEnum, dev_name: str, default_val=None):
        # Sec - Get Default Val
        if default_val is None:
            match opt_find:
                case ConfigOptions.port:
                    val_def = self.get_conf(opt_find.name, self._default_port)

                case (ConfigOptions.socket | ConfigOptions.host
                      | ConfigOptions.user | ConfigOptions.password
                      | ConfigOptions.db):
                    val_def = self.get_conf(opt_find.name, "")

                case ConfigOptions.enabled:
                    val_def = self.get_conf(opt_find.name, self._default_enabled)

                case None:
                    raise ValueError("opt_find it can not be None!")
                case _:
                    raise TypeError(f"{opt_find.name} is not valid option!")
        else:
            val_def = default_val

        # Sec - Get Data
        value = self.get_conf_in_list(opt_find, dev_name, val_def)

        # Sec - Format Return Data
        match opt_find:
            case ConfigOptions.port:
                return self._parse_conf_int(value, val_def)
            case ConfigOptions.enabled:
                return bool(value)
            case (ConfigOptions.socket | ConfigOptions.host
                  | ConfigOptions.user | ConfigOptions.password
                  | ConfigOptions.db):
                return self._parse_conf_str(value, val_def)
            case _:
                return value

