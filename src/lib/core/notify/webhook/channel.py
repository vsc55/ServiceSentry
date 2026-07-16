#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook notification channel — self-registers with the core registry.

Webhooks are discrete events (the norm for integrations): both a single dispatch and a
monitor cycle send **one call per alert** to every enabled webhook (``webhook_ids``
optionally restricts the destinations on a single dispatch).
"""

from __future__ import annotations

import time

from lib.core.notify.formatting import plain
from lib.core.notify.registry import Channel, register_channel

# ── store ownership (the webhook channel owns its store; the router only caches it) ──
_STORE_KEY = 'webhook'


def get_store(router):
    """The channel's :class:`WebhooksStore`, built once from the router's context."""
    from lib.core.notify.webhook.store import WebhooksStore  # noqa: PLC0415
    return router.store(_STORE_KEY, lambda ctx: WebhooksStore(
        ctx.db, fernet=ctx.fernet, secret_keys=ctx.secret_keys))


def load(router, *, decrypt: bool = True) -> list:
    """Current webhooks from this channel's store (decrypted); [] on any error."""
    try:
        return get_store(router).list(decrypt=decrypt)
    except Exception:  # pylint: disable=broad-except
        return []


def send(router, cfg, *, webhook_ids=None, kind='', module='', item='', status='',
         message='', timestamp='', **_extra) -> tuple:
    from lib.core.notify.webhook import notify as webhook_notify  # noqa: PLC0415
    return webhook_notify.send_all(router, cfg=cfg, webhook_ids=webhook_ids, kind=kind,
                                   module=module, item=item, status=status,
                                   message=message, timestamp=timestamp)


def flush(router, cfg, alerts, hostname, public_url) -> tuple:
    from lib.core.notify.webhook import notify as webhook_notify  # noqa: PLC0415
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    ok_all, infos = True, []
    for a in alerts:
        ok, msg = webhook_notify.send_all(
            router, kind=a['kind'], module=a['module'], item=a['item'] or hostname,
            status=a['kind'], message=plain(a['message']), timestamp=ts, cfg=cfg)
        ok_all = ok_all and ok
        infos.append(msg)
    return (ok_all, '; '.join(infos))


register_channel(Channel('webhook', send, flush))
