#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSRF guard for user-supplied URLs fetched server-side.

ServiceSentry is a monitoring tool, so requests to private/internal hosts
(RFC1918 10/8, 172.16/12, 192.168/16) are a *legitimate* use case and are NOT
blocked.  What we do block is what is never a legitimate monitoring target and
is a classic SSRF escalation vector:

* non-HTTP(S) schemes — ``file://``, ``ftp://``, ``data://``, ``gopher://`` …
  (e.g. ``file:///etc/passwd`` local file read)
* the link-local range 169.254.0.0/16, which includes the cloud
  instance-metadata endpoint 169.254.169.254 (IAM credential theft)
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def validate_external_url(url: str, *, allowed_schemes=('http', 'https')) -> str | None:
    """Validate a user-supplied URL for safe server-side fetching.

    Returns ``None`` if the URL is acceptable, or a short human-readable reason
    string if it must be rejected.
    """
    if not url or not isinstance(url, str):
        return 'empty URL'
    try:
        parsed = urlparse(url.strip())
    except (ValueError, TypeError):
        return 'malformed URL'

    scheme = (parsed.scheme or '').lower()
    if scheme not in allowed_schemes:
        return f'scheme {scheme or "(none)"!r} not allowed (use http/https)'

    host = parsed.hostname
    if not host:
        return 'missing host'

    # Resolve every address the host maps to and reject link-local / metadata.
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        # Can't resolve — let the actual request fail rather than guess.
        return None
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split('%')[0])  # strip scope id
        except ValueError:
            continue
        if ip.is_link_local:          # 169.254.0.0/16 + fe80::/10 (cloud metadata)
            return 'link-local / metadata address blocked'
    return None
