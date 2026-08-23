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
    and returns a list — dropping any non-dict entries.

    **A protocol the core declares says what its own fields are.** A module names the
    protocol it binds to; which fields that protocol HAS is not the module's to state, and
    eleven of them were stating it — ten repeating the same seven SSH names. The catalogue
    already overrode those copies for the form it draws, so a module list that drifted from
    the core one did not change the form: it changed which values a bound host was allowed to
    push onto the check, and nothing said so.

    What the module keeps is ``address_field``: which field of ITS item receives the host's
    address is genuinely its own business (``web`` puts it in ``server``, SNMP in ``host``).
    """
    if isinstance(host_profile, dict):
        specs = [host_profile]
    elif isinstance(host_profile, list):
        specs = [s for s in host_profile if isinstance(s, dict)]
    else:
        return []
    return [_from_core(s) for s in specs]


def _from_core(spec: dict) -> dict:
    """*spec* with the core's field list, when the core owns that protocol.

    The spec's own ``address_field`` joins the list, because it is host-owned by
    definition — it is the field that RECEIVES the host's address, so a check bound to a
    host must neither draw it nor keep its own value in it. The eleven modules all listed
    it for exactly that reason (SNMP's ``host``, SSH's ``ssh_host``), and dropping it would
    have left `datastore` drawing an ``ssh_host`` box on a bound check.

    A profile the core does NOT own keeps whatever the module says, address field included:
    ``web``'s ``server`` is visible on purpose, so one host behind a reverse proxy can serve
    several FQDNs. If a core-owned protocol ever needs that, the core declaration is where
    it would say so.
    """
    key = str(spec.get('key') or '').strip()
    if not key:
        return spec
    # Imported here, not at module scope: this file is the framework-free half and
    # lib.core.hosts.profiles pulls in the module registry and the translations, which
    # would close a cycle (lib.modules.host_binding imports this module).
    from lib.core.hosts.profiles import core_profile_field_names   # noqa: PLC0415
    names = core_profile_field_names(key)
    if not names:
        return spec
    addr = str(spec.get('address_field') or '').strip()
    fields = ([addr] if addr and addr not in names else []) + list(names)
    if list(spec.get('fields') or ()) == fields:
        return spec
    return {**spec, 'fields': fields}


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
