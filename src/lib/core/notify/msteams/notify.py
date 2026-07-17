#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Teams notification sender.

Fans one alert out to both destination kinds of the single ``msteams`` channel:

* **channels** — POST an Adaptive/MessageCard to each enabled Incoming Webhook
  (loaded via :func:`lib.core.notify.msteams.channel.load` — the :class:`MsTeamsStore`
  records the channel owns);
* **users** — when the ``msteams`` config section enables user delivery, send to the
  resolved recipients via the selected mechanism (``activity_feed`` Graph notification
  or ``bot`` Bot Framework proactive message).

Every path is best-effort and returns ``(ok, summary)``; a failure in one destination
never raises out of :func:`send_all`.
"""

from __future__ import annotations

from lib.config.spec import cfg_get
from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase
from lib.core.notify.msteams import cards
from lib.i18n import translate

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


def send_all(wa, kind: str = 'info', module: str = '', item: str = '',
             status: str = '', message: str = '', timestamp: str = '',
             cfg: dict | None = None, channel_ids=None, lang: str = '') -> tuple[bool, str]:
    """Send to every enabled Teams channel + (if enabled) directly to users.

    Returns ``(all_ok, summary)``.  ``channel_ids`` optionally restricts the channel
    fan-out to those destination ids.  ``cfg`` is the ``msteams`` config section
    (user-mode settings); loaded from *wa* when not provided.
    """
    if not _HAS_REQUESTS:
        return False, translate(lang, 'msteams_no_requests')
    if cfg is None:
        cfg = wa._config_section('msteams')

    results: list[tuple[bool, str, str]] = []

    # ── (a) channels — Incoming Webhook cards ───────────────────────────────
    channels = [c for c in (_load_channels(wa) or [])
                if c.get('enabled') and (c.get('webhook_url') or '').strip()]
    if channel_ids:
        wanted = {str(i) for i in channel_ids}
        channels = [c for c in channels if str(c.get('id') or c.get('uid') or '') in wanted]
    card = cards.message_card(kind=kind, module=module, item=item,
                              status=status, message=message, timestamp=timestamp)
    for ch in channels:
        ok, msg = _post_card(ch['webhook_url'], card)
        results.append((ok, msg, ch.get('name') or ch.get('id', '?')))

    # ── (b) users — direct delivery (activity feed or bot) ───────────────────
    if cfg.get('user_enabled'):
        text = cards.plain_text(kind=kind, module=module, item=item,
                                message=message, timestamp=timestamp)
        results.extend(_send_users(wa, cfg, text))

    if not results:
        return False, translate(lang, 'msteams_no_destinations')
    all_ok = all(r[0] for r in results)
    summary = '; '.join(f'{r[2]}: {r[1]}' for r in results)
    return all_ok, summary


def send_channel_test(channel: dict, lang: str = '') -> tuple[bool, str]:
    """POST a test card to a single channel record (used by the per-channel test route)."""
    if not _HAS_REQUESTS:
        return False, translate(lang, 'msteams_no_requests')
    url = (channel.get('webhook_url') or '').strip()
    if not url:
        return False, translate(lang, 'msteams_url_required')
    card = cards.message_card(kind='test', module='ServiceSentry', item='msteams_test',
                              status='TEST', message='ServiceSentry Teams test', timestamp='')
    return _post_card(url, card)


def send_user_test(wa, cfg: dict | None = None, lang: str = '') -> tuple[bool, str]:
    """Send a test message via the configured user-delivery mechanism."""
    if not _HAS_REQUESTS:
        return False, translate(lang, 'msteams_no_requests')
    if cfg is None:
        cfg = wa._config_section('msteams')
    text = cards.plain_text(kind='test', item='msteams_test', message='ServiceSentry Teams test')
    results = _send_users(wa, cfg, text)
    if not results:
        return False, translate(lang, 'msteams_no_recipients')
    return all(r[0] for r in results), '; '.join(f'{r[2]}: {r[1]}' for r in results)


def _load_channels(wa) -> list[dict]:
    from lib.core.notify.msteams import channel as _channel  # noqa: PLC0415
    return _channel.load(wa)


def _post_card(webhook_url: str, card: dict) -> tuple[bool, str]:
    """POST a MessageCard to a Teams Incoming Webhook (always POST/unsigned)."""
    try:
        resp = _req.post(webhook_url.strip(), json=card,
                         headers={'Content-Type': 'application/json'}, timeout=15)
        # Connector webhooks return 200 with body "1" on success.
        if 200 <= resp.status_code < 300:
            return True, f'delivered (HTTP {resp.status_code})'
        return False, f'HTTP {resp.status_code}'
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)


# ── user delivery ───────────────────────────────────────────────────────────
def _resolve_recipients(wa, cfg: dict) -> list[str]:
    """UPNs/emails to notify: the configured list + (optionally) panel users."""
    out: list[str] = []
    raw = (cfg.get('recipients') or '')
    out += [e.strip() for e in raw.replace(';', ',').split(',') if e.strip()]
    if cfg.get('notify_panel_users'):
        emails = getattr(wa, '_panel_user_emails', None)
        if callable(emails):
            out += [e for e in (emails() or []) if e]
    # de-dupe case-insensitively, preserve order
    seen, uniq = set(), []
    for e in out:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def _send_users(wa, cfg: dict, text: str) -> list[tuple[bool, str, str]]:
    recipients = _resolve_recipients(wa, cfg)
    if not recipients:
        return [(False, 'no recipients', 'users')]
    delivery = cfg_get(cfg, 'msteams|delivery', falsy=True) or 'activity_feed'
    ObjectBase.debug.print(
        f'> Teams >> user delivery={delivery} to {len(recipients)} recipient(s)',
        DebugLevel.debug)
    if delivery == 'bot':
        return _send_users_bot(wa, cfg, recipients, text)
    return _send_users_activity(wa, cfg, recipients, text)


def _send_users_activity(wa, cfg, recipients, text) -> list[tuple[bool, str, str]]:
    from lib.providers.entraid import auth, teams  # noqa: PLC0415
    tenant = (cfg.get('tenant_id') or '').strip()
    client_id = (cfg.get('client_id') or '').strip()
    client_secret = (cfg.get('client_secret') or '').strip()
    if not (tenant and client_id and client_secret):
        return [(False, 'activity feed needs tenant/client id+secret', 'users')]
    try:
        token = auth.app_token(tenant, client_id, client_secret)
    except Exception as exc:  # pylint: disable=broad-except
        return [(False, f'token: {exc}', 'users')]
    out = []
    for upn in recipients:
        try:
            # web_url is built by the helper as a Teams deep link (Graph requires it).
            teams.send_activity_notification(token, upn, text=text)
            out.append((True, 'notified', upn))
        except Exception as exc:  # pylint: disable=broad-except
            out.append((False, str(exc), upn))
    return out


def _send_users_bot(wa, cfg, recipients, text) -> list[tuple[bool, str, str]]:
    from lib.providers.entraid import teams  # noqa: PLC0415
    app_id = (cfg.get('bot_app_id') or '').strip()
    app_password = (cfg.get('bot_app_password') or '').strip()
    tenant = (cfg.get('bot_tenant_id') or '').strip()
    if not (app_id and app_password):
        return [(False, 'bot needs app id + password', 'users')]
    from lib.core.notify.msteams import channel as _channel  # noqa: PLC0415
    refmap = _channel.bot_refs(wa)
    try:
        token = teams.bot_token(tenant, app_id, app_password)
    except Exception as exc:  # pylint: disable=broad-except
        return [(False, f'bot token: {exc}', 'users')]
    out = []
    for upn in recipients:
        ref = refmap.get(upn.lower())
        if not ref:
            out.append((False, 'no bot conversation (user must start the bot first)', upn))
            continue
        try:
            teams.send_bot_message(token, ref, text)
            out.append((True, 'messaged', upn))
        except Exception as exc:  # pylint: disable=broad-except
            out.append((False, str(exc), upn))
    return out
