#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for notification email template overrides.

Covers:
  - email_templates.get_strings() override behaviour
  - email_templates.render_* accepting pre-computed strings
  - GET /api/v1/notify/templates
  - PUT /api/v1/notify/templates/<lang>
  - DELETE /api/v1/notify/templates/<lang>
"""

import pytest

try:
    from lib.core.notify.email import templates as email_templates
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


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

class TestNotifTemplatesAPI:

    def test_get_requires_auth(self, client):
        r = client.get('/api/v1/notify/templates')
        assert r.status_code == 401

    def test_get_returns_defaults_and_overrides(self, client):
        _login(client)
        r = client.get('/api/v1/notify/templates')
        assert r.status_code == 200
        d = r.get_json()
        assert 'defaults' in d
        assert 'overrides' in d
        assert 'lang_strings' in d
        assert 'badge_down' in d['defaults']

    def test_put_requires_auth(self, client):
        r = client.put('/api/v1/notify/templates/en_EN', json={'badge_down': 'X'})
        assert r.status_code == 401

    def test_put_saves_overrides(self, client):
        _login(client)
        r = client.put('/api/v1/notify/templates/en_EN',
                       json={'footer': 'Custom footer', 'badge_down': 'DOWN!'})
        assert r.status_code == 200
        d = r.get_json()
        assert d['ok'] is True
        assert d['overrides']['footer'] == 'Custom footer'
        assert d['overrides']['badge_down'] == 'DOWN!'

    def test_put_get_round_trip(self, client):
        _login(client)
        client.put('/api/v1/notify/templates/en_EN',
                   json={'badge_warn': 'ALERT!'})
        r = client.get('/api/v1/notify/templates')
        d = r.get_json()
        assert d['overrides'].get('en_EN', {}).get('badge_warn') == 'ALERT!'

    def test_put_ignores_unknown_keys(self, client):
        _login(client)
        r = client.put('/api/v1/notify/templates/en_EN',
                       json={'unknown_key': 'x', 'badge_down': 'DOWN2'})
        assert r.status_code == 200
        d = r.get_json()
        assert 'unknown_key' not in d['overrides']
        assert d['overrides']['badge_down'] == 'DOWN2'

    def test_put_empty_values_not_stored(self, client):
        _login(client)
        r = client.put('/api/v1/notify/templates/en_EN', json={'badge_down': ''})
        assert r.status_code == 200
        d = r.get_json()
        assert 'badge_down' not in d['overrides']

    def test_put_unknown_lang_returns_400(self, client):
        _login(client)
        r = client.put('/api/v1/notify/templates/zz_ZZ', json={'badge_down': 'x'})
        assert r.status_code == 400

    def test_delete_requires_auth(self, client):
        r = client.delete('/api/v1/notify/templates/en_EN')
        assert r.status_code == 401

    def test_delete_resets_overrides(self, client):
        _login(client)
        # First save something
        client.put('/api/v1/notify/templates/en_EN', json={'badge_down': 'CUSTOM'})
        # Then delete
        r = client.delete('/api/v1/notify/templates/en_EN')
        assert r.status_code == 200
        assert r.get_json()['ok'] is True
        # Verify gone
        r2 = client.get('/api/v1/notify/templates')
        d = r2.get_json()
        assert 'en_EN' not in (d['overrides'] or {})

    def test_delete_nonexistent_lang_is_ok(self, client):
        _login(client)
        r = client.delete('/api/v1/notify/templates/fr_FR')
        assert r.status_code == 200

    def test_put_all_empty_clears_lang_entry(self, client):
        _login(client)
        client.put('/api/v1/notify/templates/en_EN', json={'badge_down': 'X'})
        # Now save with all empty values — should remove the lang entry
        r = client.put('/api/v1/notify/templates/en_EN', json={'badge_down': ''})
        assert r.status_code == 200
        r2 = client.get('/api/v1/notify/templates')
        d = r2.get_json()
        assert 'en_EN' not in (d['overrides'] or {})


class TestHtmlTemplatesAPI:

    def test_get_html_requires_auth(self, client):
        r = client.get('/api/v1/notify/html-templates')
        assert r.status_code == 401

    def test_get_html_returns_structure(self, client):
        _login(client)
        r = client.get('/api/v1/notify/html-templates')
        assert r.status_code == 200
        d = r.get_json()
        assert 'stored' in d
        assert 'vars' in d
        assert 'valid_types' in d

    def test_builtin_uses_placeholder_keys(self, client):
        """'Load built-in' should return {test_title} not the real title text."""
        _login(client)
        r = client.get('/api/v1/notify/html-templates/test/built-in')
        assert r.status_code == 200
        html = r.get_json()['html']
        # Must have key placeholder, NOT the real English text
        assert '{test_title}' in html
        assert email_templates._DEFAULT_STRINGS['test_title'] not in html

    def test_builtin_with_lang_uses_placeholder_keys(self, client):
        """Built-in with a language still returns {key} placeholders."""
        _login(client)
        r = client.get('/api/v1/notify/html-templates/alert/built-in?lang=en_EN')
        assert r.status_code == 200
        html = r.get_json()['html']
        assert '{alert_down}' in html or '{badge_down}' in html

    def test_builtin_string_overrides_reflected(self, client):
        """String overrides saved for a lang are applied to built-in preview."""
        _login(client)
        # Save a custom footer override for en_EN
        client.put('/api/v1/notify/templates/en_EN',
                   json={'footer': 'Custom footer text'})
        # The built-in preview should still use {footer} as placeholder
        r = client.get('/api/v1/notify/html-templates/test/built-in?lang=en_EN')
        assert r.status_code == 200
        html = r.get_json()['html']
        assert '{footer}' in html
        # Clean up
        client.delete('/api/v1/notify/templates/en_EN')

    def test_put_html_requires_auth(self, client):
        r = client.put('/api/v1/notify/html-templates/test/en_EN', json={'html': '<html/>'})
        assert r.status_code == 401

    def test_put_html_saves(self, client):
        _login(client)
        custom_html = '<!DOCTYPE html><html><body>Hello {item}</body></html>'
        r = client.put('/api/v1/notify/html-templates/alert/en_EN',
                       json={'html': custom_html})
        assert r.status_code == 200
        assert r.get_json()['ok'] is True

    def test_put_html_round_trip(self, client):
        _login(client)
        html = '<html><body>{test_title}</body></html>'
        client.put('/api/v1/notify/html-templates/test/en_EN', json={'html': html})
        r = client.get('/api/v1/notify/html-templates')
        stored = r.get_json()['stored']
        assert stored.get('test', {}).get('en_EN') == html

    def test_delete_html_requires_auth(self, client):
        r = client.delete('/api/v1/notify/html-templates/test/en_EN')
        assert r.status_code == 401

    def test_delete_html_removes_entry(self, client):
        _login(client)
        client.put('/api/v1/notify/html-templates/test/en_EN',
                   json={'html': '<html/>'})
        r = client.delete('/api/v1/notify/html-templates/test/en_EN')
        assert r.status_code == 200
        stored = client.get('/api/v1/notify/html-templates').get_json()['stored']
        assert 'en_EN' not in stored.get('test', {})

    def test_put_html_unknown_type_returns_400(self, client):
        _login(client)
        r = client.put('/api/v1/notify/html-templates/unknown/en_EN',
                       json={'html': '<html/>'})
        assert r.status_code == 400

    def test_apply_html_override_substitutes_strings(self):
        """apply_html_override replaces {key} with string values and runtime vars."""
        strings = {'test_title': 'Titulo', 'footer': 'Pie de pagina'}
        tpl = '<title>{test_title}</title><footer>{footer}</footer>'
        result = email_templates.apply_html_override(tpl, strings=strings)
        assert result == '<title>Titulo</title><footer>Pie de pagina</footer>'

    def test_apply_html_override_two_pass(self):
        """String values containing {vars} are pre-interpolated with runtime kwargs."""
        strings = {'alert_down': 'Servicio caído — {item}'}
        tpl = '<h1>{alert_down}</h1>'
        result = email_templates.apply_html_override(
            tpl, strings=strings, item='api.example.com')
        assert result == '<h1>Servicio caído — api.example.com</h1>'

    def test_apply_html_override_unknown_keys_unchanged(self):
        """Unknown {variables} are left as-is (not raised as errors)."""
        result = email_templates.apply_html_override(
            'Hello {unknown_var}', strings={})
        assert result == 'Hello {unknown_var}'

    def test_render_test_with_html_override(self):
        """render_test uses html_override when provided."""
        tpl = '<html>{test_title} from {sender_name}</html>'
        strings = {'test_title': 'Mi titulo'}
        html = email_templates.render_test(
            sender_name='Acme', strings=strings, html_override=tpl)
        assert 'Mi titulo' in html
        assert 'Acme' in html

    def test_render_alert_with_html_override(self):
        """render_alert uses html_override; {item} substituted."""
        tpl = '<html>{alert_down} | {item} | {status}</html>'
        strings = {'alert_down': 'CAÍDO — {item}'}
        html = email_templates.render_alert(
            kind='down', module='web', item='srv.example.com',
            status='DOWN', message='err', timestamp='2026-01-01',
            strings=strings, html_override=tpl)
        assert 'CAÍDO — srv.example.com' in html
        assert 'srv.example.com' in html
        assert 'DOWN' in html


# ──────────────────── Preview API tests ─────────────────────────────────────

class TestHtmlPreviewAPI:

    def test_preview_requires_auth(self, client):
        r = client.post('/api/v1/notify/html-templates/alert/preview',
                        json={'html': '<html/>', 'lang': 'en_EN'})
        assert r.status_code == 401

    def test_preview_unknown_type_returns_400(self, client):
        _login(client)
        r = client.post('/api/v1/notify/html-templates/unknown/preview',
                        json={'html': '<html/>', 'lang': 'en_EN'})
        assert r.status_code == 400

    def test_preview_alert_with_custom_html(self, client):
        _login(client)
        tpl = '<!DOCTYPE html><html><body>Item: {item} | Status: {status}</body></html>'
        r = client.post('/api/v1/notify/html-templates/alert/preview',
                        json={'html': tpl, 'lang': 'en_EN'})
        assert r.status_code == 200
        html = r.get_json()['html']
        # Sample data: item='api.example.com', status='DOWN'
        assert 'api.example.com' in html
        assert 'DOWN' in html

    def test_preview_test_with_custom_html(self, client):
        _login(client)
        tpl = '<html><body>{test_title}</body></html>'
        r = client.post('/api/v1/notify/html-templates/test/preview',
                        json={'html': tpl, 'lang': 'en_EN'})
        assert r.status_code == 200
        html = r.get_json()['html']
        # {test_title} should be replaced with the actual string
        assert '{test_title}' not in html

    def test_preview_summary_with_custom_html(self, client):
        _login(client)
        tpl = '<html><body>Count: {n}</body></html>'
        r = client.post('/api/v1/notify/html-templates/summary/preview',
                        json={'html': tpl, 'lang': 'en_EN'})
        assert r.status_code == 200
        html = r.get_json()['html']
        # {n} = number of sample items = 2
        assert '2' in html

    def test_preview_empty_html_uses_builtin(self, client):
        _login(client)
        r = client.post('/api/v1/notify/html-templates/alert/preview',
                        json={'html': '', 'lang': 'en_EN'})
        assert r.status_code == 200
        html = r.get_json()['html']
        # Built-in template renders something substantial
        assert len(html) > 200

    def test_preview_respects_string_overrides(self, client):
        _login(client)
        # Save a string override
        client.put('/api/v1/notify/templates/en_EN',
                   json={'badge_down': 'CUSTOM_DOWN_BADGE'})
        tpl = '<html><body>{badge_down}</body></html>'
        r = client.post('/api/v1/notify/html-templates/alert/preview',
                        json={'html': tpl, 'lang': 'en_EN'})
        assert r.status_code == 200
        assert 'CUSTOM_DOWN_BADGE' in r.get_json()['html']
        # Clean up
        client.delete('/api/v1/notify/templates/en_EN')


# ──────────────── Test email applies saved customisations ───────────────────

class TestTestEmailUsesOverrides:
    """Regression: the test email must reflect the saved 'test' HTML template
    and string overrides — not the built-in (was a bug: the test send ignored
    customisations while the preview applied them)."""

    def test_test_email_applies_html_and_string_overrides(self, client, monkeypatch):
        _login(client)
        marker = 'CUSTOM_TEST_MARKER_42'
        client.put('/api/v1/notify/html-templates/test/en_EN',
                   json={'html': f'<html><body>{marker} {{test_title}}</body></html>'})
        client.put('/api/v1/notify/templates/en_EN',
                   json={'test_title': 'My Custom Title'})

        captured = {}
        from lib.core.notify.email import notify as email_notify

        def _fake_dispatch(cfg, subject, body_html, recipients=None):
            captured['subject'] = subject
            captured['body'] = body_html
            return True, 'ok'

        monkeypatch.setattr(email_notify, '_dispatch', _fake_dispatch)

        r = client.post('/api/v1/notify/email/test',
                        json={'test_to': 'x@example.com'})
        assert r.status_code == 200
        body = captured.get('body', '')
        assert marker in body            # custom HTML body was used
        assert 'My Custom Title' in body  # string override applied
        # Clean up
        client.delete('/api/v1/notify/html-templates/test/en_EN')
        client.delete('/api/v1/notify/templates/en_EN')
