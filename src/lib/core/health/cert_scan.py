#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Certificate-expiry scanner — proactive ``cert_expiring`` notifications.

Periodically scans the certificates of every configured ``ssl_cert`` check (host:port,
resolving a ``host_uid`` to its address via the hosts store) and emits a ``cert_expiring``
notification when a cert is within ``certs|warn_days`` of expiry — **once per severity**
(``expiring`` → ``expired``), so it never spams every scan; a cert that recovers (renewed)
re-arms for a future alert.  Leader-gated so replicas don't double-alert.

This is the proactive, low-frequency heads-up (a daily scan by default); the real-time
reachability/expiry state of a configured check still routes through the monitor's
``down`` / ``warn`` events independently.

``enumerate_targets`` and the alert transition logic are pure (no network / threads), so
they are unit-tested; the TLS fetch (:func:`cert_days_left`) is injected as ``days_fn``.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time


def enumerate_targets(modules_cfg: dict, *, host_address=lambda _uid: None,
                      default_warn: int = 21) -> list[dict]:
    """Cert targets from the ``ssl_cert`` module config → list of dicts with
    ``key/label/host/port/server_name/verify/warn_days``.  ``host_uid`` items resolve
    their address via ``host_address(uid)``; disabled items are skipped."""
    ssl_mod = (modules_cfg or {}).get('ssl_cert') or {}
    items = ssl_mod.get('list') or {}
    try:
        mod_warn = int(ssl_mod.get('warning_days') or 0) or default_warn
    except (TypeError, ValueError):
        mod_warn = default_warn
    out: list[dict] = []
    for key, v in items.items():
        if not isinstance(v, dict) or v.get('enabled') is False:
            continue
        host = (v.get('host') or '').strip()
        uid = (v.get('host_uid') or '').strip()
        if not host and uid:
            host = (host_address(uid) or '').strip()
        host = host or str(key)
        try:
            port = int(v.get('port') or 0) or 443
        except (TypeError, ValueError):
            port = 443
        server_name = (v.get('server_name') or '').strip() or host
        try:
            warn = int(v.get('warning_days') or 0) or mod_warn
        except (TypeError, ValueError):
            warn = mod_warn
        label = (v.get('label') or '').strip() or server_name or host or str(key)
        out.append({'key': str(key), 'label': label, 'host': host, 'port': port,
                    'server_name': server_name, 'verify': bool(v.get('verify', True)),
                    'warn_days': warn})
    return out


def cert_days_left(target: dict, *, timeout: float = 10) -> float | None:
    """Days until *target*'s TLS certificate expires, or None on any error.

    Fetches the peer cert (binary, so it works in insecure mode too) and reads notAfter
    with ``cryptography`` — the same parse the ``ssl_cert`` watchful uses."""
    try:
        ctx = ssl.create_default_context()
        if not target.get('verify', True):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((target['host'], target['port']), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=target['server_name']) as ssock:
                der = ssock.getpeercert(binary_form=True)
        from cryptography import x509  # noqa: PLC0415
        cert = x509.load_der_x509_certificate(der)
        try:
            dt = cert.not_valid_after_utc                     # cryptography >= 42 (tz-aware)
        except AttributeError:                                # older: naive UTC
            import datetime  # noqa: PLC0415
            dt = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        return (dt.timestamp() - time.time()) / 86400
    except Exception:  # pylint: disable=broad-except
        return None


def _default_text(key, *args):
    """Fallback text resolver (no host wired): the default-language i18n string."""
    from lib.i18n import translate  # noqa: PLC0415
    return translate('', key, *args)


class CertExpiryScanner:
    """Periodically scan cert targets and emit cert_expiring on the expiring/expired edge."""

    def __init__(self, *, targets_provider, dispatch, config_getter,
                 days_fn=cert_days_left, is_leader=lambda: True, dbg=lambda *a, **k: None,
                 text_fn=None):
        text_fn = text_fn or _default_text
        self._targets = targets_provider     # () -> list[target]
        self._dispatch = dispatch            # (kind, **fields) -> None
        self._config = config_getter         # () -> dict (the 'certs' section)
        self._days_fn = days_fn
        self._is_leader = is_leader
        self._dbg = dbg
        self._text = text_fn                 # (key, *args) -> localized text with admin override
        self._alerted: dict[str, str] = {}   # target key -> last alerted severity
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def evaluate_once(self, *, now: float) -> dict:
        """Scan once; emit cert_expiring for targets that entered/escalated the warn window.
        Returns ``{key: days_left}`` for the alerts emitted."""
        cfg = self._config() or {}
        if not cfg.get('notify_expiry'):
            return {}
        try:
            warn_days = max(1, int(cfg.get('warn_days') or 21))
        except (TypeError, ValueError):
            warn_days = 21
        if not self._is_leader():
            return {}
        emitted: dict[str, float] = {}
        for t in self._targets() or []:
            days = self._days_fn(t)
            if days is None:
                continue                              # unreachable/error → leave state as-is
            if days > warn_days:
                self._alerted.pop(t['key'], None)     # renewed/healthy → re-arm
                continue
            sev = 'expired' if days <= 0 else 'expiring'
            if self._alerted.get(t['key']) == sev:
                continue                              # already alerted at this severity
            self._alerted[t['key']] = sev
            emitted[t['key']] = days
            try:
                msg = (self._text('notif_msg_cert_expired', t['label'], f'{abs(days):.0f}')
                       if days <= 0
                       else self._text('notif_msg_cert_expiring', t['label'], f'{days:.0f}'))
                status = self._text('notif_status_expired' if days <= 0
                                    else 'notif_status_expiring')
                self._dispatch('cert_expiring', module='certs', item=t['label'],
                               status=status, message=msg)
            except Exception:  # pylint: disable=broad-except
                self._dbg(f"> Certs >> dispatch failed for {t['key']!r}")
        return emitted

    # ── background loop ──────────────────────────────────────────────────────────
    def start(self, *, poll_getter=lambda: 86400) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def _loop():
            # First scan shortly after boot, then every scan_every_secs.
            if self._stop.wait(30):
                return
            while True:
                try:
                    self.evaluate_once(now=time.time())
                except Exception:  # pylint: disable=broad-except
                    pass
                try:
                    interval = max(3600, int(poll_getter() or 86400))
                except (TypeError, ValueError):
                    interval = 86400
                if self._stop.wait(interval):
                    return

        self._thread = threading.Thread(target=_loop, name='cert-scan', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
