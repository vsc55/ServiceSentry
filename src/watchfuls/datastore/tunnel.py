#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - Datastore watchful: reaching a database that is not exposed.
#
"""A local TCP listener that forwards each connection over SSH.

A database worth monitoring is usually one you cannot reach directly. Rather than teaching
every engine driver about SSH, the tunnel opens a local port, and the driver connects to
localhost like any other host - so the ten drivers stay ignorant of how they got there.
"""

import os
import socket
import threading

from . import deps

if deps._PARAMIKO:
    import paramiko


# ── SSH tunnel ────────────────────────────────────────────────────────────────

def _pkey_from_string(key_string: str, password: str = ''):
    """Load a paramiko private key from PEM/OpenSSH text (any supported type)."""
    import io  # noqa: PLC0415
    last_exc = None
    for cls_name in ('Ed25519Key', 'ECDSAKey', 'RSAKey', 'DSSKey'):
        cls = getattr(paramiko, cls_name, None)
        if cls is None:
            continue
        try:
            return cls.from_private_key(io.StringIO(key_string),
                                        password=password or None)
        except Exception as exc:  # pylint: disable=broad-except
            last_exc = exc
    raise ValueError(f'Unsupported or invalid private key: {last_exc}')


class _SSHTunnel:
    """SSH TCP port-forward tunnel — serves multiple connections until ``close()``."""

    def __init__(self, ssh_host, ssh_port, ssh_user, ssh_password, ssh_key,
                 remote_host, remote_port, timeout=10, verify_host=False,
                 ssh_key_string=''):
        client = paramiko.SSHClient()
        if verify_host:
            # Strict mode: only hosts present in the system/user known_hosts are
            # accepted; an unknown or changed key aborts the connection (MITM-safe).
            client.load_system_host_keys()
            try:
                client.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
            except (OSError, IOError):
                pass
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            # Convenience mode (default): accept any host key on first contact.
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = {
            'hostname': str(ssh_host), 'port': int(ssh_port),
            'username': str(ssh_user),
            'timeout': timeout, 'banner_timeout': timeout, 'auth_timeout': timeout,
        }
        if ssh_key_string:
            # Inline private key (PEM/OpenSSH text) — stored encrypted on the
            # host profile / item; ssh_password doubles as its passphrase.
            kw['pkey'] = _pkey_from_string(str(ssh_key_string), str(ssh_password or ''))
        elif ssh_key:
            kw['key_filename'] = str(ssh_key)
        elif ssh_password:
            kw['password'] = str(ssh_password)
        client.connect(**kw)
        transport = client.get_transport()
        transport.set_keepalive(10)
        self._client = client
        self._transport = transport
        self._remote_host = str(remote_host)
        self._remote_port = int(remote_port)
        self._closed = False

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', 0))
        # Backlog > 1: serve MULTIPLE connections through the forward, not just one — a
        # backend may open several (InfluxDB 2.x→1.x fallback probe, MongoDB SDAM monitor
        # sockets). Closing after the first accept broke those over SSH.
        srv.listen(8)
        self.local_port = srv.getsockname()[1]
        self._server = srv
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        """Accept connections until the tunnel is closed, relaying each on its own thread."""
        self._server.settimeout(1.0)
        while not self._closed:
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            threading.Thread(target=self._handle_conn, args=(conn, addr), daemon=True).start()

    def _handle_conn(self, conn, addr):
        chan = None
        try:
            chan = self._transport.open_channel(
                'direct-tcpip', (self._remote_host, self._remote_port), addr)
            if chan is None:
                raise RuntimeError('SSH channel returned None')
            chan.settimeout(None)
        except Exception:
            conn.close()
            return
        try:
            self._relay(conn, chan)
        finally:
            try: conn.close()
            except Exception: pass
            try: chan.close()
            except Exception: pass

    @staticmethod
    def _relay(conn, chan):
        def fwd(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
        t1 = threading.Thread(target=fwd, args=(conn, chan), daemon=True)
        t2 = threading.Thread(target=fwd, args=(chan, conn), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()

    def close(self):
        self._closed = True   # stop the accept loop
        try: self._server.close()
        except Exception: pass
        try: self._client.close()
        except Exception: pass
