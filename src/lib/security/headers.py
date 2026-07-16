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
_CSP_HEAD = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; "
    "connect-src 'self'; "
)
_CSP_TAIL = "base-uri 'self'; form-action 'self'; object-src 'none'"
# NOTE: this module stays provider-agnostic. Integration-specific frame-ancestors (e.g. the
# Microsoft Teams/Outlook hosts) are declared by the provider via wa._register_embed_origins()
# and discovered at startup — not hardcoded here.


def build_csp(frame_ancestors=None) -> str:
    """Build the CSP. ``frame_ancestors`` (a list of origins) opens ``frame-ancestors``
    to ``'self'`` + those origins; empty/None keeps framing fully blocked (``'none'``)."""
    if frame_ancestors:
        fa = "frame-ancestors 'self' " + ' '.join(frame_ancestors)
    else:
        fa = "frame-ancestors 'none'"
    return f"{_CSP_HEAD}{fa}; {_CSP_TAIL}"


_CSP = build_csp()   # default (framing blocked) — module constant; imported by overview2

SECURITY_HEADERS: dict[str, str] = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options':        'DENY',
    'Referrer-Policy':        'strict-origin-when-cross-origin',
    'Permissions-Policy':     'geolocation=(), microphone=(), camera=(), payment=()',
    'Content-Security-Policy': _CSP,
    # HSTS is intentionally NOT here — it must only be sent over HTTPS and is added
    # by the TLS proxy. Duplicating it at the app layer risks conflicting max-ages.
}


def apply_security_headers(response, *, frame_ancestors=None):
    """Add the defense-in-depth security headers to *response* (in place).

    Uses ``setdefault`` so a value already set upstream (proxy) wins.  When
    *frame_ancestors* is a non-empty list, the app may be iframed by those origins:
    the default CSP's ``frame-ancestors`` is opened to them and ``X-Frame-Options``
    (which cannot express an allowlist and would still block) is dropped.  A route
    that set its own CSP (e.g. /overview2) is left untouched."""
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if frame_ancestors and response.headers.get('Content-Security-Policy') == _CSP:
        response.headers['Content-Security-Policy'] = build_csp(frame_ancestors)
    # Whenever the effective CSP allows framing (the global allowlist above OR a route
    # that set its own frame-ancestors, e.g. the Teams tab), X-Frame-Options — which
    # can only say DENY/SAMEORIGIN — must not be left blocking it.
    csp = response.headers.get('Content-Security-Policy', '')
    if 'frame-ancestors' in csp and "frame-ancestors 'none'" not in csp:
        response.headers.pop('X-Frame-Options', None)
    return response
