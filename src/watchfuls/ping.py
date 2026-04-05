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
""" Watchful module to check if a host is reachable via ICMP ping. """

import concurrent.futures

from pythonping import ping

from lib.debug import DebugLevel
from lib.modules import ModuleBase

# import os
# import socket
# import struct
# import time

# from enum import IntEnum

# class ConfigOptions(IntEnum):
#     enabled = 1
#     alert = 2
#     host = 3
#     timeout = 100
#     attempt = 101


class Watchful(ModuleBase):
    """Watchful module to check if a host is reachable via ICMP ping."""

    ITEM_SCHEMA = {
        'list': {
            'enabled': {
                'default': True,
                'type': 'bool'
            },
            'host': {
                'default': '',
                'type': 'str'
            },
            'timeout': {
                'default': 5,
                'type': 'int',
                'min': 1,
                'max': 300
            },
            'attempt': {
                'default': 3,
                'type': 'int',
                'min': 1,
                'max': 50
            },
            'alert': {
                'default': 1,
                'type': 'int',
                'min': 1,
                'max': 100
            },
        },
    }

    # Default values are derived from ITEM_SCHEMA so there is a single
    # source of truth that the web UI can also consume.
    _DEFAULTS = {k: v['default'] for k, v in ITEM_SCHEMA['list'].items()}

    def __init__(self, monitor):
        super().__init__(monitor, __name__)
        # Consecutive failure counter per host (not persisted).
        self._fail_count: dict[str, int] = {}

    def check(self):
        if not self.is_enabled:
            self._debug("Ping: Module disabled, skipping check.", DebugLevel.info)
            return self.dict_return

        list_host = []
        for (key, value) in self.get_conf('list', {}).items():
            is_enabled = self._DEFAULTS['enabled']
            match value:
                case bool():
                    # Legacy support: if the value is a boolean, use it directly as enabled/disabled
                    # and treat the key as the host.
                    is_enabled = value
                    host = key
                    self._debug(
                        f"[Deprecate] Check: {host} - Enabled: {is_enabled}. Please update format.",
                        DebugLevel.warning
                    )

                case dict():
                    # New format: value is a dict with possible 'enabled' and 'host' keys.
                    # If 'enabled' is not specified, default to the module's default enabled state.
                    # If 'host' is not specified, default to the key.
                    is_enabled = value.get("enabled", is_enabled)
                    host = (value.get('host', '') or '').strip() or key
                    self._debug(f"Check: {host} - Enabled: {is_enabled}", DebugLevel.info)

                case _:
                    # If the value is neither a bool nor a dict, treat it as disabled and use
                    # the key as the host for logging purposes.
                    is_enabled = False
                    host = key
                    self._debug(
                        f"Check: {host} - Invalid configuration format. Treating as disabled.",
                        DebugLevel.warning
                    )

            if is_enabled:
                list_host.append((key, host))

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.get_conf('threads', self._default_threads)) as executor:
            future_to_ping = {
                executor.submit(self._ping_check, name, host): (name, host)
                for name, host in list_host
            }
            for future in concurrent.futures.as_completed(future_to_ping):
                name, host = future_to_ping[future]
                try:
                    future.result()

                except Exception as exc: # pylint: disable=broad-except
                    self._debug(f"Check: {name} - Exception: {exc}", DebugLevel.error)
                    message = f'Check: {name} - *Error: {exc}* 💥'
                    self.dict_return.set(name, False, message)

        super().check()
        return self.dict_return

    def _ping_check(self, name, host):
        t_alert = self.get_conf_in_list("alert", name, self._DEFAULTS['alert'])
        t_timeout = self.get_conf_in_list("timeout", name, self._DEFAULTS['timeout'])
        t_attempt = self.get_conf_in_list("attempt", name, self._DEFAULTS['attempt'])

        # TODO: Pending implemantation latency measurement and reporting in other_data. pylint: disable=fixme
        ping_ok = self._ping_return(host, t_timeout, t_attempt)

        # ── Alert threshold: only declare KO after *alert* consecutive
        #    full-check failures. ──
        if ping_ok:
            self._fail_count[name] = 0
            status = True
        else:
            self._fail_count[name] = self._fail_count.get(name, 0) + 1
            status = self._fail_count[name] < t_alert

        icon = '🔼' if status else '🔽'
        s_message = f'Ping: *{name}* {icon}'

        self.dict_return.set(name, status, s_message, False)

        if self.check_status(status, self.name_module, name):
            self.send_message(s_message, status)

    def _ping_return(self, host, timeout, attempt):
        try:
            resp = ping(host, count=int(attempt), timeout=float(timeout))
            return resp.success()

        except Exception as exc: # pylint: disable=broad-except
            self._debug(f"Ping check failed for {host}: {exc}", DebugLevel.error)
            return False

    #     """Try to ping *host* up to *attempt* times using native ICMP."""
    #     for _ in range(attempt):
    #         if self._icmp_ping(host, timeout):
    #             return True
    #         time.sleep(1)
    #     return False

    # ── Native ICMP implementation ────────────────────────────────

    # @staticmethod
    # def _icmp_checksum(data: bytes) -> int:
    #     """Calculate the Internet checksum (RFC 1071)."""
    #     if len(data) % 2:
    #         data += b'\x00'
    #     s = 0
    #     for i in range(0, len(data), 2):
    #         w = (data[i] << 8) + data[i + 1]
    #         s += w
    #     s = (s >> 16) + (s & 0xFFFF)
    #     s += s >> 16
    #     return ~s & 0xFFFF

    # def _icmp_ping(self, host: str, timeout: int) -> bool:
    #     """Send a single ICMP Echo Request and wait for a reply.

    #     Uses a raw ICMP socket (``SOCK_RAW``) when the process has
    #     sufficient privileges, otherwise falls back to a datagram ICMP
    #     socket (``SOCK_DGRAM``) which is allowed by the kernel on many
    #     Linux distributions for unprivileged users.

    #     Returns ``True`` if a valid Echo Reply is received within
    #     *timeout* seconds, ``False`` otherwise.
    #     """
    #     try:
    #         dest = socket.gethostbyname(host)
    #     except socket.gaierror:
    #         return False

    #     icmp_proto = socket.getprotobyname('icmp')
    #     sock = self._create_icmp_socket(icmp_proto)
    #     if sock is None:
    #         return False

    #     try:
    #         sock.settimeout(timeout)
    #         packet_id = os.getpid() & 0xFFFF
    #         seq = 1
    #         packet = self._build_icmp_packet(packet_id, seq)
    #         sock.sendto(packet, (dest, 0))
    #         return self._receive_icmp_reply(sock, packet_id, seq, timeout)
    #     except (OSError, socket.error):
    #         return False
    #     finally:
    #         sock.close()

    # @staticmethod
    # def _create_icmp_socket(icmp_proto: int):
    #     """Create an ICMP socket, trying RAW first, then DGRAM."""
    #     for sock_type in (socket.SOCK_RAW, socket.SOCK_DGRAM):
    #         try:
    #             return socket.socket(
    #                 socket.AF_INET, sock_type, icmp_proto,
    #             )
    #         except PermissionError:
    #             continue
    #         except OSError:
    #             continue
    #     return None

    # @staticmethod
    # def _build_icmp_packet(packet_id: int, seq: int) -> bytes:
    #     """Build an ICMP Echo Request packet."""
    #     # Type 8, Code 0 = Echo Request
    #     icmp_type = 8
    #     icmp_code = 0
    #     checksum = 0
    #     payload = b'ServiceSentry'  # arbitrary payload

    #     # Header with dummy checksum
    #     header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, packet_id, seq)
    #     # Calculate real checksum
    #     checksum = Watchful._icmp_checksum(header + payload)
    #     header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, packet_id, seq)
    #     return header + payload

    # @staticmethod
    # def _receive_icmp_reply(sock, packet_id: int, seq: int, timeout: int) -> bool:
    #     """Wait for the matching ICMP Echo Reply."""
    #     deadline = time.monotonic() + timeout
    #     while True:
    #         remaining = deadline - time.monotonic()
    #         if remaining <= 0:
    #             return False
    #         sock.settimeout(remaining)
    #         try:
    #             data, _ = sock.recvfrom(1024)
    #         except (socket.timeout, OSError):
    #             return False

    #         # Determine where the ICMP header starts.
    #         # RAW sockets include the IP header (usually 20 bytes),
    #         # DGRAM sockets strip it.
    #         if len(data) >= 28 and (data[0] >> 4) == 4:
    #             # IPv4 header present — extract IHL
    #             ip_hdr_len = (data[0] & 0x0F) * 4
    #             icmp_data = data[ip_hdr_len:]
    #         else:
    #             icmp_data = data

    #         if len(icmp_data) < 8:
    #             continue

    #         icmp_type, icmp_code, _, recv_id, recv_seq = struct.unpack(
    #             '!BBHHH', icmp_data[:8],
    #         )
    #         # Type 0 = Echo Reply
    #         if icmp_type == 0 and icmp_code == 0:
    #             if recv_id == packet_id and recv_seq == seq:
    #                 return True

    # def _get_conf(self, opt_find: IntEnum, dev_name: str, default_val=None):
    #     # Sec - Get Default Val
    #     if default_val is None:
    #         match opt_find:
    #             case ConfigOptions.attempt:
    #                 val_def = self.get_conf(opt_find.name, self._DEFAULTS['attempt'])

    #             case ConfigOptions.timeout:
    #                 val_def = self.get_conf(opt_find.name, self._DEFAULTS['timeout'])

    #             case ConfigOptions.enabled:
    #                 val_def = self.get_conf(opt_find.name, self._DEFAULTS['enabled'])

    #             case ConfigOptions.alert:
    #                 val_def = self.get_conf(opt_find.name, self._DEFAULTS['alert'])

    #             case ConfigOptions.host:
    #                 val_def = self._DEFAULTS['host']

    #             case None:
    #                 raise ValueError("opt_find it can not be None!")
    #             case _:
    #                 raise TypeError(f"{opt_find.name} is not valid option!")
    #     else:
    #         val_def = default_val

    #     # Sec - Get Data
    #     value = self.get_conf_in_list(opt_find, dev_name, val_def)

    #     # Sec - Format Return Data
    #     match opt_find:
    #         case ConfigOptions.attempt | ConfigOptions.timeout | ConfigOptions.alert:
    #             return self._parse_conf_int(value, val_def)
    #         case ConfigOptions.enabled:
    #             return bool(value)
    #         case ConfigOptions.host:
    #             return self._parse_conf_str(value, val_def)
    #         case _:
    #             return value
