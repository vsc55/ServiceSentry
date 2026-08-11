#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-contributed backup parts — generic catalog (core, no module code).

A watchful module keeps files of its own outside the database — MIBs, templates, whatever it
downloads or an operator uploads — and those files are part of the install. The core cannot
name them: it ships no string that names a module, and a backup that knew about one directory
because somebody wrote its path into ``lib/core/backup`` would hold that module's files and
silently miss the next module's.

So the module says it, in its ``schema.json``::

    "__backup_part__": {"id": "mibs", "dir": "snmp_mibs/raw",
                        "label_key": "backup_part_mibs", "default": false}

* ``id`` — what the part is called in the form, the manifest and the API. Defaults to the
  module's own name. It may not take one of the core's ids: a part that shadowed ``core``
  would quietly replace the copy's tables with a directory.
* ``dir`` — **relative to ``var_dir``**, and it stays there. An absolute path or one that
  climbs out with ``..`` is dropped: this directory is read when a copy is made and
  **written** when one is restored, so a declaration that escaped ``var_dir`` would let a
  module choose where the panel writes.
* ``label_key`` — a key under the module's own ``lang/*.json`` ``ui`` section. Falls back to
  the module's translated ``pretty_name``, which is right when the module contributes one
  part and its own name is the answer.
* ``default`` — whether the form pre-ticks it. Bulk data usually should not be.

A list contributes several parts. Tables need no declaration at all: ``core`` is defined as
every table no other part claimed, so a module's own tables — including the ones it creates at
runtime — are already in the copy.
"""

from __future__ import annotations

import json
import os

from lib.modules.discovery.credential_schemas import (_i18n_for, _module_i18n,
                                                      _watchfuls_dir)


def _safe_rel(value) -> str:
    """*value* as a var_dir-relative directory, or '' when it does not stay inside one.

    Checked HERE and not at the call site because there are two of them — the copy reads this
    directory and the restore writes it — and a check in one of the two is the half that gets
    forgotten.
    """
    rel = str(value or '').strip().replace('\\', '/')
    # Checked BEFORE the leading separator is stripped: turning "/etc/passwd" into
    # "<var_dir>/etc/passwd" would be reading a declaration as something other than what it
    # says, and a module that meant an absolute path should be told no rather than redirected.
    if not rel or rel.startswith('/') or os.path.isabs(rel) or ':' in rel:
        return ''
    rel = rel.strip('/')
    parts = [p for p in rel.split('/') if p]
    if not parts or any(p == '..' for p in parts):
        return ''
    return '/'.join(parts)


def backup_parts_catalog(watchfuls_dir: str | None = None, reserved=()) -> list:
    """``[{id, module, dir, default, label_i18n}]`` for every module declaring one.

    *reserved* is the core's own part ids; a module that claims one is skipped rather than
    shadowing it.
    """
    out: list = []
    base = _watchfuls_dir(watchfuls_dir)
    if not os.path.isdir(base):
        return out
    taken = set(reserved)
    for entry in sorted(os.listdir(base)):
        if entry.startswith('_'):
            continue
        sp = os.path.join(base, entry, 'schema.json')
        if not os.path.isfile(sp):
            continue
        try:
            with open(sp, encoding='utf-8') as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            # One malformed schema must not cost every OTHER module its part — discovery is
            # per-file precisely so a broken module stays contained.
            continue
        decl = schema.get('__backup_part__')
        specs = [decl] if isinstance(decl, dict) else (
            [d for d in decl if isinstance(d, dict)] if isinstance(decl, list) else [])
        if not specs:
            continue
        lang_data = _module_i18n(os.path.join(base, entry))
        pretty = {lang: data.get('pretty_name') for lang, data in lang_data.items()
                  if isinstance(data, dict) and isinstance(data.get('pretty_name'), str)}
        for spec in specs:
            pid = str(spec.get('id') or entry).strip()
            rel = _safe_rel(spec.get('dir'))
            if not pid or not rel or pid in taken:
                continue
            taken.add(pid)
            label = _i18n_for(lang_data, 'ui', str(spec.get('label_key') or ''))
            out.append({
                'id': pid,
                'module': entry,
                'dir': rel,
                'default': bool(spec.get('default')),
                'label_i18n': label or pretty or {'en_EN': pid},
            })
    return out
