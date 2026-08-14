#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The diagnostics payload as a document to send: text, JSON or XML.

Extracted from :mod:`lib.core.diagnostics.routes`, which had become three serialisers with a
route on top. Pure functions of the payload dict — no Flask, no `wa`, no collectors — so the
formats are testable without an app, which matters because what breaks in a serialiser is the
shape of the output and nothing else.

**One set of collectors, three renderings.** A format that gathered its own data would be a
second answer to the same question, and two reports of the same install disagreeing is exactly
the thing a diagnostics report exists to rule out.

Text is the default elsewhere because the destination is usually a comment box; JSON and XML
are for the other destination, an asset or ticketing system that ingests one of them, where the
alternative is somebody writing a parser for prose.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from lib import APP_NAME

# `(mimetype, extension)` per format. The fallback is TEXT and not an error: this is reached
# from a link somebody clicks, and refusing to produce a report over a query string is refusing
# at the moment they are least able to care.
FORMATS: dict = {
    'txt':  ('text/plain', 'txt'),
    'json': ('application/json', 'json'),
    'xml':  ('application/xml', 'xml'),
}
DEFAULT = 'txt'


def render(data: dict, fmt: str, stamp: str) -> tuple:
    """`(body, mimetype, extension)` for *data* in *fmt*, falling back to text."""
    key = str(fmt or '').lower()
    if key not in FORMATS:
        key = DEFAULT
    body = {'txt': as_text, 'json': as_json, 'xml': as_xml}[key](data, stamp)
    return (body,) + FORMATS[key]


def as_json(data: dict, stamp: str) -> str:
    """Indented, not compact: it is read by a person before it is fed to anything."""
    return json.dumps({'generated': stamp, **data}, ensure_ascii=False, indent=2)


def as_text(data: dict, stamp: str) -> str:
    lines = [f'{APP_NAME} diagnostics — {stamp}', '']
    for title, block in (('Runtime', data['runtime']), ('System', data['system']),
                         ('Network', data.get('network') or {}),
                         ('Database', data['database'])):
        lines.append(f'[{title}]')
        lines += [f'  {k} = {v}' for k, v in block.items()]
        lines.append('')
    lines.append('[Storage]')
    lines += [f'  {r["key"]} = {r["path"]} (exists={r["exists"]} '
              f'writable={r["writable"]} free={r["free_bytes"]})' for r in data['storage']]
    lines.append('')
    lines.append('[Optional features]')
    lines += [f'  {f["module"]} = ' + ('yes ' + f['version'] if f['available'] else 'no')
              for f in data['features']]
    lines.append('')
    deps = data['dependencies']
    lines.append(f'[Dependencies] total={len(deps["rows"])} missing={deps["missing"]} '
                 f'mismatch={deps["mismatch"]}')
    # EVERY row, differences first (the collector sorts them that way). The SCREEN folds the
    # matching ones away because it is read at a glance; this is a file somebody pastes into an
    # issue, where "which versions is it actually running" is worth answering — and a section
    # that lists nothing because nothing is wrong reads as a section that failed to collect.
    lines += [f'  {r["name"]}: required={r["required"] or "-"} '
              f'installed={r["installed"] or "-"} ({r["status"]})'
              for r in deps['rows']] or ['  (no dependency information)']
    return '\n'.join(lines) + '\n'


def as_xml(data: dict, stamp: str) -> str:
    """The same tree, for a system that ingests XML.

    Built with `ElementTree` and not by writing tags: the values include Windows paths and
    version strings, and hand-rolled escaping is how a report becomes unparsable at the one
    destination that was supposed to parse it.
    """
    root = ET.Element('diagnostics', {'generated': stamp})
    for name in ('runtime', 'system', 'network', 'database'):
        block = ET.SubElement(root, name)
        for key, value in (data.get(name) or {}).items():
            child = ET.SubElement(block, key)
            # A list (the embedded services) becomes repeated children rather than a
            # stringified Python list, which is the whole reason to offer XML at all.
            if isinstance(value, list):
                for item in value:
                    ET.SubElement(child, 'item').text = str(item)
            else:
                child.text = str(value)
    storage = ET.SubElement(root, 'storage')
    for row in data['storage']:
        ET.SubElement(storage, 'path', {
            'key': row['key'], 'exists': str(row['exists']).lower(),
            'writable': str(row['writable']).lower(),
            'free_bytes': str(row['free_bytes']),
            'total_bytes': str(row['total_bytes'])}).text = row['path']
    features = ET.SubElement(root, 'features')
    for f in data['features']:
        ET.SubElement(features, 'feature', {
            'module': f['module'], 'available': str(f['available']).lower(),
            'version': f['version']})
    deps = data['dependencies']
    node = ET.SubElement(root, 'dependencies', {
        'total': str(len(deps['rows'])), 'missing': str(deps['missing']),
        'mismatch': str(deps['mismatch'])})
    for r in deps['rows']:
        ET.SubElement(node, 'dependency', {
            'name': r['name'], 'required': r['required'],
            'installed': r['installed'], 'status': r['status']})
    ET.indent(root, space='  ')
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'
