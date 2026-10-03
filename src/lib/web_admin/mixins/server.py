#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Binding the interfaces and serving, with a start-up that never lies.

The rule this file exists to keep is one line long and easy to lose: **fail-soft per interface,
fail-hard overall**. Some interfaces failing is a warning and the panel runs on the rest; ALL of
them failing is an exit, because a process that reports "listening" while nothing is bound sends
an operator to debug the network, the proxy and the firewall before anyone thinks to check
whether the server ever came up.

Binding is separated from serving (:meth:`_bind_web_servers` opens the sockets and returns; the
caller decides whether enough came up) so that policy is testable without starting a loop.
"""

import os
import sys
import threading
import time


class _ServerMixin:
    """Start-up: bind the interfaces, report honestly, serve until stopped."""

    def run(self, host: str | None = None, port: int | None = None,
            debug: bool = False):
        """Start the web administration server, binding one or more interfaces.

        *host* may name several interfaces (comma/space separated); each is bound
        independently.  Binding is **fail-soft per interface but fail-hard
        overall**:

        * if some — but not all — interfaces fail to bind, the failures are
          logged as warnings and the server runs on those that succeeded;
        * if **no** interface can be bound (e.g. the port is already in use), an
          error is logged and the process exits non-zero — it never reports a
          running server when nothing is actually listening.

        Args:
            host: Interface(s) to bind (default ``0.0.0.0``).  Accepts a list as
                a comma/space separated string, e.g. ``"10.0.0.1, 10.0.0.2"``.
            port: TCP port to listen on (default ``8080``).
            debug: Enable the interactive debugger and verbose errors.
        """
        port = int(port or self.DEFAULT_PORT)
        hosts = str(host or self.DEFAULT_HOST).replace(',', ' ').split() \
            or [self.DEFAULT_HOST]

        # No reloader: __init__ already bound the syslog ports and started the
        # scheduler/event worker, so Werkzeug's reloader (which re-runs __init__ in
        # a child) would double-bind. Dev reloads are handled by dev_watch.py.
        self._app.debug = debug
        wsgi_app = self._app
        if debug:
            from werkzeug.debug import DebuggedApplication  # noqa: PLC0415
            wsgi_app = DebuggedApplication(self._app, evalex=True)

        servers, failed = self._bind_web_servers(hosts, port, wsgi_app)

        # Startup bind status goes to stdout/stderr directly (not the debug log,
        # whose default level is 'off') so it is always visible — like main.py's
        # startup banner.
        for _h, exc in failed:
            print('  ⚠  ' + self._t('web_bind_fail', _h, port, exc), file=sys.stderr)

        if not servers:
            # Nothing is listening: fail loudly and exit instead of leaving the
            # daemon threads running and faking a started server.  os._exit (not
            # sys.exit) because a plain SystemExit would block on the non-daemon
            # threads some background services spawn (e.g. the scheduler's
            # ThreadPoolExecutor) — the process would hang instead of closing.
            print('  ✖  ' + self._t('web_bind_none', port), file=sys.stderr)
            # On Windows a 10013 is often a reserved (winnat/Hyper-V/WSL/Docker)
            # range, not a process: point the user straight at the cause + remedy.
            from lib.system.windows import port_excluded  # noqa: PLC0415
            rng = port_excluded(port)
            if rng:
                print('     ↳ ' + self._t('web_bind_reserved', port, rng[0], rng[1]),
                      file=sys.stderr)
            sys.stderr.flush()
            sys.stdout.flush()
            os._exit(1)

        shown = set()
        for _h, srv in servers:
            # A wildcard bind (0.0.0.0 / ::) listens on every interface — list the
            # concrete reachable addresses too, as Werkzeug's dev server used to.
            for disp in self._display_hosts(_h):
                if disp not in shown:
                    shown.add(disp)
                    print('  ' + self._t('web_listening', disp, port))
        if failed:
            print('  ' + self._t('web_bind_partial', len(servers), len(hosts), len(failed)))
        print()   # blank line between the startup banner and the request logs

        threads = []
        for _h, srv in servers:
            t = threading.Thread(target=srv.serve_forever,
                                 name=f"web-{_h}:{port}", daemon=True)
            t.start()
            threads.append(t)

        stop_requested = threading.Event()
        previous = self._install_stop_signals(stop_requested)
        try:
            while any(t.is_alive() for t in threads) and not stop_requested.wait(0.5):
                pass
            if stop_requested.is_set():
                print('  ' + self._t('web_stop_requested'))
        except KeyboardInterrupt:
            print('  ' + self._t('web_stop_requested'))
        finally:
            self._restore_signals(previous)
            # Services first, while the process is still whole: the syslog writer drains
            # its queue, the leases are given back (a standby takes over now, not when they
            # expire) and this instance's rows say it is down instead of "running".
            self.shutdown_services()
            for _h, srv in servers:
                try:
                    srv.shutdown()
                except Exception:  # pylint: disable=broad-except
                    pass

    @staticmethod
    def _install_stop_signals(stop_requested: threading.Event) -> dict:
        """Route SIGTERM (``docker stop``, systemd, Kubernetes) and SIGINT to *stop_requested*.

        Only SIGINT used to be handled, as a KeyboardInterrupt: SIGTERM killed the process
        where it stood. Signal handlers can only be installed from the main thread, so from
        any other thread (a test, an embedding host) this is a no-op. Returns the previous
        handlers for :meth:`_restore_signals`."""
        import signal  # noqa: PLC0415
        previous: dict = {}
        if threading.current_thread() is not threading.main_thread():
            return previous

        def _handler(_signum, _frame):
            stop_requested.set()

        for name in ('SIGTERM', 'SIGINT'):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                previous[sig] = signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass                                   # unsupported on this platform
        return previous

    @staticmethod
    def _restore_signals(previous: dict) -> None:
        import signal  # noqa: PLC0415
        for sig, handler in (previous or {}).items():
            try:
                signal.signal(sig, handler if handler is not None else signal.SIG_DFL)
            except (ValueError, OSError, TypeError):
                pass

    def shutdown_services(self) -> None:
        """Stop what this process runs in the background, for a clean exit. Idempotent.

        Each embedded service gets ``on_shutdown()`` (the syslog listener drains its writer
        queue) and then ``stop_heartbeat()`` (lease released, instance row marked down);
        then the panel's own scanners and backup runner stop and give their leases back.
        Every step is guarded: one that fails must not keep the others from running."""
        if getattr(self, '_services_shut_down', False):
            return
        self._services_shut_down = True
        for _svc in (getattr(self, '_embedded_services', None) or {}).values():
            for step in ('on_shutdown', 'stop_heartbeat'):
                fn = getattr(_svc, step, None)
                if not callable(fn):
                    continue
                try:
                    fn()
                except Exception:  # pylint: disable=broad-except
                    pass
        stop_bg = getattr(self, 'stop_background', None)
        if callable(stop_bg):
            try:
                stop_bg()
            except Exception:  # pylint: disable=broad-except
                pass

    @staticmethod
    def _display_hosts(host):
        """Addresses to advertise for *host* in the startup banner.

        A wildcard bind (``0.0.0.0`` / ``::``) actually listens on every
        interface, so list the machine's concrete addresses too (like Werkzeug's
        dev server did) — the literal wildcard first, then the resolved IPs."""
        if host not in ('0.0.0.0', '::', '*', ''):
            return [host]
        out = [host or '0.0.0.0']
        try:
            import socket  # noqa: PLC0415
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                if ip not in out:
                    out.append(ip)
        except Exception:  # pylint: disable=broad-except
            pass
        return out

    @staticmethod
    def _bind_web_servers(hosts, port: int, wsgi_app):
        """Try to bind *wsgi_app* on each host at *port*.

        Returns ``(servers, failed)`` where ``servers`` is a list of
        ``(host, werkzeug_server)`` successfully bound and ``failed`` a list of
        ``(host, OSError)``.  Binding happens here (sockets are opened) but no
        request is served yet — so the caller decides whether enough interfaces
        came up before serving.  Kept separate (and side-effect-light) so the
        bind policy is unit-testable without starting the server loop.
        """
        import contextlib  # noqa: PLC0415
        import io  # noqa: PLC0415
        from werkzeug.serving import make_server  # noqa: PLC0415
        servers, failed = [], []
        for _h in hosts:
            try:
                # Werkzeug prints the raw OS strerror to stderr on a bind failure
                # (then sys.exit(1)).  Swallow that uncontrolled, OS-localised line
                # so only our own i18n message is shown — the OSError detail still
                # reaches it via the exception.
                with contextlib.redirect_stderr(io.StringIO()):
                    srv = make_server(_h, port, wsgi_app, threaded=True)
                servers.append((_h, srv))
            except OSError as exc:
                failed.append((_h, exc))
            except SystemExit as exc:
                # make_server calls sys.exit(1) instead of propagating OSError;
                # catch it so one unbindable interface doesn't abort the whole
                # process, recovering the underlying OSError (its __context__).
                cause = exc.__context__ if isinstance(exc.__context__, OSError) else None
                failed.append((_h, cause or OSError(f'bind {_h}:{port} failed')))
        return servers, failed
