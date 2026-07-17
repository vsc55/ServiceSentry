#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Email notification channel — self-registers with the core registry.

* ``send``  — one alert email rendered from the (admin-overridable) alert template.
* ``flush`` — a single digest email listing every alert in the monitor cycle + a summary.
"""

from __future__ import annotations

import time

from lib.core.notify.formatting import notify_lang, plain
from lib.core.notify.recipients import RecipientResolver
from lib.core.notify.registry import Channel, register_channel


def _resolve_recipients(router, email_cfg) -> list:
    """Expand the configured recipient tokens (plain email | ``group:<uid>``) to a flat
    email list, via the router-owned resolver (works in web + monitor). Empty/unknown
    groups are logged, not fatal."""
    resolver = router.store('recipients', lambda ctx: RecipientResolver(ctx.db))
    res = resolver.expand(email_cfg.get('recipients', ''))
    if res.get('skipped'):
        router._dbg(f"email: recipient(s) with no deliverable address skipped: "
                    f"{', '.join(res['skipped'])}")
    return res['emails']


def send(router, cfg, *, kind='', module='', item='', status='', message='',
         timestamp='', **_extra) -> tuple:
    from lib.core.notify.email import notify as email_notify, templates as email_templates  # noqa: PLC0415,E501
    email_cfg = cfg.get('email') or {}
    lang = notify_lang(cfg)
    lang_key = lang or 'en_EN'
    # Admin-configured text-string overrides + HTML body override for alert emails.
    _tpl_overrides = (cfg.get('notif_templates') or {}).get(lang_key) or None
    strings = email_templates.get_strings(lang, overrides=_tpl_overrides)
    _html_override = (
        (cfg.get('notif_html_templates') or {}).get('alert', {}).get(lang_key)
    ) or None
    prefix = email_cfg.get('subject_prefix') or '[ServiceSentry]'
    subject = f'{prefix} {kind.upper()}: {item}'
    body_html = email_templates.render_alert(
        kind=kind, module=module, item=item, status=status,
        message=message, timestamp=timestamp,
        lang=lang, strings=strings, html_override=_html_override,
    )
    return email_notify._dispatch(
        email_cfg, subject=subject, body_html=body_html,
        recipients=_resolve_recipients(router, email_cfg),   # expand group tokens → emails
        lang=lang,
    )


def flush(router, cfg, alerts, hostname, public_url) -> tuple:
    from lib.core.notify.email import notify as email_notify, templates as email_templates  # noqa: PLC0415,E501
    email_cfg = cfg.get('email') or {}
    lang = notify_lang(cfg)
    lang_key = lang or 'en_EN'
    strings = email_templates.get_strings(
        lang, overrides=(cfg.get('notif_templates') or {}).get(lang_key) or None)
    html_override = (cfg.get('notif_html_templates') or {}).get('summary', {}).get(lang_key) or None
    items = [{'module': a['module'], 'item': a['item'],
              'status': a['kind'], 'message': plain(a['message'])} for a in alerts]
    body_html = email_templates.render_summary(
        items=items, timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
        public_url=public_url, lang=lang, strings=strings, html_override=html_override)
    prefix = email_cfg.get('subject_prefix') or '[ServiceSentry]'
    subject = f'{prefix} {hostname}: {len(alerts)} alert(s)'
    return email_notify._dispatch(email_cfg, subject=subject, body_html=body_html,
                                  recipients=_resolve_recipients(router, email_cfg), lang=lang)


register_channel(Channel('email', send, flush))
