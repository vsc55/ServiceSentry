#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render ServiceSentry's shield-check mark to a multi-size .ico.

Run once; the .ico is committed. No image library involved: a PNG is a handful of
zlib-compressed scanlines and an .ico is a directory of PNGs, so both are written by hand
rather than adding a dependency for a file that changes approximately never.

The shape is defined analytically and supersampled 4x, so every size is rendered from the
geometry instead of downscaling one bitmap — a 16x16 downscale of a 48x48 shield loses the
check mark to blur, which is the size that actually appears in a browser tab.
"""

import math
import os
import struct
import zlib

SHIELD = (13, 110, 253)      # Bootstrap primary — the panel's own accent
CHECK = (255, 255, 255)

# Geometry in 0..1 space (y grows downward), matching the bi-shield-check silhouette.
TOP, WAIST, TIP = 0.10, 0.56, 0.94
HALF_W, CORNER = 0.33, 0.07
STROKE = 0.085
CHECK_PTS = ((0.31, 0.52), (0.44, 0.65), (0.71, 0.35))


def _in_shield(x: float, y: float) -> bool:
    if y < TOP or y > TIP:
        return False
    if y <= WAIST:
        hw = HALF_W
        # Round the two top corners so the mark does not read as a box at 16px.
        if y < TOP + CORNER:
            dx = abs(x - 0.5) - (HALF_W - CORNER)
            if dx > 0:
                dy = (TOP + CORNER) - y
                if dx * dx + dy * dy > CORNER * CORNER:
                    return False
    else:
        # Elliptical taper from the waist to a point at the tip.
        t = (y - WAIST) / (TIP - WAIST)
        hw = HALF_W * math.sqrt(max(0.0, 1.0 - t * t))
    return abs(x - 0.5) <= hw


def _dist_to_seg(px, py, ax, ay, bx, by) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return math.hypot(dx, dy)


def _on_check(x: float, y: float) -> bool:
    half = STROKE / 2
    for i in range(len(CHECK_PTS) - 1):
        (ax, ay), (bx, by) = CHECK_PTS[i], CHECK_PTS[i + 1]
        if _dist_to_seg(x, y, ax, ay, bx, by) <= half:
            return True
    return False


def _render(size: int, ss: int = 4) -> bytes:
    """RGBA rows for one size, supersampled `ss`x per axis."""
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / size
                    y = (py + (sy + 0.5) / ss) / size
                    if not _in_shield(x, y):
                        continue
                    col = CHECK if _on_check(x, y) else SHIELD
                    r += col[0]
                    g += col[1]
                    b += col[2]
                    a += 255
            n = ss * ss
            if a:
                # Un-premultiply: colour is the average of the covered samples only, so a
                # partly-covered edge pixel keeps the shape's colour and varies in alpha.
                cov = a // 255
                row += bytes((r // cov, g // cov, b // cov, a // n))
            else:
                row += b'\x00\x00\x00\x00'
        rows.append(bytes(row))
    return rows


def _png(size: int, rows) -> bytes:
    raw = b''.join(b'\x00' + r for r in rows)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


def build_ico(sizes=(16, 32, 48)) -> bytes:
    """A multi-size .ico: a directory of PNGs, one rendered per size.

    Every modern browser reads PNG-in-ICO, and rendering each size from the geometry beats
    downscaling one bitmap — at 16px, which is the size a browser tab actually shows, a
    downscaled check mark turns to mush.
    """
    images = [_png(s, _render(s)) for s in sizes]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b'', b''
    for size, blob in zip(sizes, images):
        entries += struct.pack('<BBBBHHII', size if size < 256 else 0,
                               size if size < 256 else 0, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        blobs += blob
    return header + entries + blobs


ICO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'lib', 'web_admin', 'static', 'img', 'favicon.ico')

if __name__ == '__main__':
    data = build_ico()
    with open(ICO_PATH, 'wb') as fh:
        fh.write(data)
    print(f'{ICO_PATH}: {len(data)} bytes')
