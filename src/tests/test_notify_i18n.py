#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification titles are localised to the *system* notification language.

A notification has no user context but a system one — the global ``notifications|lang``
(falling back to the panel language). The Telegram single-event title is translated with
that language, not English-only.
"""

from lib.core.notify.formatting import event_title, notify_lang
from lib.core.notify.telegram.notify import _format


class TestEventTitle:

    def test_translates_to_the_given_language(self):
        assert event_title('auth_login', 'es_ES') == 'Inicio de sesión'
        assert event_title('auth_login', 'en_EN') == 'Login'

    def test_empty_lang_uses_the_default_language(self):
        assert event_title('cert_expiring', '') == event_title('cert_expiring', 'en_EN')

    def test_unknown_kind_falls_back_to_a_prettified_key(self):
        assert event_title('some_new_kind', 'es_ES') == 'Some new kind'

    def test_format_title_is_localised(self):
        msg = _format('auth_login', 'auth', 'admin', 'LOGIN', 'x', '', 'es_ES')
        assert '<b>Inicio de sesión</b>' in msg


class TestNotifyLang:

    def test_precedence_notifications_over_panel(self):
        assert notify_lang({'notifications': {'lang': 'es_ES'},
                            'web_admin': {'lang': 'en_EN'}}) == 'es_ES'

    def test_falls_back_to_panel_language(self):
        assert notify_lang({'web_admin': {'lang': 'es_ES'}}) == 'es_ES'

    def test_empty_when_unset(self):
        assert notify_lang({}) == ''


class TestBodyTemplates:
    """The framework body/status templates (filled positionally by translate)."""

    def test_auth_login_body(self):
        from lib.i18n import translate
        assert (translate('en_EN', 'notif_msg_auth_login', 'admin', 'LDAP', '10.0.0.1')
                == 'admin signed in via LDAP from 10.0.0.1')
        assert (translate('es_ES', 'notif_msg_auth_login', 'admin', 'LDAP', '10.0.0.1')
                == 'admin inició sesión vía LDAP desde 10.0.0.1')

    def test_scheduler_and_ip_bodies(self):
        from lib.i18n import translate
        assert translate('en_EN', 'notif_msg_scheduler_started', 60) == 'Scheduler started (every 60s)'
        assert translate('es_ES', 'notif_msg_ip_banned', '1.2.3.4') == 'IP 1.2.3.4 bloqueada'

    def test_service_and_cert_bodies(self):
        from lib.i18n import translate
        assert translate('en_EN', 'notif_msg_service_down', 'monitor') == 'Service monitor is down'
        assert (translate('es_ES', 'notif_msg_cert_expiring', 'web01', '5')
                == 'El certificado web01 caduca en 5 día(s)')
