#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A QR code, from the standard library, because the alternative was worse.

Enrolling a second factor means getting a hundred-odd characters from this screen into a phone.
The base32 secret is always on the page and always will be — it is the half somebody can read
back and check — but nobody types it if there is a square to point a camera at, and a panel
that only offers the string is a panel whose MFA gets put off until next week.

There is no QR library in this project and adding one to draw a square is not a trade worth
making, so this is ISO/IEC 18004 in about two hundred lines: **byte mode, error correction
level L, versions 1 to 10**. That covers 213 bytes where an `otpauth://` link is about 140, and
the version is chosen from the length rather than fixed, so the smallest square that fits is
the one drawn.

**Nothing here is guessed.** The Reed–Solomon arithmetic is checked in the tests against the
codewords the specification publishes for its own worked example, the format-information bits
against the published table of thirty-two, and the finder, timing and alignment patterns
against the positions the standard fixes. What a test cannot do is hold a phone up to the
screen — so the enrolment flow never trusts this alone: the secret is printed beside it, and
the code the app produces has to verify before the factor is switched on.

Nothing from a user reaches the output. The SVG is built from integers — module coordinates —
and the only text input is the `otpauth:` URI this package assembles itself.
"""

from __future__ import annotations

# ── Capacity, per version, at error-correction level L ───────────────────────
#
# `(ec_per_block, ((block_count, data_per_block), …))`. The blocks are the awkward part of the
# format and the reason a version cannot be treated as one long string of codewords: from
# version 6 the data is split, each block gets its own error correction, and the two are then
# INTERLEAVED. Reading the table as one block produces a symbol that is structurally valid and
# decodes to rubbish, which is the failure that looks like a broken camera.
_EC_L: dict[int, tuple] = {
    1:  (7,  ((1, 19),)),
    2:  (10, ((1, 34),)),
    3:  (15, ((1, 55),)),
    4:  (20, ((1, 80),)),
    5:  (26, ((1, 108),)),
    6:  (18, ((2, 68),)),
    7:  (20, ((2, 78),)),
    8:  (24, ((2, 97),)),
    9:  (30, ((2, 116),)),
    10: (18, ((2, 68), (2, 69))),
}

# Where the alignment patterns go, per version — the row/column centres, every pairing of
# which carries one except the three corners already occupied by the finders.
_ALIGN: dict[int, tuple] = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30),
    6: (6, 34), 7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
}

# Error-correction level L as the format information encodes it (M=00, L=01, H=10, Q=11).
_EC_LEVEL_BITS = 0b01
# The mask the format information is XORed with, so a symbol of all-zero format bits is not a
# valid one — without it an unwritten symbol reads as a legitimate configuration.
_FORMAT_MASK = 0b101010000010010
_FORMAT_POLY = 0b10100110111        # BCH(15,5) generator
_VERSION_POLY = 0b1111100100101     # BCH(18,6) generator, versions 7+

_MAX_VERSION = max(_EC_L)


# ── GF(256) ──────────────────────────────────────────────────────────────────
# The field QR arithmetic lives in: byte values, addition is XOR, multiplication is a log
# table over the primitive polynomial x⁸+x⁴+x³+x²+1 (0x11D).

_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a: int, b: int) -> int:
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list:
    """The generator polynomial for *degree* error-correction codewords: ∏(x − α^i)."""
    poly = [1]
    for i in range(degree):
        poly.append(0)
        for j in range(len(poly) - 1, 0, -1):
            poly[j] = poly[j - 1] ^ _gf_mul(poly[j], _EXP[i])
        poly[0] = _gf_mul(poly[0], _EXP[i])
    return poly


def rs_ecc(data: bytes, degree: int) -> bytes:
    """The *degree* error-correction codewords for one block — polynomial long division.

    Public because it is the half of this file that is checkable against something outside it:
    the specification's worked example publishes both the data codewords and the ones this
    must answer for them.
    """
    gen = _rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(degree):
            rem[i] ^= _gf_mul(gen[degree - 1 - i], factor)
    return bytes(rem)


# ── Encoding ─────────────────────────────────────────────────────────────────

class _Bits:
    """A bit string being built. A list of 0/1 rather than an int: the payload is read back
    bit by bit in a fixed order, and the leading zeros an int would drop are data."""

    def __init__(self) -> None:
        self.bits: list = []

    def put(self, value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self) -> int:
        return len(self.bits)


def _char_count_bits(version: int) -> int:
    """Byte mode: 8 bits of length below version 10, 16 from there on."""
    return 8 if version < 10 else 16


def capacity(version: int) -> int:
    """How many payload bytes fit in *version* at level L."""
    _ec_per_block, groups = _EC_L[version]
    total = sum(count * size for count, size in groups)
    # Four bits of mode indicator plus the character count, rounded down to whole bytes.
    return total - 1 - (_char_count_bits(version) // 8)


def best_version(nbytes: int) -> int:
    """The smallest version that holds *nbytes*, or 0 when nothing here does.

    Zero rather than an exception: a link too long for a version 10 symbol means the caller
    shows the secret and no square, which is a page with one thing missing rather than a 500
    on the screen somebody is trying to enrol from.
    """
    for version in range(1, _MAX_VERSION + 1):
        if nbytes <= capacity(version):
            return version
    return 0


def data_codewords(payload: bytes, version: int) -> bytes:
    """Payload → the data codewords for *version*: mode, length, bytes, terminator, padding.

    Split out from the interleaving because it is the half with a published answer to compare
    against — everything after it is bookkeeping.
    """
    _ec_per_block, groups = _EC_L[version]
    data_total = sum(count * size for count, size in groups)

    bits = _Bits()
    bits.put(0b0100, 4)                                   # byte mode
    bits.put(len(payload), _char_count_bits(version))
    for byte in payload:
        bits.put(byte, 8)
    # Terminator: up to four zero bits, fewer when the capacity is nearly used.
    bits.put(0, min(4, data_total * 8 - len(bits)))
    bits.put(0, -len(bits) % 8)                           # pad to a byte boundary
    data = bytearray(int(''.join(str(b) for b in bits.bits[i:i + 8]), 2)
                     for i in range(0, len(bits), 8))
    # The two pad codewords the standard names, alternating, until the block is full.
    for i in range(data_total - len(data)):
        data.append(0xEC if i % 2 == 0 else 0x11)
    return bytes(data)


def _interleave(data: bytes, version: int) -> bytes:
    """The data codewords split into blocks, each with its own error correction, interleaved.

    The awkward part of the format and the reason a version cannot be treated as one long
    string: from version 6 the data is split, each block is protected on its own, and the two
    are then woven together. Read as one block it produces a symbol that is structurally valid
    and decodes to rubbish — the failure that looks like a broken camera.
    """
    ec_per_block, groups = _EC_L[version]
    blocks, eccs, pos = [], [], 0
    for count, size in groups:
        for _ in range(count):
            block = bytes(data[pos:pos + size])
            pos += size
            blocks.append(block)
            eccs.append(rs_ecc(block, ec_per_block))
    # Interleaved: the first codeword of every block, then the second of every block… and the
    # error correction after it, the same way. A burst of damage then falls across blocks
    # instead of destroying one.
    out = bytearray()
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_per_block):
        for ecc in eccs:
            out.append(ecc[i])
    return bytes(out)


# ── The symbol ───────────────────────────────────────────────────────────────

def _poly_degree(poly: int) -> int:
    return poly.bit_length() - 1


def _bch_remainder(value: int, poly: int, data_bits: int) -> int:
    """`value` shifted up by the generator's degree, reduced modulo *poly*."""
    degree = _poly_degree(poly)
    rem = value << degree
    for shift in range(data_bits - 1, -1, -1):
        if rem & (1 << (shift + degree)):
            rem ^= poly << shift
    return rem


def format_bits(mask: int) -> int:
    """The fifteen format-information bits for level L and *mask*, masked as the standard says."""
    value = (_EC_LEVEL_BITS << 3) | (mask & 0b111)
    return ((value << 10) | _bch_remainder(value, _FORMAT_POLY, 5)) ^ _FORMAT_MASK


def version_bits(version: int) -> int:
    """The eighteen version-information bits — present from version 7 only."""
    return (version << 12) | _bch_remainder(version, _VERSION_POLY, 6)


def _blank(size: int) -> tuple:
    return ([[False] * size for _ in range(size)],
            [[False] * size for _ in range(size)])   # modules, reserved


def _place_function_patterns(mod: list, res: list, version: int) -> None:
    size = len(mod)

    def square(top: int, left: int, dim: int, fn) -> None:
        for r in range(dim):
            for c in range(dim):
                rr, cc = top + r, left + c
                if 0 <= rr < size and 0 <= cc < size:
                    mod[rr][cc] = fn(r, c)
                    res[rr][cc] = True

    # Finder patterns and their separators, in the three corners that are not bottom-right.
    # A finder is the 7×7 ring, a gap, and the 3×3 core: dark on the border, dark in the
    # middle three by three, light in between.
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        square(top, left, 7,
               lambda r, c: r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
        # The one-module light separator around each finder.
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = top + r, left + c
                if 0 <= rr < size and 0 <= cc < size and not res[rr][cc]:
                    mod[rr][cc] = False
                    res[rr][cc] = True

    # Timing patterns: the alternating row and column that fix the module pitch.
    for i in range(size):
        for rr, cc in ((6, i), (i, 6)):
            if not res[rr][cc]:
                mod[rr][cc] = (i % 2 == 0)
                res[rr][cc] = True

    # Alignment patterns, at every pairing of the version's centres except the three that
    # would sit on a finder.
    centres = _ALIGN[version]
    for row in centres:
        for col in centres:
            if (row, col) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    mod[row + r][col + c] = max(abs(r), abs(c)) != 1
                    res[row + r][col + c] = True

    # The dark module: one fixed black square that is not part of anything else.
    mod[size - 8][8] = True
    res[size - 8][8] = True

    # Reserve the format information areas (written after the mask is chosen). Row 8 and
    # column 8 up to the ninth module, timing crossings included: those two carry timing and
    # are simply never written by `_write_format`, but they must not take data either.
    for i in range(9):
        res[8][i] = True
        res[i][8] = True
    for i in range(8):
        res[8][size - 1 - i] = True
        res[size - 1 - i][8] = True

    # And the version information blocks, from version 7.
    if version >= 7:
        for i in range(18):
            r, c = i // 3, i % 3
            res[size - 11 + c][r] = True
            res[r][size - 11 + c] = True


def _write_version(mod: list, version: int) -> None:
    if version < 7:
        return
    size = len(mod)
    bits = version_bits(version)
    for i in range(18):
        bit = bool((bits >> i) & 1)
        r, c = i // 3, i % 3
        mod[size - 11 + c][r] = bit
        mod[r][size - 11 + c] = bit


def _write_format(mod: list, mask: int) -> None:
    size = len(mod)
    bits = format_bits(mask)

    def bit(i: int) -> bool:
        return bool((bits >> i) & 1)

    # The copy around the top-left finder, split by the timing row and column — which is why
    # this is written out rather than looped: bits 0–5 run along row 8, then the sequence
    # steps over column 6 and turns the corner up column 8.
    for i in range(6):
        mod[8][i] = bit(i)
    mod[8][7] = bit(6)
    mod[8][8] = bit(7)
    mod[7][8] = bit(8)
    for i in range(9, 15):
        mod[14 - i][8] = bit(i)
    # The second copy, so the format survives losing a corner.
    for i in range(8):
        mod[8][size - 1 - i] = bit(i)
    for i in range(8, 15):
        mod[size - 15 + i][8] = bit(i)


def _mask_at(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _place_data(mod: list, res: list, data: bytes, mask: int) -> None:
    """The payload, up and down two columns at a time from the bottom-right, masked as it goes."""
    size = len(mod)
    bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:            # the timing column is not a data column
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if res[row][c]:
                    continue
                bit = bool(bits[idx]) if idx < len(bits) else False
                idx += 1
                mod[row][c] = bit != _mask_at(mask, row, c)
        col -= 2
        upward = not upward


def _penalty(mod: list) -> int:
    """How badly a masked symbol reads, by the four rules the standard defines.

    The mask is not a preference: a symbol with a large blank field, or one carrying something
    that looks like a finder pattern, is one a camera locks onto wrongly. The lowest score wins.
    """
    size = len(mod)
    score = 0

    # Rule 1 — runs of five or more of the same colour, in both directions.
    for line in [mod[r] for r in range(size)] + [[mod[r][c] for r in range(size)]
                                                 for c in range(size)]:
        run, prev = 1, line[0]
        for value in line[1:]:
            if value == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, value
        if run >= 5:
            score += 3 + (run - 5)

    # Rule 2 — every 2×2 block of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if mod[r][c] == mod[r][c + 1] == mod[r + 1][c] == mod[r + 1][c + 1]:
                score += 3

    # Rule 3 — the finder-like 1:1:3:1:1 sequence with four light modules beside it.
    pattern_a = [True, False, True, True, True, False, True, False, False, False, False]
    pattern_b = list(reversed(pattern_a))
    for line in [mod[r] for r in range(size)] + [[mod[r][c] for r in range(size)]
                                                 for c in range(size)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == pattern_a or window == pattern_b:
                score += 40

    # Rule 4 — how far the proportion of dark modules is from half.
    dark = sum(1 for row in mod for value in row if value)
    score += 10 * (abs(dark * 100 // (size * size) - 50) // 5)
    return score


def matrix(text: str) -> list:
    """*text* as a list of rows of booleans — True is a dark module.

    Empty when it does not fit in a version 10 symbol at level L: the caller shows the secret
    without a square, rather than the page failing.
    """
    payload = str(text or '').encode('utf-8')
    version = best_version(len(payload))
    if not version:
        return []
    size = version * 4 + 17
    data = _interleave(data_codewords(payload, version), version)

    best, best_score = None, None
    for mask in range(8):
        mod, res = _blank(size)
        _place_function_patterns(mod, res, version)
        _write_version(mod, version)
        _place_data(mod, res, data, mask)
        _write_format(mod, mask)
        score = _penalty(mod)
        if best_score is None or score < best_score:
            best, best_score = mod, score
    return best


def svg(text: str, *, quiet: int = 4) -> str:
    """The symbol as an SVG element, or `''` when there is nothing to draw.

    Built from integers only — the coordinates of dark modules. No part of *text* reaches the
    output, which is what makes it safe to drop into the page as markup.

    `viewBox` in module units with no width or height, so the page decides how big it is with
    CSS; a QR drawn at a size the server chose is one that does not fit somebody's phone at
    arm's length. The quiet zone is four modules because the standard says four — a symbol
    flush against a card border is the other reason a camera does not lock on.
    """
    mod = matrix(text)
    if not mod:
        return ''
    size = len(mod)
    total = size + quiet * 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
             f'shape-rendering="crispEdges" role="img">',
             f'<rect width="{total}" height="{total}" fill="#fff"/>']
    # One path of rectangles rather than one element per module: a version 10 symbol is 3,249
    # of them, and that many DOM nodes is a page that stutters while it draws.
    runs = []
    for r, row in enumerate(mod):
        c = 0
        while c < size:
            if row[c]:
                start = c
                while c < size and row[c]:
                    c += 1
                runs.append(f'M{start + quiet} {r + quiet}h{c - start}v1h-{c - start}z')
            else:
                c += 1
    parts.append(f'<path fill="#000" d="{"".join(runs)}"/>')
    parts.append('</svg>')
    return ''.join(parts)
