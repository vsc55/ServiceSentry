#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID / Graph — Teams user-directed delivery helpers.

Two independent mechanisms for messaging a *user* (not a channel):

* :func:`send_activity_notification` — Graph ``users/{id}/teamwork/sendActivityNotification``
  (application permission ``TeamsActivity.Send``).  Outbound only; the Teams app must
  be installed for the target user.  Uses the ``systemDefault`` activity type so no
  custom manifest activity types are required.
* :func:`bot_token` / :func:`send_bot_message` — Bot Framework (Azure Bot) proactive
  messaging via the Bot Connector, using a stored conversation reference captured by
  the inbound messaging endpoint.  Requires a publicly reachable bot endpoint.

Pure HTTP helpers; they take already-acquired tokens / references and raise on failure.
"""

from __future__ import annotations

from urllib.parse import quote

import requests as _req

from lib.providers.entraid.client import GRAPH_BASE, graph_error


# ── Graph activity-feed notification ────────────────────────────────────────
def send_activity_notification(access_token: str, user_id: str, *, text: str,
                               web_url: str = '', topic: str = 'ServiceSentry') -> None:
    """Send a Teams *activity feed* notification to a user via Graph.  Raises on failure.

    ``user_id`` is the user's object id or UPN/email.  For a ``source: text`` topic,
    Graph requires ``webUrl`` to be a **Teams deep link** (Teams domain + ``/l/``); an
    arbitrary https URL is rejected.  So unless *web_url* is already such a deep link,
    we build a chat deep link to the recipient."""
    if not (web_url or '').startswith('https://teams.microsoft.com/l/'):
        web_url = f'https://teams.microsoft.com/l/chat/0/0?users={quote(user_id)}'
    payload = {
        'topic': {'source': 'text', 'value': topic, 'webUrl': web_url},
        'activityType': 'systemDefault',
        'previewText': {'content': text[:150]},
        'templateParameters': [{'name': 'systemDefaultText', 'value': text}],
    }
    r = _req.post(
        f'{GRAPH_BASE}/users/{user_id}/teamwork/sendActivityNotification',
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
        json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(graph_error(r))


# ── Bot Framework proactive messaging ───────────────────────────────────────
_BOT_LOGIN = ('https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token')
_BOT_SCOPE = 'https://api.botframework.com/.default'


def bot_token(tenant: str, app_id: str, app_password: str) -> str:
    """Acquire a Bot Connector access token (client-credentials).  Raises on failure.

    Single-tenant bots use their tenant; multi-tenant bots historically use
    ``botframework.com`` — pass whichever the Azure Bot is configured for."""
    r = _req.post(
        _BOT_LOGIN.format(tenant=tenant or 'botframework.com'),
        data={'grant_type': 'client_credentials', 'client_id': app_id,
              'client_secret': app_password, 'scope': _BOT_SCOPE},
        timeout=30)
    if not r.ok:
        raise RuntimeError(f'Bot token error: HTTP {r.status_code} {r.text[:200]}')
    return r.json()['access_token']


def send_bot_message(access_token: str, reference: dict, text: str) -> None:
    """Post a proactive message into an existing conversation via the Bot Connector.

    ``reference`` is a stored conversation reference (captured by the inbound
    endpoint) with at least ``service_url`` and ``conversation_id``.  Raises on failure."""
    service_url = (reference.get('service_url') or '').rstrip('/')
    conv_id = reference.get('conversation_id') or ''
    if not service_url or not conv_id:
        raise RuntimeError('Incomplete Teams conversation reference (no service_url/conversation_id)')
    from urllib.parse import quote
    r = _req.post(
        f'{service_url}/v3/conversations/{quote(conv_id, safe="")}/activities',
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
        json={'type': 'message', 'text': text}, timeout=30)
    if not r.ok:
        raise RuntimeError(f'Bot send error: HTTP {r.status_code} {r.text[:200]}')
