#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What an archive IS: where it lives, how it is laid out, and how a value goes in and out.

The bottom of the domain. Everything else here — making a copy, putting one back, checking
one, protecting one — starts by turning a name into a path and ends by writing or reading a
member, so those two answers live in one place and are given once.

Nothing in this module knows what a backup CONTAINS. That is `parts.py`, which is the
vocabulary; this is the container.

Imports nothing from its siblings, deliberately: it is what they all import, and a dependency
pointing back up from here would be a cycle through the one module that cannot afford one.
"""

from __future__ import annotations

import base64
import datetime as _dt
import decimal
import hashlib
import io
import json
import os
import re
import zipfile

from lib.core.object_base import ObjectBase
from lib.debug.debug_level import DebugLevel
from lib.security.secret_manager import ENC_PREFIX


def _log(message: str, level: DebugLevel = DebugLevel.info) -> None:
    """Say what is happening, on the panel's own log.

    A copy and a restore are the two operations here that take minutes, run on a thread and
    rewrite the install — and until this existed they went past in total silence, so a screen
    that failed to open its dialog left nothing anywhere to say whether anything had happened
    at all. Through `ObjectBase.debug` like the rest of the panel, so `global|log_level`
    governs it and there is no second logging path to configure.
    """
    ObjectBase.debug.print(message, level)


# Format version of the archive itself. Bumped when the LAYOUT changes in a way an older
# reader cannot make sense of — not when a part is added, which older readers simply do not
# ask for. `restore` refuses a major it does not know rather than half-applying it.
FORMAT = 1

MANIFEST_NAME = 'manifest.json'
DB_DIR = 'db'
FILES_DIR = 'files'


# A backup name is used as a FILENAME and echoed back in URLs. Anything outside this cannot be
# one, which is what keeps `..` and separators out of every path built from it.
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


# Where a module's files go inside the archive. Derived from the part id on both sides rather
# than recorded per copy, so a restore and a copy cannot disagree about where the files are.
PARTS_PREFIX = f'{FILES_DIR}/parts'


def valid_name(name: str) -> bool:
    """Is *name* usable as a backup's file name?"""
    return bool(_NAME_RE.match(str(name or '')))


def backups_dir(var_dir: str, configured: str = '') -> str:
    """Where copies live: the configured directory, or ``<var_dir>/backups``.

    A parameter and not a constant because a copy on the same disk as the data it copies
    survives a mistake and nothing else. Resolved on every call, so moving it takes effect on
    the next copy rather than on the next restart — an operator who changed it mid-day would
    otherwise write to the old path and go looking in the new one.
    """
    configured = str(configured or '').strip()
    return configured or os.path.join(str(var_dir or ''), 'backups')


def archive_path(var_dir: str, name: str, configured: str = '') -> str:
    """The archive for *name*, or '' when the name could not be one.

    Built from a validated name rather than joined and checked afterwards: a name that cannot
    contain a separator cannot walk out of the directory, and there is no second path to keep
    the check in step with.
    """
    if not valid_name(name):
        return ''
    return os.path.join(backups_dir(var_dir, configured), f'{name}.zip')


# ── Secrets ──────────────────────────────────────────────────────────────────

def _strip_secrets(value):
    """Blank every encrypted value in *value*, at any depth.

    "Stored encrypted" IS the marker, and the only one worth using here. The alternative — a
    list of secret field names — exists (``ENCRYPT_KEYS``) but is only half the truth: watchful
    modules declare their own secret fields in their schemas, so a registry-driven pass would
    skip a module's API token and produce a backup that says it holds no secrets while holding
    one. Anything the panel wrote with the `enc:` prefix is a secret, whoever declared it.
    """
    if isinstance(value, str):
        return '' if value.startswith(ENC_PREFIX) else value
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


def clean_cell(value, keep_secrets: bool):
    """One column value, ready for JSON — and stripped when secrets are being left out.

    A column holding JSON is walked as JSON: the credential store keeps its fields in a `data`
    blob, so the secret is a value *inside* the string rather than the string itself. Text that
    does not parse is left exactly as it was; guessing at it would corrupt the row.
    """
    if isinstance(value, (bytes, bytearray)):
        # Binary survives the round trip through base64 rather than a lossy decode.
        return {'__b64__': base64.b64encode(bytes(value)).decode('ascii')}
    # What the server drivers hand back for DATETIME/DATE/TIME/DECIMAL: SQLite gives text and
    # numbers, so nobody saw that `json.dumps` refuses these — and on MySQL and PostgreSQL every
    # copy holding syslog (`SystemEvents.ReceivedAt`) came out `partial`. As the text both
    # engines take back on restore.
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat(sep=' ') if isinstance(value, _dt.datetime) else value.isoformat()
    if isinstance(value, _dt.timedelta):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if keep_secrets or not isinstance(value, str):
        return value
    if value.startswith(ENC_PREFIX):
        return ''
    # `"…"` too: the config table keeps each value as JSON, so a secret setting is the JSON
    # STRING `"enc:…"` — quoted, so the prefix test above never saw it, and a copy «without
    # secrets» carried every SMTP password and client secret of the configuration.
    if value[:1] in ('{', '[', '"'):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        stripped = _strip_secrets(parsed)
        # Untouched when there was nothing to strip: re-serialising would still change the
        # bytes (key spacing, escaped accents) of every JSON cell in the copy.
        return value if stripped == parsed else json.dumps(stripped, ensure_ascii=False)
    return value


def restore_cell(value):
    """Undo :func:`clean_cell` for a value on its way back into a row."""
    if isinstance(value, dict) and set(value) == {'__b64__'}:
        try:
            return base64.b64decode(value['__b64__'])
        except (ValueError, TypeError):
            return b''
    return value


# ── A table's member, streamed ───────────────────────────────────────────────
#
# Still ONE JSON document per table, `{"columns": [...], "rows": [[...], ...]}`, so every
# reader that ever loaded it whole still can (an older install restoring a newer copy, a
# person with `unzip -p … | jq`). What changed is the layout inside it: the header on the
# first line and then ONE ROW PER LINE, which is what lets both sides stream it. The copy
# wrote `json.dumps` of the whole table and the restore `json.loads` of the whole member — a
# history of 27 million measurements is gigabytes of Python objects twice over, and the
# process died of it (OOM) before the archive was closed. JSON never puts a raw newline
# inside a value (`\n` is escaped), so a line is always exactly one row.

_ROWS_OPEN = '"rows":['


def write_table_member(zf: zipfile.ZipFile, member: str, columns, batches) -> tuple:
    """Write one table as *member*, batch by batch. ``(rows written, sha256 of the member)``.

    *batches* yields lists of rows already made JSON-safe (:func:`clean_cell`). Nothing is
    held beyond one batch: the member is written through a zip stream and hashed as it goes.
    """
    digest = hashlib.sha256()
    count = 0
    dumps = json.JSONEncoder(ensure_ascii=False, separators=(',', ':')).encode

    with zf.open(member, 'w', force_zip64=True) as out:
        def put(text: str) -> None:
            data = text.encode('utf-8')
            digest.update(data)
            out.write(data)

        put('{"columns":' + dumps(list(columns)) + ',' + _ROWS_OPEN)
        for batch in batches:
            chunk = []
            for row in batch:
                chunk.append(('\n' if count == 0 else ',\n') + dumps(row))
                count += 1
            if chunk:
                put(''.join(chunk))
        put('\n]}')
    return count, digest.hexdigest()


def iter_table_member(zf: zipfile.ZipFile, member: str, size: int = 2000):
    """``(columns, batches)`` of a table member — *batches* yields lists of up to *size* rows.

    Reads both layouts: the streamed one (header line, a row per line) a row at a time, and
    the single-line document every copy before it was written as, which can only be read
    whole — that is what those copies are, and they must keep restoring.
    """
    fh = io.TextIOWrapper(zf.open(member), encoding='utf-8', newline='\n')
    first = fh.readline()
    head = first.rstrip('\n')
    if head.endswith(_ROWS_OPEN):
        columns = json.loads(head + ']}').get('columns') or []

        def batches():
            try:
                chunk = []
                for line in fh:
                    line = line.strip()
                    if not line or line == ']}':
                        continue
                    chunk.append(json.loads(line[:-1] if line.endswith(',') else line))
                    if len(chunk) >= size:
                        yield chunk
                        chunk = []
                if chunk:
                    yield chunk
            finally:
                fh.close()
        return columns, batches()

    # The old layout: the whole document on that one line (or more, pretty-printed by hand).
    rest = fh.read()
    fh.close()
    payload = json.loads(first + rest)
    rows = payload.get('rows') or []

    def old_batches():
        for i in range(0, len(rows), size):
            yield rows[i:i + size]
    return payload.get('columns') or [], old_batches()


def member_tables(names) -> list:
    """The table names an archive's member list holds, sorted.

    ``db/devices.json`` → ``devices``. Here and not in `parts.py` because it is the LAYOUT
    talking: which directory the tables go in and what the members are called is this
    module's rule, and grouping them into parts is the other one's. Neither has to know both.
    """
    return sorted(n[len(DB_DIR) + 1:-len('.json')] for n in names
                  if n.startswith(f'{DB_DIR}/') and n.endswith('.json'))


def read_manifest(path: str) -> dict | None:
    """The manifest inside an archive, or None when it is not one of ours."""
    try:
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def file_sha256(path: str) -> str:
    """The digest of a file, read in chunks — an archive can be gigabytes."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()
