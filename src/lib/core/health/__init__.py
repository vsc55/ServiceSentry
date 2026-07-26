#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Platform self-monitoring (core).

Health of the platform *itself* — is my background stack alive, are my certificates
valid — as opposed to :mod:`lib.services.monitoring`, which monitors external targets.
It sits below the monitoring service: two lightweight, leader-gated background evaluators
that turn observed state into notification events routed by :mod:`lib.core.notify`.

* :class:`lib.core.health.health.ServiceHealthMonitor` — ``service_down`` / ``service_up``
  from the heartbeat registry.
* :class:`lib.core.health.cert_scan.CertExpiryScanner` — ``cert_expiring`` from the
  configured ``ssl_cert`` checks.

Kept import-light (no Flask, no eager service imports); the events it publishes are
declared in :mod:`lib.core.health.manifest` and discovered by the notify registry.
"""


def default_text(key, *args) -> str:
    """Fallback text resolver: the default-language i18n string.

    The evaluators in this package run **without a host wired** (leader-gated background
    threads, no request, no session), so there is no per-user language to resolve against.
    Each of them used to carry its own identical copy of this; one is enough, and the
    import stays local so the package remains import-light.
    """
    from lib.i18n import translate  # noqa: PLC0415
    return translate('', key, *args)
