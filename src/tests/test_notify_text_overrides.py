#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Admin text-override layer: custom notification text on top of i18n, and its discovery.

Flow: a per-language admin override wins; otherwise the i18n string (core) or the module's
own lang file (modules). The Templates UI discovers every editable string as a package with
its default + current override.
"""

import os

from lib.core.notify.formatting import notify_text, text_override, event_title
from lib.core.notify.text_catalog import discover_text_packages

_MODULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'watchfuls')


class TestResolution:

    def test_override_wins_over_i18n(self):
        cfg = {'notif_text_overrides': {'es_ES': {'core:notif_msg_ip_banned': 'IP {} VETADA'}}}
        assert notify_text(cfg, 'es_ES', 'notif_msg_ip_banned', '1.2.3.4') == 'IP 1.2.3.4 VETADA'

    def test_falls_back_to_i18n_without_override(self):
        assert notify_text({}, 'es_ES', 'notif_msg_ip_banned', '1.2.3.4') == 'IP 1.2.3.4 bloqueada'

    def test_event_title_honours_override(self):
        cfg = {'notif_text_overrides': {'es_ES': {'core:notif_event_auth_login': 'Acceso!'}}}
        assert event_title('auth_login', 'es_ES', cfg) == 'Acceso!'
        assert event_title('auth_login', 'es_ES', {}) == 'Inicio de sesión'

    def test_text_override_empty_when_unset(self):
        assert text_override({}, 'es_ES', 'core:whatever') == ''


class TestDiscovery:

    def _pkgs(self, lang='es_ES', overrides=None, email_overrides=None):
        return discover_text_packages(lang, overrides=overrides or {},
                                      email_overrides=email_overrides or {},
                                      modules_dir=_MODULES_DIR)

    def test_core_groups_and_modules_present(self):
        ids = {p['id'] for p in self._pkgs()}
        assert {'core.events', 'core.messages', 'core.statuses', 'core.email'} <= ids
        assert 'mod.cpu' in ids and 'mod.ssl_cert' in ids
        # one package per module that declares messages (all 19 converted)
        assert sum(1 for p in self._pkgs() if p.get('group') == 'modules') >= 19

    def test_entry_carries_default_and_custom(self):
        ov = {'es_ES': {'mod:cpu:cpu_high': 'CPU X'}}
        cpu = next(p for p in self._pkgs(overrides=ov) if p['id'] == 'mod.cpu')
        e = next(x for x in cpu['entries'] if x['key'] == 'mod:cpu:cpu_high')
        assert e['default'] == 'CPU ({}) uso excesivo {}% ⚠️'   # es_ES i18n default
        assert e['custom'] == 'CPU X'

    def test_core_message_declares_named_placeholders(self):
        # Each {N} placeholder gets a human name so the editor can label/insert it.
        msg = next(p for p in self._pkgs() if p['id'] == 'core.messages')
        e = next(x for x in msg['entries'] if x['key'] == 'core:notif_msg_auth_failed')
        assert [(v['i'], v['name']) for v in e['vars']] == [
            (0, 'usuario'), (1, 'motivo'), (2, 'dirección IP')]

    def test_placeholderless_message_has_no_vars(self):
        msg = next(p for p in self._pkgs() if p['id'] == 'core.messages')
        e = next(x for x in msg['entries'] if x['key'] == 'core:notif_msg_scheduler_stopped')
        assert e['vars'] == []

    def test_email_package_uses_notif_templates_store(self):
        eo = {'es_ES': {'footer': 'Mi pie'}}
        email = next(p for p in self._pkgs(email_overrides=eo) if p['id'] == 'core.email')
        e = next(x for x in email['entries'] if x['key'] == 'email:footer')
        assert e['custom'] == 'Mi pie'
