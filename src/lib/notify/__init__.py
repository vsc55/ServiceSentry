#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification subsystem (Flask-free, reusable by every runtime).

A single ``dispatch`` entry point routes an alert to the configured channels —
Telegram, e-mail (SMTP, with i18n templates) and outgoing webhooks — so the web
admin, the monitor daemon and the standalone syslog/events workers all notify
the same way without depending on the web layer.

* :mod:`lib.notify.notification_dispatcher` — ``dispatch()`` router;
* :mod:`lib.notify.telegram_notify` / :mod:`lib.notify.email_notify` /
  :mod:`lib.notify.webhook_notify` — per-channel senders;
* :mod:`lib.notify.email_templates` — localized e-mail bodies.

Kept import-light on purpose: the dispatcher pulls each sender lazily, so
importing this package does not drag in ``smtplib`` / ``requests``.
"""
