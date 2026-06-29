#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared host-resolution primitives.

The monitor (:meth:`lib.modules.module_base.ModuleBase.resolve_host`) and the
web "run a watchful action" route both merge a referenced host's connection
onto a config.  These small, store-free helpers hold the pieces that were
duplicated between the two, so the shared behaviour lives in one place.
"""

from __future__ import annotations


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
