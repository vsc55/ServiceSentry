#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared host-resolution primitives.

The monitor (:meth:`lib.modules.module_base.ModuleBase.resolve_host`) and the
web "run a watchful action" route both merge a referenced host's connection
onto a config.  These small, store-free helpers hold the pieces that were
duplicated between the two, so the shared behaviour lives in one place.
"""

from __future__ import annotations

# ── Results that belong to a host rather than to a check ─────────────────────────────────
#
# A check is an item somebody configured, and its result is filed under that item's key. Some
# results have no item behind them: a device the panel monitors because the HOST says it is
# one — an SNMP profile with device profiles assigned — is read without anybody creating a
# check about it. Those results still belong to a host, and the Servers tab has to be able to
# say so, or a device can be sampled, reported down, and still show a neutral dash.
#
# The convention rather than a module name: any module may file a result this way, and core
# code that reads it stays ignorant of which one did.
HOST_RESULT_PREFIX = 'host.'


def host_result_key(host_uid: str) -> str:
    """The result key a host-owned (item-less) result is recorded under."""
    return f'{HOST_RESULT_PREFIX}{host_uid}'


def host_uid_from_key(key: str) -> str:
    """The host uid a result key names, or ``''`` when it names a check instead.

    Tolerates the ``<key>/<metric>`` composite the recorders already use, so
    ``host.abc123/metrics`` answers ``abc123``.
    """
    text = str(key or '')
    if not text.startswith(HOST_RESULT_PREFIX):
        return ''
    return text[len(HOST_RESULT_PREFIX):].split('/', 1)[0].strip()


def host_profile_specs(host_profile) -> list[dict]:
    """Normalise a module's ``__host_profile__`` to a list of spec dicts.

    Accepts a single spec (``dict``), several (``list``) or nothing (``None``),
    and returns a list — dropping any non-dict entries."""
    if isinstance(host_profile, dict):
        return [host_profile]
    if isinstance(host_profile, list):
        return [s for s in host_profile if isinstance(s, dict)]
    return []


def resolve_os(os_value, is_remote: bool, remote_auto: str = 'auto') -> str:
    """Resolve a host OS token.

    A concrete value is returned as-is (lower-cased).  ``'auto'`` resolves to
    this process's platform on a **local** host; on a **remote** host it cannot
    be probed here, so *remote_auto* is returned — the monitor keeps ``'auto'``
    (resolved later over SSH), while the web discovery flow assumes ``'linux'``.
    """
    os_ = str(os_value or 'auto').strip().lower()
    if os_ != 'auto':
        return os_
    if is_remote:
        return remote_auto
    from lib.util.os_detect import local_os  # noqa: PLC0415
    return local_os()
