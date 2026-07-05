#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSRF protection — double-submit token.

Stateless helpers over Flask's ``session``/``request``: a per-session random
token is issued (and echoed into pages), and every state-changing request must
carry it in the ``X-CSRF-Token`` header (JSON APIs) or the ``csrf_token`` form
field (form posts). Compared in constant time. The web layer owns the wiring
(``before_request`` + injecting the token into templates); this module owns the
policy.
"""

from __future__ import annotations

import hmac
import secrets

SESSION_KEY = '_csrf'
HEADER_NAME = 'X-CSRF-Token'
FORM_FIELD  = 'csrf_token'
UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


def issue_token(session) -> str:
    """Return the session's CSRF token, creating it on first use."""
    tok = session.get(SESSION_KEY)
    if not tok:
        tok = session[SESSION_KEY] = secrets.token_hex(32)
    return tok


def needs_check(method: str, path: str, exempt_prefixes) -> bool:
    """True when a request must be CSRF-validated: a state-changing method on a
    path not covered by an exemption (e.g. token-authed SCIM, IdP callbacks)."""
    if method not in UNSAFE_METHODS:
        return False
    return not any(path.startswith(p) for p in exempt_prefixes)


def is_valid(request, session) -> bool:
    """Constant-time check of the submitted token against the session token."""
    expected = session.get(SESSION_KEY, '')
    sent = request.headers.get(HEADER_NAME) or request.form.get(FORM_FIELD, '')
    return bool(expected) and bool(sent) and hmac.compare_digest(str(sent), str(expected))
