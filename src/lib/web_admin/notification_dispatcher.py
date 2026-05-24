#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central notification dispatcher for ServiceSentry.

Call ``dispatch(wa, kind, ...)`` to send a notification to all configured
channels (Telegram, Email, Webhooks) based on the ``notifications`` routing
config in config.json. This is the single entry-point used by the daemon.
"""

from __future__ import annotations


def dispatch(wa, kind: str, module: str = '', item: str = '',
             status: str = '', message: str = '',
             timestamp: str = '') -> dict[str, tuple[bool, str]]:
    """Send a notification to every enabled channel for the given event kind.

    Returns a dict mapping channel name → (ok, message) for each channel
    attempted. Channels not triggered (routing config off) are omitted.
    """
    results: dict[str, tuple[bool, str]] = {}
    try:
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
    except Exception:
        return results

    notif = cfg.get('notifications') or {}
    kwargs = dict(kind=kind, module=module, item=item,
                  status=status, message=message, timestamp=timestamp)

    if notif.get(f'telegram_on_{kind}', False):
        try:
            from lib.web_admin import telegram_notify
            ok, msg = telegram_notify._dispatch(cfg.get('telegram') or {}, **kwargs)
            results['telegram'] = (ok, msg)
        except Exception as exc:
            results['telegram'] = (False, str(exc))

    if notif.get(f'email_on_{kind}', False):
        try:
            from lib.web_admin import email_notify, email_templates
            email_cfg = cfg.get('email') or {}
            lang = email_cfg.get('lang') or ''
            lang_key = lang or 'en_EN'
            # Load admin-configured text-string overrides
            _tpl_overrides = (cfg.get('notif_templates') or {}).get(lang_key) or None
            strings = email_templates.get_strings(lang, overrides=_tpl_overrides)
            # Load admin-configured HTML body override for alert emails
            _html_override = (
                (cfg.get('notif_html_templates') or {})
                .get('alert', {}).get(lang_key)
            ) or None
            prefix = email_cfg.get('subject_prefix') or '[ServiceSentry]'
            subject = f'{prefix} {kind.upper()}: {item}'
            body_html = email_templates.render_alert(
                kind=kind, module=module, item=item, status=status,
                message=message, timestamp=timestamp,
                lang=lang, strings=strings,
                html_override=_html_override,
            )
            ok, msg = email_notify._dispatch(
                email_cfg,
                subject=subject,
                body_html=body_html,
            )
            results['email'] = (ok, msg)
        except Exception as exc:
            results['email'] = (False, str(exc))

    if notif.get(f'webhook_on_{kind}', False):
        try:
            from lib.web_admin import webhook_notify
            ok, msg = webhook_notify.send_all(wa, cfg=cfg, **kwargs)
            results['webhook'] = (ok, msg)
        except Exception as exc:
            results['webhook'] = (False, str(exc))

    return results
