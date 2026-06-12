#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification template override API.

String-override endpoints
-------------------------
GET  /api/v1/notify/templates
    Returns the default English strings and per-language override dicts.

PUT  /api/v1/notify/templates/<lang>
    Save (or replace) the custom text-string overrides for a language.
    Body: {key: value, ...}

DELETE /api/v1/notify/templates/<lang>
    Reset all custom string overrides for a language.

HTML-body endpoints
-------------------
GET  /api/v1/notify/html-templates
    Returns stored custom HTML bodies {type: {lang: html}}.

GET  /api/v1/notify/html-templates/<type>/built-in
    Returns the built-in rendered HTML for *type* (sample data, for
    reference when the user wants to start from the default).

PUT  /api/v1/notify/html-templates/<type>/<lang>
    Save a full custom HTML body for email type + language.
    Body: {"html": "<!DOCTYPE html>..."}

DELETE /api/v1/notify/html-templates/<type>/<lang>
    Remove custom HTML, reverting to the built-in template.

Valid types: "test", "alert", "summary".
"""
from __future__ import annotations

from flask import jsonify, request

_VALID_HTML_TYPES = {'test', 'alert', 'summary'}

# Sample data used to render built-in HTML previews
_SAMPLE_ALERT = dict(
    kind='down', module='http_check', item='api.example.com',
    status='DOWN', message='Connection timed out after 10 s',
    timestamp='2026-01-15T12:34:56Z', public_url='',
)
_SAMPLE_ITEMS = [
    {'module': 'http_check', 'item': 'api.example.com',
     'status': 'DOWN',     'message': 'timeout'},
    {'module': 'ping',       'item': 'db.example.com',
     'status': 'WARN',     'message': 'high latency'},
]


def register(app, wa):
    config_edit_req = wa._perm_required('config_edit')
    config_view_req = wa._perm_required('config_view', 'config_edit')

    # ── String overrides ─────────────────────────────────────────────────────

    @app.route('/api/v1/notify/templates', methods=['GET'])
    @config_view_req
    def api_get_notif_templates():
        """Return default strings and stored per-language overrides."""
        from lib.web_admin import email_templates
        from lib.web_admin.constants import SUPPORTED_LANGS

        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        stored = cfg.get('notif_templates') or {}

        lang_strings: dict[str, dict[str, str]] = {}
        for lc in SUPPORTED_LANGS:
            lang_strings[lc] = email_templates.get_strings(lc)

        return jsonify({
            'defaults':     email_templates._DEFAULT_STRINGS,
            'overrides':    stored,
            'lang_strings': lang_strings,
        }), 200

    @app.route('/api/v1/notify/templates/<lang>', methods=['PUT'])
    @config_edit_req
    def api_save_notif_template_lang(lang):
        """Save custom string overrides for one language."""
        from lib.web_admin import email_templates
        from lib.web_admin.constants import SUPPORTED_LANGS

        valid_langs = set(SUPPORTED_LANGS) | {'en_EN'}
        if lang not in valid_langs:
            return jsonify({'error': f'Unknown language: {lang}'}), 400

        body = request.get_json(force=True, silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'Expected a JSON object'}), 400

        valid_keys = set(email_templates._DEFAULT_STRINGS.keys())
        clean: dict[str, str] = {
            k: v for k, v in body.items()
            if k in valid_keys and isinstance(v, str) and v.strip()
        }

        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        if 'notif_templates' not in cfg:
            cfg['notif_templates'] = {}
        if clean:
            cfg['notif_templates'][lang] = clean
        else:
            cfg['notif_templates'].pop(lang, None)
        if not cfg['notif_templates']:
            del cfg['notif_templates']
        wa._save_config_file(wa._CONFIG_FILE, cfg)

        wa._audit('notif_template_saved', detail={'lang': lang, 'keys': sorted(clean.keys())})
        return jsonify({'ok': True, 'lang': lang, 'overrides': clean}), 200

    @app.route('/api/v1/notify/templates/<lang>', methods=['DELETE'])
    @config_edit_req
    def api_reset_notif_template_lang(lang):
        """Reset all custom string overrides for a language."""
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        removed = False
        tpl = cfg.get('notif_templates') or {}
        if lang in tpl:
            del tpl[lang]
            removed = True
            if tpl:
                cfg['notif_templates'] = tpl
            else:
                cfg.pop('notif_templates', None)
            wa._save_config_file(wa._CONFIG_FILE, cfg)

        if removed:
            wa._audit('notif_template_reset', detail={'lang': lang})
        return jsonify({'ok': True}), 200

    # ── HTML body overrides ──────────────────────────────────────────────────

    @app.route('/api/v1/notify/html-templates', methods=['GET'])
    @config_view_req
    def api_get_html_templates():
        """Return all stored custom HTML bodies."""
        from lib.web_admin import email_templates
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        stored = cfg.get('notif_html_templates') or {}
        return jsonify({
            'stored':     stored,
            'valid_types': sorted(_VALID_HTML_TYPES),
            'vars':        email_templates.HTML_TPL_VARS,
        }), 200

    @app.route('/api/v1/notify/html-templates/<tpl_type>/built-in', methods=['GET'])
    @config_view_req
    def api_get_html_template_builtin(tpl_type):
        """Return the built-in rendered HTML for *tpl_type* with current strings.

        Query param ``lang`` selects the language (default ``en_EN``).
        String overrides from ``config.notif_templates`` are applied so the
        preview reflects the customised text strings.
        """
        if tpl_type not in _VALID_HTML_TYPES:
            return jsonify({'error': f'Unknown type: {tpl_type}'}), 400
        from lib.web_admin import email_templates
        from flask import request as _req

        lang = (_req.args.get('lang') or '').strip()
        lang_key = lang or 'en_EN'

        # Load string overrides so the preview uses customised text
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        str_overrides = (cfg.get('notif_templates') or {}).get(lang_key) or None
        strings = email_templates.get_strings(lang, overrides=str_overrides)

        # Replace each string value with its {key} placeholder so the returned
        # HTML uses {test_title}, {footer}, etc. instead of hardcoded text.
        # Python's html.escape() does NOT escape { or }, so the placeholders
        # survive the HTML generation intact.
        template_strings = {k: '{' + k + '}' for k in email_templates._DEFAULT_STRINGS}

        # Merge: use the real (possibly customised) value as placeholder
        # label only for keys that were overridden, so the user can identify
        # which strings they already personalised.
        # (We still use {key} notation; the actual value is shown as a hint in the UI.)

        if tpl_type == 'test':
            html_out = email_templates.render_test(
                sender_name='{sender_name}', lang=lang, strings=template_strings)
        elif tpl_type == 'alert':
            sample = {**_SAMPLE_ALERT,
                      'item': '{item}', 'module': '{module}', 'status': '{status}',
                      'message': '{message}', 'timestamp': '{timestamp}',
                      'kind': _SAMPLE_ALERT['kind']}
            html_out = email_templates.render_alert(**sample, lang=lang, strings=template_strings)
        else:
            html_out = email_templates.render_summary(
                items=_SAMPLE_ITEMS, timestamp='{timestamp}',
                lang=lang, strings=template_strings)
        return jsonify({'html': html_out, 'strings': strings}), 200

    @app.route('/api/v1/notify/html-templates/<tpl_type>/preview', methods=['POST'])
    @config_view_req
    def api_preview_html_template(tpl_type):
        """Render a live preview of *tpl_type* with the posted HTML and sample data.

        Body: {"html": "<html>...</html>", "lang": "en_EN"}
        Returns: {"html": "<rendered html>"}
        If ``html`` is empty, renders using the built-in template.
        """
        if tpl_type not in _VALID_HTML_TYPES:
            return jsonify({'error': f'Unknown type: {tpl_type}'}), 400
        from lib.web_admin import email_templates

        body = request.get_json(force=True, silent=True) or {}
        html_tpl = body.get('html', '')
        lang = (body.get('lang') or '').strip()
        lang_key = lang or 'en_EN'

        if not isinstance(html_tpl, str):
            return jsonify({'error': 'Field "html" must be a string'}), 400

        # Load current string overrides so preview reflects customised text
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        str_overrides = (cfg.get('notif_templates') or {}).get(lang_key) or None
        strings = email_templates.get_strings(lang, overrides=str_overrides)

        html_override = html_tpl.strip() or None

        if tpl_type == 'test':
            html_out = email_templates.render_test(
                sender_name='ServiceSentry', lang=lang, strings=strings,
                html_override=html_override)
        elif tpl_type == 'alert':
            html_out = email_templates.render_alert(
                **_SAMPLE_ALERT, lang=lang, strings=strings,
                html_override=html_override)
        else:
            html_out = email_templates.render_summary(
                items=_SAMPLE_ITEMS, timestamp=_SAMPLE_ALERT['timestamp'],
                lang=lang, strings=strings,
                html_override=html_override)
        return jsonify({'html': html_out}), 200

    @app.route('/api/v1/notify/html-templates/<tpl_type>/<lang>', methods=['PUT'])
    @config_edit_req
    def api_save_html_template(tpl_type, lang):
        """Save a custom HTML body for *tpl_type* + *lang*."""
        from lib.web_admin.constants import SUPPORTED_LANGS
        if tpl_type not in _VALID_HTML_TYPES:
            return jsonify({'error': f'Unknown type: {tpl_type}'}), 400
        valid_langs = set(SUPPORTED_LANGS) | {'en_EN'}
        if lang not in valid_langs:
            return jsonify({'error': f'Unknown language: {lang}'}), 400

        body = request.get_json(force=True, silent=True) or {}
        html_body = body.get('html', '')
        if not isinstance(html_body, str):
            return jsonify({'error': 'Field "html" must be a string'}), 400

        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        tpls = cfg.setdefault('notif_html_templates', {})
        if html_body.strip():
            tpls.setdefault(tpl_type, {})[lang] = html_body
        else:
            tpls.get(tpl_type, {}).pop(lang, None)
            if not tpls.get(tpl_type):
                tpls.pop(tpl_type, None)
        if not tpls:
            cfg.pop('notif_html_templates', None)
        wa._save_config_file(wa._CONFIG_FILE, cfg)

        wa._audit('notif_html_template_saved', detail={'type': tpl_type, 'lang': lang})
        return jsonify({'ok': True}), 200

    @app.route('/api/v1/notify/html-templates/<tpl_type>/<lang>', methods=['DELETE'])
    @config_edit_req
    def api_delete_html_template(tpl_type, lang):
        """Delete the custom HTML body for *tpl_type* + *lang*."""
        cfg = wa._read_config_file(wa._CONFIG_FILE) or {}
        removed = False
        tpls = cfg.get('notif_html_templates') or {}
        if lang in tpls.get(tpl_type, {}):
            del tpls[tpl_type][lang]
            removed = True
            if not tpls[tpl_type]:
                del tpls[tpl_type]
            if tpls:
                cfg['notif_html_templates'] = tpls
            else:
                cfg.pop('notif_html_templates', None)
            wa._save_config_file(wa._CONFIG_FILE, cfg)
        if removed:
            wa._audit('notif_html_template_reset', detail={'type': tpl_type, 'lang': lang})
        return jsonify({'ok': True}), 200
