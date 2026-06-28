#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public status page route — no authentication required."""

import json
import os

from flask import abort, render_template, session

from lib.web_admin.constants import DEFAULT_LANG, TRANSLATIONS

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


def _check_labels(mod_cfg) -> dict:
    """Map ``{item_key: label}`` for a module's checks, so the status page can
    show a friendly label even when the key is an opaque UID."""
    out: dict = {}
    if not isinstance(mod_cfg, dict):
        return out
    for coll, items in mod_cfg.items():
        if coll.startswith('__') or not isinstance(items, dict):
            continue
        for key, item in items.items():
            if isinstance(item, dict):
                lbl = str(item.get('label') or '').strip()
                if lbl:
                    out[key] = lbl
                    # Multi-bind checks (e.g. clusters) are keyed in the status
                    # payload by the item UID, not its collection key — map both.
                    uid = str(item.get('uid') or '').strip()
                    if uid:
                        out[uid] = lbl
    return out


def register(app, wa):

    @app.route('/status')
    def public_status():
        """Public status page — always visible to logged-in users; only to guests when public_status=True."""
        logged_in = wa._check_session()
        if not wa._public_status and not logged_in:
            abort(404)

        # Per-item detail: always for logged-in users; for guests only when the
        # "detail for guests" option is enabled. Otherwise show module-level
        # status only (no per-item breakdown).
        show_detail = logged_in or bool(getattr(wa, '_public_status_detail', False))

        # ── Language priority ──────────────────────────────────────────
        # 1. User preference (set in their session)
        # 2. Status-page-specific language (wa._STATUS_LANG)
        # 3. Default web-admin language (wa._default_lang)
        lang = session.get('lang') or wa._STATUS_LANG or wa._default_lang
        i18n = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])

        status_raw: dict = wa._read_check_status()

        modules_cfg = wa._load_modules()

        modules = []
        total_ok = 0
        total_all = 0
        for mod_name, checks in status_raw.items():
            if not isinstance(checks, dict):
                continue
            # Pretty name priority: watchful lang file > module config label > title-cased fallback
            mod_cfg = (modules_cfg.get(mod_name)
                       or modules_cfg.get(f'watchfuls.{mod_name}')
                       or modules_cfg.get(mod_name.split('.')[-1]) or {})
            label = (
                _module_pretty_name(wa._modules_dir, mod_name, lang)
                or mod_cfg.get('label')
                or mod_name.replace('_', ' ').title()
            )
            # A check's display name uses its item 'label' when set (the stored
            # key may be an opaque UID), falling back to the raw status key.
            check_labels = _check_labels(mod_cfg)
            items = []
            mod_ok = 0
            for check_name, info in checks.items():
                st = info.get('status') if isinstance(info, dict) else None
                ok = st is True
                if ok:
                    mod_ok += 1
                extra = info.get('other_data', {}) if isinstance(info, dict) else {}
                # Display name priority: a name the module emitted (for derived
                # result keys, e.g. "NS1 - RAM") > the item 'label' > the raw key.
                disp = (extra.get('name') if isinstance(extra, dict) else None) \
                    or check_labels.get(check_name)
                if not disp and '/' in check_name:
                    # Composite '<item>/<metric>' (multi-bind, e.g. clusters):
                    # resolve the first segment to its label, keep the suffix.
                    head, _, rest = check_name.partition('/')
                    base = check_labels.get(head)
                    if base:
                        disp = f'{base} / {rest}'
                disp = disp or check_name
                items.append({'name': disp, 'ok': ok, 'extra': extra})
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
            show_detail=show_detail,
            lang=lang,
            i18n=i18n,
        )

