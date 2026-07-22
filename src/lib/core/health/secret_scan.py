#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entra ID client-secret expiry scanner — warning + optional unattended rotation.

An Entra app secret has a finite life (the tenant policy decides how long, so the only
trustworthy value is the ``endDateTime`` Graph returned when the secret was minted — it is
stored in ``oidc|secret_expires_at``).  This scanner periodically checks how much life is
left and:

* emits a ``secret_expiring`` notification once per severity (``expiring`` → ``expired``),
  never re-alerting at the same severity, and re-arming when the secret is renewed;
* if ``oidc|secret_auto_rotate`` is on, mints a replacement secret once the remaining life
  drops below ``oidc|secret_rotate_days`` — the **margin** — and persists it, emitting
  ``secret_rotated``.  Rotation is attempted BEFORE the warning so a successful rotation
  doesn't also fire an expiry alert.

Adding a secret in Entra does not revoke the previous one, so a rotation that succeeds is
non-disruptive: the running config is updated to the new secret while the old one is still
valid.  A rotation that FAILS still warns (the operator must act), and unattended rotation
needs the app to be able to authenticate as itself (app-only token) with permission to
modify its own application object — if that is not granted, rotation fails and this falls
back to warning only.

All I/O is injected (``rotate_fn`` / ``save_fn`` / ``dispatch``), so :meth:`evaluate_once`
is pure decision logic and unit-testable without Graph or threads.
"""

from __future__ import annotations

import datetime
import threading
import time


def parse_expiry(value) -> float | None:
    """ISO-8601 timestamp → POSIX seconds, or None if empty/unparseable.

    Graph returns e.g. ``2027-01-15T10:20:30Z``; ``fromisoformat`` needs ``+00:00`` for the
    military ``Z`` on older Pythons, and a naive value is assumed UTC."""
    txt = str(value or '').strip()
    if not txt:
        return None
    if txt.endswith('Z'):
        txt = txt[:-1] + '+00:00'
    try:
        dt = datetime.datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def days_left(value, *, now: float) -> float | None:
    """Days until *value* (ISO-8601) elapses; None when unknown."""
    ts = parse_expiry(value)
    return None if ts is None else (ts - now) / 86400


def _default_text(key, *args):
    """Fallback text resolver (no host wired): the default-language i18n string."""
    from lib.i18n import translate  # noqa: PLC0415
    return translate('', key, *args)


class SecretExpiryScanner:
    """Warn (and optionally rotate) an Entra client secret before it expires."""

    def __init__(self, *, config_getter, dispatch, rotate_fn, save_fn,
                 is_leader=lambda: True, dbg=lambda *a, **k: None, text_fn=None,
                 label: str = 'Entra ID (OIDC)'):
        self._config = config_getter      # () -> dict (the 'oidc' section)
        self._dispatch = dispatch         # (kind, **fields) -> None
        self._rotate = rotate_fn          # () -> {'secret', 'expires_at'}; raises on failure
        self._save = save_fn              # (secret, expires_at) -> None
        self._is_leader = is_leader
        self._dbg = dbg
        self._text = text_fn or _default_text
        self._label = label
        self._alerted: str = ''           # last alerted severity ('' | 'expiring' | 'expired')
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def _int(cfg, key, default):
        try:
            return max(1, int(cfg.get(key) or default))
        except (TypeError, ValueError):
            return default

    def evaluate_once(self, *, now: float) -> dict:
        """Check the stored expiry once.  Returns a small report:
        ``{'days': float, 'rotated': bool, 'alert': '' | 'expiring' | 'expired'}`` — or
        ``{}`` when there is nothing to do (disabled, not leader, or expiry unknown)."""
        cfg = self._config() or {}
        if not cfg.get('enabled'):
            return {}                                   # OIDC itself is off
        notify = bool(cfg.get('secret_notify_expiry'))
        auto = bool(cfg.get('secret_auto_rotate'))
        if not (notify or auto):
            return {}
        if not self._is_leader():
            return {}                                   # a replica must not double-alert/rotate
        days = days_left(cfg.get('secret_expires_at'), now=now)
        if days is None:
            return {}                                   # unknown expiry → nothing we can assert
        warn_days = self._int(cfg, 'secret_warn_days', 30)
        rotate_days = self._int(cfg, 'secret_rotate_days', 15)
        report = {'days': days, 'rotated': False, 'alert': ''}

        # ── rotation first: a successful rotation must not also raise an expiry alert ──
        if auto and days <= rotate_days:
            try:
                res = self._rotate() or {}
                secret, expires_at = res.get('secret', ''), res.get('expires_at', '')
                if not secret:
                    raise RuntimeError('empty secret returned')
                self._save(secret, expires_at)
                self._alerted = ''                      # re-arm: the secret is fresh again
                report['rotated'] = True
                new_days = days_left(expires_at, now=now)
                self._dispatch(
                    'secret_rotated', module='oidc', item=self._label,
                    status=self._text('notif_status_rotated'),
                    message=self._text('notif_msg_secret_rotated', self._label,
                                       f'{new_days:.0f}' if new_days is not None else '?'))
                return report
            except Exception as exc:  # pylint: disable=broad-except
                self._dbg(f'> Secret >> rotation failed: {exc}')
                # fall through to the warning below — the operator has to act

        # ── warning (once per severity) ───────────────────────────────────────────────
        if not notify or days > warn_days:
            if days > warn_days:
                self._alerted = ''                      # renewed/healthy → re-arm
            return report
        sev = 'expired' if days <= 0 else 'expiring'
        if self._alerted == sev:
            return report                               # already alerted at this severity
        self._alerted = sev
        report['alert'] = sev
        try:
            msg = (self._text('notif_msg_secret_expired', self._label, f'{abs(days):.0f}')
                   if days <= 0
                   else self._text('notif_msg_secret_expiring', self._label, f'{days:.0f}'))
            self._dispatch('secret_expiring', module='oidc', item=self._label,
                           status=self._text('notif_status_expired' if days <= 0
                                             else 'notif_status_expiring'),
                           message=msg)
        except Exception:  # pylint: disable=broad-except
            self._dbg('> Secret >> dispatch failed')
        return report

    # ── background loop ──────────────────────────────────────────────────────────
    def start(self, *, poll_getter=lambda: 86400) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def _loop():
            if self._stop.wait(45):        # first check shortly after boot
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

        self._thread = threading.Thread(target=_loop, name='secret-scan', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
