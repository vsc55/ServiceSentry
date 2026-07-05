#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP response security headers (defense-in-depth).

A single source for the browser-hardening headers the app emits on every
response.  Applied with ``setdefault`` so a TLS-terminating proxy that already
sets a header (e.g. HSTS) is never overridden.
"""

from __future__ import annotations

# Content-Security-Policy: keeps `'unsafe-inline'` for script/style (the UI relies
# on inline handlers/styles) but blocks framing (clickjacking), plugins, and
# cross-origin form/base hijacking. Everything else is same-origin.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'; object-src 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options':        'DENY',
    'Referrer-Policy':        'strict-origin-when-cross-origin',
    'Permissions-Policy':     'geolocation=(), microphone=(), camera=(), payment=()',
    'Content-Security-Policy': _CSP,
    # HSTS is intentionally NOT here — it must only be sent over HTTPS and is added
    # by the TLS proxy. Duplicating it at the app layer risks conflicting max-ages.
}


def apply_security_headers(response):
    """Add the defense-in-depth security headers to *response* (in place).

    Uses ``setdefault`` so a value already set upstream (proxy) wins. Returns the
    same response for convenient chaining in an ``after_request`` hook."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response
