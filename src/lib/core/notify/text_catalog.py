#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discovery of editable notification texts — the "language packages" the admin can override.

A *package* is a group of translatable strings (a Core theme, the Email strings, or one watchful
module).  Each entry carries its default (the i18n text for the requested language, falling back
to the default language) and the admin's current custom override, so the UI can show the default
as a template and let the admin edit per language.

Scoped keys — the stable id a stored override is keyed by:
    core:<i18n_key>       Core notification strings (events / messages / statuses)
    email:<string_key>    Email template strings (own store: the ``notif_templates`` config)
    mod:<module>:<key>    A watchful module's ``messages`` entry
"""

from __future__ import annotations

import json
import os

# Core theme groups, keyed by the i18n-key prefixes they collect (order = display order).
_CORE_GROUPS = (
    ('events',   'notif_event_'),
    ('messages', 'notif_msg_'),
    ('statuses', ('notif_status_', 'notif_auth_', 'notif_source_')),
)

# Core message placeholder names live in the general lang files under 'notif_msg_vars'
# ({msg_key: [name, …]}, translated per language) — the same idea as a module's messages_vars.


def _i18n_maps(lang: str):
    """(lang strings, default-language strings) flat dicts."""
    from lib.i18n import TRANSLATIONS, DEFAULT_LANG  # noqa: PLC0415
    base = TRANSLATIONS.get(lang) if lang else None
    return (base or {}), TRANSLATIONS.get(DEFAULT_LANG, {})


def _entry(scoped: str, label: str, default: str, overrides: dict, variables=None) -> dict:
    return {'key': scoped, 'label': label, 'default': default,
            'custom': overrides.get(scoped, '') if isinstance(overrides, dict) else '',
            'vars': variables or []}


def _core_packages(lang: str, overrides: dict) -> list:
    base, dflt = _i18n_maps(lang)

    # {msg_key: [name, …]} from the lang file (requested lang, else default) — like a module's.
    msg_vars = base.get('notif_msg_vars') or dflt.get('notif_msg_vars') or {}
    dflt_msg_vars = dflt.get('notif_msg_vars') or {}

    def _vars(i18n_key):
        names = msg_vars.get(i18n_key) or dflt_msg_vars.get(i18n_key)
        return [{'i': i, 'name': n, 'ph': '{%d}' % i}
                for i, n in enumerate(names)] if isinstance(names, list) else []
    out = []
    for gid, prefixes in _CORE_GROUPS:
        pref = prefixes if isinstance(prefixes, tuple) else (prefixes,)
        # Only real string entries are editable — skip meta keys like ``notif_msg_vars``
        # (a dict of placeholder names) that share the prefix but aren't user-facing text.
        keys = sorted(k for k in dflt if k.startswith(pref) and isinstance(dflt.get(k), str))
        entries = [_entry(f'core:{k}', k, base.get(k) or dflt.get(k) or k, overrides, _vars(k))
                   for k in keys]
        if entries:
            out.append({'id': f'core.{gid}', 'group': 'core', 'name_key': f'notif_pkg_{gid}',
                        'entries': entries})
    return out


def _email_package(lang: str, email_overrides: dict) -> list:
    """Email template strings — defaults from the email template engine, overrides from the
    legacy per-lang ``notif_templates`` store (kept as email's own storage)."""
    try:
        from lib.core.notify.email.templates import get_strings, _DEFAULT_STRINGS  # noqa: PLC0415
    except Exception:  # pylint: disable=broad-except
        return []
    defaults = get_strings(lang) or {}
    ov = (email_overrides or {}).get(lang, {}) if isinstance(email_overrides, dict) else {}
    base, dflt = _i18n_maps(lang)
    evars = base.get('notif_email_vars') or dflt.get('notif_email_vars') or {}
    dflt_evars = dflt.get('notif_email_vars') or {}

    def _ev(k):
        pairs = evars.get(k) or dflt_evars.get(k)
        return [{'ph': p[0], 'name': p[1]} for p in pairs
                if isinstance(p, (list, tuple)) and len(p) == 2] if isinstance(pairs, list) else []
    entries = [{'key': f'email:{k}', 'label': k, 'default': defaults.get(k, ''),
                'custom': ov.get(k, '') if isinstance(ov, dict) else '', 'vars': _ev(k)}
               for k in sorted(_DEFAULT_STRINGS)]
    return [{'id': 'core.email', 'group': 'core', 'name_key': 'notif_pkg_email',
             'entries': entries}] if entries else []


def _module_packages(lang: str, overrides: dict, modules_dir: str) -> list:
    """One package per watchful module that declares a ``messages`` section in its lang file."""
    from lib.i18n import DEFAULT_LANG  # noqa: PLC0415
    if not modules_dir or not os.path.isdir(modules_dir):
        return []
    out = []
    for mod in sorted(os.listdir(modules_dir)):
        lang_dir = os.path.join(modules_dir, mod, 'lang')
        if mod.startswith('__') or not os.path.isdir(lang_dir):
            continue

        def _section(lc, name):
            try:
                with open(os.path.join(lang_dir, f'{lc}.json'), encoding='utf-8') as fh:
                    return json.load(fh).get(name) or {}
            except (OSError, ValueError):
                return {}
        dflt_msgs = _section(DEFAULT_LANG, 'messages')
        lang_msgs = _section(lang, 'messages') if lang and lang != DEFAULT_LANG else {}
        if not dflt_msgs and not lang_msgs:
            continue
        # Optional per-message placeholder names: a "messages_vars" section ({key: [name, …]}),
        # in the module's own language (requested lang wins, else default).
        mvars = {**_section(DEFAULT_LANG, 'messages_vars'),
                 **(_section(lang, 'messages_vars') if lang and lang != DEFAULT_LANG else {})}

        def _mv(k):
            names = mvars.get(k)
            return ([{'i': i, 'name': n, 'ph': '{%d}' % i} for i, n in enumerate(names)]
                    if isinstance(names, list) else [])
        keys = sorted(set(dflt_msgs) | set(lang_msgs))
        entries = [_entry(f'mod:{mod}:{k}', k, lang_msgs.get(k) or dflt_msgs.get(k) or k,
                          overrides, _mv(k))
                   for k in keys]
        # Friendly module name from its lang file (pretty_name), falling back to the folder.
        name = ''
        try:
            with open(os.path.join(lang_dir, f'{lang or DEFAULT_LANG}.json'), encoding='utf-8') as fh:
                name = json.load(fh).get('pretty_name') or ''
        except (OSError, ValueError):
            pass
        out.append({'id': f'mod.{mod}', 'group': 'modules', 'name': name or mod, 'entries': entries})
    return out


def discover_text_packages(lang: str, *, overrides: dict, email_overrides: dict,
                           modules_dir: str) -> list:
    """All editable notification-text packages for *lang* (Core themes → Email → modules)."""
    ov = (overrides or {}).get(lang, {}) if isinstance(overrides, dict) else {}
    return (_core_packages(lang, ov)
            + _email_package(lang, email_overrides)
            + _module_packages(lang, ov, modules_dir))
