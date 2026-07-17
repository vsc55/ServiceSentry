#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Teams notification channel — self-registers with the core registry.

Both a single dispatch and a monitor cycle send **one card per alert** to every enabled
Teams channel + (if enabled) direct-to-user delivery, via
:func:`lib.core.notify.msteams.notify.send_all` (the ``msteams`` config section).
"""

from __future__ import annotations

import time

from lib.core.notify.formatting import notify_lang, plain
from lib.core.notify.registry import Channel, register_channel

# ── store ownership (the Teams channel owns its stores; the router only caches them) ──
_STORE_KEY = 'msteams'
_BOT_STORE_KEY = 'msteams_bot'


def get_store(router):
    """The channel's :class:`MsTeamsStore` (Incoming-Webhook destinations)."""
    from lib.core.notify.msteams.store import MsTeamsStore  # noqa: PLC0415
    return router.store(_STORE_KEY, lambda ctx: MsTeamsStore(
        ctx.db, fernet=ctx.fernet, secret_keys=ctx.secret_keys))


def get_bot_store(router):
    """The channel's :class:`MsTeamsBotStore` (Bot Framework conversation references)."""
    from lib.core.notify.msteams.bot_store import MsTeamsBotStore  # noqa: PLC0415
    return router.store(_BOT_STORE_KEY, lambda ctx: MsTeamsBotStore(ctx.db))


def load(router, *, decrypt: bool = True) -> list:
    """Teams channel destinations from this channel's store (decrypted); [] on error."""
    try:
        return get_store(router).list(decrypt=decrypt)
    except Exception:  # pylint: disable=broad-except
        return []


def bot_refs(router) -> dict:
    """Captured Bot Framework conversation references; {} on error."""
    try:
        return get_bot_store(router).all_refs()
    except Exception:  # pylint: disable=broad-except
        return {}


def send(router, cfg, *, kind='', module='', item='', status='', message='',
         timestamp='', **_extra) -> tuple:
    from lib.core.notify.msteams import notify as msteams_notify  # noqa: PLC0415
    return msteams_notify.send_all(router, cfg=cfg.get('msteams') or {}, kind=kind,
                                   module=module, item=item, status=status,
                                   message=message, timestamp=timestamp, lang=notify_lang(cfg))


def flush(router, cfg, alerts, hostname, public_url) -> tuple:
    from lib.core.notify.msteams import notify as msteams_notify  # noqa: PLC0415
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    msteams_cfg = cfg.get('msteams') or {}
    ok_all, infos = True, []
    for a in alerts:
        ok, msg = msteams_notify.send_all(
            router, kind=a['kind'], module=a['module'], item=a['item'] or hostname,
            status=a['kind'], message=plain(a['message']), timestamp=ts, cfg=msteams_cfg,
            lang=notify_lang(cfg))
        ok_all = ok_all and ok
        infos.append(msg)
    return (ok_all, '; '.join(infos))


register_channel(Channel('msteams', send, flush))
