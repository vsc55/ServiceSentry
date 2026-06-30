#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiny HTTP control listener for a standalone service — the *poke* accelerator.

The distributed control plane's source of truth is the shared database (desired
state in ``config``, the command queue in ``service_commands``); a service
already reconciles to it on a timer.  This listener only makes that reconcile
*immediate*: the web admin writes the desired state / enqueues a command, then
best-effort ``POST``s ``/control/reconcile`` here so the service converges now
instead of waiting for its next poll.  If the poke never arrives (web down, net
partition, listener off), the periodic reconcile still converges — so this is an
optimisation, never the contract.

No Flask: a stdlib :class:`http.server.ThreadingHTTPServer` in a daemon thread,
guarded by a bearer token.  Endpoints:

* ``GET  /control/health``    → ``{"ok": true, ...}`` (no auth — for k8s probes).
* ``POST /control/reconcile`` → run a reconcile + drain commands now; returns a
  small status snapshot.  Requires ``Authorization: Bearer <token>``.

Configuration (env, so it maps cleanly to a k8s Secret / Docker env):
  ``SS_CONTROL_TOKEN``     shared bearer token; **no token → the listener is off**.
  ``SS_CONTROL_PORT``      listen port (default 8765).
  ``SS_CONTROL_BIND``      bind address (default 0.0.0.0).
  ``SS_CONTROL_ADVERTISE`` address peers should reach this instance at (default:
                           the pod/host name); published as the heartbeat
                           ``control_url`` so the web admin knows where to poke.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lib.debug import DebugLevel
from lib.services.heartbeat import hostname

_DEFAULT_PORT = 8765


def control_token() -> str | None:
    tok = os.environ.get('SS_CONTROL_TOKEN')
    return tok.strip() if tok and tok.strip() else None


def control_port() -> int:
    try:
        return int(os.environ.get('SS_CONTROL_PORT') or _DEFAULT_PORT)
    except (TypeError, ValueError):
        return _DEFAULT_PORT


def control_advertise_url() -> str:
    addr = os.environ.get('SS_CONTROL_ADVERTISE') or hostname()
    return f'http://{addr}:{control_port()}'


class _Handler(BaseHTTPRequestHandler):
    # The owning ControlServer sets these on the server instance.
    @property
    def _service(self):
        return self.server._ss_service          # type: ignore[attr-defined]

    @property
    def _token(self):
        return self.server._ss_token            # type: ignore[attr-defined]

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except Exception:  # pylint: disable=broad-except
            pass

    def _authed(self) -> bool:
        hdr = self.headers.get('Authorization', '')
        prefix = 'Bearer '
        if not hdr.startswith(prefix):
            return False
        return hmac.compare_digest(hdr[len(prefix):].strip(), self._token or '')

    def do_GET(self):  # noqa: N802
        if self.path.rstrip('/') == '/control/health':
            svc = self._service
            self._send(200, {'ok': True, 'key': getattr(svc, '_HB_KEY', None)})
        else:
            self._send(404, {'ok': False, 'error': 'not_found'})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip('/') != '/control/reconcile':
            self._send(404, {'ok': False, 'error': 'not_found'})
            return
        if not self._authed():
            self._send(401, {'ok': False, 'error': 'unauthorized'})
            return
        try:
            result = self._service._control_reconcile()
        except Exception as exc:  # pylint: disable=broad-except
            self._send(500, {'ok': False, 'error': str(exc)})
            return
        self._send(200, result)

    def log_message(self, *_a):  # silence the default stderr access log
        return


class ControlServer:
    """A daemon-thread HTTP control listener bound to one service object."""

    def __init__(self, service, token: str, port: int, bind: str = '0.0.0.0'):
        self._service = service
        self._httpd = ThreadingHTTPServer((bind, port), _Handler)
        self._httpd._ss_service = service       # type: ignore[attr-defined]
        self._httpd._ss_token = token           # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name='control-server', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._httpd.shutdown()
        except Exception:  # pylint: disable=broad-except
            pass


def start_control_server(service):
    """Start the control listener for *service* if a token is configured.

    Returns the :class:`ControlServer` (kept alive by the caller) or None when no
    ``SS_CONTROL_TOKEN`` is set (the listener stays off — poke disabled, the
    periodic reconcile still works).  Also stamps the advertised ``control_url`` on
    the service so its heartbeat publishes where to be poked."""
    token = control_token()
    if not token:
        return None
    port = control_port()
    bind = os.environ.get('SS_CONTROL_BIND') or '0.0.0.0'
    try:
        srv = ControlServer(service, token, port, bind)
    except OSError as exc:
        # Port busy / not bindable — log and carry on without the poke.
        dbg = getattr(service, '_dbg', None)
        if dbg:
            dbg(f'> Control >> listener not started on {bind}:{port}: {exc}',
                DebugLevel.warning)
        return None
    service._control_url = control_advertise_url()
    srv.start()
    dbg = getattr(service, '_dbg', None)
    if dbg:
        dbg(f'> Control >> listening on {bind}:{port} '
            f'(advertise {service._control_url})', DebugLevel.info)
    return srv
