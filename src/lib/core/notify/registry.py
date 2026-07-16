#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification-channel registry — the core owns *which* channels exist.

Each channel (Telegram, Email, Webhook, Microsoft Teams) is a self-describing
:class:`Channel` that **registers itself** here on import, declaring how to send a
single event and how to flush a monitor cycle's grouped alerts.  The router and the
monitor's cycle notifier iterate this registry instead of hard-coding the channel
list, so adding a channel is a new ``channel.py`` that calls :func:`register_channel`
— nothing in the router or the monitor changes.

``load_builtin_channels()`` **discovers** those ``channel.py`` modules (every
``lib/core/notify/<name>/channel.py``) and imports them on first access, so there is no
central channel list to maintain and the registry is populated lazily (no import-time
cycles).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Channel:
    """A self-describing notification channel.

    ``send``  — ``(router, cfg, **event) -> (ok, msg)``: deliver one event now.  *cfg* is
                the full effective config; the channel reads its own section.  *event*
                carries ``kind/module/item/status/message/timestamp`` (+ channel-specific
                extras like ``webhook_ids`` that other channels ignore).
    ``flush`` — ``(router, cfg, alerts, hostname, public_url) -> (ok, msg)``: deliver a
                monitor cycle's alerts already filtered for this channel, grouped however
                the channel sees fit (one digest, one message per alert, …).
    """

    name: str
    send: Callable[..., tuple]
    flush: Callable[..., tuple]


_REGISTRY: dict[str, Channel] = {}
_LOADED = False


def register_channel(channel: Channel) -> None:
    """Register (or replace) a channel by name.  Called by each channel module on import."""
    _REGISTRY[channel.name] = channel


def load_builtin_channels() -> None:
    """Discover and import every channel module so it registers itself.

    A channel is any subpackage of :mod:`lib.core.notify` that ships a ``channel.py``
    (``lib/core/notify/<name>/channel.py``) — no central list to keep in sync; dropping a
    new ``channel.py`` in its own package is enough.  Discovered in a stable (sorted) order
    so dispatch/flush iteration is deterministic.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    import importlib  # noqa: PLC0415
    import importlib.util  # noqa: PLC0415
    import pkgutil  # noqa: PLC0415
    import lib.core.notify as _pkg  # noqa: PLC0415

    for info in sorted(pkgutil.iter_modules(_pkg.__path__), key=lambda m: m.name):
        if not info.ispkg:
            continue
        modname = f'{_pkg.__name__}.{info.name}.channel'
        if importlib.util.find_spec(modname) is None:
            continue   # that subpackage isn't a notification channel
        importlib.import_module(modname)   # importing registers it (see register_channel)


def channels() -> dict[str, Channel]:
    """Every registered channel, in registration order (built-ins loaded on demand)."""
    load_builtin_channels()
    return dict(_REGISTRY)


def get_channel(name: str) -> Channel | None:
    load_builtin_channels()
    return _REGISTRY.get(name)
