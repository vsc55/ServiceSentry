#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public status page route — no authentication required."""

import os

from flask import abort, render_template

from lib.config import ConfigControl


def register(app, wa):

    @app.route('/status')
    def public_status():
        """Public status page — always visible to logged-in users; only to guests when public_status=True."""
        if not wa._public_status and not wa._check_session():
            abort(404)

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
            label = mod_name.replace('_', ' ').title()
            mod_cfg = modules_cfg.get(mod_name, {})
            if isinstance(mod_cfg, dict) and mod_cfg.get('label'):
                label = mod_cfg['label']
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
        )
