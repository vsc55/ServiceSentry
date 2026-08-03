#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for notification email template overrides.

Covers:
  - email_templates.get_strings() override behaviour
  - email_templates.render_* accepting pre-computed strings
  - GET /api/v1/notify/templates
  - PUT /api/v1/notify/templates/<lang>
  - DELETE /api/v1/notify/templates/<lang>


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_wa_notif_templates.py`` lives in
``tests/integration/test_wa_notif_templates.py``."""


from lib.core.notify.email import templates as email_templates


# ────────────────────── email_templates unit tests ──────────────────────────

class TestGetStrings:

    def test_default_returns_english(self):
        s = email_templates.get_strings()
        assert s['badge_down'] == 'DOWN'
        assert s is email_templates._DEFAULT_STRINGS

    def test_unknown_lang_falls_back_to_english(self):
        s = email_templates.get_strings('zz_ZZ')
        assert s['badge_down'] == 'DOWN'

    def test_overrides_take_precedence(self):
        s = email_templates.get_strings('', overrides={'badge_down': 'CAÍDO'})
        assert s['badge_down'] == 'CAÍDO'
        # Other keys unaffected
        assert s['badge_warn'] == email_templates._DEFAULT_STRINGS['badge_warn']

    def test_overrides_ignore_unknown_keys(self):
        s = email_templates.get_strings('', overrides={'totally_fake_key': 'x'})
        assert 'totally_fake_key' not in s

    def test_overrides_ignore_empty_string_values(self):
        s = email_templates.get_strings('', overrides={'badge_down': ''})
        # Empty override → not applied → falls back to default
        assert s['badge_down'] == 'DOWN'

    def test_overrides_with_known_lang(self):
        """Overrides stack on top of language-specific built-in overlay."""
        # es_ES has a built-in 'badge_down' override in email_tpl
        s_es    = email_templates.get_strings('es_ES')
        custom  = {'footer': 'Pie personalizado'}
        s_custom = email_templates.get_strings('es_ES', overrides=custom)
        assert s_custom['footer'] == 'Pie personalizado'
        # badge_down still comes from the es_ES built-in overlay (if present)
        # or from defaults — either way must be a string
        assert isinstance(s_custom['badge_down'], str)

    def test_none_overrides_same_as_no_overrides(self):
        s1 = email_templates.get_strings('')
        s2 = email_templates.get_strings('', overrides=None)
        assert s1 == s2


class TestRenderWithStrings:

    def test_render_test_uses_custom_strings(self):
        custom = email_templates.get_strings('', overrides={'test_title': 'Custom Title'})
        html = email_templates.render_test(strings=custom)
        assert 'Custom Title' in html

    def test_render_alert_uses_custom_strings(self):
        custom = email_templates.get_strings('', overrides={'alert_down': 'Servicio CAÍDO — {item}'})
        html = email_templates.render_alert(
            kind='down', module='web', item='example.com',
            status='DOWN', message='timeout', timestamp='2026-01-01T00:00:00',
            strings=custom,
        )
        assert 'Servicio CAÍDO' in html
        assert 'example.com' in html

    def test_render_summary_uses_custom_strings(self):
        custom = email_templates.get_strings('', overrides={'summary_intro': 'Resumen personalizado:'})
        html = email_templates.render_summary(
            items=[{'module': 'web', 'item': 'test.com', 'status': 'DOWN', 'message': 'err'}],
            timestamp='2026-01-01T00:00:00',
            strings=custom,
        )
        assert 'Resumen personalizado:' in html

    def test_render_test_without_strings_uses_lang(self):
        html = email_templates.render_test(lang='')
        assert email_templates._DEFAULT_STRINGS['test_title'] in html


# ──────────────────── API integration tests ─────────────────────────────────


# ──────────────────── Preview API tests ─────────────────────────────────────


# ──────────────── Test email applies saved customisations ───────────────────

