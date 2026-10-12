#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Privilege holes found by the 2026-10-12 audit — each pinned so it does not come back.

Identity: a scoped API token of an admin counted as an admin; your own password could be set
without the current one, and by a token; `groups_edit` alone let anyone join a group carrying
permissions they lack; a disabled role was assignable by anyone and then switched on; a
session of an account SCIM deleted came back as the account later created under that name;
and the LDAP and SMTP tests sent the stored password to whatever server the form named.

DCIM: deleting a room left its room items without a room and an owner; the generic item
route moved a room item into another company's room; a cable's near end and a power feed's
item were never checked.
"""

from __future__ import annotations

import socket
import threading

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


def _token(admin, client, perms):
    _login(client)
    r = client.post('/api/v1/account/tokens', json={'name': 'ci', 'permissions': perms})
    assert r.status_code in (200, 201), r.get_json()
    b = admin.app.test_client()
    b.environ_base['HTTP_AUTHORIZATION'] = 'Bearer ' + r.get_json()['token']
    return b


class TestIdentity:

    def test_a_scoped_token_of_an_admin_is_not_an_admin(self, admin, client):
        from lib.core.constants import BUILTIN_ROLE_UIDS               # noqa: PLC0415
        b = _token(admin, client, ['users_add', 'users_view'])
        r = b.post('/api/v1/users', json={'username': 'intruso', 'password': 'Passw0rd!xyzLONG',
                                          'role': BUILTIN_ROLE_UIDS['admin']})
        assert r.status_code == 403
        assert 'intruso' not in admin._users

    def test_no_password_through_a_token_nor_your_own_without_the_current_one(self, admin, client):
        b = _token(admin, client, ['users_edit', 'users_view'])
        assert b.put('/api/v1/users/admin', json={'password': 'NewPassw0rd!long'}).status_code == 403
        assert client.put('/api/v1/users/admin', json={'password': 'NewPassw0rd!long'}).status_code == 403
        assert _login(admin.app.test_client()).status_code == 200, 'the old password still works'

    def test_groups_edit_alone_does_not_join_a_powerful_group(self, admin, client):
        _login(client)
        rol = _uid_201(client.post('/api/v1/roles', json={'name': 'Ops', 'permissions': ['config_edit', 'config_view']}))
        grupo = _uid_201(client.post('/api/v1/groups', json={'name': 'OpsGroup', 'roles': [rol]}))
        m = _login_as(admin, 'mallory', perms=['groups_edit', 'groups_view'])
        assert m.put(f'/api/v1/groups/{grupo}', json={'members': ['mallory']}).status_code == 403
        assert 'config_edit' not in admin._get_effective_permissions('mallory', admin._users['mallory']['role'])

    def test_a_disabled_role_is_neither_assigned_nor_switched_on_freely(self, admin, client):
        _login(client)
        rol = _uid_201(client.post('/api/v1/roles', json={'name': 'Ops', 'permissions': ['config_edit', 'config_view'],
                                                          'enabled': False}))
        m = _login_as(admin, 'mallory', perms=['users_edit', 'users_view'])
        assert m.put('/api/v1/users/mallory', json={'role': rol}).status_code == 403
        e = _login_as(admin, 'eve', perms=['roles_edit', 'roles_view'])
        assert e.put(f'/api/v1/roles/{rol}', json={'enabled': True}).status_code == 403
        assert client.put(f'/api/v1/roles/{rol}', json={'enabled': True}).status_code == 200, 'an admin may'

    def test_a_scim_deleted_account_takes_its_sessions_away(self, admin, client):
        from lib.core.constants import BUILTIN_ROLE_UIDS               # noqa: PLC0415
        from lib.providers.scim.service import ScimService             # noqa: PLC0415
        _login(client)
        assert client.post('/api/v1/users', json={'username': 'bob', 'password': 'pw-secret-123',
                                                  'role': BUILTIN_ROLE_UIDS['viewer']}).status_code == 201
        admin._users['bob'].update(auth_source='scim', provisioned_by='scim')
        b = admin.app.test_client()
        _login(b, 'bob', 'pw-secret-123')
        assert b.get('/api/v1/me').status_code == 200
        viejo = admin._users['bob']['uid']
        with admin.app.test_request_context('/scim/v2/Users'):
            ScimService(admin, 'http://x/scim/v2').delete_user(viejo)
        assert not [t for t, e in admin._sessions.items() if e.get('user_uid') == viejo],             'its sessions go with it'
        assert client.post('/api/v1/users', json={'username': 'bob', 'password': 'other-pass-999',
                                                  'role': BUILTIN_ROLE_UIDS['admin']}).status_code == 201
        assert b.get('/api/v1/me').status_code != 200, "the old cookie is not the new bob"

    def test_a_session_whose_uid_is_gone_does_not_fall_back_to_the_name(self, admin, client):
        _login(client)
        token = next(iter(admin._sessions))
        admin._sessions[token]['user_uid'] = 'u-gone'
        assert client.get('/api/v1/me').status_code != 200

    def test_the_ldap_test_sends_the_stored_password_only_to_the_stored_server(self, admin):
        pytest.importorskip('ldap3')
        cfg = admin._read_config_file(admin._CONFIG_FILE)
        cfg.setdefault('ldap', {}).update({'server': 'ldap.corp.example', 'bind_dn': 'cn=svc,dc=corp',
                                           'bind_password': 'S3cretBindPW!'})
        admin._write_config(cfg)
        admin._apply_saved_config()
        oido, recibido = socket.socket(), []
        oido.bind(('127.0.0.1', 0))
        oido.listen(1)

        def escucha():
            try:
                s, _ = oido.accept()
                s.settimeout(3)
                recibido.append(s.recv(4096))
                s.close()
            except OSError:
                pass
        threading.Thread(target=escucha, daemon=True).start()
        m = _login_as(admin, 'mallory', perms=['config_edit', 'config_view'])
        m.post('/api/v1/auth/ldap/test', json={'server': '127.0.0.1', 'port': oido.getsockname()[1],
                                               'use_ssl': False, 'timeout': 2})
        oido.close()
        assert not any(b'S3cretBindPW!' in x for x in recibido)


def _uid_201(r):
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def dos(admin, client):
    """Two companies, each with a site, a room, a rack, a rack item and a room PC."""
    _login(client)
    c = client
    a = _uid(c.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
    b = _uid(c.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
    sa = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SA'}))
    sb = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SB'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sa, 'org_uid': a})
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sb, 'org_uid': b})
    ra = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': sa, 'name': 'RA'}))
    rb = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': sb, 'name': 'RB'}))
    ka = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': ra, 'name': 'KA', 'u_height': 42}))
    kb = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': rb, 'name': 'KB', 'u_height': 42}))
    ia = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': ka, 'u_start': 1, 'u_height': 1, 'label': 'IA'}))
    ib = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': kb, 'u_start': 1, 'u_height': 1, 'label': 'IB'}))
    pa = _uid(c.post(f'/api/v1/dcim/rooms/{ra}/items', json={'role': 'pc', 'label': 'PC-A'}))
    pb = _uid(c.post(f'/api/v1/dcim/rooms/{rb}/items', json={'role': 'pc', 'label': 'PC-B'}))
    ua = _login_as(admin, 'ua', perms=['dcim_view', 'dcim_edit', 'dcim_cable_edit', f'org.{a}.view'])
    return dict(a=a, b=b, sa=sa, sb=sb, ra=ra, rb=rb, ka=ka, kb=kb, ia=ia, ib=ib, pa=pa, pb=pb, ua=ua)


class TestDcim:

    def test_a_room_with_room_items_is_not_deleted_from_under_them(self, admin, client, dos):
        # Only room items in it: no rack, nothing drawn.
        sala = _uid(client.post('/api/v1/dcim/rooms', json={'site_uid': dos['sa'], 'name': 'Oficina'}))
        pc = _uid(client.post(f'/api/v1/dcim/rooms/{sala}/items', json={'role': 'pc', 'label': 'PC'}))
        assert client.delete(f'/api/v1/dcim/rooms/{sala}').status_code == 409
        assert admin._dcim_store.rooms.get(sala) and admin._dcim_store.items.get(pc)
        assert client.get(f'/api/v1/dcim/rooms/{sala}/holds').get_json()['contains'] == {'items': 1}

    def test_a_floors_area_with_room_items_stays(self, admin, client, dos):
        fl = _uid(client.post('/api/v1/dcim/floors', json={'site_uid': dos['sb'], 'name': 'F1'}))
        area = client.post(f'/api/v1/dcim/floors/{fl}/area').get_json()['room_uid']
        pc = _uid(client.post(f'/api/v1/dcim/rooms/{area}/items', json={'role': 'pc', 'label': 'SUELTO'}))
        assert client.delete(f'/api/v1/dcim/floors/{fl}').status_code == 200
        assert admin._dcim_store.rooms.get(area) and admin._dcim_store.items.get(pc)

    def test_the_generic_item_route_does_not_move_a_room_item(self, admin, dos):
        r = dos['ua'].put(f'/api/v1/dcim/items/{dos["pa"]}', json={'room_uid': dos['rb']})
        assert r.status_code == 400
        assert admin._dcim_store.items.get(dos['pa'])['room_uid'] == dos['ra']
        r = dos['ua'].post('/api/v1/dcim/items', json={'rack_uid': dos['ka'], 'placement': 'room',
                                                       'room_uid': dos['rb']})
        assert r.status_code == 400

    def test_both_ends_of_a_new_cable_are_checked(self, admin, dos):
        ua = dos['ua']
        r = ua.post('/api/v1/dcim/cables', json={'a_item': dos['pb'], 'b_item': dos['ia'],
                                                 'a_port': 'eth0', 'b_port': '1'})
        assert r.status_code == 403
        r = ua.post('/api/v1/dcim/cables', json={'a_item': 'nada', 'b_item': dos['ia'],
                                                 'a_port': 'eth0', 'b_port': '2'})
        assert r.status_code == 404
        assert not admin._dcim_store.cables_of([dos['ia']])

    def test_a_feeds_item_is_checked(self, admin, dos):
        ua = dos['ua']
        pdu = _uid(ua.post('/api/v1/dcim/pdus', json={'rack_uid': dos['ka'], 'name': 'P', 'outlets': 8}))
        assert ua.post('/api/v1/dcim/feeds', json={'pdu_uid': pdu, 'item_uid': dos['ib'],
                                                   'outlet': 1}).status_code == 403
        assert ua.post('/api/v1/dcim/feeds', json={'pdu_uid': pdu, 'item_uid': 'nada',
                                                   'outlet': 2}).status_code == 404
        assert ua.post('/api/v1/dcim/feeds', json={'pdu_uid': pdu, 'item_uid': dos['ia'],
                                                   'outlet': 3}).status_code == 200
