#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook notification module for WebAdmin.

Sends an HTTP request (POST, PUT, or GET) to a configured URL when a service
state changes. Supports custom headers, a body template with placeholder
substitution, and optional HMAC-SHA256 request signing (GitHub-style).
"""

from __future__ import annotations

import hashlib
import hmac
import json as _json

from lib.config.spec import cfg_get
from lib.debug import DebugLevel
from lib.core.object_base import ObjectBase

try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

_DEFAULT_BODY_TPL = (
    '{"kind":"{kind}","module":"{module}","item":"{item}",'
    '"status":"{status}","message":"{message}","timestamp":"{timestamp}"}'
)

_PLACEHOLDERS = ('kind', 'module', 'item', 'status', 'message', 'timestamp')


def send_all(wa, kind: str = 'info', module: str = '', item: str = '',
             status: str = '', message: str = '',
             timestamp: str = '', cfg: dict | None = None,
             webhook_ids=None) -> tuple[bool, str]:
    """Send to all enabled webhooks. Returns (all_ok, summary).

    Webhooks live in their own DB-backed store (``wa._load_webhooks``); *cfg* is
    accepted only for backwards compatibility and ignored for the webhook list.
    When *webhook_ids* is a non-empty iterable, only those destinations (matched
    by id) are notified; otherwise every enabled webhook is.
    """
    webhooks = [w for w in (wa._load_webhooks() or [])
                if w.get('enabled') and (w.get('url') or '').strip()]
    if webhook_ids:
        wanted = {str(i) for i in webhook_ids}
        webhooks = [w for w in webhooks if str(w.get('id') or w.get('uid') or '') in wanted]
        if not webhooks:
            return False, 'No matching enabled webhooks selected'
    if not webhooks:
        return False, 'No enabled webhooks configured'
    results = []
    for wh in webhooks:
        ok, msg = _dispatch(wh, kind=kind, module=module, item=item,
                            status=status, message=message, timestamp=timestamp)
        results.append((ok, msg, wh.get('name') or wh.get('id', '?')))
    all_ok = all(r[0] for r in results)
    summary = '; '.join(f"{r[2]}: {r[1]}" for r in results)
    return all_ok, summary


def _dispatch(cfg: dict, *, kind: str = 'test', module: str = '',
              item: str = '', status: str = '', message: str = '',
              timestamp: str = '') -> tuple[bool, str]:
    """Send webhook with the given payload. Returns (ok, message)."""
    if not cfg.get('enabled'):
        return False, 'Webhook notifications are not enabled'
    if not _HAS_REQUESTS:
        return False, 'Webhook requires the requests package'
    url = (cfg.get('url') or '').strip()
    if not url:
        return False, 'Webhook URL is not configured'

    method         = cfg_get(cfg, 'webhooks|method', falsy=True).upper()
    timeout        = cfg_get(cfg, 'webhooks|timeout', falsy=True)
    ObjectBase.debug.print(
        f"> Webhook >> sending {cfg.get('name') or cfg.get('id', '?')!r} {method} "
        f"(timeout={timeout}s)", DebugLevel.debug)
    secret         = (cfg.get('secret') or '').strip()
    secret_header  = cfg_get(cfg, 'webhooks|secret_header', falsy=True).strip()

    vals = {
        'kind': kind, 'module': module, 'item': item,
        'status': status, 'message': message, 'timestamp': timestamp,
    }

    # Parse optional extra headers
    extra_headers: dict[str, str] = {}
    raw_headers = (cfg.get('headers') or '').strip()
    if raw_headers:
        try:
            parsed = _json.loads(raw_headers)
            if isinstance(parsed, dict):
                extra_headers = {str(k): str(v) for k, v in parsed.items()}
        except _json.JSONDecodeError:
            return False, 'Webhook headers field is not valid JSON'

    try:
        if method == 'GET':
            req_url = url
            for k, v in vals.items():
                req_url = req_url.replace(f'{{{k}}}', v)
            resp = _req.get(req_url, headers=extra_headers or None, timeout=timeout)
        else:
            tpl = (cfg.get('body_template') or '').strip() or _DEFAULT_BODY_TPL
            body = tpl
            for k, v in vals.items():
                body = body.replace(f'{{{k}}}', v)
            body_bytes = body.encode('utf-8')

            headers = {'Content-Type': 'application/json'}
            headers.update(extra_headers)

            if secret:
                sig = hmac.new(
                    secret.encode('utf-8'), body_bytes, hashlib.sha256,
                ).hexdigest()
                headers[secret_header] = f'sha256={sig}'

            req_fn = _req.put if method == 'PUT' else _req.post
            resp = req_fn(url, data=body_bytes, headers=headers, timeout=timeout)

        if 200 <= resp.status_code < 300:
            return True, f'Webhook delivered (HTTP {resp.status_code})'
        return False, f'Webhook failed: HTTP {resp.status_code}'
    except Exception as exc:
        return False, str(exc)
