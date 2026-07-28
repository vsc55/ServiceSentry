#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Ping watchful: speaking ICMP.
#
"""Echo request, echo reply, and the socket that carries them.

Written by hand rather than shelling out to the system ``ping``: parsing another program's
localised, per-platform output to learn a round-trip time is a worse contract than building
the packet ourselves. The cost is that a raw socket needs privilege, which is what
MISSING_DEPS reports when it is absent.

A check decides what a lost packet MEANS - how many attempts, which threshold. This decides
how to send one and how to recognise the answer as ours: the reply carries the identifier and
sequence we put in, and a reply that matches neither belongs to somebody else's ping.
"""

import concurrent.futures
import secrets
import socket
import struct
import time

# A convenience library, not a requirement: the native implementation below is the one that
# always works, and MISSING_DEPS stays empty because its absence costs nothing.
try:
    from pythonping import ping as _pythonping
    _PYTHONPING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYTHONPING_AVAILABLE = False


class IcmpClient:
    """The native ICMP implementation, mixed into ``Watchful``."""

    # ── Native ICMP implementation ────────────────────────────────

    @staticmethod
    def _icmp_checksum(data: bytes) -> int:
        """Calculate the Internet checksum (RFC 1071)."""
        if len(data) % 2:
            data += b'\x00'
        s = 0
        for i in range(0, len(data), 2):
            w = (data[i] << 8) + data[i + 1]
            s += w
        s = (s >> 16) + (s & 0xFFFF)
        s += s >> 16
        return ~s & 0xFFFF

    def _icmp_ping(self, host: str, timeout: int) -> float | None:
        """Send a single ICMP Echo Request and wait for a reply.

        Uses ``pythonping`` when available (cross-platform, no root needed
        on Windows).  Falls back to a native ICMP socket implementation
        when ``pythonping`` is not installed: tries ``SOCK_RAW`` first
        (requires elevated privileges) and then ``SOCK_DGRAM`` (allowed
        on many Linux distributions for unprivileged users).

        Returns RTT in milliseconds on success, or ``None`` on failure.
        """
        if _PYTHONPING_AVAILABLE:
            try:
                result = _pythonping(host, timeout=timeout, count=1, verbose=False)
                if result.success():
                    return result.rtt_avg_ms
                return None
            except Exception:  # pylint: disable=broad-except
                return None
        else:
            # pythonping not available — native ICMP fallback
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                    _fut = _ex.submit(socket.gethostbyname, host)
                    dest = _fut.result(timeout=timeout)
            except (socket.gaierror, concurrent.futures.TimeoutError):
                return None

            icmp_proto = socket.getprotobyname('icmp')
            sock = self._create_icmp_socket(icmp_proto)
            if sock is None:
                return None

            try:
                sock.settimeout(timeout)
                packet_id = secrets.randbits(16)
                seq = 1
                packet = self._build_icmp_packet(packet_id, seq)
                t0 = time.monotonic()
                sock.sendto(packet, (dest, 0))
                if self._receive_icmp_reply(sock, packet_id, seq, timeout):
                    return (time.monotonic() - t0) * 1000
                return None
            except (OSError, socket.error):
                return None
            finally:
                sock.close()

    @staticmethod
    def _create_icmp_socket(icmp_proto: int):
        """Create an ICMP socket, trying RAW first, then DGRAM."""
        for sock_type in (socket.SOCK_RAW, socket.SOCK_DGRAM):
            try:
                return socket.socket(
                    socket.AF_INET, sock_type, icmp_proto,
                )
            except PermissionError:
                continue
            except OSError:
                continue
        return None

    @staticmethod
    def _build_icmp_packet(packet_id: int, seq: int) -> bytes:
        """Build an ICMP Echo Request packet."""
        # Type 8, Code 0 = Echo Request
        icmp_type = 8
        icmp_code = 0
        checksum = 0
        payload = b'ServiceSentry'  # arbitrary payload

        # Header with dummy checksum
        header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, packet_id, seq)
        # Calculate real checksum
        checksum = IcmpClient._icmp_checksum(header + payload)
        header = struct.pack('!BBHHH', icmp_type, icmp_code, checksum, packet_id, seq)
        return header + payload

    @staticmethod
    def _receive_icmp_reply(sock, packet_id: int, seq: int, timeout: int) -> bool:
        """Wait for the matching ICMP Echo Reply."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(1024)
            except (socket.timeout, OSError):
                return False

            # Determine where the ICMP header starts.
            # RAW sockets include the IP header (usually 20 bytes),
            # DGRAM sockets strip it.
            if len(data) >= 28 and (data[0] >> 4) == 4:
                # IPv4 header present — extract IHL
                ip_hdr_len = (data[0] & 0x0F) * 4
                icmp_data = data[ip_hdr_len:]
            else:
                icmp_data = data

            if len(icmp_data) < 8:
                continue

            icmp_type, icmp_code, _, recv_id, recv_seq = struct.unpack(
                '!BBHHH', icmp_data[:8],
            )
            # Type 0 = Echo Reply
            if icmp_type == 0 and icmp_code == 0:
                if recv_id == packet_id and recv_seq == seq:
                    return True