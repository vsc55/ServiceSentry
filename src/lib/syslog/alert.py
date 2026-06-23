#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Route a syslog record through the notification dispatcher.

Shared by the in-web-admin mixin and the standalone service.  ``ctx`` is any
object exposing the small surface the dispatcher needs — ``_read_config_file``,
``_config_section``, ``_load_webhooks`` and ``_dbg`` — so both the full WebAdmin
and the lightweight :class:`lib.syslog.service.SyslogService` qualify.
"""

from __future__ import annotations


def dispatch_syslog_alert(ctx, rec: dict) -> None:
    """Fire a ``kind='syslog'`` notification for *rec* (best-effort)."""
    try:
        from lib.web_admin.notification_dispatcher import dispatch  # noqa: PLC0415
        host = rec.get('hostname') or rec.get('source') or '?'
        dispatch(ctx, kind='syslog', module='syslog', item=host,
                 status=rec.get('severity_name', ''),
                 message=rec.get('message', ''),
                 timestamp=rec.get('received_at', ''))
    except Exception:  # pylint: disable=broad-except
        pass
