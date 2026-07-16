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

from lib.services.syslog.parser import parse_message

_MAX_DATAGRAM = 65535          # UDP theoretical max
_FLUSH_SECS = 1.0              # writer batch interval
_FLUSH_MAX = 500              # writer batch size cap
_SOCK_TIMEOUT = 0.5            # so stop() is responsive
_DROP_LOG_EVERY = 30.0        # min seconds between allowlist-drop logs per source
_DROPS_MAX = 500              # cap distinct dropped sources tracked in memory


def build_server(cfg: dict, *, sink, on_message=None, dbg=None,
                 dbg_warn=None, on_drop=None, is_banned=None, on_offense=None) -> 'SyslogServer':
    """Construct a :class:`SyslogServer` from a ``syslog`` config dict.  Shared by
    the in-web-admin mixin and the standalone service so the wiring lives once.

    ``is_banned(ip) -> bool`` / ``on_offense(ip, category)`` wire the receiver into
    the shared internal fail2ban: a jailed IP is dropped up-front, and a source that
    keeps violating the allowlist is reported so it can be jailed across services."""
    sources = [s for s in re.split(r'[,\s]+', str(cfg.get('allowed_sources') or '')) if s]
    return SyslogServer(
        sink=sink, on_message=on_message,
        bind_host=str(cfg.get('bind_host') or ''),   # blank → all IPv4 + IPv6 (see _parse_binds)
        udp_port=int(cfg.get('udp_port') or 0),
        tcp_port=int(cfg.get('tcp_port') or 0),
        tls_port=int(cfg.get('tls_port') or 0),
        tls_cert=str(cfg.get('tls_cert') or ''),
        tls_key=str(cfg.get('tls_key') or ''),
        allowed_sources=sources, dbg=dbg, dbg_warn=dbg_warn, on_drop=on_drop,
        is_banned=is_banned, on_offense=on_offense)


def _parse_binds(bind_host) -> list:
    """Return ``[(family, address)]`` for every configured bind address.

    ``bind_host`` may list several addresses (comma/space/newline separated) so
    the receiver can listen on specific interfaces only; each is detected as IPv4
    or IPv6.  Blank → all IPv4 interfaces (``0.0.0.0``); use ``::`` for all IPv6.
    """
    raw = [s.strip().strip('[]') for s in re.split(r'[,\s]+', str(bind_host or '')) if s.strip()]
    if not raw:
        return [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')]   # all IPv4 + IPv6
    out, seen = [], set()
    for a in raw:
        try:
            fam = socket.AF_INET6 if ipaddress.ip_address(a).version == 6 else socket.AF_INET
        except ValueError:
            fam = socket.AF_INET                # hostname or junk → let bind() decide/fail
        key = (fam, a)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


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
                 allowed_sources=None, dbg=None, dbg_warn=None, on_drop=None,
                 is_banned=None, on_offense=None):
        self._sink = sink                       # callable(list[dict]) -> None  (batch store)
        self._on_message = on_message           # optional callable(dict) per message
        self._bind = bind_host or '0.0.0.0'
        self._binds = _parse_binds(self._bind)  # [(family, address)] — one per interface
        self._udp_port = int(udp_port or 0)
        self._tcp_port = int(tcp_port or 0)
        self._tls_port = int(tls_port or 0)
        self._tls_cert = tls_cert or ''
        self._tls_key = tls_key or ''
        self._allow = _parse_allowlist(allowed_sources)
        self._dbg = dbg or (lambda *a, **k: None)
        self._dbg_warn = dbg_warn or self._dbg   # drop notices log at warning
        self._on_drop = on_drop                  # callable(source, transport, delta)
        self._is_banned = is_banned              # callable(ip) -> bool  (shared fail2ban)
        self._on_offense = on_offense            # callable(ip, category) — report abuse
        self._drops: dict = {}                  # ip -> {count, last_log, flushed}
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
            problems += self._start_udp(self._udp_port)
        if self._tcp_port:
            problems += self._start_tcp(self._tcp_port, tls_ctx=None)
        # TLS binds only when a port AND a cert+key are configured. A port set
        # without a cert (e.g. the 6514 default before certs are provided) is NOT an
        # error — TLS simply stays off silently until a cert/key is set.
        if self._tls_port and self._tls_cert and self._tls_key:
            ctx, err = self._tls_context()
            if err:
                problems.append(f'TLS :{self._tls_port}: {err}')
            else:
                problems += self._start_tcp(self._tls_port, tls_ctx=ctx)
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
        # Prune finished per-connection threads first, so a long-lived listener with many
        # short TCP/TLS connections doesn't accumulate dead Thread objects without bound.
        self._threads = [x for x in self._threads if x.is_alive()]
        t = threading.Thread(target=target, name=name, args=args, daemon=True)
        t.start()
        self._threads.append(t)

    # ── transports ─────────────────────────────────────────────────────────────
    def _new_socket(self, family: int, sock_type: int, addr: str, port: int):
        """Create, configure and bind one socket (IPv6 bound v6-only so IPv4 and
        IPv6 wildcards don't collide)."""
        s = socket.socket(family, sock_type)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            try:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            except (OSError, AttributeError):
                pass
        s.bind((addr, port))
        s.settimeout(_SOCK_TIMEOUT)
        return s

    def _start_udp(self, port: int) -> list:
        """Bind a UDP socket per configured address; return per-address problems."""
        problems = []
        for fam, addr in self._binds:
            try:
                s = self._new_socket(fam, socket.SOCK_DGRAM, addr, port)
            except OSError as e:
                problems.append(f'UDP {addr}:{port}: {e}')
                continue
            self._socks.append(s)
            self._spawn(self._udp_loop, name=f'syslog-udp-{port}', args=(s,))
            self._dbg(f'> Syslog >> UDP listening on {addr}:{port}')
        return problems

    def _start_tcp(self, port: int, *, tls_ctx) -> list:
        """Bind a TCP/TLS socket per configured address; return per-address problems."""
        kind = 'TLS' if tls_ctx else 'TCP'
        problems = []
        for fam, addr in self._binds:
            try:
                s = self._new_socket(fam, socket.SOCK_STREAM, addr, port)
                s.listen(64)
            except OSError as e:
                problems.append(f'{kind} {addr}:{port}: {e}')
                continue
            self._socks.append(s)
            self._spawn(self._tcp_accept_loop, name=f'syslog-{kind.lower()}-{port}', args=(s, tls_ctx))
            self._dbg(f'> Syslog >> {kind} listening on {addr}:{port}')
        return problems

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
    def _banned(self, ip: str) -> bool:
        """True if *ip* is jailed by the shared internal fail2ban — dropped up-front
        regardless of the allowlist (a ban from any service applies to syslog too)."""
        if not self._is_banned or not ip:
            return False
        try:
            return bool(self._is_banned(ip))
        except Exception:  # pylint: disable=broad-except
            return False

    def _reject(self, ip: str, transport: str) -> None:
        """Record an allowlist drop and report it to the shared fail2ban so a source
        that keeps violating the allowlist eventually gets jailed for every service."""
        self._note_drop(ip, transport)
        if self._on_offense and ip:
            try:
                self._on_offense(ip, 'syslog_drop')
            except Exception:  # pylint: disable=broad-except
                pass

    def _allowed(self, ip: str) -> bool:
        if not self._allow:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self._allow)

    def _note_drop(self, ip: str, transport: str) -> None:
        """Count an allowlist-rejected packet/connection.  At most once every
        ``_DROP_LOG_EVERY`` seconds per source (so a flood never spams) it logs a
        warning and flushes the new drops to the persistent tally via ``on_drop``."""
        d = self._drops.get(ip)
        if d is None:
            if len(self._drops) >= _DROPS_MAX:   # cap distinct sources (spoof flood)
                return
            d = self._drops[ip] = {'count': 0, 'last_log': 0.0, 'flushed': 0}
        d['count'] += 1
        now = time.time()
        if now - d['last_log'] >= _DROP_LOG_EVERY:
            d['last_log'] = now
            delta = d['count'] - d['flushed']
            d['flushed'] = d['count']
            self._dbg_warn(f'> Syslog >> dropped {transport} from {ip or "?"} '
                           f'(not in allowed sources) — {d["count"]} dropped so far')
            if self._on_drop and delta > 0:
                try:
                    self._on_drop(ip, transport, delta)
                except Exception:               # pylint: disable=broad-except
                    pass

    def _udp_loop(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(_MAX_DATAGRAM)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            if not data:
                continue
            ip = addr[0] if addr else ''
            if self._banned(ip):
                self._note_drop(ip, 'UDP')       # jailed source → drop, no re-offense
            elif self._allowed(ip):
                self._enqueue(data, ip)
            else:
                self._reject(ip, 'UDP')

    def _tcp_accept_loop(self, sock: socket.socket, tls_ctx) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            ip = addr[0] if addr else ''
            if self._banned(ip) or not self._allowed(ip):
                if self._banned(ip):
                    self._note_drop(ip, 'TCP')   # jailed source → drop, no re-offense
                else:
                    self._reject(ip, 'TCP')
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
