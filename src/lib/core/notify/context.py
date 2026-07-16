#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit collaborator bundle for the notification router.

:class:`NotifyContext` is the *only* thing :class:`lib.core.notify.router.NotificationRouter`
knows about its host.  It carries the handful of collaborators the router needs —
a DB connector for the channel stores, a config reader, the secret cipher, a debug
sink, an optional audit sink and public-URL/panel-user callables — **as plain
callables/values**, never the web admin or a Flask app.

Each host (the web admin, the monitor/events/syslog workers) builds one of these from
its own surface and hands it to a router; the router stays Flask-free and
web_admin-independent, which is the whole point of moving routing into ``lib/core/notify``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


def _noop(*_a, **_k) -> None:
    return None


def _empty_config() -> dict:
    return {}


@dataclass
class NotifyContext:
    """The collaborators a :class:`NotificationRouter` needs — nothing web-specific.

    ``db``                DB connector the channel stores bind to (webhooks, Teams).
    ``read_config``       ``() -> dict`` returning the full effective config.
    ``fernet``            secret cipher for the stores' at-rest encryption (or None).
    ``secret_keys``       field-name set that marks values to encrypt (or None → default).
    ``dbg``               ``(message, level) -> None`` debug sink.
    ``audit``             ``(event, detail) -> None`` audit sink (optional).
    ``public_url``        ``() -> str`` the panel's public base URL (optional).
    ``panel_user_emails`` ``() -> list[str]`` enabled panel-user emails (optional).
    ``config_file``       config filename token passed to ``read_config`` legacy callers.
    """

    db: object
    read_config: Callable[[], dict] = _empty_config
    fernet: object = None
    secret_keys: object = None
    dbg: Callable[..., None] = _noop
    audit: Callable[..., None] = _noop
    public_url: Optional[Callable[[], str]] = None
    panel_user_emails: Optional[Callable[[], list]] = None
    config_file: str = 'config.json'
