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
