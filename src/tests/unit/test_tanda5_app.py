#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deferred findings of the 2026-10-12 audit, fifth batch — the parts that need no app.

* P10 — a copy took every unclaimed table, the runtime ones included: `sessions` (every live
  login, token in clear), `session_access` and the service leadership tables. A restore then
  replaced the target's live sessions and leader with the copy's. They are now neither copied
  nor restored; `api_tokens` are configuration and keep travelling.
* V11 — a rule created without a cooldown notified on every match. A NEW rule now gets 60 s
  when the field is absent; stored rules, a deliberate blank and an explicit 0 are unchanged.

Flask-free: a real SQLite connector and the rule logic, nothing else.
"""

from __future__ import annotations

import pytest

from lib.core.backup import create as bk_create
from lib.core.backup import parts as bk_parts
from lib.core.backup import restore as bk_restore
from lib.db.schema import Column, TableSpec
from lib.db.sqlite import SQLiteConnector
from lib.services.events import rules_logic


_RUNTIME = ('sessions', 'session_access', 'service_leader', 'service_instances',
            'service_commands')


def _spec(name, cols):
    return TableSpec(name=name, columns=[Column(c, 'TEXT', nullable=True) for c in cols])


@pytest.fixture
def db(tmp_path):
    con = SQLiteConnector(str(tmp_path / 'data.db'))
    con.reconcile_table(_spec('devices', ['uid', 'name']))
    con.reconcile_table(_spec('api_tokens', ['uid', 'name', 'token_hash']))
    con.reconcile_table(_spec('api_token_access', ['uid', 'token_uid', 'ts']))
    for t in _RUNTIME:
        con.reconcile_table(_spec(t, ['uid', 'token']))
        con.execute(f"INSERT INTO {t} (uid, token) VALUES ('old', 'tok-of-the-copy')")
    con.execute("INSERT INTO devices (uid, name) VALUES ('h1', 'SRV01')")
    con.execute("INSERT INTO api_tokens (uid, name, token_hash) VALUES ('t1', 'ci', 'h-1')")
    con.execute("INSERT INTO api_token_access (uid, token_uid, ts) VALUES ('x1', 't1', '1')")
    con.commit()
    yield con
    con.close()


def _make(db, tmp_path, name='copia'):
    return bk_create.create_backup(db, name, var_dir=str(tmp_path), config_dir=str(tmp_path),
                                   parts=['core'], include_secrets=True)


def _go_live(db):
    """What the target looks like by restore time: its own sessions and leader, not the copy's."""
    for t in _RUNTIME:
        db.execute(f'DELETE FROM {t}')
        db.execute(f"INSERT INTO {t} (uid, token) VALUES ('live', 'tok-of-the-target')")
    db.commit()


class TestRuntimeTablesStayOut:
    """P10."""

    def test_a_copy_does_not_carry_sessions_or_the_service_tables(self, db, tmp_path):
        res = _make(db, tmp_path)
        assert res['ok'], res.get('message')
        tables = set(res['manifest']['tables'])
        assert not tables & set(_RUNTIME), tables & set(_RUNTIME)
        assert {'devices', 'api_tokens', 'api_token_access'} <= tables

    def test_a_restore_leaves_the_targets_sessions_and_leader_alone(self, db, tmp_path):
        """Even from an archive written before the rule existed, which DOES hold them: they
        are ignored, not applied — the target's live logins and leader survive."""
        orig = bk_parts._RUNTIME_LOWER
        bk_parts._RUNTIME_LOWER = frozenset()          # an old archive: runtime tables inside
        try:
            assert _make(db, tmp_path, 'vieja')['ok']
        finally:
            bk_parts._RUNTIME_LOWER = orig
        _go_live(db)
        out = bk_restore.restore_backup(db, str(tmp_path), 'vieja')
        assert out['ok'], out.get('message')
        assert not set(out['tables']) & set(_RUNTIME)
        for t in _RUNTIME:
            assert [tuple(r) for r in db.fetchall(f'SELECT uid, token FROM {t}')] == \
                [('live', 'tok-of-the-target')], t

    def test_the_restore_form_does_not_offer_them(self, db, tmp_path):
        orig = bk_parts._RUNTIME_LOWER
        bk_parts._RUNTIME_LOWER = frozenset()
        try:
            assert _make(db, tmp_path, 'vieja')['ok']
        finally:
            bk_parts._RUNTIME_LOWER = orig
        res = bk_restore.archive_contents(str(tmp_path), 'vieja')
        offered = {t['name'] for p in res['parts'] for t in p['tables']}
        assert not offered & set(_RUNTIME)
        assert {'api_tokens', 'api_token_access'} <= offered

    def test_api_tokens_survive_a_round_trip(self, db, tmp_path):
        """The owner's worry, pinned: tokens are configuration a script depends on."""
        assert _make(db, tmp_path)['ok']
        db.execute('DELETE FROM api_tokens')
        db.execute('DELETE FROM api_token_access')
        db.commit()
        out = bk_restore.restore_backup(db, str(tmp_path), 'copia')
        assert out['ok'], out.get('message')
        assert [tuple(r) for r in db.fetchall('SELECT uid, name, token_hash FROM api_tokens')] \
            == [('t1', 'ci', 'h-1')]
        assert db.fetchone('SELECT token_uid FROM api_token_access')[0] == 't1'

    def test_the_list_names_the_real_tables_and_not_the_tokens(self):
        """A rename of one of them would silently put it back in every copy."""
        from lib.core.apitokens import store as tok_store          # noqa: PLC0415
        from lib.core.sessions import store as ses_store           # noqa: PLC0415
        from lib.services.manager import commands, instances, leader  # noqa: PLC0415
        declared = set()
        for mod in (ses_store, commands, instances, leader, tok_store):
            for v in vars(mod).values():
                if isinstance(v, TableSpec):
                    declared.add(v.name)
        assert bk_parts.RUNTIME_TABLES <= declared
        assert not bk_parts.RUNTIME_TABLES & {'api_tokens', 'api_token_access'}


class _NoNames:
    def name_taken(self, *_a, **_k):
        return False


_RULE = {'name': 'r', 'source': 'syslog', 'channels': ['telegram']}


class TestNewRuleCooldown:
    """V11."""

    def test_a_new_rule_without_a_cooldown_gets_sixty_seconds(self):
        rule = rules_logic.prepare_rule(_NoNames(), dict(_RULE), new=True)
        assert rule['cooldown'] == rules_logic.NEW_RULE_COOLDOWN == 60

    def test_an_explicit_zero_still_means_zero(self):
        rule = rules_logic.prepare_rule(_NoNames(), dict(_RULE, cooldown=0), new=True)
        assert rule['cooldown'] == 0

    def test_a_deliberate_blank_still_inherits_the_global(self):
        for blank in (None, ''):
            rule = rules_logic.prepare_rule(_NoNames(), dict(_RULE, cooldown=blank), new=True)
            assert rule['cooldown'] is None

    def test_an_update_never_invents_one(self):
        assert rules_logic.prepare_rule(_NoNames(), dict(_RULE))['cooldown'] is None


# ── D12: a chain that crosses sites says so, and only as much as the reader may see ──────────

class TestChainAcrossSites:
    """The list a view hands the chain is one site's; the hop to another is fetched by uid,
    marked, and anonymous to whoever may not see that site."""

    _AQUI = [{'uid': 'pan', 'name': 'Panel', 'kind': 'panel', 'site_uid': 's1',
              'upstream_uid': 'ups'}]
    _ALLI = {'ups': {'uid': 'ups', 'name': 'Far UPS', 'kind': 'ups', 'site_uid': 's2',
                     'upstream_uid': 'red'},
             'red': {'uid': 'red', 'name': 'Far mains', 'kind': 'mains', 'site_uid': 's2'}}

    def _path(self, ve):
        from lib.core.dcim import service
        return service.power_path(self._AQUI, [{'uid': 'p', 'rack_uid': 'r', 'source_uid': 'pan'}],
                                  fetch=self._ALLI.get, may_see_site=lambda s: ve,
                                  site_name=lambda s: 'Far site')['paths']['p']

    def test_a_visible_hop_is_marked_with_its_site_and_followed(self):
        now = self._path(True)['now']
        assert [n['name'] for n in now] == ['Panel', 'Far UPS', 'Far mains']
        assert 'cross_site' not in now[0]
        assert now[1]['cross_site'] is True and now[1]['site_name'] == 'Far site'
        assert 'cross_site' not in now[2], 'only the hop is marked, not the rest of that site'
        assert self._path(True)['ups'] == ['ups']

    def test_a_hidden_hop_is_anonymous_and_ends_the_chain(self):
        camino = self._path(False)
        now = camino['now']
        assert len(now) == 2 and now[1]['hidden'] is True and now[1]['cross_site'] is True
        assert now[1]['name'] == '' and now[1]['uid'] == '' and 'site_name' not in now[1]
        assert 'Far' not in repr(camino), 'something of the hidden site leaked'

    def test_without_a_fetcher_the_chain_stops_as_before(self):
        from lib.core.dcim import service
        assert [n['uid'] for n in service.chain_up(self._AQUI, 'pan')] == ['pan']
