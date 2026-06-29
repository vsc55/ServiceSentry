#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central notification dispatcher for ServiceSentry.

Call ``dispatch(wa, kind, ...)`` to send a notification to all configured
channels (Telegram, Email, Webhooks) based on the ``notifications`` routing
config in config.json. This is the single entry-point used by the daemon.
"""

from __future__ import annotations

from lib.debug import DebugLevel


def dispatch(wa, kind: str, module: str = '', item: str = '',
             status: str = '', message: str = '',
             timestamp: str = '', channels=None,
             webhook_ids=None) -> dict[str, tuple[bool, str]]:
    """Send a notification to every enabled channel for the given event kind.

    By default the channels are chosen by the ``notifications`` routing matrix
    (``{channel}_on_{kind}``).  Pass *channels* (an iterable of channel names) to
    target an explicit set instead — used by the event-rules manager, where each
    rule picks its own channels.  *webhook_ids* optionally restricts the webhook
    channel to specific destinations (empty/None → every enabled webhook).

    Returns a dict mapping channel name → (ok, message) for each channel
    attempted. Channels not triggered are omitted.
    """
    results: dict[str, tuple[bool, str]] = {}
    try:
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
    except Exception as exc:
        wa._dbg(f"> Notify >> config read failed: {exc}", DebugLevel.error)
        return results

    notif = cfg.get('notifications') or {}
    kwargs = dict(kind=kind, module=module, item=item,
                  status=status, message=message, timestamp=timestamp)
    if channels is not None:
        _active = {c for c in ('telegram', 'email', 'webhook') if c in set(channels)}
    else:
        _active = {c for c in ('telegram', 'email', 'webhook')
                   if notif.get(f'{c}_on_{kind}', False)}
    wa._dbg(f"> Notify >> {kind} {module}/{item}: channels={sorted(_active) or 'none'}",
            DebugLevel.info)

    if 'telegram' in _active:
        try:
            from lib.notify import telegram_notify
            ok, msg = telegram_notify._dispatch(cfg.get('telegram') or {}, **kwargs)
            results['telegram'] = (ok, msg)
            wa._dbg(f"> Notify > telegram >> ok={ok}: {msg}",
                    DebugLevel.debug if ok else DebugLevel.warning)
        except Exception as exc:
            results['telegram'] = (False, str(exc))
            wa._dbg(f"> Notify > telegram >> {type(exc).__name__}: {exc}", DebugLevel.error)

    if 'email' in _active:
        try:
            from lib.notify import email_notify, email_templates
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
                recipients=None,   # None → fall back to the configured recipients
            )
            results['email'] = (ok, msg)
            wa._dbg(f"> Notify > email >> ok={ok}: {msg}",
                    DebugLevel.debug if ok else DebugLevel.warning)
        except Exception as exc:
            results['email'] = (False, str(exc))
            wa._dbg(f"> Notify > email >> {type(exc).__name__}: {exc}", DebugLevel.error)

    if 'webhook' in _active:
        try:
            from lib.notify import webhook_notify
            ok, msg = webhook_notify.send_all(wa, cfg=cfg, webhook_ids=webhook_ids, **kwargs)
            results['webhook'] = (ok, msg)
            wa._dbg(f"> Notify > webhook >> ok={ok}: {msg}",
                    DebugLevel.debug if ok else DebugLevel.warning)
        except Exception as exc:
            results['webhook'] = (False, str(exc))
            wa._dbg(f"> Notify > webhook >> {type(exc).__name__}: {exc}", DebugLevel.error)

    return results
