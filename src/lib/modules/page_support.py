#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Support for watchfuls that contribute a section page or an Overview widget.

A module that declares ``__page__`` in its schema answers the core's generic renderer with
data, and it does so from **classmethods with no monitor behind them** — the web process
calls them directly.  That rules out the module's normal i18n and its normal check loop,
so both are provided here in a monitor-free form.

Nothing in this file is specific to any vendor: any watchful with a page needs it.
"""

from __future__ import annotations

import json
import os

# Keys the web layer adds to a config payload that are NOT item fields.  They steer the
# call itself (which item, which credential, which single check, which language) and must
# never reach the check as configuration — a stray ``_lang`` in an item dict is a field
# the module never declared.
CONTROL_KEYS = ('_item_key', 'cred_uid', '_service', '_lang')


def lang_section(module_file: str, lang: str, section: str) -> dict:
    """A section of a module's ``lang/<lang>.json``, falling back to ``en_EN``.

    Reads the file directly rather than going through the monitor's i18n, because the page
    and widget hooks run without a monitor.  *module_file* is the calling module's
    ``__file__``; its ``lang/`` directory is what gets read.

    Returns ``{}`` when the file, the language or the section is missing: a page with
    untranslated labels is far better than a page that fails to render.
    """
    ldir = os.path.join(os.path.dirname(module_file), 'lang')
    for fn in (f'{lang}.json', 'en_EN.json'):
        p = os.path.join(ldir, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding='utf-8') as fh:
                d = (json.load(fh) or {}).get(section)
            if isinstance(d, dict):
                return d
        except (OSError, ValueError):
            continue
    return {}


def strip_control_keys(config: dict) -> dict:
    """A config payload reduced to the item's own fields.

    Drops the ``__dunder__`` wrappers the web adds around a payload and the control keys
    above, so what is left is what the module actually declared in its schema.
    """
    return {k: v for k, v in (config or {}).items()
            if not (str(k).startswith('__') and str(k).endswith('__'))
            and k not in CONTROL_KEYS}


def run_item_once(module: str, config: dict, *, modules_dir: str,
                  services: tuple = (), default_key: str = 'item',
                  service: str = '') -> tuple[list, str]:
    """Run ONE item's enabled checks right now → ``(results, error_message)``.

    This is what both "test this credential" and "refresh this page live" need, and they
    differ only in how they present the answer.  The run goes through the monitor's own
    ``run_module_check``, so an on-demand run takes exactly the same path as a scheduled
    one — a test that passed through different code would prove nothing about the check
    that actually runs at 3am.

    *services* is the module's ``_SERVICES`` table ``(toggle, suffix, handler)``; passing
    *service* (a suffix) turns every other toggle off, so the answer is about the one check
    the admin clicked and nothing else.

    Never raises: a failure comes back as the second element, because these callers all
    answer an HTTP request and a traceback helps nobody there.
    """
    from lib.core.hosts.probe import run_module_check  # noqa: PLC0415 (web-only path)
    item = strip_control_keys(config)
    item['enabled'] = True
    if service:
        for tog, sfx, _handler in services:
            item[tog] = (sfx == service)
    key = str((config or {}).get('_item_key') or default_key)
    try:
        raw = run_module_check(module, {f'watchfuls.{module}': {'list': {key: item}}},
                               modules_dir=modules_dir)
    except Exception as exc:  # pylint: disable=broad-except
        return [], str(exc)
    return list(raw or []), ''


def modules_dir_for(module_file: str) -> str:
    """The watchfuls directory a module lives in, from its ``__file__``.

    ``run_module_check`` needs it to import the module the way the monitor does (by bare
    name), and every page hook would otherwise spell the same two ``dirname`` calls.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(module_file)))
