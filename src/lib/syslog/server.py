#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The syslog listener: UDP + TCP (+ optional TLS) receivers feeding a store.

Design
------
* One reader thread per transport (UDP, TCP, TLS); TCP/TLS spawn a short-lived
  thread per accepted connection.  Sockets use a short timeout so ``stop()`` is
  prompt.
* Parsed records go on a bounded queue; a single writer thread batches them to
  the store (``add_many``) every ~1 s, so receiving never blocks on the DB.
* An optional ``on_message`` callback runs per record (alert-rule evaluation).
* Senders can be restricted to an allowlist of IPs / CIDRs.

Everything is best-effort and defensive: a bad datagram or a dead connection
never takes the listener down.
"""

from __future__ import annotations

import ipaddress
import queue
import re
import socket
import ssl
import threading
import time

from lib.syslog.parser import parse_message

_MAX_DATAGRAM = 65535          # UDP theoretical max
_FLUSH_SECS = 1.0              # writer batch interval
_FLUSH_MAX = 500              # writer batch size cap
_SOCK_TIMEOUT = 0.5            # so stop() is responsive


def build_server(cfg: dict, *, sink, on_message=None, dbg=None) -> 'SyslogServer':
    """Construct a :class:`SyslogServer` from a ``syslog`` config dict.  Shared by
    the in-web-admin mixin and the standalone service so the wiring lives once."""
    sources = [s for s in re.split(r'[,\s]+', str(cfg.get('allowed_sources') or '')) if s]
    return SyslogServer(
        sink=sink, on_message=on_message,
        bind_host=str(cfg.get('bind_host') or '0.0.0.0'),
        udp_port=int(cfg.get('udp_port') or 0),
        tcp_port=int(cfg.get('tcp_port') or 0),
        tls_port=int(cfg.get('tls_port') or 0),
        tls_cert=str(cfg.get('tls_cert') or ''),
        tls_key=str(cfg.get('tls_key') or ''),
        allowed_sources=sources, dbg=dbg)


def should_alert(cfg: dict, rec: dict, alert_last: dict, *, cooldown: int = 60) -> bool:
    """Decide whether *rec* matches the alert rule (severity ≤ threshold and, if
    set, the regex) honouring a per-source cooldown.  Mutates *alert_last* on a
    positive so the caller just dispatches.  Shared by mixin + standalone service."""
    if not cfg.get('alert_enabled'):
        return False
    try:
        sev_max = int(cfg.get('alert_severity_max', 3))
    except (TypeError, ValueError):
        sev_max = 3
    if rec.get('severity', 5) > sev_max:            # lower number = more severe
        return False
    rx = str(cfg.get('alert_regex') or '').strip()
    if rx:
        try:
            if not re.search(rx, rec.get('message', '')):
                return False
        except re.error:
            return False
    src = rec.get('source') or rec.get('hostname') or '?'
    now = time.time()
    if now - alert_last.get(src, 0) < cooldown:
        return False
    alert_last[src] = now
    return True


def _parse_allowlist(sources) -> list:
    """Turn a list of IP / CIDR strings into ip_network objects (ignoring junk)."""
    nets = []
    for s in (sources or []):
        s = str(s).strip()
        if not s:
            continue
        try:
            nets.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            continue
    return nets


class SyslogServer:
    """Receive syslog over UDP/TCP/TLS and hand parsed records to a sink."""

    def __init__(self, *, sink, on_message=None, bind_host='0.0.0.0',
                 udp_port=0, tcp_port=0, tls_port=0, tls_cert='', tls_key='',
                 allowed_sources=None, dbg=None):
        self._sink = sink                       # callable(list[dict]) -> None  (batch store)
        self._on_message = on_message           # optional callable(dict) per message
        self._bind = bind_host or '0.0.0.0'
        self._udp_port = int(udp_port or 0)
        self._tcp_port = int(tcp_port or 0)
        self._tls_port = int(tls_port or 0)
        self._tls_cert = tls_cert or ''
        self._tls_key = tls_key or ''
        self._allow = _parse_allowlist(allowed_sources)
        self._dbg = dbg or (lambda *a, **k: None)
        self._q: queue.Queue = queue.Queue(maxsize=200000)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._socks: list[socket.socket] = []
        self.running = False

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> list[str]:
        """Bind the configured transports and start the threads.  Returns a list
        of human-readable problems (empty when everything bound)."""
        problems: list[str] = []
        self._stop.clear()
        if self._udp_port:
            try:
                self._start_udp(self._udp_port)
            except OSError as e:
                problems.append(f'UDP :{self._udp_port}: {e}')
        if self._tcp_port:
            try:
                self._start_tcp(self._tcp_port, tls_ctx=None)
            except OSError as e:
                problems.append(f'TCP :{self._tcp_port}: {e}')
        if self._tls_port:
            ctx, err = self._tls_context()
            if err:
                problems.append(f'TLS :{self._tls_port}: {err}')
            else:
                try:
                    self._start_tcp(self._tls_port, tls_ctx=ctx)
                except OSError as e:
                    problems.append(f'TLS :{self._tls_port}: {e}')
        if self._threads:                       # at least one transport bound
            self._spawn(self._writer_loop, name='syslog-writer')
            self.running = True
        return problems

    def stop(self) -> None:
        self._stop.set()
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()
        self._socks.clear()
        self.running = False

    def _spawn(self, target, *, name, args=()):
        t = threading.Thread(target=target, name=name, args=args, daemon=True)
        t.start()
        self._threads.append(t)

    # ── transports ─────────────────────────────────────────────────────────────
    def _start_udp(self, port: int) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self._bind, port))
        s.settimeout(_SOCK_TIMEOUT)
        self._socks.append(s)
        self._spawn(self._udp_loop, name=f'syslog-udp-{port}', args=(s,))
        self._dbg(f'> Syslog >> UDP listening on {self._bind}:{port}')

    def _start_tcp(self, port: int, *, tls_ctx) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self._bind, port))
        s.listen(64)
        s.settimeout(_SOCK_TIMEOUT)
        self._socks.append(s)
        kind = 'TLS' if tls_ctx else 'TCP'
        self._spawn(self._tcp_accept_loop, name=f'syslog-{kind.lower()}-{port}', args=(s, tls_ctx))
        self._dbg(f'> Syslog >> {kind} listening on {self._bind}:{port}')

    def _tls_context(self):
        if not (self._tls_cert and self._tls_key):
            return None, 'tls_cert/tls_key not configured'
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self._tls_cert, self._tls_key)
            return ctx, None
        except (OSError, ssl.SSLError) as e:
            return None, str(e)

    # ── receive loops ───────────────────────────────────────────────────────────
    def _allowed(self, ip: str) -> bool:
        if not self._allow:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self._allow)

    def _udp_loop(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(_MAX_DATAGRAM)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            ip = addr[0] if addr else ''
            if data and self._allowed(ip):
                self._enqueue(data, ip)

    def _tcp_accept_loop(self, sock: socket.socket, tls_ctx) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            ip = addr[0] if addr else ''
            if not self._allowed(ip):
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            self._spawn(self._tcp_conn_loop, name='syslog-conn', args=(conn, tls_ctx, ip))

    def _tcp_conn_loop(self, conn: socket.socket, tls_ctx, ip: str) -> None:
        try:
            if tls_ctx is not None:
                conn = tls_ctx.wrap_socket(conn, server_side=True)
            conn.settimeout(_SOCK_TIMEOUT)
            buf = b''
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(8192)
                except (socket.timeout, TimeoutError):
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                buf = self._consume_stream(buf, ip)
                if len(buf) > _MAX_DATAGRAM:     # runaway frame → drop
                    buf = b''
            # flush any trailing partial line
            if buf.strip():
                self._enqueue(buf, ip)
        except (ssl.SSLError, OSError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _consume_stream(self, buf: bytes, ip: str) -> bytes:
        """Frame TCP syslog: octet-counted (RFC 6587 "N MSG") or newline-delimited."""
        while buf:
            # octet-counted framing: leading "<len> "
            sp = buf.find(b' ')
            head = buf[:sp] if sp != -1 else b''
            if sp != -1 and head.isdigit():
                n = int(head)
                if len(buf) < sp + 1 + n:
                    break                        # incomplete frame, wait for more
                msg = buf[sp + 1: sp + 1 + n]
                self._enqueue(msg, ip)
                buf = buf[sp + 1 + n:]
                continue
            # non-transparent framing: split on newline
            nl = buf.find(b'\n')
            if nl == -1:
                break                            # no complete line yet
            line = buf[:nl]
            if line.strip():
                self._enqueue(line, ip)
            buf = buf[nl + 1:]
        return buf

    # ── queue → writer ──────────────────────────────────────────────────────────
    def _enqueue(self, data: bytes, ip: str) -> None:
        try:
            self._q.put_nowait((data, ip, time.time()))
        except queue.Full:
            pass                                 # shed load rather than block receivers

    def _writer_loop(self) -> None:
        while not self._stop.is_set() or not self._q.empty():
            batch: list[dict] = []
            deadline = time.time() + _FLUSH_SECS
            while len(batch) < _FLUSH_MAX and time.time() < deadline:
                try:
                    data, ip, ts = self._q.get(timeout=0.2)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                rec = parse_message(data, source=ip)
                rec['ts'] = ts
                batch.append(rec)
            if not batch:
                continue
            try:
                self._sink(batch)
            except Exception as e:               # pylint: disable=broad-except
                self._dbg(f'> Syslog >> store batch failed: {e}')
            if self._on_message:
                for rec in batch:
                    try:
                        self._on_message(rec)
                    except Exception:            # pylint: disable=broad-except
                        pass
