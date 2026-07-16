#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification subsystem (Flask-free, reusable by every runtime).

A core-owned :class:`~lib.core.notify.router.NotificationRouter`, built from an explicit
:class:`~lib.core.notify.context.NotifyContext`, owns the channel stores and routes an
alert to the configured channels — Telegram, e-mail (SMTP, with i18n templates), outgoing
webhooks and Microsoft Teams.  The web admin, the monitor daemon and the standalone
syslog/events workers each build one router and notify the same way, with no dependency on
the web layer.

* :mod:`lib.core.notify.router` — the ``NotificationRouter`` + ``run_dispatch`` logic;
* :mod:`lib.core.notify.context` — the ``NotifyContext`` collaborator bundle;
* :mod:`lib.core.notify.registry` — the self-registering channel registry;
* :mod:`lib.core.notify.<channel>.channel` — each channel's ``send``/``flush`` descriptor;
* :mod:`lib.core.notify.notification_dispatcher` — thin ``dispatch(wa, …)`` façade;
* :mod:`lib.core.notify.monitor_notifier` — the monitor's cycle-scoped, grouped notifier.

Kept import-light on purpose: the router and each channel pull their senders lazily, so
importing this package does not drag in ``smtplib`` / ``requests``.
"""
