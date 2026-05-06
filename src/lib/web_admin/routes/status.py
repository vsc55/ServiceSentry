#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public status page route — no authentication required."""

import json
import os

from flask import abort, render_template, session

from lib.config import ConfigControl

# Fallback language for watchful pretty-name lookup.
_LANG_FALLBACK = 'en_EN'


def _module_pretty_name(modules_dir: str | None, mod_name: str, lang: str) -> str | None:
    """Return the pretty_name for *mod_name* from its lang JSON file.

    Tries ``{modules_dir}/{mod_name}/lang/{lang}.json`` first; if that
    file doesn't exist or lacks a ``pretty_name`` key, falls back to
    ``en_EN.json``.  Returns ``None`` when no lang file is found at all.
    """
    if not modules_dir:
        return None
    for try_lang in (lang, _LANG_FALLBACK):
        path = os.path.join(modules_dir, mod_name, 'lang', f'{try_lang}.json')
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            name = data.get('pretty_name')
            if name:
                return str(name)
        except (OSError, ValueError, KeyError):
            pass
    return None


def register(app, wa):

    @app.route('/status')
    def public_status():
        """Public status page — always visible to logged-in users; only to guests when public_status=True."""
        if not wa._public_status and not wa._check_session():
            abort(404)

        # ── Language priority ──────────────────────────────────────────
        # 1. User preference (set in their session)
        # 2. Status-page-specific language (wa._STATUS_LANG)
        # 3. Default web-admin language (wa._default_lang)
        lang = session.get('lang') or wa._STATUS_LANG or wa._default_lang

        status_raw: dict = {}
        if wa._var_dir:
            path = os.path.join(wa._var_dir, wa._STATUS_FILE)
            cfg = ConfigControl(path)
            status_raw = cfg.read() or {}

        modules_cfg = wa._read_config_file(wa._MODULES_FILE)

        modules = []
        total_ok = 0
        total_all = 0
        for mod_name, checks in status_raw.items():
            if not isinstance(checks, dict):
                continue
            # Pretty name priority: watchful lang file > modules.json label > title-cased fallback
            label = (
                _module_pretty_name(wa._modules_dir, mod_name, lang)
                or (modules_cfg.get(mod_name) or {}).get('label')
                or mod_name.replace('_', ' ').title()
            )
            items = []
            mod_ok = 0
            for check_name, info in checks.items():
                st = info.get('status') if isinstance(info, dict) else None
                ok = st is True
                if ok:
                    mod_ok += 1
                items.append({
                    'name': check_name,
                    'ok': ok,
                    'extra': info.get('other_data', {}) if isinstance(info, dict) else {},
                })
            n = len(items)
            total_ok += mod_ok
            total_all += n
            modules.append({
                'name': mod_name,
                'label': label,
                'checks': items,
                'ok': mod_ok,
                'total': n,
                'pct': round(100 * mod_ok / n) if n else 100,
                'all_ok': mod_ok == n,
            })

        overall_ok = total_all == 0 or total_ok == total_all
        overall_pct = round(100 * total_ok / total_all) if total_all else 100

        return render_template(
            'status.html',
            modules=modules,
            overall_ok=overall_ok,
            overall_pct=overall_pct,
            total_ok=total_ok,
            total_all=total_all,
            refresh_secs=wa._STATUS_REFRESH_SECS,
            lang=lang,
        )

