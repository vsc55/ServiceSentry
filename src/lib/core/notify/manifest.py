#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What this package contributes, discovered by :mod:`lib.discovery`.

The notification channels: what they write to the audit log when a destination is
created, edited or tested, and when a message template is saved or reset.
"""

# What this package writes to the audit log, and how loud each one is. Declared here rather
# than guessed from the event name: the badge is the only thing a glance down two hundred
# rows gives you, and deriving it from a noun made the colour depend on what somebody called
# the event (see lib/core/audit/events.py).
AUDIT_EVENTS = [
    {'key': 'email_test_ok', 'severity': 'success'},
    {'key': 'email_test_fail', 'severity': 'danger'},
    {'key': 'telegram_test_ok', 'severity': 'success'},
    {'key': 'telegram_test_fail', 'severity': 'danger'},
    {'key': 'webhook_created', 'severity': 'success'},
    {'key': 'webhook_updated', 'severity': 'info'},
    {'key': 'webhook_deleted', 'severity': 'danger'},
    {'key': 'webhook_enabled', 'severity': 'info'},
    {'key': 'webhook_disabled', 'severity': 'warning'},
    {'key': 'webhook_test_ok', 'severity': 'success'},
    {'key': 'webhook_test_fail', 'severity': 'danger'},
    {'key': 'msteams_channel_created', 'severity': 'success'},
    {'key': 'msteams_channel_updated', 'severity': 'info'},
    {'key': 'msteams_channel_deleted', 'severity': 'danger'},
    {'key': 'msteams_channel_enabled', 'severity': 'info'},
    {'key': 'msteams_channel_disabled', 'severity': 'warning'},
    {'key': 'msteams_test_ok', 'severity': 'success'},
    {'key': 'msteams_test_fail', 'severity': 'danger'},
    {'key': 'notif_template_saved', 'severity': 'info'},
    {'key': 'notif_template_reset', 'severity': 'warning'},
    {'key': 'notif_html_template_saved', 'severity': 'info'},
    {'key': 'notif_html_template_reset', 'severity': 'warning'},
    {'key': 'notif_text_saved', 'severity': 'info'},
]
