#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-section actions contributed by a package (self-describing discovery).

A provider declares its buttons as DATA (``CONFIG_ACTIONS``) and web_admin renders them
generically, so no package-specific glue lives in the panel. These tests pin the contract:
the descriptors are discovered, normalised, ordered, and surfaced on the config layout.
"""

from lib.config.config_actions import _normalize, actions_for, discover_config_actions
from lib.config.layout import config_layout


class TestNormalize:

    def test_drops_entries_missing_required_keys(self):
        assert _normalize({'section': 'oidc', 'id': 'x', 'label_key': 'k'}) is None   # no fn
        assert _normalize({'id': 'x', 'label_key': 'k', 'fn': 'f'}) is None           # no section
        assert _normalize('not-a-dict') is None

    def test_keeps_known_keys_and_defaults(self):
        act = _normalize({'section': 'oidc', 'id': 'x', 'label_key': 'k', 'fn': 'f',
                          'bogus': 'dropped'})
        assert act['variant'] == 'secondary' and act['order'] == 100
        assert 'bogus' not in act

    def test_explicit_variant_and_order_win(self):
        act = _normalize({'section': 'oidc', 'id': 'x', 'label_key': 'k', 'fn': 'f',
                          'variant': 'warning', 'order': 5})
        assert (act['variant'], act['order']) == ('warning', 5)


class TestDiscovery:

    def test_entraid_provider_contributes_oidc_actions(self):
        ids = [a['id'] for a in actions_for('oidc')]
        assert {'register', 'rotate_secret'} <= set(ids)

    def test_actions_are_ordered(self):
        acts = actions_for('oidc')
        assert [a['order'] for a in acts] == sorted(a['order'] for a in acts)

    def test_every_action_names_a_js_function_and_i18n_key(self):
        for a in discover_config_actions():
            assert a['fn'] and isinstance(a['fn'], str)
            assert a['label_key'] and isinstance(a['label_key'], str)

    def test_unknown_section_has_no_actions(self):
        assert actions_for('does-not-exist') == []


class TestLayoutExposure:

    def test_layout_attaches_actions_to_the_matching_card(self):
        cards = {c['id']: c for c in config_layout()['cards']}
        assert 'actions' in cards['oidc']
        assert any(a['fn'] == 'showEntraOidcRotateSecret' for a in cards['oidc']['actions'])

    def test_cards_without_contributions_carry_no_actions_key(self):
        cards = {c['id']: c for c in config_layout()['cards']}
        # 'ldap' has no package-contributed buttons today
        assert 'actions' not in cards.get('ldap', {})


class TestMaintenanceCard:
    """Destructive data wipes live in Config → General → Maintenance.

    They used to sit in the toolbar of the very section they erase — a page left open all
    day, one stray click from "delete everything". The card itself knows nothing about
    history or syslog: it has no fields and is assembled purely from what each domain
    contributes as a CONFIG_ACTION on section 'maintenance'."""

    def _card(self):
        return next(c for c in config_layout()['cards'] if c['id'] == 'maintenance')

    def _templates(self):
        import glob
        import io
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pat = os.path.join(root, 'lib', 'web_admin', 'templates', '**', '*.html')
        return {p: io.open(p, encoding='utf-8', errors='replace').read()
                for p in glob.glob(pat, recursive=True)}

    def test_it_is_assembled_from_contributions_only(self):
        card = self._card()
        assert card.get('fields') == [], 'the Maintenance card must have no fields of its own'
        assert {a['id'] for a in card['actions']} == {
            'history_clear_series', 'history_clear_all', 'syslog_clear'}

    def test_every_wipe_is_permission_gated(self):
        """A user without the delete permission must not even see the button."""
        from lib.core.permissions import PERMISSIONS
        known = {p['flag'] if isinstance(p, dict) else p for p in PERMISSIONS}
        for act in self._card()['actions']:
            perm = act.get('perm')
            assert perm, f"{act['id']} offers a data wipe with no permission gate"
            assert perm in known, f"{act['id']} declares unknown permission {perm}"

    def test_the_panel_can_render_an_actions_only_card(self):
        """A card with no fields was previously skipped, and generic cards ignored
        actions entirely — both had to give for this card to exist."""
        joined = '\n'.join(self._templates().values())
        assert 'return h + _cfgSectionActions(' in joined, \
            'generic cards do not render their contributed actions'
        assert 'Array.isArray(_c.actions)' in joined, \
            'a card without fields is still skipped, so the Maintenance card cannot appear'

    def test_the_named_functions_exist(self):
        joined = '\n'.join(self._templates().values())
        for act in self._card()['actions']:
            assert f"function {act['fn']}(" in joined, \
                f"{act['id']} names {act['fn']}(), which no template defines"

    def test_the_buttons_left_the_section_toolbars(self):
        """The whole point of the move: they are gone from History and Syslog."""
        for path, text in self._templates().items():
            if 'history' in path or 'syslog' in path:
                assert 'history-clear-all-wrap' not in text
                assert 'id="history-clear-btn"' not in text
                assert "onclick=\"_syslogClear()\"" not in text


class TestGroupLabel:
    """The actions row is captioned by the package when they all come from one, so the UI
    reads "Entra ID" instead of a generic "Actions" (the frontend falls back to the generic
    label when a section mixes packages)."""

    def test_entraid_actions_declare_their_group(self):
        for sec in ('oidc', 'saml2'):
            groups = {a.get('group_label_key') for a in actions_for(sec)}
            assert groups == {'entra_id'}, f'{sec} actions must share one group label'

    def test_group_label_key_is_translatable(self):
        from lib.i18n import translate
        assert translate('en_EN', 'entra_id') == 'Entra ID'
        assert translate('es_ES', 'entra_id') == 'Entra ID'

    def test_group_label_key_survives_normalization(self):
        act = _normalize({'section': 's', 'id': 'i', 'label_key': 'k', 'fn': 'f',
                          'group_label_key': 'g'})
        assert act['group_label_key'] == 'g'


class TestI18nKeysExist:

    def test_declared_label_keys_are_translatable(self):
        from lib.i18n import translate
        for a in discover_config_actions():
            for key in filter(None, (a['label_key'], a.get('tooltip_key'))):
                assert translate('en_EN', key) != key, f'missing i18n for {key}'
                assert translate('es_ES', key) != key, f'missing i18n for {key}'
