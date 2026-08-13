#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Config-section actions contributed by a package (self-describing discovery).

A provider declares its buttons as DATA (``CONFIG_ACTIONS``) and web_admin renders them
generically, so no package-specific glue lives in the panel. These tests pin the contract:
the descriptors are discovered, normalised, ordered, and surfaced on the config layout.


Split by category: this file holds the isolated tests (no app, no DB, no HTTP); the rest of the
original ``test_config_actions.py`` lives in ``tests/meta/test_config_actions.py``."""

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
        root = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
        pat = os.path.join(root, 'lib', 'web_admin', 'templates', '**', '*.html')
        return {p: io.open(p, encoding='utf-8', errors='replace').read()
                for p in glob.glob(pat, recursive=True)}

    def test_it_is_assembled_from_contributions_only(self):
        card = self._card()
        assert card.get('fields') == [], 'the Maintenance card must have no fields of its own'
        assert {a['id'] for a in card['actions']} == {
            'db_optimize', 'db_compact',
            'history_clear_series', 'history_clear_all', 'syslog_clear', 'audit_clear_all',
            'events_clear_log', 'ipban_clear_history', 'status_reset'}

    def test_the_two_kinds_of_action_are_told_apart(self):
        """Reclaiming space and deleting data have opposite consequences, and the section
        showed eight identical red buttons in one row saying they were the same kind.

        The distinction is DECLARED (`group_label_key`), not inferred from the handler name or
        the button colour — those are presentation, and the next action added would have had
        to guess which convention it was joining."""
        by_group = {}
        for act in self._card()['actions']:
            by_group.setdefault(act.get('group_label_key'), set()).add(act['id'])
        assert None not in by_group,             f'ungrouped maintenance actions: {by_group.get(None)}'
        assert by_group.get('cfg_actions_group_db') == {'db_optimize', 'db_compact'}
        assert len(by_group.get('cfg_actions_group_wipe', ())) == 7

    def test_every_action_says_what_it_does(self):
        """A button caption fits a verb and a noun — enough to recognise an action you
        already know, not enough to learn what it will do to your data. In Maintenance being
        wrong about that is expensive, so the description is required rather than optional."""
        for act in self._card()['actions']:
            assert act.get('desc_key'), f"{act['id']} offers no description"

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
        """The whole point of the move: they are gone from History, Syslog and Audit."""
        for path, text in self._templates().items():
            if 'history' in path or 'syslog' in path:
                assert 'history-clear-all-wrap' not in text
                assert 'id="history-clear-btn"' not in text
                assert "onclick=\"_syslogClear()\"" not in text
        # Audit's wipe lived in the panel's own markup, not under a section folder.
        joined = '\n'.join(self._templates().values())
        assert 'id="btnClearAudit"' not in joined, \
            'the Audit toolbar still offers the log wipe'
        assert 'onclick="_eventClearLog()"' not in joined, \
            'the Events toolbar still offers the notification-log wipe'


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


class TestTheButtonSaysTheVerbAndTheCardSaysTherest:
    """A card carries the icon, the name and one line of what the action does. Repeating all
    of that on the button inside it gives you "Eliminar todos los eventos de auditoría" in a
    box two lines under a heading that already said so.

    `button_key` is optional and falls back to `label_key`, because an action rendered as a
    bare row has no card around it — there the button IS the only label.
    """

    def _card(self):
        return next(c for c in config_layout()['cards'] if c['id'] == 'maintenance')

    def test_the_wipes_carry_a_short_verb(self):
        for act in self._card()['actions']:
            if act.get('group_label_key') == 'cfg_actions_group_wipe':
                assert act.get('button_key'), \
                    f"{act['id']} repeats its full title on the button"

    def test_they_all_use_the_same_verb(self):
        """Seven actions that all delete stored records read as three different operations
        when one says "Borrar", another "Eliminar" and a third "Vaciar". The difference
        implies a distinction that is not there, and the reader spends attention working out
        that there is none — in the section where attention is worth most.

        All THREE layers, because the split kept reappearing one level down: the titles were
        unified first and every description still said "Elimina", and the action moved in from
        the Status toolbar arrived saying "Vacía".
        """
        from lib.i18n.lang import en_EN, es_ES
        for lang_name, table in (('es_ES', es_ES.LANG), ('en_EN', en_EN.LANG)):
            words = set()
            for act in self._card()['actions']:
                if act.get('group_label_key') != 'cfg_actions_group_wipe':
                    continue
                for key in ('label_key', 'button_key', 'desc_key'):
                    words.add(table[act[key]].split()[0].lower())
            # Descriptions are third person ("Borra"/"Deletes") and titles infinitive
            # ("Borrar"/"Delete"), so compare stems rather than whole words — the thing that
            # must not vary is the VERB, not its conjugation.
            stems = {w.rstrip('aers') for w in words}
            assert len(stems) == 1, \
                f'{lang_name} mixes verbs across the wipes: {sorted(words)}'

    def test_the_database_actions_keep_their_own_name(self):
        """"Optimizar" and "Compactar" are already one verb; a shorter one would say less."""
        for act in self._card()['actions']:
            if act.get('group_label_key') == 'cfg_actions_group_db':
                assert not act.get('button_key'), \
                    f"{act['id']} shortens a label that was already a verb"

    def test_the_short_label_exists_in_both_languages(self):
        from lib.i18n.lang import en_EN, es_ES
        for act in self._card()['actions']:
            key = act.get('button_key')
            if key:
                assert key in es_ES.LANG, f'{key} missing from es_ES'
                assert key in en_EN.LANG, f'{key} missing from en_EN'

    def test_the_renderer_only_shortens_inside_a_card(self):
        """The fallback is the whole safety of this: a section with no card around its
        actions must go on showing the full label."""
        import io as _io
        import os as _os
        root = _os.path.abspath(__file__).split(_os.sep + 'tests' + _os.sep)[0]
        body = _io.open(_os.path.join(root, 'lib', 'web_admin', 'templates', 'partials',
                                      'cfg', '_actions.html'), encoding='utf-8').read()
        assert 'shortLabel && a.button_key) || a.label_key' in body, \
            'the button label no longer falls back to the full one'




class TestTheAuditEntrySaysWhereTheActionCameFrom:
    """Reported: deleting a history series from Maintenance logged "Histórico: Entrada
    Eliminada". Accurate about the domain and useless about the act — somebody reading the
    log wants to know a person went to Maintenance and wiped a table, not which subsystem
    owns the rows.

    Every one of these nine is reachable ONLY from that section: the buttons that used to sit
    on the History, Syslog, Audit and Status toolbars are gone. So the prefix is a fact, not
    an approximation — which is why it is checked here rather than assumed.
    """

    _EVENT_OF = {
        'db_optimize': 'db_optimized', 'db_compact': 'db_compacted',
        'history_clear_series': 'history_deleted', 'history_clear_all': 'history_all_deleted',
        'audit_clear_all': 'audit_cleared', 'syslog_clear': 'syslog_cleared',
        'events_clear_log': 'notification_log_cleared',
        'ipban_clear_history': 'ipban_history_cleared', 'status_reset': 'status_cleared',
    }

    def _card(self):
        return next(c for c in config_layout()['cards'] if c['id'] == 'maintenance')

    def test_every_action_maps_to_a_known_event(self):
        """The guard's own premise: if an action stops writing the event named here, the
        checks below would pass while testing nothing."""
        from lib.i18n.lang import es_ES
        catalog = es_ES.LANG['audit_events']
        ids = {a['id'] for a in self._card()['actions']}
        assert ids == set(self._EVENT_OF), \
            f'the section changed; update the map: {ids ^ set(self._EVENT_OF)}'
        for event in self._EVENT_OF.values():
            assert event in catalog, f'{event} has no label'

    def test_they_all_say_maintenance(self):
        from lib.i18n.lang import en_EN, es_ES
        for name, table, prefix in (('es_ES', es_ES.LANG, 'Mantenimiento:'),
                                    ('en_EN', en_EN.LANG, 'Maintenance:')):
            for act_id, event in self._EVENT_OF.items():
                label = table['audit_events'][event]
                assert label.startswith(prefix), f'{name}/{act_id}: {label!r}'

    def test_the_seven_wipes_end_in_the_same_verb(self):
        """Eight said "Deleted" and one "Cleared" — the same split the buttons had, one layer
        down. Six others mixed "De" and "de" mid-label while their neighbours did not. Neither
        changes what the entry means, and both make a list of nine read as if the differences
        were carrying information."""
        from lib.i18n.lang import en_EN, es_ES
        wipes = [self._EVENT_OF[a['id']] for a in self._card()['actions']
                 if a.get('group_label_key') == 'cfg_actions_group_wipe']
        for name, table in (('es_ES', es_ES.LANG), ('en_EN', en_EN.LANG)):
            endings = {table['audit_events'][e].split()[-1].lower() for e in wipes}
            # Spanish agrees with its noun (Borrado/Borrada/Borrados), so compare stems.
            stems = {w.rstrip('aos') for w in endings}
            assert len(stems) == 1, f'{name} mixes verbs: {sorted(endings)}'

    def test_prepositions_are_not_capitalised(self):
        """The catalog's own convention — "Auth: Inicio de Sesión". Worth pinning because a
        label is written once and read for years, and the drift is invisible until nine of
        them sit in a column together."""
        from lib.i18n.lang import es_ES
        for event in self._EVENT_OF.values():
            label = es_ES.LANG['audit_events'][event]
            assert ' De ' not in label and ' Del ' not in label, label

    def test_actions_reachable_elsewhere_keep_their_own_domain(self):
        """The prefix says where the operator was, so it may only go on events that can only
        happen there. Deleting ONE audit entry and clearing syslog DROPS are done from their
        own tabs, and calling either "Maintenance" would be a lie about who did what where."""
        from lib.i18n.lang import es_ES
        catalog = es_ES.LANG['audit_events']
        for event in ('audit_entry_deleted', 'syslog_drops_cleared'):
            assert not catalog[event].startswith('Mantenimiento:'), \
                f'{event} is not a Maintenance action'
