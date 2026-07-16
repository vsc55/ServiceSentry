#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a Microsoft Teams *app package* (manifest.json + icons, zipped).

Activity-feed notifications (`sendActivityNotification`) require a Teams app — tied
to the Entra app registration via ``webApplicationInfo.id`` — to be installed for the
target user.  The Entra "Register in Azure" wizard only creates the *app registration*;
this builds the matching Teams app package the admin uploads to the org catalog (Teams
admin center) or sideloads, then installs for the recipients.

Pure-stdlib: a tiny PNG encoder (``zlib``) draws the two required icons, so there is no
image-library dependency.
"""

from __future__ import annotations

import io
import json
import struct
import zlib

_ACCENT = (0x4B, 0x53, 0xBC)          # Teams-purple, matches the config card accent


def _png(width: int, height: int, pixel) -> bytes:
    """Encode an 8-bit RGBA PNG. ``pixel(x, y)`` returns an (r, g, b, a) tuple."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)                 # filter type 0 (None) per scanline
        for x in range(width):
            raw += bytes(pixel(x, y))

    def _chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + typ + data
                + struct.pack('>I', zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)   # 8-bit, colour type 6 (RGBA)
    return (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + _chunk(b'IEND', b''))


def _color_icon() -> bytes:
    """192×192 full-colour icon: solid accent with a white rounded square mark."""
    def px(x, y):
        # a centred white square with a margin → simple, recognisable, valid
        if 56 <= x < 136 and 56 <= y < 136:
            return (255, 255, 255, 255)
        return (*_ACCENT, 255)
    return _png(192, 192, px)


def _outline_icon() -> bytes:
    """32×32 outline icon: transparent background, white glyph (Teams tints it)."""
    def px(x, y):
        if 6 <= x < 26 and 6 <= y < 26:
            return (255, 255, 255, 255)
        return (0, 0, 0, 0)
    return _png(32, 32, px)


def build_manifest(client_id: str, *, public_url: str = '', app_name: str = 'ServiceSentry') -> dict:
    """The Teams app manifest wired to the Entra app *client_id*.

    Includes a **personal static tab**: an activity-feed-only app (just
    ``webApplicationInfo``) has no installable surface, so Teams shows it as "not
    available" and the admin cannot pre-install it.  A personal tab gives it a
    user-scope surface, making it installable (and pre-installable).  Tab content
    URLs must be https, so the server's public URL is coerced to https."""
    pub = (public_url or '').strip()
    if pub and not pub.startswith('https://'):
        pub = 'https://' + pub.split('://', 1)[-1]     # tabs require an https contentUrl
    tab_url = pub or 'https://teams.microsoft.com'
    valid_domains = []
    host = tab_url.split('://', 1)[-1].split('/', 1)[0]
    if host and host != 'teams.microsoft.com':
        valid_domains.append(host)
    return {
        '$schema': 'https://developer.microsoft.com/en-us/json-schemas/teams/v1.16/MicrosoftTeams.schema.json',
        'manifestVersion': '1.16',
        'version': '1.0.3',
        # The Teams app id must be a GUID; reuse the Entra client id (a GUID) so it is stable.
        'id': client_id,
        'packageName': 'com.servicesentry.notifications',
        'developer': {
            'name': 'ServiceSentry',
            'websiteUrl': tab_url,
            'privacyUrl': tab_url,
            'termsOfUseUrl': tab_url,
        },
        'name': {'short': app_name[:30] or 'ServiceSentry',
                 'full': f'{app_name} Notifications'[:100]},
        'description': {'short': 'ServiceSentry monitoring alerts',
                        'full': 'Receive ServiceSentry monitoring alerts as Teams activity-feed notifications.'},
        'icons': {'color': 'color.png', 'outline': 'outline.png'},
        'accentColor': '#4B53BC',
        'defaultInstallScope': 'personal',
        # A personal tab is the installable surface (without it Teams reports the app
        # as "not available" and it cannot be installed for users).
        'staticTabs': [{
            'entityId': 'servicesentry-home',
            'name': (app_name[:16] or 'ServiceSentry'),
            # The tab signs in via Teams SSO (Teams JS SDK) at /auth/msteams/tab; websiteUrl
            # opens the full panel in a normal browser (where a redirect login works).
            'contentUrl': tab_url.rstrip('/') + '/auth/msteams/tab',
            'websiteUrl': tab_url,
            'scopes': ['personal'],
        }],
        # This ties the Teams app to the Entra app registration so it may send
        # activity notifications on its behalf (TeamsActivity.Send).
        'webApplicationInfo': {'id': client_id, 'resource': f'api://{client_id}'},
        'validDomains': valid_domains,
    }


def build_package(client_id: str, *, public_url: str = '', app_name: str = 'ServiceSentry') -> bytes:
    """Return a zipped Teams app package (manifest.json + color.png + outline.png)."""
    import zipfile  # noqa: PLC0415
    manifest = build_manifest(client_id, public_url=public_url, app_name=app_name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr('color.png', _color_icon())
        zf.writestr('outline.png', _outline_icon())
    return buf.getvalue()
