#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this package wakes up to do, for the background-timers list.

Four threads live here — service health, certificate expiry, provider secrets and cabling drift
— and until this file existed **none of them appeared anywhere in the panel**. They were started
at boot, they took a lease so that only one replica did the work, and the only way to know any
of it was to read the source.

Declared rather than reached for: the screen collects ``BACKGROUND_TIMERS`` from whoever declares
one, so a fifth scanner shows up by saying so here instead of by editing the screen.

Every interval is read **live** from the config, the same call the thread itself makes. A list
that showed the value the process booted with would disagree with reality the moment somebody
changed it, and disagree silently.
"""

from __future__ import annotations


def _cfg(wa, seccion: str) -> dict:
    try:
        return wa._config_section(seccion) or {}
    except Exception:  # pylint: disable=broad-except
        return {}


def _num(v, por_defecto: int) -> int:
    try:
        return int(v if v is not None else por_defecto)
    except (TypeError, ValueError):
        return por_defecto


def live(wa) -> list:
    """The four scanners, with the setting that governs each one.

    ``last_run`` is not reported here on purpose: what this process remembers is this process's,
    and on a replica that is not the leader it would read as «never ran» rather than as «not me».
    The collector takes it from the lease, which is renewed on every round of whoever is
    actually doing the work and is therefore the one answer visible from another container.
    """
    servicios = _cfg(wa, 'services')
    certs = _cfg(wa, 'certs')
    oidc = _cfg(wa, 'oidc')
    dcim = _cfg(wa, 'dcim')
    return [
        {
            'id': 'service_health', 'kind': 'health',
            'label': wa._t('timer_service_health'),
            'detail': wa._t('timer_detail_health'), 'setting': 'services|notify_down',
            'enabled': bool(servicios.get('notify_down')),
            'every': _num(servicios.get('health_poll_secs'), 30),
            'lease': 'svc_health',
        },
        {
            'id': 'cert_expiry', 'kind': 'certs',
            'label': wa._t('timer_cert_expiry'),
            'detail': wa._t('timer_detail_certs'), 'setting': 'certs|notify_expiry',
            'enabled': bool(certs.get('notify_expiry')),
            'every': _num(certs.get('scan_every_secs'), 86400),
            'lease': 'cert_scan',
        },
        {
            'id': 'secret_expiry', 'kind': 'secrets',
            'label': wa._t('timer_secret_expiry'),
            'detail': wa._t('timer_detail_secret'), 'setting': 'oidc|secret_notify_expiry',
            'enabled': bool(oidc.get('secret_notify_expiry')),
            'every': _num(oidc.get('secret_scan_every_secs'), 86400),
            'lease': 'secret_scan',
        },
        {
            'id': 'cable_drift', 'kind': 'dcim',
            'label': wa._t('timer_cable_drift'),
            'detail': wa._t('timer_detail_cabling'), 'setting': 'dcim|notify_cabling',
            'enabled': bool(dcim.get('notify_cabling')),
            'every': _num(dcim.get('cable_scan_every_secs'), 1800),
            'lease': 'cable_scan',
        },
    ]
