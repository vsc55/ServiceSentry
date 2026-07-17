#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recipient token resolution (email | user:<uid> | group:<uid>) + suggest endpoint."""

from tests.conftest import _login


def _mk_group(client, name):
    return (client.post('/api/v1/groups', json={'name': name}).get_json() or {}).get('uid', '')


def _mk_user(admin, username, email, group_uids, enabled=True):
    # uid defaults to the username in the store, so tokens are `user:<username>` here.
    admin._users_store.upsert(username, {
        'email': email, 'enabled': enabled, 'role': 'viewer', 'groups': list(group_uids),
    })


class TestRecipientResolver:
    def test_group_expands_to_member_emails_deduped(self, admin, client):
        from lib.core.notify.recipients import RecipientResolver
        _login(client)
        gid = _mk_group(client, 'Ops')
        _mk_user(admin, 'ana', 'ana@x.com', [gid])
        _mk_user(admin, 'ben', 'ben@x.com', [gid])
        _mk_user(admin, 'noemail', '', [gid])                 # in group, no email → skipped
        _mk_user(admin, 'dis', 'dis@x.com', [gid], enabled=False)  # disabled → skipped

        res = RecipientResolver(admin._db_connector).expand(f'boss@x.com, group:{gid}, ana@x.com')
        assert set(res['emails']) == {'boss@x.com', 'ana@x.com', 'ben@x.com'}
        assert res['emails'].count('ana@x.com') == 1          # deduped
        assert res['skipped'] == []

    def test_user_token_resolves_to_email(self, admin, client):
        from lib.core.notify.recipients import RecipientResolver
        _login(client)
        _mk_user(admin, 'ana', 'ana@x.com', [])
        res = RecipientResolver(admin._db_connector).expand('user:ana')
        assert res['emails'] == ['ana@x.com'] and res['skipped'] == []

    def test_user_without_email_is_skipped(self, admin, client):
        from lib.core.notify.recipients import RecipientResolver
        _login(client)
        _mk_user(admin, 'noemail', '', [])
        res = RecipientResolver(admin._db_connector).expand('user:noemail')
        assert res['emails'] == []
        assert res['skipped'] == ['noemail']                  # label falls back to the name/uid

    def test_disabled_group_does_not_send(self, admin, client):
        from lib.core.notify.recipients import RecipientResolver
        _login(client)
        gid = _mk_group(client, 'Ops')
        _mk_user(admin, 'ana', 'ana@x.com', [gid])
        client.put(f'/api/v1/groups/{gid}', json={'enabled': False})   # disable the group
        res = RecipientResolver(admin._db_connector).expand(f'group:{gid}')
        assert res['emails'] == []                       # disabled group is not notified
        assert res['skipped'] == ['Ops']

    def test_disabled_user_token_skipped_with_name(self, admin, client):
        from lib.core.notify.recipients import RecipientResolver
        _login(client)
        _mk_user(admin, 'gone', 'gone@x.com', [], enabled=False)
        res = RecipientResolver(admin._db_connector).expand('user:gone')
        assert res['emails'] == [] and res['skipped'] == ['gone']

    def test_empty_group_reported_not_fatal(self, admin, client):
        from lib.core.notify.recipients import RecipientResolver
        _login(client)
        gid = _mk_group(client, 'Empty')
        res = RecipientResolver(admin._db_connector).expand(f'group:{gid}')
        assert res['emails'] == [] and res['skipped'] == ['Empty']

    def test_unknown_token_reported(self, admin):
        from lib.core.notify.recipients import RecipientResolver
        res = RecipientResolver(admin._db_connector).expand('a@x.com, group:nope, user:ghost')
        assert res['emails'] == ['a@x.com']
        assert set(res['skipped']) == {'nope', 'ghost'}


class TestSuggestEndpoint:
    def test_suggest_lists_users_with_uid_and_groups(self, admin, client):
        _login(client)
        gid = _mk_group(client, 'Ops')
        _mk_user(admin, 'ana', 'ana@x.com', [gid])
        _mk_user(admin, 'noemail', '', [gid])
        _mk_user(admin, 'dis', 'dis@x.com', [], enabled=False)
        data = client.get('/api/v1/notify/recipients/suggest').get_json()
        by_name = {u['name']: u for u in data['users']}
        assert 'ana' in by_name and by_name['ana']['email'] == 'ana@x.com'
        assert 'noemail' in by_name and by_name['noemail']['email'] == ''  # emailless still listed
        assert 'dis' not in by_name                                        # disabled excluded
        assert all('uid' in u for u in data['users'])                      # uid for user: tokens
        assert 'Ops' in {g['name'] for g in data['groups']}

    def test_suggest_requires_config_edit(self, client):
        assert client.get('/api/v1/notify/recipients/suggest').status_code in (401, 403)


class TestDispatchNoFallback:
    def test_empty_explicit_list_does_not_fall_back_to_raw_tokens(self):
        """A resolved empty list must NOT fall back to the raw config (which could mail a
        literal `group:`/`user:` token)."""
        from lib.core.notify.email import notify as email_notify
        cfg = {'enabled': True, 'provider': 'smtp', 'recipients': 'group:zzz'}
        ok, msg = email_notify._dispatch(cfg, subject='s', body_html='<b>x</b>', recipients=[])
        assert ok is False and 'recipient' in msg.lower()
