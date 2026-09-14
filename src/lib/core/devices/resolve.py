#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared device-resolution primitives.

The monitor (:meth:`lib.modules.module_base.ModuleBase.resolve_device`) and the
web "run a watchful action" route both merge a referenced device's connection
onto a config.  These small, store-free helpers hold the pieces that were
duplicated between the two, so the shared behaviour lives in one place.
"""

from __future__ import annotations

# ── Results that belong to a device rather than to a check ─────────────────────────────────
#
# A check is an item somebody configured, and its result is filed under that item's key. Some
# results have no item behind them: a device the panel monitors because the HOST says it is
# one — an SNMP profile with device profiles assigned — is read without anybody creating a
# check about it. Those results still belong to a device, and the Servers tab has to be able to
# say so, or a device can be sampled, reported down, and still show a neutral dash.
#
# The convention rather than a module name: any module may file a result this way, and core
# code that reads it stays ignorant of which one did.
#: **El valor se queda en `host.`**: es lo que llevan dentro las claves de resultado ya
#: guardadas. El nombre de la constante dice de qué habla; el valor dice qué hay escrito.
DEVICE_RESULT_PREFIX = 'host.'


def device_result_key(device_uid: str) -> str:
    """The result key a device-owned (item-less) result is recorded under."""
    return f'{DEVICE_RESULT_PREFIX}{device_uid}'


def device_uid_from_key(key: str) -> str:
    """The device uid a result key names, or ``''`` when it names a check instead.

    Tolerates the ``<key>/<metric>`` composite the recorders already use, so
    ``device.abc123/metrics`` answers ``abc123``.
    """
    text = str(key or '')
    if not text.startswith(DEVICE_RESULT_PREFIX):
        return ''
    return text[len(DEVICE_RESULT_PREFIX):].split('/', 1)[0].strip()


def device_profile_specs(device_profile) -> list[dict]:
    """Normalise a module's ``__device_profile__`` to a list of spec dicts.

    Accepts a single spec (``dict``), several (``list``) or nothing (``None``),
    and returns a list — dropping any non-dict entries.

    **A protocol the core declares says what its own fields are.** A module names the
    protocol it binds to; which fields that protocol HAS is not the module's to state, and
    eleven of them were stating it — ten repeating the same seven SSH names. The catalogue
    already overrode those copies for the form it draws, so a module list that drifted from
    the core one did not change the form: it changed which values a bound device was allowed to
    push onto the check, and nothing said so.

    What the module keeps is ``address_field``: which field of ITS item receives the device's
    address is genuinely its own business (``web`` puts it in ``server``, SNMP in ``device``).
    """
    if isinstance(device_profile, dict):
        specs = [device_profile]
    elif isinstance(device_profile, list):
        specs = [s for s in device_profile if isinstance(s, dict)]
    else:
        return []
    return [_from_core(s) for s in specs]


def _from_core(spec: dict) -> dict:
    """*spec* with the core's field list, when the core owns that protocol.

    The spec's own ``address_field`` joins the list, because it is device-owned by
    definition — it is the field that RECEIVES the device's address, so a check bound to a
    device must neither draw it nor keep its own value in it. The eleven modules all listed
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
    # lib.core.devices.profiles pulls in the module registry and the translations, which
    # would close a cycle (lib.modules.device_binding imports this module).
    from lib.core.devices.profiles import core_profile_field_names   # noqa: PLC0415
    names = core_profile_field_names(key)
    if not names:
        return spec
    addr = str(spec.get('address_field') or '').strip()
    fields = ([addr] if addr and addr not in names else []) + list(names)
    if list(spec.get('fields') or ()) == fields:
        return spec
    return {**spec, 'fields': fields}


#: The roles a module files a platform under, most precise first.
#:
#: `os` is a module that KNOWS — a net-snmp `extend` running `lsb_release`, which answers
#: "Debian GNU/Linux 12" and nothing else. `description` is the one every SNMP agent has:
#: `sysDescr`, which is a sentence with the platform somewhere in it ("Linux nas-01 5.10…",
#: "Hardware: Intel64 … Windows Version 10.0"). Both are declarations the core already
#: understands, so this reads a ROLE and never a module — nothing here knows what SNMP is.
_OS_ROLES = ('os', 'description')


def reported_facts(status_raw: dict, uid: str) -> dict:
    """``{role: [{'value', 'source'}, …]}`` — what a device has SAID about ITSELF.

    One pass over the recorded state for every role at once. Three screens want three
    different facts out of the same scan (what it runs, who made it, which model it is), and
    three passes over the whole fleet's state to answer them would be two too many.

    **The device and not its rows.** A result carrying ``_row`` is about one disk, one port,
    one volume — a Synology files a model per disk, so a scan that took them would answer "this
    machine is a WD40EFRX". Which is the same rule the identity column already draws by, and it
    is why a fact here can be trusted as a fact about the box.

    The *source* travels with the value because a registry entry can front several pieces of
    equipment: a NAS and the UPS plugged into it both answer "model", and the two answers are
    only telling apart by which of them said it.
    """
    out: dict = {}
    uid = str(uid or '').strip()
    if not uid or not isinstance(status_raw, dict):
        return out
    seen = set()
    for mod_status in status_raw.values():
        if not isinstance(mod_status, dict):
            continue
        for res_key, info in mod_status.items():
            if device_uid_from_key(res_key) != uid or not isinstance(info, dict):
                continue
            data = info.get('other_data')
            if not isinstance(data, dict) or str(data.get('_row') or '').strip():
                continue                    # a row's facts belong to that row
            for source, facts in (data.get('_attrs') or {}).items():
                if not isinstance(facts, dict):
                    continue
                for role, value in facts.items():
                    role, value = str(role or '').strip(), str(value or '').strip()
                    if not role or not value or (role, source) in seen:
                        continue
                    seen.add((role, source))
                    out.setdefault(role, []).append({'value': value,
                                                     'source': str(source or '')})
    return out


def reported_os(status_raw: dict, uid: str) -> str:
    """The platform a device has SAID it runs, out of what a module recorded about it.

    ``''`` when nothing said anything, or when what it said maps to no platform this panel
    has a word for — a switch describes itself perfectly well and the answer is still not an
    operating system, and writing one down would be deciding something nobody decided.
    """
    return os_from_facts(reported_facts(status_raw, uid))


def os_from_facts(facts: dict) -> str:
    """The platform out of an already-taken scan (:func:`reported_facts`).

    Split from the scan so the fleet screen, which wants three facts, pays for one pass.
    """
    from lib.util.os_detect import OS_AUTO, OS_OTHER, canonical_os  # noqa: PLC0415
    for role in _OS_ROLES:
        for said in (facts or {}).get(role) or ():
            got = canonical_os(str((said or {}).get('value') or ''))
            if got and got not in (OS_AUTO, OS_OTHER):
                return got
    return ''


def resolve_os(os_value, is_remote: bool, remote_auto: str = 'auto', reported: str = '') -> str:
    """Resolve a device OS token.

    A concrete value is returned as-is (lower-cased) — it is what somebody chose, and nothing
    the device says overrules a decision.

    ``'auto'`` means work it out, and the first place to look is what the machine SAID: a
    device answering SNMP has told us its platform, and the panel was throwing that away and
    guessing instead. `auto` on a device whose kind is neither local nor remote resolved to the
    PANEL's platform, which is how a Synology came out as whatever the server runs.

    Failing that, the old answer: this process's platform on a **local** device, and on a remote
    one *remote_auto* — the monitor keeps ``'auto'`` (resolved later over SSH), while the web
    discovery flow assumes ``'linux'``.
    """
    from lib.util.os_detect import OS_AUTO, OS_OTHER, canonical_os, local_os  # noqa: PLC0415
    os_ = str(os_value or 'auto').strip().lower()
    if os_ != 'auto':
        return os_
    said = canonical_os(reported) if str(reported or '').strip() else ''
    if said and said not in (OS_AUTO, OS_OTHER):
        return said
    if is_remote:
        return remote_auto
    return local_os()
