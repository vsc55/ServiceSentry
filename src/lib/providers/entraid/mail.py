#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — mail send via Graph ``sendMail`` (used by the M365 email
notifier).  Pure Graph call that takes an app-only access token."""

from __future__ import annotations

import requests as _req

from lib.providers.entraid.client import GRAPH_BASE, graph_error


def send_mail(access_token: str, from_email: str, message: dict) -> None:
    """Send *message* as *from_email* via Graph ``sendMail``.  Raises on failure."""
    r = _req.post(
        f'{GRAPH_BASE}/users/{from_email}/sendMail',
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
        json={'message': message, 'saveToSentItems': False}, timeout=30)
    if not r.ok:
        raise RuntimeError(graph_error(r))
